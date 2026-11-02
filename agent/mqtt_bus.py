"""Klien MQTT untuk agent (Fase 4).

Satu koneksi untuk:
  subscribe  sakato/monitor/+/event    -> event deteksi
  subscribe  sakato/monitor/+/status   -> status kamera (retain)
  subscribe  sakato/monitor/agent/inbox -> pesan masuk untuk agent
  publish    sakato/monitor/agent/outbox
  publish    sakato/monitor/command (+ per kamera)

Pola graceful seperti modul lain: bila broker tak ada, warning sekali,
program tetap jalan; reconnect otomatis via paho.
"""

from __future__ import annotations

import json
import os
import threading

try:
    import paho.mqtt.client as mqtt
    _MQTT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MQTT_AVAILABLE = False


class AgentBus:
    def __init__(self, on_event=None, on_status=None, on_inbox=None,
                 host=None, port=None, user=None, password=None):
        self.host = host or os.environ.get("MQTT_HOST", "localhost")
        try:
            self.port = int(port or os.environ.get("MQTT_PORT", "1883"))
        except ValueError:
            self.port = 1883
        self.user = user if user is not None else os.environ.get("MQTT_USER", "")
        self.password = (password if password is not None
                         else os.environ.get("MQTT_PASSWORD", ""))

        self.on_event = on_event      # fn(camera, payload_dict)
        self.on_status = on_status    # fn(camera, payload_dict)
        self.on_inbox = on_inbox      # fn(payload_dict | str)

        self.enabled = _MQTT_AVAILABLE
        self._client = None
        self._warned = False
        self._started = False
        self._lock = threading.Lock()

        if self.enabled:
            self._client = mqtt.Client(client_id="sakato-agent")
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
                print(f"[agent-bus] PERINGATAN: {msg} "
                      f"({self.host}:{self.port}) — agent tetap jalan.")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            with self._lock:
                self._warned = False
            print(f"[agent-bus] terhubung ke broker {self.host}:{self.port}")
            for topic in ("sakato/monitor/+/event",
                          "sakato/monitor/+/status",
                          "sakato/monitor/agent/inbox"):
                client.subscribe(topic, qos=1)
        else:
            self._warn_once(f"koneksi ditolak broker (rc={rc})")

    @staticmethod
    def _camera_from_topic(topic: str) -> str:
        parts = topic.split("/")
        return parts[2] if len(parts) > 3 else ""

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            payload = msg.payload.decode("utf-8", errors="replace")
        try:
            if msg.topic.endswith("/event") and self.on_event:
                self.on_event(self._camera_from_topic(msg.topic), payload)
            elif msg.topic.endswith("/status") and self.on_status:
                self.on_status(self._camera_from_topic(msg.topic), payload)
            elif msg.topic.endswith("/inbox") and self.on_inbox:
                self.on_inbox(payload)
        except Exception as e:  # pragma: no cover - defensif
            print(f"[agent-bus] error handler {msg.topic}: {e}")

    # ---------- API ----------

    def start(self):
        if not self.enabled or self._started:
            return
        self._started = True
        try:
            self._client.connect_async(self.host, self.port, keepalive=30)
            self._client.loop_start()
        except Exception as e:
            self._warn_once(f"gagal memulai koneksi: {e}")

    def stop(self):
        if self._client is not None and self._started:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        self._started = False

    def publish(self, topic: str, payload: dict) -> bool:
        """Kembalikan True bila berhasil di-queue. Aman bila tak terhubung."""
        if not self.enabled or not self._started or self._client is None:
            return False
        try:
            info = self._client.publish(
                topic, json.dumps(payload, ensure_ascii=False), qos=1)
            return info.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception:
            return False

    def publish_outbox(self, text: str) -> bool:
        from datetime import datetime, timezone
        return self.publish("sakato/monitor/agent/outbox",
                            {"ts": datetime.now(timezone.utc).isoformat(),
                             "text": text})
