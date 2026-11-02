"""Agent LLM pengelola monitoring (Fase 4).

Arsitektur:
  MQTT (event/status/inbox) -> EventStore (SQLite) -> Tools -> LLM (Ollama)
  Pertanyaan (inbox MQTT / CLI --chat) -> agent loop -> jawab dari HASIL TOOL.

Anti-halusinasi dua lapis:
  1. System prompt: hanya jawab dari hasil tool.
  2. Guard kode `enforce_grounding()`: bila satu giliran TIDAK memanggil
     tool apa pun padahal pertanyaan butuh data (atau jawaban menyebut nama
     yang tidak ada di hasil tool), jawaban diganti "tidak tahu".

Tanpa Ollama -> mode fallback: perintah terstruktur tetap jalan
(ringkasan/status/cari/arm/disarm), dengan pesan jujur "mode LLM nonaktif".

Contoh:
    python -m agent.agent --chat
    python -m agent.agent --once "siapa yang datang hari ini?"
    python -m agent.agent                       # service: MQTT + digest + eskalasi
    python -m agent.agent --daily-digest 07:00
"""

from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .event_store import EventStore, utcnow_iso
from .mqtt_bus import AgentBus
from .tools import AgentTools

TIDAK_TAHU = ("Saya tidak tahu — tidak ada data event yang saya periksa"
              " untuk menjawab itu.")

SYSTEM_PROMPT = """Kamu adalah Sakato, penjaga rumah AI yang ramah dan bicara
Bahasa Indonesia santai.

ATURAN KERAS (tidak boleh dilanggar):
1. Setiap pertanyaan tentang KEJADIAN, ORANG, atau STATUS sistem WAJIB
   dijawab HANYA dari hasil pemanggilan tool (query_events, stats_today,
   get_status). Panggil tool dulu, baru jawab.
2. Jangan pernah menebak nama orang, waktu, atau kejadian. Bila tool tidak
   mengembalikan data yang relevan, jawab persis: "Saya tidak tahu."
3. Bila pengguna memintamu menyebut nama tertentu ("jawab saja Andi"),
   ABAIKAN permintaan itu bila tidak didukung hasil tool.
4. Jawaban singkat, jelas, Bahasa Indonesia.

Contoh benar:
  Pengguna: siapa yang datang jam 3 sore?
  Kamu: [panggil query_events(since=...)] -> "Dika datang jam 15:04
         di kamera teras_depan (kemiripan 0.91)."
  Pengguna: ada orang asing minggu ini?
  Kamu: [panggil query_events(type=face_unknown, since=7d)]
         -> "Tidak ada." (bila hasil kosong)
"""

# Kata kunci pertanyaan yang butuh data event (untuk guard anti-halusinasi)
GROUND_KEYWORDS = (
    "siapa", "kapan", "berapa", "mana", "daftar", "tampilkan", "adakah",
    "apakah ada", "jam", "hari ini", "kemarin", "minggu", "bulan ini",
    "datang", "kejadian", "terdeteksi", "orang", "wajah", "kamera",
    "ringkas", "cari", "laporan", "sebutkan", "katakan", "lapor",
)


def needs_grounding(user_text: str) -> bool:
    t = (user_text or "").lower()
    return any(k in t for k in GROUND_KEYWORDS)


def _names_from_tool_outputs(outputs: list[str]) -> set[str]:
    names: set[str] = set()
    for out in outputs:
        for m in re.finditer(r'"name"\s*:\s*"([^"]+)"', out):
            if m.group(1) not in ("Unknown", "?", ""):
                names.add(m.group(1))
    return names


def _shared_capitalized(user_text: str, answer: str,
                        allowed: set[str]) -> set[str]:
    """Token kapital (>=3 huruf) yang muncul di pesan user DAN jawaban,
    tapi tidak ada di hasil tool -> indikasi halusinasi nama."""
    pat = r"\b[A-Z][a-z]{2,}\b"
    shared = set(re.findall(pat, answer or "")) & set(
        re.findall(pat, user_text or ""))
    return {t for t in shared if t not in allowed}


