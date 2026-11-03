"""Web UI konfigurasi Sakato Smart Monitor (multi-kamera + snapshot).

Jalankan:
    cd web
    python -m venv .venv && source .venv/bin/activate   # sekali saja
    pip install -r requirements.txt                     # sekali saja
    python app.py

Buka: http://localhost:8080

Fitur: kelola banyak kamera (laptop/USB/RTSP CCTV/file), tab per kamera di
dashboard, snapshot frame terakhir auto-refresh, start/stop per kamera atau
sekaligus, event terfilter per kamera.

Config v2 (web/config.json):
    {"cameras": [{"id": "teras_depan", "camera_type": "laptop", ...}],
     "active": "teras_depan"}
Migrasi otomatis dari format v1 (single kamera) saat dibaca.

PERINGATAN: tanpa autentikasi. Hanya untuk LAN rumah — JANGAN expose ke internet.
"""

import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from subprocess import Popen, STDOUT, TimeoutExpired

from flask import Flask, jsonify, render_template_string, request, send_file

WEB_DIR = Path(__file__).resolve().parent
ROOT = WEB_DIR.parent
CONFIG_PATH = WEB_DIR / "config.json"
SNAPSHOT_DIR = WEB_DIR / "snapshots"
LOGS_DIR = WEB_DIR / "logs"

CAMERA_TYPES = ("laptop", "usb", "rtsp", "file")
BOOL_KEYS = ("telegram", "mqtt", "describe", "no_show")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MAX_CAM_WARN = 4  # tampilkan peringatan bila >= ini kamera aktif bersamaan

DEFAULT_CAMERA = {
    "id": "default",
    "camera_type": "laptop",  # laptop | usb | rtsp | file
    "usb_index": "1",
    "rtsp_url": "",
    "video_file": "",
    "camera_name": "Kamera",
    "gallery": "gallery/",
    "telegram": False,
    "mqtt": False,
    "describe": False,
    "no_show": True,
}

_procs = {}  # camera_id -> Popen
_lock = threading.Lock()


# ---------- config ----------

def blank_camera(cid):
    cam = dict(DEFAULT_CAMERA)
    cam["id"] = cid
    return cam


def load_config():
    """Kembalikan {'cameras': [...], 'active': id}.

    Migrasi otomatis: config v1 (single, camera_type di top-level)
    dikonversi menjadi satu kamera ber-id 'default'.
    """
    fallback = {"cameras": [blank_camera("default")], "active": "default"}
    try:
        if not CONFIG_PATH.exists():
            return fallback
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback
    if not isinstance(saved, dict):
        return fallback
    # --- migrasi v1 -> v2 ---
    if "cameras" not in saved and "camera_type" in saved:
        cam = blank_camera("default")
        for k in cam:
            if k in saved and k != "id":
                cam[k] = saved[k]
        return {"cameras": [cam], "active": "default"}
    # --- v2 ---
    if isinstance(saved.get("cameras"), list):
        cams, seen = [], set()
        for raw in saved["cameras"]:
            if not isinstance(raw, dict):
                continue
            cid = str(raw.get("id", "")).strip()
            if not ID_RE.match(cid) or cid in seen:
                continue
            cam = blank_camera(cid)
            for k in cam:
                if k in raw and k != "id":
                    cam[k] = raw[k]
            seen.add(cid)
            cams.append(cam)
        if not cams:
            return fallback
        active = saved.get("active")
        if active not in seen:
            active = cams[0]["id"]
        return {"cameras": cams, "active": active}
    return fallback


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                           encoding="utf-8")


def get_camera(cfg, cid):
    for cam in cfg["cameras"]:
        if cam["id"] == cid:
            return cam
    return None


def resolve_source(cam):
    """Kembalikan string --source untuk prototype/main.py."""
    ct = cam.get("camera_type", "laptop")
    if ct == "usb":
        return str(cam.get("usb_index", "1")).strip() or "1"
    if ct == "rtsp":
        return str(cam.get("rtsp_url", "")).strip()
    if ct == "file":
        return str(cam.get("video_file", "")).strip()
    return "0"


