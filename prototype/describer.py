"""Deskripsi kejadian dengan VLM lokal via Ollama (Fase 5).

- Model dari env VLM_MODEL (default "moondream:1.8b", ~1.7 GB;
  alternatif "qwen2.5vl:3b"). Install: `ollama pull moondream:1.8b`.
- Dipanggil HANYA untuk event penting (lihat should_describe) agar hemat.
- Gagal / timeout -> "" (tidak pernah blokir pipeline).
- DescribeWorker: antrean di thread latar; callback on_done dipanggil
  dengan hasil deskripsi (atau "" bila gagal).
"""

from __future__ import annotations

import base64
import os

try:
    import requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REQUESTS_AVAILABLE = False

PROMPT_ID = (
    "Deskripsikan singkat dalam Bahasa Indonesia apa yang terjadi pada "
    "gambar ini: siapa orangnya, apa yang sedang dilakukan, dan di mana. "
    "Maksimal 2 kalimat."
)


def should_describe(event_type: str, armed: bool) -> bool:
    """Keputusan murni: hanya event penting & saat armed yang dideskripsikan."""
    if not armed:
        return False
    return event_type in ("face_unknown", "person_entered")


class EventDescriber:
    def __init__(self, host=None, model=None, timeout=60):
        self.host = (host or os.environ.get(
            "OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.model = model or os.environ.get("VLM_MODEL", "moondream:1.8b")
        self.timeout = timeout

    def available(self) -> bool:
        """True bila Ollama terjangkau (tidak mengecek model spesifik)."""
        if not _REQUESTS_AVAILABLE:
            return False
        try:
            r = requests.get(self.host + "/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def describe(self, jpg_bytes: bytes, context: str = "") -> str:
        """Kembalikan 1-2 kalimat Bahasa Indonesia, atau "" bila gagal."""
        if not jpg_bytes or not _REQUESTS_AVAILABLE:
            return ""
        prompt = PROMPT_ID
        if context:
            prompt += f" Konteks: {context}."
        try:
            r = requests.post(
                self.host + "/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "images": [base64.b64encode(jpg_bytes).decode("ascii")],
                    "stream": False,
                },
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return ""
            text = r.json().get("response", "")
            return " ".join(str(text).split())
        except Exception:
            return ""


class DescribeWorker:
    """Antrean deskripsi di thread latar — pipeline utama tidak diblokir."""

    def __init__(self, describer: EventDescriber):
        import queue
        import threading
        self._describer = describer
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="vlm-describer")
        self._thread.start()

    def submit(self, track_id, jpg_bytes, context, on_done):
        """on_done(description: str) dipanggil di thread worker."""
        self._queue.put((track_id, jpg_bytes, context, on_done))

    def _run(self):
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except Exception:
                continue
            if item is None:
                break
            track_id, jpg_bytes, context, on_done = item
            try:
                desc = self._describer.describe(jpg_bytes, context)
            except Exception:
                desc = ""
            try:
                on_done(desc)
            except Exception as e:  # pragma: no cover - defensif
                print(f"[vlm] error callback deskripsi: {e}")
            finally:
                self._queue.task_done()

    def stop(self):
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout=10)
