"""Abstraksi sumber kamera.

Satu interface seragam untuk semua sumber: kamera laptop (index 0),
kamera USB (index 1, 2, ...), RTSP kamera IP, atau file video.

Contoh:
    cam = CameraSource(0)                    # kamera laptop
    cam = CameraSource(1)                    # kamera USB
    cam = CameraSource("rtsp://u:p@ip/stream")  # kamera IP
    cam = CameraSource("rekaman.mp4")        # file video
"""

import time

import cv2


class CameraSource:
    RECONNECT_DELAY = 2.0  # detik, jeda antar percobaan reconnect RTSP

    def __init__(self, source):
        """source: int (index kamera) atau str (URL RTSP / path file)."""
        self.source = source
        self.is_rtsp = isinstance(source, str) and source.startswith("rtsp://")
        self.cap = None
        self._open()

    def _open(self):
        self.cap = cv2.VideoCapture(self.source)
        if not self.cap.isOpened():
            raise RuntimeError(f"Tidak bisa membuka sumber kamera: {self.source!r}")

    def read(self):
        """Kembalikan frame (numpy array) atau None bila stream habis/gagal."""
        if self.cap is None:
            return None
        ok, frame = self.cap.read()
        if ok:
            return frame
        # Frame gagal dibaca.
        if self.is_rtsp:
            # Coba reconnect untuk stream RTSP yang putus.
            self._reconnect()
            if self.cap is not None:
                ok, frame = self.cap.read()
                return frame if ok else None
            return None
        # File video: stream habis -> None (pemicu berhenti).
        # Kamera USB/laptop: kembalikan None agar pemanggil bisa memutuskan.
        return None

    def _reconnect(self):
        try:
            self.cap.release()
        except Exception:
            pass
        time.sleep(self.RECONNECT_DELAY)
        try:
            self._open()
            print(f"[camera] Reconnect RTSP berhasil: {self.source}")
        except RuntimeError as e:
            print(f"[camera] Reconnect RTSP gagal: {e}")
            self.cap = None

    def release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def parse_source(value):
    """Ubah argumen CLI --source: angka tetap angka, sisanya string."""
    value = value.strip()
    if value.lstrip("-").isdigit():
        return int(value)
    return value