def validate_camera(data, is_new=False):
    """Validasi satu kamera. Kembalikan (cam_bersih, errors)."""
    errors = []
    cam = blank_camera("tmp")
    if is_new:
        cid = str(data.get("id", "")).strip()
        if not ID_RE.match(cid):
            errors.append(
                "id kamera wajib diisi: huruf/angka/_/- saja (maks 40).")
        cam["id"] = cid or "tmp"

    ct = str(data.get("camera_type", "laptop")).strip()
    if ct not in CAMERA_TYPES:
        errors.append(f"camera_type tidak valid: {ct!r}")
        ct = "laptop"
    cam["camera_type"] = ct

    if ct == "rtsp":
        url = str(data.get("rtsp_url", "")).strip()
        if not url:
            errors.append("URL RTSP wajib diisi untuk tipe kamera RTSP.")
        elif not url.startswith("rtsp://"):
            errors.append("URL RTSP harus diawali 'rtsp://'.")
        cam["rtsp_url"] = url
    elif ct == "usb":
        idx = str(data.get("usb_index", "")).strip()
        if not idx.isdigit():
            errors.append("Index USB harus angka (contoh: 1).")
        cam["usb_index"] = idx or "1"
    elif ct == "file":
        vf = str(data.get("video_file", "")).strip()
        if not vf:
            errors.append("Path file video wajib diisi untuk tipe kamera file.")
        cam["video_file"] = vf

    name = str(data.get("camera_name", "")).strip()
    if not name:
        errors.append("Nama kamera wajib diisi.")
    cam["camera_name"] = name or DEFAULT_CAMERA["camera_name"]

    gal = str(data.get("gallery", "")).strip()
    cam["gallery"] = gal or DEFAULT_CAMERA["gallery"]

    for k in BOOL_KEYS:
        cam[k] = bool(data.get(k, False))

    return cam, errors


# ---------- pipeline (multi-kamera) ----------

def snapshot_path(cid):
    return str(SNAPSHOT_DIR / f"{cid}.jpg")


def event_log_path(cid):
    return str(LOGS_DIR / f"{cid}.jsonl")


def cam_log_path(cid):
    return str(LOGS_DIR / f"{cid}.log")


def venv_python():
    proto = ROOT / "prototype"
    if os.name == "nt":
        return str(proto / ".venv" / "Scripts" / "python.exe")
    return str(proto / ".venv" / "bin" / "python")


def build_args(cam):
    args = [venv_python(), "main.py",
            "--source", resolve_source(cam),
            "--camera-name", cam["camera_name"],
            "--gallery", cam["gallery"],
            "--snapshot-file", snapshot_path(cam["id"]),
            "--log", event_log_path(cam["id"])]
    for key in BOOL_KEYS:
        if cam.get(key):
            args.append("--" + key.replace("_", "-"))
    return args


def camera_running(cid):
    p = _procs.get(cid)
    return p is not None and p.poll() is None


def running_count():
    return sum(1 for cid in _procs if camera_running(cid))


def start_camera(cam):
    """Jalankan pipeline untuk satu kamera. Kembalikan (ok, pesan)."""
    cid = cam["id"]
    with _lock:
        if camera_running(cid):
            return False, f"kamera {cid} sudah berjalan"
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        n = running_count()
        warn = (f" ⚠️ peringatan: {n + 1} kamera aktif bersamaan — "
                f"beban CPU tinggi!" if n >= MAX_CAM_WARN else "")
        logf = open(cam_log_path(cid), "ab")
        try:
            logf.write(f"\n===== start {datetime.now().isoformat()} id={cid} "
                       f"source={resolve_source(cam)} =====\n".encode())
            logf.flush()
            _procs[cid] = Popen(build_args(cam), cwd=str(ROOT / "prototype"),
                                stdout=logf, stderr=STDOUT)
        except OSError as e:
            logf.close()
            return False, f"gagal start kamera {cid}: {e}"
        return True, f"kamera {cid} dimulai (pid {_procs[cid].pid})." + warn


