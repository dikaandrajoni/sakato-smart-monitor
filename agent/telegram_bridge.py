"""Bridge outbox agent -> Telegram (Fase 5).

Subscribe `sakato/monitor/agent/outbox`, teruskan teks ke chat Telegram
via Bot API langsung (requests — tanpa menambah dependensi, tanpa
asyncio). Token & chat ID dari env TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
(hormati file .env).

Dipakai agar digest harian & eskalasi agent (Fase 4) sampai ke HP Boss:
    python -m agent.agent --bridge

Pola graceful seperti modul lain: tanpa token -> nonaktif dengan
peringatan; tanpa broker -> warning sekali, tetap jalan.
"""

from __future__ import annotations

import os
import threading

try:
    import paho.mqtt.client as mqtt
    _MQTT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MQTT_AVAILABLE = False

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REQUESTS_AVAILABLE = False

OUTBOX_TOPIC = "sakato/monitor/agent/outbox"
TG_LIMIT = 4096  # batas karakter per pesan Bot API


def split_message(text: str, limit: int = TG_LIMIT) -> list[str]:
    """Potong pesan panjang per baris agar tidak melebihi limit."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        parts.append(cur)
    return parts or [text]


class TelegramBridge:
    def __init__(self, token=None, chat_id=None,
                 host=None, port=None, user=None, password=None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.host = host or os.environ.get("MQTT_HOST", "localhost")
        try:
            self.port = int(port or os.environ.get("MQTT_PORT", "1883"))
        except ValueError:
            self.port = 1883
        self.user = user if user is not None else os.environ.get("MQTT_USER", "")
        self.password = (password if password is not None
                         else os.environ.get("MQTT_PASSWORD", ""))

        self.enabled = bool(self.token and self.chat_id) \
            and _MQTT_AVAILABLE and _REQUESTS_AVAILABLE
        if not self.enabled:
            missing = []
            if not (self.token and self.chat_id):
                missing.append("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID")
            if not _MQTT_AVAILABLE:
                missing.append("paho-mqtt")
            if not _REQUESTS_AVAILABLE:
                missing.append("requests")
            print("[bridge] NONAKTIF (kurang: "
                  + ", ".join(missing) + ").")

        self._client = None
        self._warned = False
        self._started = False
        self._lock = threading.Lock()

        if self.enabled:
            self._client = mqtt.Client(client_id="sakato-tg-bridge")
            if self.user:
                self._client.username_pw_set(self.user, self.password or None)
            self._client.reconnect_delay_set(min_delay=1, max_delay=30)
            self._client.on_connect = self._on_connect
            self._client.on_connect_fail = lambda c, u: self._warn_once(
                "tidak bisa terhubung ke broker")
            self._client.on_message = self._on_message

    # ---------- internal ----------

    def _warn_once(self, msg):
        with self._lock:
            if not self._warned:
                self._warned = True
                print(f"[bridge] PERINGATAN: {msg} "
                      f"({self.host}:{self.port}) — bridge tetap jalan.")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            with self._lock:
                self._warned = False
            print(f"[bridge] terhubung ke broker {self.host}:{self.port}, "
                  f"mendengar {OUTBOX_TOPIC}")
            client.subscribe(OUTBOX_TOPIC, qos=1)
        else:
            self._warn_once(f"koneksi ditolak broker (rc={rc})")

    def _on_message(self, client, userdata, msg):
        try:
            import json
            payload = json.loads(msg.payload.decode("utf-8"))
            text = payload.get("text", "") if isinstance(payload, dict) \
                else str(payload)
        except Exception:
            text = msg.payload.decode("utf-8", errors="replace")
        if text and text.strip():
            self.forward(text)

    def forward(self, text: str) -> bool:
        """Kirim teks ke Telegram. True bila seluruh potongan terkirim."""
        if not self.enabled:
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        ok = True
        for part in split_message(text):
            try:
                r = requests.post(url, json={"chat_id": self.chat_id,
                                             "text": part},
                                  timeout=15)
                ok = ok and r.status_code == 200
            except Exception as e:
                print(f"[bridge] gagal kirim ke Telegram: {e}")
                return False
        return ok

    # ---------- lifecycle ----------

    def start(self):
        if not self.enabled or self._started:
            return False
        self._started = True
        try:
            self._client.connect_async(self.host, self.port, keepalive=30)
            self._client.loop_start()
            print("[bridge] bridge outbox->Telegram berjalan.")
            return True
        except Exception as e:
            self._warn_once(f"gagal memulai koneksi: {e}")
            return False

    def stop(self):
        if self._client is not None and self._started:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._started = False
