"""Web UI konfigurasi Sakato Smart Monitor.

Jalankan:
    cd web
    python -m venv .venv && source .venv/bin/activate   # sekali saja
    pip install -r requirements.txt                     # sekali saja
    python app.py

Buka: http://localhost:8080

Fitur: pilih sumber kamera (laptop/USB/RTSP CCTV/file), atur nama kamera,
telegram/mqtt/describe, start/stop pipeline, lihat event terakhir & log.

PERINGATAN: tanpa autentikasi. Hanya untuk LAN rumah — JANGAN expose ke internet.
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from subprocess import Popen, STDOUT, TimeoutExpired

from flask import Flask, jsonify, render_template_string, request

WEB_DIR = Path(__file__).resolve().parent
ROOT = WEB_DIR.parent
CONFIG_PATH = WEB_DIR / "config.json"
LOG_PATH = WEB_DIR / "pipeline.log"
EVENTS_PATH = ROOT / "prototype" / "events.jsonl"

DEFAULT_CONFIG = {
    "camera_type": "laptop",  # laptop | usb | rtsp | file
    "usb_index": "1",
    "rtsp_url": "",
    "video_file": "",
    "camera_name": "teras_depan",
    "gallery": "gallery/",
    "telegram": False,
    "mqtt": False,
    "describe": False,
    "no_show": False,
}

CAMERA_TYPES = ("laptop", "usb", "rtsp", "file")
BOOL_KEYS = ("telegram", "mqtt", "describe", "no_show")

_proc = None
_lock = threading.Lock()


# ---------- config ----------

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.exists():
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k in DEFAULT_CONFIG:
                if k in saved:
                    cfg[k] = saved[k]
    except (json.JSONDecodeError, OSError):
        pass
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False),
                           encoding="utf-8")


def resolve_source(cfg):
    """Kembalikan string --source untuk prototype/main.py."""
    ct = cfg.get("camera_type", "laptop")
    if ct == "usb":
        return str(cfg.get("usb_index", "1")).strip() or "1"
    if ct == "rtsp":
        return str(cfg.get("rtsp_url", "")).strip()
    if ct == "file":
        return str(cfg.get("video_file", "")).strip()
    return "0"


def validate_config(data):
    """Kembalikan (config_bersih, errors)."""
    errors = []
    cfg = dict(DEFAULT_CONFIG)

    ct = str(data.get("camera_type", "laptop")).strip()
    if ct not in CAMERA_TYPES:
        errors.append(f"camera_type tidak valid: {ct!r}")
        ct = "laptop"
    cfg["camera_type"] = ct

    if ct == "rtsp":
        url = str(data.get("rtsp_url", "")).strip()
        if not url:
            errors.append("URL RTSP wajib diisi untuk tipe kamera RTSP.")
        elif not url.startswith("rtsp://"):
            errors.append("URL RTSP harus diawali 'rtsp://'.")
        cfg["rtsp_url"] = url
    elif ct == "usb":
        idx = str(data.get("usb_index", "")).strip()
        if not idx.isdigit():
            errors.append("Index USB harus angka (contoh: 1).")
        cfg["usb_index"] = idx or "1"
    elif ct == "file":
        vf = str(data.get("video_file", "")).strip()
        if not vf:
            errors.append("Path file video wajib diisi untuk tipe kamera file.")
        cfg["video_file"] = vf

    name = str(data.get("camera_name", "")).strip()
    if not name:
        errors.append("Nama kamera wajib diisi.")
    cfg["camera_name"] = name or DEFAULT_CONFIG["camera_name"]

    gal = str(data.get("gallery", "")).strip()
    cfg["gallery"] = gal or DEFAULT_CONFIG["gallery"]

    for k in BOOL_KEYS:
        cfg[k] = bool(data.get(k, False))

    return cfg, errors


# ---------- pipeline ----------

def venv_python():
    proto = ROOT / "prototype"
    if os.name == "nt":
        return str(proto / ".venv" / "Scripts" / "python.exe")
    return str(proto / ".venv" / "bin" / "python")


def build_args(cfg):
    args = [venv_python(), "main.py",
            "--source", resolve_source(cfg),
            "--camera-name", cfg["camera_name"],
            "--gallery", cfg["gallery"]]
    for key in BOOL_KEYS:
        if cfg.get(key):
            args.append("--" + key.replace("_", "-"))
    return args


def pipeline_running():
    return _proc is not None and _proc.poll() is None


def start_pipeline(cfg):
    """Jalankan prototype/main.py sebagai subprocess. Kembalikan (ok, pesan)."""
    global _proc
    with _lock:
        if pipeline_running():
            return False, "pipeline sudah berjalan"
        logf = open(LOG_PATH, "ab")
        try:
            logf.write(f"\n===== start {datetime.now().isoformat()} "
                       f"source={resolve_source(cfg)} =====\n".encode())
            logf.flush()
            _proc = Popen(build_args(cfg), cwd=str(ROOT / "prototype"),
                          stdout=logf, stderr=STDOUT)
        except OSError as e:
            logf.close()
            return False, f"gagal start: {e}"
        return True, f"pipeline dimulai (pid {_proc.pid})"


def stop_pipeline():
    """Hentikan pipeline. Kembalikan (ok, pesan)."""
    global _proc
    with _lock:
        if not pipeline_running():
            return False, "pipeline tidak sedang berjalan"
        _proc.terminate()
        try:
            _proc.wait(timeout=10)
            msg = "pipeline dihentikan"
        except TimeoutExpired:
            _proc.kill()
            msg = "pipeline di-kill paksa"
        _proc = None
        return True, msg


def tail_events(n=10):
    events = []
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
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


def tail_log(n=50):
    try:
        lines = LOG_PATH.read_text(encoding="utf-8",
                                   errors="replace").splitlines()
    except OSError:
        return []
    return lines[-n:]


# ---------- app ----------

def create_app():
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.get("/config")
    def config_page():
        return render_template_string(CONFIG_HTML)

    @app.get("/api/status")
    def api_status():
        return jsonify({
            "running": pipeline_running(),
            "config": load_config(),
            "events": tail_events(10),
            "log_tail": tail_log(50),
        })

    @app.post("/api/config")
    def api_config():
        data = request.get_json(force=True, silent=True) or {}
        cfg, errors = validate_config(data)
        if errors:
            return jsonify({"ok": False, "errors": errors}), 400
        save_config(cfg)
        return jsonify({"ok": True, "config": cfg})

    @app.post("/api/start")
    def api_start():
        ok, msg = start_pipeline(load_config())
        return jsonify({"ok": ok, "message": msg}), 200 if ok else 409

    @app.post("/api/stop")
    def api_stop():
        ok, msg = stop_pipeline()
        return jsonify({"ok": ok, "message": msg}), 200 if ok else 409

    return app


app = create_app()

# ---------- templates ----------

BASE_CSS = """
body{font-family:system-ui,sans-serif;max-width:900px;margin:0 auto;padding:16px;background:#111;color:#eee}
nav{margin-bottom:16px}a{color:#7fd4ff;margin-right:12px}
.card{background:#1c1c1c;border:1px solid #333;border-radius:8px;padding:16px;margin-bottom:16px}
.badge{display:inline-block;padding:4px 12px;border-radius:12px;font-weight:bold}
.on{background:#14532d;color:#86efac}.off{background:#3f3f3f;color:#ccc}
button{padding:8px 16px;margin:4px;border-radius:6px;border:0;cursor:pointer;font-size:14px}
.start{background:#16a34a;color:#fff}.stop{background:#dc2626;color:#fff}.save{background:#2563eb;color:#fff}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border-bottom:1px solid #333;padding:6px;text-align:left}
pre{background:#000;padding:12px;border-radius:6px;max-height:300px;overflow:auto;font-size:12px;white-space:pre-wrap}
label{display:block;margin:10px 0 4px}input,select{padding:8px;width:100%;max-width:420px;background:#222;color:#eee;border:1px solid #444;border-radius:6px}
input[type=checkbox]{width:auto;transform:scale(1.3);margin-right:8px}
.cond{display:none}.err{color:#f87171}.ok{color:#86efac}
"""

DASHBOARD_HTML = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sakato Smart Monitor</title><style>""" + BASE_CSS + """</style></head>
<body>
<nav><a href="/">Dashboard</a><a href="/config">Konfigurasi</a></nav>
<h1>Sakato Smart Monitor</h1>
<div class="card">
  <span id="badge" class="badge off">memuat...</span>
  <span id="src" style="margin-left:12px;color:#aaa"></span>
  <div style="margin-top:12px">
    <button class="start" onclick="act('start')">▶ Start</button>
    <button class="stop" onclick="act('stop')">⏹ Stop</button>
  </div>
  <p id="msg"></p>
</div>
<div class="card"><h3>10 event terakhir</h3><table>
<thead><tr><th>Waktu</th><th>Tipe</th><th>Track</th><th>Nama</th></tr></thead>
<tbody id="events"><tr><td colspan="4">memuat...</td></tr></tbody></table></div>
<div class="card"><h3>Log pipeline (50 baris terakhir)</h3><pre id="log">memuat...</pre></div>
<script>
async function act(a){
  const r=await fetch('/api/'+a,{method:'POST'});const j=await r.json();
  document.getElementById('msg').textContent=j.message;
  document.getElementById('msg').className=j.ok?'ok':'err';refresh();
}
async function refresh(){
  const r=await fetch('/api/status');const s=await r.json();
  const b=document.getElementById('badge');
  b.textContent=s.running?'BERJALAN':'BERHENTI';
  b.className='badge '+(s.running?'on':'off');
  document.getElementById('src').textContent='sumber: '+s.config.camera_type+' | kamera: '+s.config.camera_name;
  const tb=document.getElementById('events');
  tb.innerHTML=s.events.length?s.events.map(e=>'<tr><td>'+(e.ts||'-')+'</td><td>'+(e.type||'-')+'</td><td>'+(e.track_id??'-')+'</td><td>'+(e.name||'-')+'</td></tr>').join(''):'<tr><td colspan="4">belum ada event</td></tr>';
  document.getElementById('log').textContent=s.log_tail.join('\\n')||'(log kosong)';
}
setInterval(refresh,5000);refresh();
</script></body></html>"""

CONFIG_HTML = """<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Konfigurasi — Sakato Smart Monitor</title><style>""" + BASE_CSS + """</style></head>
<body>
<nav><a href="/">Dashboard</a><a href="/config">Konfigurasi</a></nav>
<h1>Konfigurasi</h1>
<div class="card">
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
<label>Nama kamera</label><input id="camera_name">
<label>Folder galeri wajah</label><input id="gallery">
<label><input type="checkbox" id="telegram"> Notifikasi Telegram</label>
<label><input type="checkbox" id="mqtt"> Publisher MQTT</label>
<label><input type="checkbox" id="describe"> Deskripsi VLM (butuh Ollama)</label>
<label><input type="checkbox" id="no_show"> Tanpa jendela GUI (headless)</label>
<div style="margin-top:16px"><button class="save" onclick="save()">💾 Simpan</button></div>
<p id="msg"></p>
<p style="color:#aaa;font-size:13px">Config tersimpan di <code>web/config.json</code>
(berisi kredensial RTSP — jangan di-commit, sudah di-.gitignore).</p>
</div>
<script>
let cfg={};
async function load(){
  const r=await fetch('/api/status');const s=await r.json();cfg=s.config;fill();
}
  document.getElementById('camera_type').value=cfg.camera_type||'laptop';
  for(const k of ['usb_index','rtsp_url','video_file','camera_name','gallery'])
    document.getElementById(k).value=cfg[k]||'';
  for(const k of ['telegram','mqtt','describe','no_show'])
    document.getElementById(k).checked=!!cfg[k];
  toggle();
}
function toggle(){
  const t=document.getElementById('camera_type').value;
  document.getElementById('c-usb').style.display=t==='usb'?'block':'none';
  document.getElementById('c-rtsp').style.display=t==='rtsp'?'block':'none';
  document.getElementById('c-file').style.display=t==='file'?'block':'none';
}
document.getElementById('camera_type').addEventListener('change',toggle);
async function save(){
  const data={camera_type:document.getElementById('camera_type').value};
  for(const k of ['usb_index','rtsp_url','video_file','camera_name','gallery'])
    data[k]=document.getElementById(k).value;
  for(const k of ['telegram','mqtt','describe','no_show'])
    data[k]=document.getElementById(k).checked;
  const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const j=await r.json();
  const m=document.getElementById('msg');
  if(j.ok){m.textContent='✅ tersimpan';m.className='ok';}
  else{m.textContent='❌ '+j.errors.join('; ');m.className='err';}
}
load();
</script></body></html>"""

if __name__ == "__main__":
    print("Sakato Smart Monitor — web UI di http://localhost:8080")
    print("PERINGATAN: tanpa auth, hanya untuk LAN rumah.")
    app.run(host="0.0.0.0", port=8080, debug=False)