def stop_camera(cid):
    """Hentikan pipeline satu kamera. Kembalikan (ok, pesan)."""
    with _lock:
        if not camera_running(cid):
            return False, f"kamera {cid} tidak sedang berjalan"
        p = _procs[cid]
        p.terminate()
        try:
            p.wait(timeout=10)
            msg = f"kamera {cid} dihentikan"
        except TimeoutExpired:
            p.kill()
            msg = f"kamera {cid} di-kill paksa"
        _procs.pop(cid, None)
        return True, msg


def stop_all():
    msgs = []
    for cid in list(_procs.keys()):
        ok, msg = stop_camera(cid)
        msgs.append(msg)
    return msgs or ["tidak ada kamera yang berjalan"]


def tail_events(path, n=10):
    events = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(events))


def tail_log(path, n=50):
    try:
        lines = Path(path).read_text(encoding="utf-8",
                                     errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]


def camera_status(cam):
    cid = cam["id"]
    return {
        "id": cid,
        "camera_name": cam["camera_name"],
        "camera_type": cam["camera_type"],
        "running": camera_running(cid),
        "config": cam,
        "events": tail_events(event_log_path(cid), 10),
        "log_tail": tail_log(cam_log_path(cid), 50),
    }


# ---------- app ----------

def create_app():
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.get("/config")
    def config_page():
        return render_template_string(CONFIG_HTML)

    @app.get("/live")
    def live_page():
        return render_template_string(LIVE_HTML)

    @app.get("/snapshot/<cid>")
    def snapshot(cid):
        if not ID_RE.match(cid):
            return "id kamera tidak valid", 400
        p = SNAPSHOT_DIR / f"{cid}.jpg"
        if not p.exists():
            return "belum ada snapshot — jalankan pipeline kamera ini dulu", 404
        return send_file(p, mimetype="image/jpeg")

    @app.get("/api/status")
    def api_status():
        cfg = load_config()
        cams = [camera_status(c) for c in cfg["cameras"]]
        active = get_camera(cfg, cfg["active"])
        return jsonify({
            "cameras": cams,
            "active": cfg["active"],
            "running_count": sum(1 for c in cams if c["running"]),
            # kompatibilitas: endpoint lama membaca kamera aktif
            "running": active is not None and camera_running(active["id"]),
            "config": active or {},
        })

    # --- kelola kamera ---
    @app.get("/api/cameras")
    def api_cameras_list():
        return jsonify(load_config())

    @app.post("/api/cameras")
    def api_cameras_add():
        data = request.get_json(force=True, silent=True) or {}
        cfg = load_config()
        if get_camera(cfg, str(data.get("id", "")).strip()):
            return jsonify({"ok": False,
                            "errors": ["id kamera sudah dipakai."]}), 400
        cam, errors = validate_camera(data, is_new=True)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        cfg["cameras"].append(cam)
        save_config(cfg)
        return jsonify({"ok": True, "camera": cam})

    @app.put("/api/cameras/<cid>")
    def api_cameras_update(cid):
        if not ID_RE.match(cid):
            return jsonify({"ok": False,
                            "errors": ["id kamera tidak valid."]}), 400
        data = request.get_json(force=True, silent=True) or {}
        cfg = load_config()
        cam = get_camera(cfg, cid)
        if cam is None:
            return jsonify({"ok": False,
                            "errors": ["kamera tidak ditemukan."]}), 404
        new, errors = validate_camera(data, is_new=False)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        new["id"] = cid  # id tidak bisa diubah
        cfg["cameras"] = [new if c["id"] == cid else c
                          for c in cfg["cameras"]]
        save_config(cfg)
        return jsonify({"ok": True, "camera": new})

    @app.delete("/api/cameras/<cid>")
    def api_cameras_delete(cid):
        cfg = load_config()
        if get_camera(cfg, cid) is None:
            return jsonify({"ok": False,
                            "errors": ["kamera tidak ditemukan."]}), 404
        if camera_running(cid):
            stop_camera(cid)
        cfg["cameras"] = [c for c in cfg["cameras"] if c["id"] != cid]
        if not cfg["cameras"]:
            cfg["cameras"] = [blank_camera("default")]
        if cfg["active"] == cid:
            cfg["active"] = cfg["cameras"][0]["id"]
        save_config(cfg)
        return jsonify({"ok": True})

    @app.post("/api/active")
    def api_set_active():
        data = request.get_json(force=True, silent=True) or {}
        cfg = load_config()
        cid = str(data.get("id", "")).strip()
        if get_camera(cfg, cid) is None:
            return jsonify({"ok": False,
                            "errors": ["kamera tidak ditemukan."]}), 404
        cfg["active"] = cid
        save_config(cfg)
        return jsonify({"ok": True, "active": cid})

    # --- kontrol pipeline ---
    @app.post("/api/cameras/<cid>/start")
    def api_camera_start(cid):
        cfg = load_config()
        cam = get_camera(cfg, cid)
        if cam is None:
            return jsonify({"ok": False, "message": "kamera tidak ditemukan."}), 404
        ok, msg = start_camera(cam)
        return jsonify({"ok": ok, "message": msg}), 200 if ok else 409

    @app.post("/api/cameras/<cid>/stop")
    def api_camera_stop(cid):
        cfg = load_config()
        if get_camera(cfg, cid) is None:
            return jsonify({"ok": False, "message": "kamera tidak ditemukan."}), 404
        ok, msg = stop_camera(cid)
        return jsonify({"ok": ok, "message": msg}), 200 if ok else 409

    @app.post("/api/start-all")
    def api_start_all():
        cfg = load_config()
        results = []
        for cam in cfg["cameras"]:
            ok, msg = start_camera(cam)
            results.append({"id": cam["id"], "ok": ok, "message": msg})
        return jsonify({"ok": True, "results": results})

    @app.post("/api/stop-all")
    def api_stop_all():
        return jsonify({"ok": True, "messages": stop_all()})

    # --- endpoint lama: operasikan kamera aktif ---
    @app.post("/api/config")
    def api_config_legacy():
        data = request.get_json(force=True, silent=True) or {}
        cfg = load_config()
        active = get_camera(cfg, cfg["active"]) or cfg["cameras"][0]
        new, errors = validate_camera(data, is_new=False)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        new["id"] = active["id"]
        cfg["cameras"] = [new if c["id"] == active["id"] else c
                          for c in cfg["cameras"]]
        save_config(cfg)
        return jsonify({"ok": True, "config": new})

    @app.post("/api/start")
    def api_start_legacy():
        cfg = load_config()
        cam = get_camera(cfg, cfg["active"]) or cfg["cameras"][0]
        ok, msg = start_camera(cam)
        return jsonify({"ok": ok, "message": msg}), 200 if ok else 409

    @app.post("/api/stop")
    def api_stop_legacy():
        cfg = load_config()
        cam = get_camera(cfg, cfg["active"]) or cfg["cameras"][0]
        ok, msg = stop_camera(cam["id"])
        return jsonify({"ok": ok, "message": msg}), 200 if ok else 409

    return app


