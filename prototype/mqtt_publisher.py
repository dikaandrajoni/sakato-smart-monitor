"""Publisher MQTT untuk event & status monitoring (Fase 3).

Topik:
  sakato/monitor/<camera>/event   JSON event (tidak retain)
  sakato/monitor/<camera>/status  JSON status terakhir (retain)

Konfigurasi dari environment (hormati file .env — main.py sudah load_dotenv):
  MQTT_HOST      default "localhost"
  MQTT_PORT      default 1883
  MQTT_USER      default "" (tanpa auth)
  MQTT_PASSWORD  default ""

Pola graceful seperti TelegramNotifier: bila broker tidak terjangkau,
cetak peringatan sekali lalu program tetap jalan; paho-mqtt mencoba
reconnect otomatis di background (loop_start + reconnect_delay_set).
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone

try:
    import paho.mqtt.client as mqtt
    _MQTT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MQTT_AVAILABLE = False


def sanitize_camera(name: str) -> str:
    """Jadikan nama kamera aman untuk topik MQTT."""
    s = (name or "kamera").strip().lower().replace(" ", "_")
    s = re.sub(r"[^a-z0-9_/-]", "", s)
    return s or "kamera"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MqttPublisher:
    def __init__(self, host=None, port=None, user=None, password=None,
                 client_id=None):
        self.host = host or os.environ.get("MQTT_HOST", "localhost")
        try:
            self.port = int(port or os.environ.get("MQTT_PORT", "1883"))
        except ValueError:
            self.port = 1883
        self.user = user if user is not None else os.environ.get("MQTT_USER", "")
        self.password = (password if password is not None
                         else os.environ.get("MQTT_PASSWORD", ""))

        self.enabled = _MQTT_AVAILABLE
        if not self.enabled:  # pragma: no cover
            print("[mqtt] NONAKTIF: paho-mqtt belum terinstall "
                  "(pip install -r requirements.txt).")

        self._client = None
        self._connected = threading.Event()
        self._warned = False
        self._started = False
        self._lock = threading.Lock()

        if self.enabled:
            cid = client_id or "sakato-monitor"
            self._client = mqtt.Client(client_id=cid)
            if self.user:
                self._client.username_pw_set(self.user, self.password or None)
            # Reconnect otomatis dengan backoff bila broker putus.
            self._client.reconnect_delay_set(min_delay=1, max_delay=30)
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            # Dipanggil paho setiap upaya (re)connect gagal — termasuk saat
            # broker belum ada sejak awal (connect_async tidak me-raise).
            self._client.on_connect_fail = self._on_connect_fail

    # ---------- koneksi ----------

    def _warn_once(self, msg):
        with self._lock:
            if not self._warned:
                self._warned = True
                print(f"[mqtt] PERINGATAN: {msg} "
                      f"({self.host}:{self.port}) — program tetap jalan, "
                      "reconnect otomatis di background.")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected.set()
            with self._lock:
                self._warned = False  # episode baru boleh warning lagi
            print(f"[mqtt] terhubung ke broker {self.host}:{self.port}")
        else:
            self._warn_once(f"koneksi ditolak broker (rc={rc})")

    def _on_disconnect(self, client, userdata, rc):
        self._connected.clear()
        if rc != 0:
            self._warn_once("koneksi ke broker terputus")

    def _on_connect_fail(self, client, userdata):
        self._warn_once("tidak bisa terhubung ke broker")

    def start(self):
        """Koneksi non-blokir. Aman dipanggil walau broker belum ada."""
        if not self.enabled or self._started:
            return
        self._started = True
        try:
            # connect_async: tidak blokir; loop_start menjalankan network loop
            # di thread sendiri (termasuk auto-reconnect).
            self._client.connect_async(self.host, self.port, keepalive=30)
            self._client.loop_start()
        except Exception as e:  # mis. DNS/host tidak dikenal
            self._warn_once(f"gagal memulai koneksi: {e}")

    def stop(self):
        if self._client is not None and self._started:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._started = False

    @property
    def connected(self):
        return self._connected.is_set()

    # ---------- publish ----------

    def _publish(self, topic, payload, qos=1, retain=False):
        if not self.enabled or not self._started:
            return False
        try:
            info = self._client.publish(topic, payload, qos=qos, retain=retain)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            self._warn_once(f"gagal publish ke {topic}: {e}")
            return False

    def publish_event(self, camera, event_type, track_id,
                      name=None, similarity=None):
        """Kirim satu event deteksi. Kembalikan True bila berhasil di-queue."""
        cam = sanitize_camera(camera)
        payload = {
            "ts": utcnow_iso(),
            "type": event_type,          # person_entered | person_left |
                                    # face_known | face_unknown
            "track_id": track_id,
            "camera": cam,
        }
        if name is not None:
            payload["name"] = name
        if similarity is not None:
            payload["similarity"] = round(float(similarity), 3)
        topic = f"sakato/monitor/{cam}/event"
        return self._publish(topic, json.dumps(payload, ensure_ascii=False))

    def publish_status(self, camera, online=True, armed=True, visible=0):
        """Status retain: online/offline, armed, jumlah orang terlihat."""
        cam = sanitize_camera(camera)
        payload = {
            "ts": utcnow_iso(),
            "camera": cam,
            "online": bool(online),
            "armed": bool(armed),
            "visible": int(visible),
        }
        topic = f"sakato/monitor/{cam}/status"
        return self._publish(topic, json.dumps(payload, ensure_ascii=False),
                             qos=1, retain=True)
