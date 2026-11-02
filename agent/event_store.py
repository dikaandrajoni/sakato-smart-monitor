"""Event store SQLite untuk agent (Fase 4).

Menyimpan semua event & status terakhir dari MQTT:
  sakato/monitor/<camera>/event   -> tabel events
  sakato/monitor/<camera>/status  -> tabel status (upsert per kamera)

File default: agent/data/events.db (diabaikan git via .gitignore).
Pakai ":memory:" untuk unit test.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventStore:
    def __init__(self, path: str = "agent/data/events.db"):
        self.path = path
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
        # check_same_thread=False + lock: aman dipakai dari thread MQTT & utama
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self):
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts         TEXT NOT NULL,
                    camera     TEXT NOT NULL DEFAULT '',
                    type       TEXT NOT NULL DEFAULT '',
                    track_id   INTEGER,
                    name       TEXT,
                    similarity REAL,
                    payload    TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_events_ts
                    ON events(ts);
                CREATE INDEX IF NOT EXISTS idx_events_type
                    ON events(type);
                CREATE INDEX IF NOT EXISTS idx_events_camera
                    ON events(camera);
                CREATE TABLE IF NOT EXISTS status (
                    camera  TEXT PRIMARY KEY,
                    ts      TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}'
                );
                """
            )

    # ---------- tulis ----------

    def insert(self, event: dict) -> int:
        """Simpan satu event. Kembalikan row id.

        event: dict dengan kunci ts (ISO, opsional), camera, type,
               track_id, name, similarity. Kunci lain ikut ke payload.
        """
        ev = dict(event or {})
        ts = ev.get("ts") or utcnow_iso()
        payload = json.dumps(ev, ensure_ascii=False, default=str)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO events (ts, camera, type, track_id, name,"
                " similarity, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ts,
                    str(ev.get("camera") or ""),
                    str(ev.get("type") or ""),
                    ev.get("track_id"),
                    ev.get("name"),
                    ev.get("similarity"),
                    payload,
                ),
            )
            return cur.lastrowid

    def upsert_status(self, camera: str, payload: dict) -> None:
        """Simpan status terakhir (retain) per kamera."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO status (camera, ts, payload) VALUES (?, ?, ?)"
                " ON CONFLICT(camera) DO UPDATE SET ts=excluded.ts,"
                " payload=excluded.payload",
                (
                    str(camera or ""),
                    utcnow_iso(),
                    json.dumps(payload or {}, ensure_ascii=False,
                               default=str),
                ),
            )

    # ---------- baca ----------

    def query(self, since: str | None = None, camera: str | None = None,
              event_type: str | None = None, name: str | None = None,
              limit: int = 50) -> list[dict]:
        """Ambil event terurut waktu menaik (paling lama dulu).

        since: string ISO 8601 — hanya event dengan ts >= since.
        """
        sql = ("SELECT ts, camera, type, track_id, name, similarity, payload"
               " FROM events")
        conds, params = [], []
        if since:
            conds.append("ts >= ?")
            params.append(since)
        if camera:
            conds.append("camera = ?")
            params.append(camera)
        if event_type:
            conds.append("type = ?")
            params.append(event_type)
        if name:
            conds.append("LOWER(name) = LOWER(?)")
            params.append(name)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY ts ASC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            try:
                full = json.loads(r["payload"])
            except Exception:
                full = {}
            full.setdefault("ts", r["ts"])
            full.setdefault("camera", r["camera"])
            full.setdefault("type", r["type"])
            out.append(full)
        return out

    def latest_status(self) -> dict:
        """{camera: payload_dict} dari topik status terakhir."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT camera, payload FROM status").fetchall()
        out = {}
        for r in rows:
            try:
                out[r["camera"]] = json.loads(r["payload"])
            except Exception:
                out[r["camera"]] = {}
        return out

    def stats_today(self) -> dict:
        """Ringkasan hari ini (UTC): hitung per tipe + daftar nama."""
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT type, name FROM events WHERE substr(ts, 1, 10) >= ?",
                (today,),
            ).fetchall()
        by_type: dict[str, int] = {}
        names: dict[str, int] = {}
        for r in rows:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
            if r["name"] and r["name"] != "Unknown":
                names[r["name"]] = names.get(r["name"], 0) + 1
        return {
            "date": today,
            "total": sum(by_type.values()),
            "by_type": by_type,
            "known_names": sorted(names),
        }

    def unknown_tracks_since(self, since_iso: str) -> dict[int, dict]:
        """Track Unknown yang masih aktif sejak `since_iso`.

        Kembalikan {track_id: {camera, first_ts, name}} untuk track yang punya
        face_unknown/person_entered tapi belum ada person_left sesudahnya.
        Dipakai untuk eskalasi.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT track_id, camera, type, ts FROM events"
                " WHERE ts >= ? AND track_id IS NOT NULL"
                " ORDER BY ts ASC",
                (since_iso,),
            ).fetchall()
        active: dict[int, dict] = {}
        for r in rows:
            tid = r["track_id"]
            if r["type"] == "person_left":
                active.pop(tid, None)
            elif r["type"] in ("person_entered", "face_unknown"):
                active.setdefault(tid, {"camera": r["camera"],
                                        "first_ts": r["ts"]})
        return active

    def close(self):
        with self._lock:
            self._conn.close()