app = create_app()

# ---------- templates ----------

BASE_CSS = """
:root{--blue:#1E40AF;--blue-dark:#0F2B5B;--gold:#E8B923;--gold-dim:#C9A227;--bg:#0d1526;--panel:#152036;--line:#24304d;--txt:#e8ecf4;--mut:#93a0b8}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;max-width:1100px;margin:0 auto;padding:16px;background:var(--bg);color:var(--txt);line-height:1.5}
nav{margin-bottom:20px;padding:12px 4px;border-bottom:2px solid var(--blue-dark)}
nav a{color:#9fc0ff;margin-right:18px;text-decoration:none;font-weight:600}
nav a:hover,nav a.active{color:var(--gold)}
h1{color:#fff;font-size:28px;margin:4px 0 18px}
h1 .accent{color:var(--gold)}
h3{color:#fff;margin:0 0 12px}h4{color:#dfe6f3;margin:18px 0 8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px;box-shadow:0 4px 16px rgba(0,0,0,.35)}
.badge{display:inline-block;padding:4px 14px;border-radius:999px;font-weight:700;font-size:13px}
.on{background:#14532d;color:#86efac;border:1px solid #1f7a3f}
.off{background:#2a2f3a;color:#aab4c8;border:1px solid #3a4152}
button{padding:8px 16px;margin:4px;border-radius:8px;border:0;cursor:pointer;font-size:14px;font-weight:600}
button:hover{filter:brightness(1.12)}
.start{background:#16a34a;color:#fff}.stop{background:#dc2626;color:#fff}
.save{background:linear-gradient(135deg,var(--blue),var(--blue-dark));color:#fff;border:1px solid var(--gold-dim)}
.del{background:#7f1d1d;color:#fff}
.ghost{background:#222c44;color:#cdd6ea;border:1px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{background:#0f1a30;color:var(--gold);text-transform:uppercase;font-size:11px;letter-spacing:.06em}
th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left}
tbody tr:nth-child(even){background:rgba(255,255,255,.02)}
tbody tr:hover{background:rgba(232,185,35,.05)}
table button{padding:6px 10px;font-size:12px;white-space:nowrap}
td:last-child{white-space:nowrap}
pre{background:#0a0f1c;padding:12px;border-radius:8px;border:1px solid var(--line);max-height:260px;overflow:auto;font-size:12px;white-space:pre-wrap;color:#c8d2e6}
code{color:var(--gold)}
label{display:block;margin:12px 0 4px;font-weight:600;color:#dfe6f3}
input,select{padding:9px 10px;width:100%;max-width:440px;background:#0f1830;color:var(--txt);border:1px solid #33405f;border-radius:8px}
input:focus,select:focus{outline:none;border-color:var(--gold)}
input[type=checkbox]{width:auto;transform:scale(1.3);margin-right:8px}
.tabs{margin-bottom:0;display:flex;flex-wrap:wrap}
.tab{padding:8px 16px;margin:2px;border-radius:10px 10px 0 0;background:#101a30;color:#9fb0cc;border:1px solid var(--line);border-bottom:0;cursor:pointer}
.tab.active{background:var(--panel);color:#fff;font-weight:700;border-top:2px solid var(--gold)}
.tab .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px}
.dot.on{background:#4ade80;box-shadow:0 0 6px #4ade80}.dot.off{background:#5b6478}
img.snap{width:100%;border-radius:8px;border:1px solid var(--line);background:#000;min-height:120px;display:block}
.cond{display:none}.err{color:#f87171}.ok{color:#86efac}
.muted{color:var(--mut);font-size:13px}
.grid{display:grid;gap:16px;grid-template-columns:1fr;margin-bottom:16px}
@media(min-width:640px){.grid{grid-template-columns:1fr 1fr}}
@media(min-width:1024px){.grid{grid-template-columns:1fr 1fr 1fr}}
.livecard{padding:0;overflow:hidden}
.livecard .snapwrap{position:relative;background:#000}
.livecard .head{display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--line)}
.livecard .head .nm{font-weight:700;color:#fff;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.livecard .body{padding:12px 16px}
.livecard .actions{display:flex;gap:8px;margin-top:10px}
.empty{text-align:center;padding:48px 20px;color:var(--mut)}
.empty a{color:var(--gold);font-weight:700}
.livecard img.snap{border:0;border-radius:0;min-height:140px}
.brandbar{display:flex;align-items:center;gap:12px;margin-bottom:6px}
.brandbar .logo{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,var(--blue),var(--blue-dark));border:1px solid var(--gold-dim);display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--gold);font-weight:800}
"""

