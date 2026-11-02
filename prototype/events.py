"""Dedup event berbasis track ID.

- person_entered : emit SEKALI saat track ID baru pertama kali terlihat.
- person_left    : emit SEKALI saat track ID hilang selama `leave_after`
                   frame berturut-turut.
- cooldown       : jeda minimum (detik) antar event sejenis agar tidak spam.

Event ditulis ke JSONL: {"ts": iso8601, "type": ..., "track_id": ...}.
"""

import json
import threading
import time
from datetime import datetime, timezone


class EventDeduplicator:
    def __init__(self, leave_after=30, cooldown=5.0, log_path="events.jsonl",
                 time_fn=None):
        """
        leave_after : frame tak terlihat berturut-turut sebelum person_left.
        cooldown    : detik minimum antar event dengan type yang sama.
        log_path    : path file JSONL (dibuat saat init).
        time_fn     : injeksi jam (untuk unit test), default time.time.
        """
        self.leave_after = leave_after
        self.cooldown = cooldown
        self.log_path = log_path
        self._time = time_fn or time.time
        self._missing = {}      # track_id -> jumlah frame tak terlihat
        self._last_emit = {}    # event type -> timestamp emit terakhir
        self._lock = threading.Lock()  # tulis JSONL aman antar-thread (Fase 5)
        self._fh = open(log_path, "a", encoding="utf-8")

    def _emit(self, event_type, track_id, extra=None):
        now = self._time()
        last = self._last_emit.get(event_type, float("-inf"))
        if now - last < self.cooldown:
            return None  # masih dalam cooldown
        self._last_emit[event_type] = now
        event = {
            "ts": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "type": event_type,
            "track_id": track_id,
        }
        if extra:
            event.update(extra)
        with self._lock:
            self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._fh.flush()
        return event

    def log_event(self, event_type, track_id, extra=None):
        """Tulis event bebas ke JSONL (mis. face_description dari VLM).

        Tidak kena cooldown — untuk event sekali-jadi dari worker latar.
        """
        event = {
            "ts": datetime.fromtimestamp(self._time(), tz=timezone.utc).isoformat(),
            "type": event_type,
            "track_id": track_id,
        }
        if extra:
            event.update(extra)
        with self._lock:
            self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._fh.flush()
        return event

    def rotate_log(self, new_path):
        """Ganti file JSONL (rotasi harian). State tracking tetap dipertahankan."""
        with self._lock:
            try:
                self._fh.close()
            except Exception:
                pass
            self.log_path = new_path
            self._fh = open(new_path, "a", encoding="utf-8")
        print(f"[events] rotasi log -> {new_path}")

    def update(self, tracks):
        """Terima list track dict {'id': ...} dari tracker per frame.

        Kembalikan list event yang di-emit pada frame ini.
        """
        seen = {t["id"] for t in tracks}
        emitted = []

        # Track baru -> person_entered (sekali per ID).
        for tid in seen:
            if tid not in self._missing:
                ev = self._emit("person_entered", tid)
                if ev:
                    emitted.append(ev)
                    self._missing[tid] = 0
                # Bila ter-suppress cooldown, jangan tandai sebagai dikenal:
                # frame berikutnya dicoba lagi agar event tidak hilang.
            else:
                self._missing[tid] = 0

        # Track yang tidak terlihat -> hitung, lalu person_left bila cukup lama.
        for tid in list(self._missing):
            if tid not in seen:
                self._missing[tid] += 1
                if self._missing[tid] >= self.leave_after:
                    ev = self._emit("person_left", tid,
                                    {"missing_frames": self._missing[tid]})
                    if ev:
                        emitted.append(ev)
                    del self._missing[tid]

        return emitted

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