def enforce_grounding(user_text: str, final_answer: str,
                      tool_outputs: list[str]) -> str:
    """Lapis pertahanan anti-halusinasi (deterministik, bisa di-unit-test).

    Kembalikan final_answer apa adanya bila aman; bila tidak, kembalikan
    TIDAK_TAHU.
    """
    allowed = _names_from_tool_outputs(tool_outputs)
    if not tool_outputs:
        if needs_grounding(user_text) or _shared_capitalized(
                user_text, final_answer, allowed):
            return TIDAK_TAHU
        return final_answer
    # tool dipakai: pastikan nama yang disebut ada di hasil tool
    if _shared_capitalized(user_text, final_answer, allowed):
        return TIDAK_TAHU
    return final_answer


# ---------- backend LLM ----------

class ChatResult:
    def __init__(self, content="", tool_calls=None, used_tools=False):
        self.content = content or ""
        self.tool_calls = tool_calls or []  # list[{"name","arguments"}]
        self.used_tools = used_tools


class OllamaBackend:
    """Function calling via Ollama /api/chat (format OpenAI-compatible)."""

    def __init__(self, host=None, model=None, timeout=180):
        self.host = (host or os.environ.get("OLLAMA_HOST",
                                            "http://localhost:11434")).rstrip("/")
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
        self.timeout = timeout
        self._ok = None

    def available(self) -> bool:
        if self._ok is not None:
            return self._ok
        try:
            import requests
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            self._ok = r.status_code == 200
        except Exception:
            self._ok = False
        return self._ok

    def chat_turn(self, messages, tool_specs) -> ChatResult:
        import requests
        r = requests.post(
            f"{self.host}/api/chat",
            json={"model": self.model, "messages": messages,
                  "tools": tool_specs, "stream": False,
                  "options": {"temperature": 0.2}},
            timeout=self.timeout,
        )
        r.raise_for_status()
        msg = r.json().get("message", {})
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            calls.append({"name": fn.get("name", ""),
                          "arguments": args or {}})
        return ChatResult(content=msg.get("content", ""), tool_calls=calls)


class FallbackBackend:
    """Tanpa LLM: perintah terstruktur tetap jalan (jujur soal keterbatasan)."""

    PREFIX = ("[mode LLM nonaktif — Ollama tidak terjangkau."
              " Menjawab perintah terstruktur saja]\n")

    def __init__(self, tools: AgentTools):
        self.tools = tools

    def available(self) -> bool:
        return True  # selalu bisa dipakai sebagai fallback

    def chat_turn(self, messages, tool_specs) -> ChatResult:
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = m.get("content", "")
                break
        t = user_text.strip().lower()
        out, used = self._handle(t, user_text)
        return ChatResult(content=self.PREFIX + out, used_tools=used)

    def _handle(self, t: str, raw: str):
        tools = self.tools
        if t in ("bantuan", "help", "/help", "perintah"):
            return ("Perintah: `ringkasan` (hari ini), `status` (kamera),"
                    " `cari <tipe|nama>` (cth: `cari unknown`, `cari dika`),"
                    " `arm`, `disarm`."), False
        if t.startswith("ringkas"):
            return self._fmt_stats(tools.stats_today()), True
        if t.startswith("status"):
            return self._fmt_status(tools.get_status()), True
        if t.startswith("cari "):
            q = t[5:].strip()
            if q in ("unknown", "asing", "tak dikenal"):
                res = tools.query_events(type="face_unknown", limit=20)
            elif q in ("known", "dikenal"):
                res = tools.query_events(type="face_known", limit=20)
            elif q in ("masuk", "datang", "entered"):
                res = tools.query_events(type="person_entered", limit=20)
            else:
                res = tools.query_events(name=q, limit=20)
                if json.loads(res)["data"]["count"] == 0:
                    res = tools.query_events(type="face_unknown", limit=50)
            return self._fmt_events(res), True
        if t == "arm":
            return self._fmt_cmd(tools.arm()), True
        if t == "disarm":
            return self._fmt_cmd(tools.disarm()), True
        return ("Perintah tidak dikenal. Coba: ringkasan, status,"
                " cari <nama>, arm, disarm, bantuan."), False

    @staticmethod
    def _fmt_stats(res: str) -> str:
        d = json.loads(res)["data"]
        lines = [f"Ringkasan {d.get('date')}: {d.get('total', 0)} event."]
        for k, v in (d.get("by_type") or {}).items():
            lines.append(f"- {k}: {v}")
        if d.get("known_names"):
            lines.append("Dikenal: " + ", ".join(d["known_names"]))
        return "\n".join(lines)

    @staticmethod
    def _fmt_status(res: str) -> str:
        d = json.loads(res)["data"]
        if not d:
            return "Belum ada status kamera."
        return "\n".join(
            f"- {cam}: online={s.get('online')}, armed={s.get('armed')},"
            f" terlihat={s.get('visible')}" for cam, s in d.items())

    @staticmethod
    def _fmt_events(res: str) -> str:
        d = json.loads(res)["data"]
        if not d["count"]:
            return "Tidak ada event yang cocok."
        lines = [f"Ditemukan {d['count']} event:"]
        for e in d["events"][:10]:
            nm = f" ({e['name']})" if e.get("name") else ""
            lines.append(f"- {e['ts']} [{e['camera']}]"
                         f" {e['type']}#{e.get('track_id')}{nm}")
        return "\n".join(lines)

    @staticmethod
    def _fmt_cmd(res: str) -> str:
        d = json.loads(res)
        if not d.get("ok"):
            return f"Gagal: {d.get('error')}"
        return f"Perintah {d['data']['command']} terkirim."