DASHBOARD_HTML = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sakato Smart Monitor</title><style>""" + BASE_CSS + """</style></head>
<body>
<nav><a href="/" class="active">Dashboard</a><a href="/live">Live</a><a href="/config">Konfigurasi</a></nav>
<div class="brandbar"><div class="logo">S</div><h1 style="margin:0">Sakato <span class="accent">Smart Monitor</span></h1></div>
<div class="card">
  <button class="start" onclick="actAll('start-all')">▶ Start semua</button>
  <button class="stop" onclick="actAll('stop-all')">⏹ Stop semua</button>
  <span id="count" style="margin-left:12px;color:#aaa"></span>
  <p id="msg"></p>
</div>
<div class="tabs" id="tabs"></div>
<div class="card" id="panel">
  <h3 id="camtitle">memuat...</h3>
  <span id="badge" class="badge off">-</span>
  <div style="margin:12px 0">
    <button class="start" onclick="actCam('start')">▶ Start</button>
    <button class="stop" onclick="actCam('stop')">⏹ Stop</button>
  </div>
  <h4>Snapshot terakhir</h4>
  <img id="snap" class="snap" alt="belum ada snapshot">
  <h4>10 event terakhir</h4>
  <table><thead><tr><th>Waktu</th><th>Tipe</th><th>Track</th><th>Nama</th></tr></thead>
  <tbody id="events"></tbody></table>
  <h4>Log (50 baris terakhir)</h4><pre id="log"></pre>
