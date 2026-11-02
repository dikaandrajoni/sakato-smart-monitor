"""Fase 3: deteksi orang + tracking + face recognition + Telegram + MQTT.

Contoh:
    python main.py --source 0
    python main.py --source 0 --telegram --gallery gallery/
    python main.py --source rekaman.mp4 --no-show --gallery gallery/ --telegram

Alur per track: saat person_entered -> crop bbox orang -> kenali wajah
(InsightFace vs galeri) -> Unknown = notifikasi Telegram + foto,
dikenal = catat di log saja (kecuali --notify-known).

Tekan 'q' pada jendela video untuk keluar (mode GUI).

MQTT (--mqtt): publish event ke sakato/monitor/<camera>/event dan
status retain ke sakato/monitor/<camera>/status untuk Home Assistant.
"""

import argparse
import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # baca TELEGRAM_BOT_TOKEN dkk dari file .env bila ada
except ImportError:
    pass

import cv2

from camera import CameraSource, parse_source
from events import EventDeduplicator
from tracker import PersonTracker


def expand_box(xyxy, w, h, margin=0.15):
    x1, y1, x2, y2 = (int(v) for v in xyxy)
    dx, dy = int((x2 - x1) * margin), int((y2 - y1) * margin)
    return (max(0, x1 - dx), max(0, y1 - dy),
            min(w, x2 + dx), min(h, y2 + dy))


