"""Fase 1: prototipe deteksi orang + tracking.

Contoh:
    python main.py --source 0
    python main.py --source 1 --conf 0.6
    python main.py --source rtsp://user:pass@192.168.1.10:554/stream1 --no-show
    python main.py --source rekaman.mp4 --log kejadian.jsonl

Tekan 'q' pada jendela video untuk keluar (mode GUI).
"""

import argparse

import cv2

from camera import CameraSource, parse_source
from events import EventDeduplicator
from tracker import PersonTracker


def draw(frame, tracks):
    for t in tracks:
        x1, y1, x2, y2 = (int(v) for v in t["xyxy"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"id={t['id']} person {t['conf']:.2f}"
        cv2.putText(frame, label, (x1, max(0, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    return frame


def main():
    ap = argparse.ArgumentParser(description="Fase 1: deteksi orang + tracking")
    ap.add_argument("--source", required=True,
                    help="0 (kamera laptop), 1+ (USB), rtsp://..., atau path file video")
    ap.add_argument("--conf", type=float, default=0.5,
                    help="threshold confidence deteksi (default 0.5)")
    ap.add_argument("--no-show", action="store_true",
                    help="tanpa jendela GUI (untuk headless)")
    ap.add_argument("--log", default="events.jsonl",
                    help="path file JSONL event (default events.jsonl)")
    ap.add_argument("--leave-after", type=int, default=30,
                    help="frame tak terlihat sebelum person_left (default 30)")
    args = ap.parse_args()

    source = parse_source(args.source)
    print(f"[main] source={source!r} conf={args.conf}")

    tracker = PersonTracker(conf=args.conf)
    dedup = EventDeduplicator(leave_after=args.leave_after, log_path=args.log)

    try:
        with CameraSource(source) as cam:
            frames = 0
            while True:
                frame = cam.read()
                if frame is None:
                    print("[main] stream selesai / tidak ada frame.")
                    break
                tracks = tracker.track(frame)
                for ev in dedup.update(tracks):
                    print(f"[event] {ev['type']} track_id={ev['track_id']}")
                frames += 1

                if not args.no_show:
                    cv2.imshow("sakato-smart-monitor (fase 1) - tekan q untuk keluar",
                               draw(frame, tracks))
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                elif frames % 100 == 0:
                    print(f"[main] {frames} frame diproses...")
    except KeyboardInterrupt:
        print("\n[main] dihentikan pengguna.")
    finally:
        dedup.close()
        if not args.no_show:
            cv2.destroyAllWindows()
        print("[main] selesai.")


if __name__ == "__main__":
    main()