</div>
<script>
let cams=[],active=null,cur=null;
async function act(a,id){
  const r=await fetch('/api/cameras/'+id+'/'+a,{method:'POST'});
  const j=await r.json();showMsg(j.message,j.ok);refresh();
}
async function actCam(a){if(cur)act(a,cur);}
async function actAll(a){
  const r=await fetch('/api/'+a,{method:'POST'});const j=await r.json();
  const msgs=(j.results||[]).map(x=>x.id+': '+x.message).concat(j.messages||[]);
  showMsg(msgs.join(' | '),j.ok);refresh();
}
function showMsg(t,ok){const m=document.getElementById('msg');m.textContent=t;m.className=ok?'ok':'err';}
async function refresh(){
  const r=await fetch('/api/status');const s=await r.json();
  cams=s.cameras;active=s.active;
  if(!cams.length){document.getElementById('camtitle').textContent='belum ada kamera';return;}
  if(!cur||!cams.find(c=>c.id===cur))cur=active;
  const tabs=document.getElementById('tabs');
  tabs.innerHTML=cams.map(c=>'<button class="tab'+(c.id===cur?' active':'')+'" onclick="cur=\\''+c.id+'\\';refresh()">'
    +'<span class="dot '+(c.running?'on':'off')+'"></span>'+c.camera_name+'</button>').join('');
  const c=cams.find(x=>x.id===cur);
  document.getElementById('camtitle').textContent='🎥 '+c.camera_name+' ('+c.id+')';
  const b=document.getElementById('badge');
  b.textContent=c.running?'BERJALAN':'BERHENTI';b.className='badge '+(c.running?'on':'off');
  document.getElementById('count').textContent=s.running_count+' kamera berjalan';
  const img=document.getElementById('snap');
  img.src='/snapshot/'+c.id+'?t='+Date.now();
  img.onerror=()=>{img.removeAttribute('src');};
  const tb=document.getElementById('events');
  tb.innerHTML=c.events.length?c.events.map(e=>'<tr><td>'+(e.ts||'-')+'</td><td>'+(e.type||'-')+'</td><td>'+(e.track_id??'-')+'</td><td>'+(e.name||'-')+'</td></tr>').join(''):'<tr><td colspan="4">belum ada event</td></tr>';
  document.getElementById('log').textContent=c.log_tail.join('\\n')||'(log kosong)';
}
function tickSnap(){if(cur){const img=document.getElementById('snap');img.src='/snapshot/'+cur+'?t='+Date.now();}}
setInterval(refresh,5000);setInterval(tickSnap,3000);refresh();
</script></body></html>"""

CONFIG_HTML = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Konfigurasi — Sakato Smart Monitor</title><style>""" + BASE_CSS + """</style></head>
<body>
<nav><a href="/">Dashboard</a><a href="/live">Live</a><a href="/config" class="active">Konfigurasi</a></nav>
<div class="brandbar"><div class="logo">S</div><h1 style="margin:0">Konfigurasi <span class="accent">kamera</span></h1></div>
<div class="card"><h3>Daftar kamera</h3><table>
<thead><tr><th>ID</th><th>Nama</th><th>Sumber</th><th>Aksi</th></tr></thead>
<tbody id="camlist"></tbody></table></div>
<div class="card"><h3 id="formtitle">Tambah kamera</h3>
<label>ID kamera (huruf/angka/_/-, maks 40)</label><input id="cid" placeholder="teras_belakang">
<label>Sumber kamera</label>
<select id="camera_type">
  <option value="laptop">💻 Laptop (kamera internal)</option>
  <option value="usb">🔌 USB (kamera eksternal)</option>
  <option value="rtsp">📹 RTSP (CCTV / kamera IP)</option>
  <option value="file">🎞 File video</option>
</select>
<div id="c-usb" class="cond"><label>Index USB (0, 1, 2...)</label>
<input id="usb_index" placeholder="1"></div>
<div id="c-rtsp" class="cond"><label>URL RTSP</label>
<input id="rtsp_url" placeholder="rtsp://user:pass@192.168.1.10:554/stream1"></div>
<div id="c-file" class="cond"><label>Path file video</label>
<input id="video_file" placeholder="/home/dika/video.mp4"></div>
<label>Nama kamera (tampil di dashboard)</label><input id="camera_name">
<label>Folder galeri wajah</label><input id="gallery">
<label><input type="checkbox" id="telegram"> Notifikasi Telegram</label>
<label><input type="checkbox" id="mqtt"> Publisher MQTT</label>
<label><input type="checkbox" id="describe"> Deskripsi VLM (butuh Ollama)</label>
<label><input type="checkbox" id="no_show" checked> Tanpa jendela GUI (headless)</label>
<div style="margin-top:16px">
<button class="save" id="btnsave" onclick="save()">💾 Tambah</button>
<button onclick="resetForm()">Batal</button>
</div>
<p id="msg"></p>
<p style="color:#aaa;font-size:13px">Config tersimpan di <code>web/config.json</code>
(berisi kredensial RTSP — jangan di-commit, sudah di-.gitignore).
Maksimal wajar 4 kamera aktif bersamaan (beban CPU).</p>
</div>
<script>
let editId=null;
const F=['usb_index','rtsp_url','video_file','camera_name','gallery'];
const B=['telegram','mqtt','describe','no_show'];
async function load(){
  const r=await fetch('/api/cameras');const s=await r.json();
  const tb=document.getElementById('camlist');
  tb.innerHTML=s.cameras.map(c=>'<tr><td><code>'+c.id+'</code>'+(c.id===s.active?' ⭐':'')+'</td><td>'+c.camera_name+'</td><td>'+c.camera_type+'</td>'
    +'<td><button onclick="edit(\\''+c.id+'\\')">✏️</button>'
    +'<button class="del" onclick="del(\\''+c.id+'\\')">🗑</button>'
    +'<button onclick="setActive(\\''+c.id+'\\')">⭐ aktif</button></td></tr>').join('');
}
function toggle(){
  const t=document.getElementById('camera_type').value;
  document.getElementById('c-usb').style.display=t==='usb'?'block':'none';
  document.getElementById('c-rtsp').style.display=t==='rtsp'?'block':'none';
  document.getElementById('c-file').style.display=t==='file'?'block':'none';
}
document.getElementById('camera_type').addEventListener('change',toggle);
function resetForm(){
  editId=null;document.getElementById('formtitle').textContent='Tambah kamera';
  document.getElementById('btnsave').textContent='💾 Tambah';
  document.getElementById('cid').disabled=false;document.getElementById('cid').value='';
  document.getElementById('camera_type').value='laptop';
  for(const k of F)document.getElementById(k).value=(k==='gallery'?'gallery/':'');
  for(const k of B)document.getElementById(k).checked=(k==='no_show');
  document.getElementById('msg').textContent='';toggle();
}
async function edit(id){
  const r=await fetch('/api/cameras');const s=await r.json();
  const c=s.cameras.find(x=>x.id===id);if(!c)return;
  editId=id;document.getElementById('formtitle').textContent='Ubah kamera '+id;
  document.getElementById('btnsave').textContent='💾 Simpan';
  document.getElementById('cid').value=id;document.getElementById('cid').disabled=true;
  document.getElementById('camera_type').value=c.camera_type;
  for(const k of F)document.getElementById(k).value=c[k]||'';
  for(const k of B)document.getElementById(k).checked=!!c[k];
  toggle();window.scrollTo(0,document.body.scrollHeight);
}
async function del(id){
  if(!confirm('Hapus kamera '+id+'?'))return;
  const r=await fetch('/api/cameras/'+id,{method:'DELETE'});const j=await r.json();
  showMsg(j.ok?'✅ dihapus':'❌ gagal',j.ok);load();
}
async function setActive(id){
  const r=await fetch('/api/active',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
  const j=await r.json();showMsg(j.ok?'⭐ kamera aktif: '+id:'❌ gagal',j.ok);load();
}
function showMsg(t,ok){const m=document.getElementById('msg');m.textContent=t;m.className=ok?'ok':'err';}
async function save(){
  const data={camera_type:document.getElementById('camera_type').value};
  if(!editId)data.id=document.getElementById('cid').value;
  for(const k of F)data[k]=document.getElementById(k).value;
  for(const k of B)data[k]=document.getElementById(k).checked;
  const url=editId?'/api/cameras/'+editId:'/api/cameras';
  const r=await fetch(url,{method:editId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const j=await r.json();
  if(j.ok){showMsg('✅ tersimpan',true);resetForm();load();}
  else showMsg('❌ '+j.errors.join('; '),false);
}
resetForm();load();
</script></body></html>"""