def draw(frame, tracks, names):
    for t in tracks:
        x1, y1, x2, y2 = (int(v) for v in t["xyxy"])
        name, sim = names.get(t["id"], ("?", 0.0))
        color = (0, 255, 0) if name not in ("?", "Unknown") else (0, 165, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"{name} {sim:.2f}" if name != "?" else f"id={t['id']}"
        cv2.putText(frame, label, (x1, max(0, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return frame


def main():
    ap = argparse.ArgumentParser(
        description="Fase 3: deteksi + tracking + face recognition + Telegram + MQTT")
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
    # --- Fase 2 ---
    ap.add_argument("--gallery", default="gallery/",
                    help="folder galeri wajah gallery/<nama>/ (default gallery/)")
    ap.add_argument("--telegram", action="store_true",
                    help="aktifkan notifikasi Telegram (butuh env TELEGRAM_BOT_TOKEN "
                         "dan TELEGRAM_CHAT_ID)")
    ap.add_argument("--notify-known", action="store_true",
                    help="kirim notifikasi juga untuk orang yang dikenal")
    ap.add_argument("--face-threshold", type=float, default=0.6,
                    help="threshold cosine similarity wajah (default 0.6)")
    ap.add_argument("--notify-cooldown", type=int, default=300,
                    help="detik minimum antar notifikasi per track (default 300)")
    ap.add_argument("--camera-name", default="kamera",
                    help="label kamera untuk caption Telegram & topik MQTT "
                         "(default 'kamera')")
    # --- Fase 3 ---
    ap.add_argument("--mqtt", action="store_true",
                    help="aktifkan publisher MQTT (env MQTT_HOST/PORT/USER/PASSWORD; "
                         "default localhost:1883)")
    ap.add_argument("--mqtt-status-every", type=int, default=150,
                    help="publish status tiap N frame (default 150)")
    args = ap.parse_args()

    source = parse_source(args.source)
    print(f"[main] source={source!r} conf={args.conf}")

    # --- Face recognition (opsional: butuh galeri berisi foto) ---
    recognizer = None
    if os.path.isdir(args.gallery) and any(
            os.scandir(args.gallery)):
        from face_recognizer import FaceRecognizer
        print("[main] memuat model InsightFace...")
        recognizer = FaceRecognizer(threshold=args.face_threshold)
        counts = recognizer.enroll_from_gallery(
            args.gallery,
            cache_path=os.path.join(args.gallery, "embeddings.npz"))
        if counts:
            print(f"[main] galeri: {counts}")
        else:
            print("[main] galeri kosong / tak ada wajah — semua jadi Unknown.")
            recognizer = None
    else:
        print("[main] tanpa galeri wajah — semua orang = Unknown. "
              "Daftarkan via: python enroll.py --source 0 --name <nama>")

    # --- Telegram (opsional) ---
    notifier = None
    if args.telegram:
        from notifier import TelegramNotifier
        notifier = TelegramNotifier(
            cooldown=args.notify_cooldown,
            notify_known=args.notify_known,
            camera_name=args.camera_name)
        if notifier.enabled:
            notifier.start()
        else:
            notifier = None  # nonaktif: peringatan sudah dicetak

    # --- MQTT (opsional, Fase 3) ---
    mq = None
    if args.mqtt:
        from mqtt_publisher import MqttPublisher
        mq = MqttPublisher()
        mq.start()
        mq.publish_status(args.camera_name, online=True,
                          armed=(notifier.armed if notifier else True),
                          visible=0)

    tracker = PersonTracker(conf=args.conf)
    dedup = EventDeduplicator(leave_after=args.leave_after, log_path=args.log)
    face_names = {}  # track_id -> (nama, similarity), dikenali sekali saja

    try:
        with CameraSource(source) as cam:
            frames = 0
            while True:
                frame = cam.read()
                if frame is None:
                    print("[main] stream selesai / tidak ada frame.")
                    break
                h, w = frame.shape[:2]
                tracks = tracker.track(frame)
                boxes = {t["id"]: t["xyxy"] for t in tracks}

                for ev in dedup.update(tracks):
                    tid = ev["track_id"]
                    print(f"[event] {ev['type']} track_id={tid}")
                    name, sim = face_names.get(tid, ("Unknown", 0.0))
                    if ev["type"] == "person_entered" and recognizer:
                        x1, y1, x2, y2 = expand_box(boxes[tid], w, h)
                        crop = frame[y1:y2, x1:x2]
                        name, sim = recognizer.identify(crop) \
                            if crop.size > 0 else ("Unknown", 0.0)
                        face_names[tid] = (name, sim)
                        print(f"[face] track #{tid} -> {name} ({sim:.2f})")
                        if notifier is not None:
                            ok, jpg = cv2.imencode(".jpg", crop)
                            if name == "Unknown":
                                notifier.notify_unknown(
                                    tid, jpg.tobytes(), similarity=sim)
                            else:
                                notifier.notify_known(name, tid, similarity=sim)
                    if mq is not None:
                        if ev["type"] == "person_entered":
                            mq.publish_event(args.camera_name, "person_entered",
                                             tid)
                            if recognizer:
                                mq.publish_event(
                                    args.camera_name,
                                    "face_known" if name != "Unknown"
                                    else "face_unknown",
                                    tid, name=name, similarity=sim)
                        elif ev["type"] == "person_left":
                            mq.publish_event(args.camera_name, "person_left",
                                             tid)
                            face_names.pop(tid, None)

                if notifier is not None and frames % 15 == 0:
                    ok, jpg = cv2.imencode(".jpg", frame,
                                           [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok:
                        notifier.set_last_frame(jpg.tobytes())

                if mq is not None and frames % args.mqtt_status_every == 0:
                    mq.publish_status(
                        args.camera_name, online=True,
                        armed=(notifier.armed if notifier else True),
                        visible=len(tracks))

                frames += 1
                if not args.no_show:
                    cv2.imshow("sakato-smart-monitor (fase 3) - tekan q untuk keluar",
                               draw(frame, tracks, face_names))
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                elif frames % 100 == 0:
                    print(f"[main] {frames} frame diproses...")
    except KeyboardInterrupt:
        print("\n[main] dihentikan pengguna.")
    finally:
        if mq is not None:
            mq.publish_status(args.camera_name, online=False,
                              armed=(notifier.armed if notifier else True),
                              visible=0)
            mq.stop()
        if notifier is not None:
            notifier.stop()
        dedup.close()
        if not args.no_show:
            cv2.destroyAllWindows()
        print("[main] selesai.")


if __name__ == "__main__":
    main()
