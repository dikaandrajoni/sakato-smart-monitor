"""Tools untuk agent LLM (Fase 4).

Setiap tool adalah fungsi Python biasa yang mengembalikan string JSON.
ATURAN KERAS: tool hanya membaca dari EventStore / menerbitkan perintah
yang eksplisit — tidak ada tebakan, tidak ada data khayalan.

Tool yang tersedia untuk function calling:
  query_events, stats_today, get_status, arm, disarm
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .event_store import EventStore


def _ok(data) -> str:
    return json.dumps({"ok": True, "data": data}, ensure_ascii=False,
                      default=str)


def _err(msg) -> str:
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


class AgentTools:
    def __init__(self, store: EventStore, publish=None):
        """publish: callable(topic: str, payload: dict) -> bool.

        Dipakai arm/disarm untuk mengirim perintah ke
        sakato/monitor/command (+ topik per kamera bila disebut).
        """
        self.store = store
        self._publish = publish

    # ---------- tool: query ----------

    def query_events(self, since: str | None = None,
                     camera: str | None = None,
                     type: str | None = None,
                     name: str | None = None,
                     limit: int = 50) -> str:
        """Cari event. since = ISO 8601 (cth '2026-11-02T15:00:00+07:00')
        atau relatif: '2h' (2 jam lalu), '1d' (1 hari lalu)."""
        since_iso = self._resolve_since(since)
        if since and since_iso is None:
            return _err(f"format 'since' tidak dikenal: {since!r}."
                        " Pakai ISO 8601 atau relatif seperti '2h','30m','1d'.")
        events = self.store.query(since=since_iso, camera=camera,
                                  event_type=type, name=name, limit=limit)
        ringkas = [
            {k: e.get(k) for k in ("ts", "camera", "type", "track_id",
                                   "name", "similarity") if e.get(k) is not None}
            for e in events
        ]
        return _ok({"count": len(ringkas), "events": ringkas})

    @staticmethod
    def _resolve_since(since: str | None) -> str | None:
        if not since:
            return None
        s = since.strip().lower()
        try:
            if s.endswith("m") and s[:-1].isdigit():
                dt = datetime.now(timezone.utc) - timedelta(
                    minutes=int(s[:-1]))
                return dt.isoformat()
            if s.endswith("h") and s[:-1].isdigit():
                dt = datetime.now(timezone.utc) - timedelta(
                    hours=int(s[:-1]))
                return dt.isoformat()
            if s.endswith("d") and s[:-1].isdigit():
                dt = datetime.now(timezone.utc) - timedelta(
                    days=int(s[:-1]))
                return dt.isoformat()
        except Exception:
            return None
        # anggap ISO 8601 — validasi ringan
        try:
            datetime.fromisoformat(s.replace("Z", "+00:00"))
            return since
        except ValueError:
            return None

    # ---------- tool: statistik & status ----------

    def stats_today(self) -> str:
        """Ringkasan kejadian hari ini: total, per tipe, nama yang dikenal."""
        return _ok(self.store.stats_today())

    def get_status(self) -> str:
        """Status terakhir tiap kamera (online/armed/jumlah terlihat)."""
        return _ok(self.store.latest_status())

    # ---------- tool: perintah ----------

    def arm(self, camera: str | None = None) -> str:
        """Aktifkan mode siaga. Opsional: batasi ke satu kamera."""
        return self._send_command("arm", camera)

    def disarm(self, camera: str | None = None) -> str:
        """Nonaktifkan mode siaga. Opsional: batasi ke satu kamera."""
        return self._send_command("disarm", camera)

    def _send_command(self, command: str, camera: str | None) -> str:
        if self._publish is None:
            return _err("publish perintah tidak tersedia (MQTT nonaktif).")
        payload = {"command": command,
                   "ts": datetime.now(timezone.utc).isoformat()}
        topics = ["sakato/monitor/command"]
        if camera:
            cam = str(camera).strip().lower().replace(" ", "_")
            topics.append(f"sakato/monitor/{cam}/command")
        sent = [t for t in topics if self._publish(t, payload)]
        return _ok({"command": command, "camera": camera,
                    "published_to": sent})

    # ---------- spesifikasi function calling (format Ollama/OpenAI) ----------

    TOOL_SPECS = [
        {
            "type": "function",
            "function": {
                "name": "query_events",
                "description": "Cari event monitoring (orang masuk/keluar,"
                               " wajah dikenal/tak dikenal). WAJIB dipakai"
                               " sebelum menjawab pertanyaan tentang kejadian.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "since": {"type": "string",
                                  "description": "ISO 8601 atau relatif"
                                                 " ('2h','30m','1d')"},
                        "camera": {"type": "string"},
                        "type": {"type": "string",
                                 "description": "person_entered, person_left,"
                                                " face_known, face_unknown"},
                        "name": {"type": "string"},
                        "limit": {"type": "integer", "default": 50},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "stats_today",
                "description": "Ringkasan kejadian hari ini.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_status",
                "description": "Status terakhir tiap kamera"
                               " (online/armed/jumlah terlihat).",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "arm",
                "description": "Aktifkan mode siaga (notifikasi menyala).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "camera": {"type": "string",
                                   "description": "opsional, nama kamera"}},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "disarm",
                "description": "Nonaktifkan mode siaga.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "camera": {"type": "string",
                                   "description": "opsional, nama kamera"}},
                },
            },
        },
    ]

    def dispatch(self, name: str, arguments: dict) -> str:
        """Jalankan tool by name. Dipakai agent loop."""
        fn = getattr(self, name, None)
        if not callable(fn) or name.startswith("_"):
            return _err(f"tool tidak dikenal: {name}")
        try:
            return fn(**(arguments or {}))
        except TypeError as e:
            return _err(f"argumen tool {name} salah: {e}")
        except Exception as e:  # pragma: no cover - defensif
            return _err(f"tool {name} gagal: {e}")