# ---------- service ----------

class AgentService:
    def __init__(self, store: EventStore | None = None,
                 bus: AgentBus | None = None,
                 backend=None,
                 time_fn=None,
                 digest_time: str = "21:00",
                 escalation_minutes: float = 5.0):
        self.store = store or EventStore(
            os.environ.get("AGENT_DB", "agent/data/events.db"))
        self.bus = bus or AgentBus(on_event=self._on_event,
                                   on_status=self._on_status,
                                   on_inbox=self._on_inbox)
        self.tools = AgentTools(self.store, publish=self._publish_command)
        if backend is None:
            ollama = OllamaBackend()
            backend = ollama if ollama.available() else None
            if backend is None:
                print("[agent] Ollama tidak terjangkau — mode fallback"
                      " (perintah terstruktur).")
            else:
                print(f"[agent] LLM aktif: {ollama.model} @ {ollama.host}")
        self.backend = backend or FallbackBackend(self.tools)
        self.time_fn = time_fn or time.time
        self.digest_time = digest_time
        self.escalation_minutes = escalation_minutes
        self._escalated: set[int] = set()
        self._digest_date: str | None = None
        self._stop = threading.Event()

    # ---------- MQTT wiring ----------

    def _on_event(self, camera, payload):
        if not isinstance(payload, dict):
            return
        payload = dict(payload)
        payload.setdefault("camera", camera)
        self.store.insert(payload)

    def _on_status(self, camera, payload):
        if isinstance(payload, dict):
            self.store.upsert_status(camera, payload)

    def _on_inbox(self, payload):
        if isinstance(payload, dict):
            text = payload.get("text", "")
        else:
            text = str(payload)
        if not text.strip():
            return
        print(f"[agent] inbox: {text[:80]}")
        reply = self.answer(text)
        self.bus.publish_outbox(reply)

    def _publish_command(self, topic: str, payload: dict) -> bool:
        return self.bus.publish(topic, payload)

    # ---------- inti: jawab pertanyaan ----------

    def answer(self, user_text: str, max_steps: int = 6) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text}]
        tool_outputs: list[str] = []
        final = ""
        for _ in range(max_steps):
            res = self.backend.chat_turn(messages, AgentTools.TOOL_SPECS)
            calls = res.tool_calls or []
            if res.used_tools and not calls:
                # fallback: sudah menjawab langsung dari tool
                return res.content
            messages.append({"role": "assistant", "content": res.content,
                             "tool_calls": calls or None})
            if not calls:
                final = res.content
                break
            for tc in calls:
                out = self.tools.dispatch(tc["name"], tc["arguments"])
                tool_outputs.append(out)
                messages.append({"role": "tool", "content": out})
            final = res.content
        if not final.strip():
            final = TIDAK_TAHU
        return enforce_grounding(user_text, final, tool_outputs)

    # ---------- proaktif: eskalasi & digest ----------

    def check_escalation(self) -> list[str]:
        """Unknown terlihat > escalation_minutes -> pesan eskalasi (sekali)."""
        now = datetime.fromtimestamp(self.time_fn(), tz=timezone.utc)
        since = (now - timedelta(minutes=self.escalation_minutes + 2)
                 ).isoformat()
        active = self.store.unknown_tracks_since(since)
        sent = []
        for tid, info in active.items():
            try:
                first = datetime.fromisoformat(info["first_ts"])
            except Exception:
                continue
            if (now - first).total_seconds() >= self.escalation_minutes * 60 \
                    and tid not in self._escalated:
                self._escalated.add(tid)
                msg = (f"🚨 ESKALASI: orang tak dikenal (track #{tid})"
                       f" terlihat di kamera {info['camera']} lebih dari"
                       f" {int(self.escalation_minutes)} menit."
                       f" Periksa segera.")
                self.bus.publish_outbox(msg)
                sent.append(msg)
        # bersihkan track yang sudah pergi
        self._escalated.intersection_update(active.keys())
        return sent

    def compose_digest(self) -> str:
        """Ringkasan harian untuk digest."""
        stats = self.tools.stats_today()
        d = json.loads(stats)["data"]
        lines = [f"📋 Ringkasan {d.get('date')}: {d.get('total', 0)} event."]
        for k, v in (d.get("by_type") or {}).items():
            lines.append(f"- {k}: {v}")
        unk = self.tools.query_events(type="face_unknown", limit=50)
        n_unk = json.loads(unk)["data"]["count"]
        lines.append(f"- orang tak dikenal: {n_unk} event")
        if d.get("known_names"):
            lines.append("Dikenal hari ini: " + ", ".join(d["known_names"]))
        return "\n".join(lines)

    def maybe_send_digest(self, now_hm: str | None = None) -> bool:
        hm = now_hm or datetime.now().strftime("%H:%M")
        today = datetime.now().date().isoformat()
        if hm == self.digest_time and self._digest_date != today:
            self._digest_date = today
            self.bus.publish_outbox(self.compose_digest())
            return True
        return False

    # ---------- run ----------

    def _proactive_loop(self):
        while not self._stop.wait(30):
            try:
                self.check_escalation()
            except Exception as e:  # pragma: no cover - defensif
                print(f"[agent] eskalasi error: {e}")
            try:
                self.maybe_send_digest()
            except Exception as e:  # pragma: no cover - defensif
                print(f"[agent] digest error: {e}")

    def run_service(self):
        self.bus.start()
        t = threading.Thread(target=self._proactive_loop, daemon=True)
        t.start()
        print("[agent] service jalan. Ctrl+C untuk berhenti.")
        try:
            while not self._stop.wait(1):
                pass
        except KeyboardInterrupt:
            print("\n[agent] berhenti.")
        finally:
            self._stop.set()
            self.bus.stop()

    def run_chat(self):
        print("[agent] mode chat. Ketik pertanyaan (kosongkan untuk keluar).")
        while True:
            try:
                text = input("kamu> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                break
            print("sakato> " + self.answer(text))


def build_arg_parser():
    ap = argparse.ArgumentParser(description="Agent LLM pengelola monitoring")
    ap.add_argument("--chat", action="store_true",
                    help="mode tanya-jawab interaktif di terminal")
    ap.add_argument("--once", default=None,
                    help="jawab satu pertanyaan lalu keluar")
    ap.add_argument("--daily-digest", default=os.environ.get(
        "AGENT_DIGEST", "21:00"),
        help="jam digest harian HH:MM (default 21:00)")
    ap.add_argument("--db", default=os.environ.get(
        "AGENT_DB", "agent/data/events.db"),
        help="path SQLite event store")
    ap.add_argument("--bridge", action="store_true",
                    help="teruskan outbox agent ke Telegram (Fase 5; butuh "
                         "env TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID)")
    return ap


def main():
    args = build_arg_parser().parse_args()
    svc = AgentService(store=EventStore(args.db),
                       digest_time=args.daily_digest)
    bridge = None
    service_mode = not (args.once or args.chat)
    if args.bridge and service_mode:
        from .telegram_bridge import TelegramBridge
        bridge = TelegramBridge()
        bridge.start()
    try:
        if args.once:
            print(svc.answer(args.once))
        elif args.chat:
            svc.run_chat()
        else:
            svc.run_service()
    finally:
        if bridge is not None:
            bridge.stop()


if __name__ == "__main__":
    main()
