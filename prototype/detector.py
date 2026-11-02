"""Deteksi orang dengan YOLO11n (ultralytics)."""

import torch
from ultralytics import YOLO


def pick_device():
    """cuda bila tersedia, selain itu cpu."""
    return "cuda" if torch.cuda.is_available() else "cpu"


class PersonDetector:
    def __init__(self, model_path="yolo11n.pt", conf=0.5, device=None):
        self.conf = conf
        self.device = device or pick_device()
        self.model = YOLO(model_path)
        self.model.to(self.device)

    def detect(self, frame):
        """Kembalikan list dict: {'xyxy': [x1,y1,x2,y2], 'conf': float}.

        Hanya kelas 'person' (class id 0 pada COCO).
        """
        results = self.model.predict(frame, conf=self.conf, classes=[0],
                                     device=self.device, verbose=False)
        out = []
        for r in results:
            for box in r.boxes:
                out.append({
                    "xyxy": [float(v) for v in box.xyxy[0].tolist()],
                    "conf": float(box.conf[0].item()),
                })
        return out
