"""Tracking orang dengan ByteTrack (ID stabil antar-frame)."""

from ultralytics import YOLO

from detector import pick_device


class PersonTracker:
    def __init__(self, model_path="yolo11n.pt", conf=0.5, device=None,
                 tracker_cfg="bytetrack.yaml"):
        self.conf = conf
        self.device = device or pick_device()
        self.tracker_cfg = tracker_cfg
        self.model = YOLO(model_path)
        self.model.to(self.device)

    def track(self, frame):
        """Kembalikan list dict: {'id': int, 'xyxy': [...], 'conf': float}.

        persist=True membuat ByteTrack mempertahankan ID antar-frame.
        """
        results = self.model.track(frame, persist=True, conf=self.conf,
                                   classes=[0], device=self.device,
                                   tracker=self.tracker_cfg, verbose=False)
        out = []
        for r in results:
            if r.boxes is None or r.boxes.id is None:
                continue
            ids = r.boxes.id.int().tolist()
            for i, track_id in enumerate(ids):
                out.append({
                    "id": int(track_id),
                    "xyxy": [float(v) for v in r.boxes.xyxy[i].tolist()],
                    "conf": float(r.boxes.conf[i].item()),
                })
        return out

    def reset(self):
        """Reset state tracker (mis. setelah reconnect kamera)."""
        # ultralytics menyimpan state di model.predictor.trackers;
        # cara paling aman: buang predictor agar dibuat ulang.
        self.model.predictor = None