LIVE_HTML = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Live — Sakato Smart Monitor</title><style>""" + BASE_CSS + """</style></head>
<body>
<nav><a href="/">Dashboard</a><a href="/live" class="active">Live</a><a href="/config">Konfigurasi</a></nav>
<div class="brandbar"><div class="logo">S</div><h1 style="margin:0">Live <span class="accent">semua kamera</span></h1></div>
<p id="msg"></p>
<div id="wrap"></div>
<script>
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
async function act(id,a){
  const r=await fetch('/api/cameras/'+id+'/'+a,{method:'POST'});
  const j=await r.json();
  const m=document.getElementById('msg');
  m.textContent=j.message;m.className=j.ok?'ok':'err';
  refresh();
}
function card(c){
  const t=Date.now();
  return '<div class="card livecard">'
    +'<div class="head"><span class="dot '+(c.running?'on':'off')+'"></span>'
    +'<span class="nm">'+esc(c.camera_name)+'</span>'
    +'<span class="badge '+(c.running?'on':'off')+'">'+(c.running?'JALAN':'BERHENTI')+'</span></div>'
    +'<div class="snapwrap"><img class="snap" data-snap="'+c.id+'" src="/snapshot/'+c.id+'?t='+t+'" alt="belum ada snapshot"></div>'
    +'<div class="body"><span class="muted">ID: <code>'+esc(c.id)+'</code> · '+(c.running?'snapshot refresh tiap 3 detik':'pipeline berhenti')+'</span>'
    +'<div class="actions">'
    +(c.running
      ?'<button class="stop" onclick="act(\\''+c.id+'\\',\\'stop\\')">⏹ Stop</button>'
      :'<button class="start" onclick="act(\\''+c.id+'\\',\\'start\\')">▶ Start</button>')
    +'</div></div></div>';
}
async function refresh(){
  const r=await fetch('/api/status');const s=await r.json();
  const w=document.getElementById('wrap');
  if(!s.cameras.length){
    w.innerHTML='<div class="card empty"><h3>Belum ada kamera</h3>'
      +'<p>Tambahkan kamera dulu di halaman konfigurasi.</p>'
      +'<a href="/config">→ Buka Konfigurasi</a></div>';
    return;
  }
  w.innerHTML='<div class="grid">'+s.cameras.map(card).join('')+'</div>'
    +'<p class="muted">'+s.running_count+' dari '+s.cameras.length+' kamera berjalan</p>';
}
function tickSnap(){
  document.querySelectorAll('img[data-snap]').forEach(img=>{
    img.src='/snapshot/'+img.dataset.snap+'?t='+Date.now();
  });
}
setInterval(refresh,8000);setInterval(tickSnap,3000);refresh();
</script></body></html>"""

if __name__ == "__main__":
    print("Sakato Smart Monitor — web UI di http://localhost:8080")
    print("PERINGATAN: tanpa auth, hanya untuk LAN rumah.")
    app.run(host="0.0.0.0", port=8080, debug=False)
