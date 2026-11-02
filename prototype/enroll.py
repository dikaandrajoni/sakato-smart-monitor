"""Pendaftaran wajah ke galeri.

Mengambil N foto wajah dari kamera, hanya menyimpan frame yang mengandung
wajah (crop wajah terbesar), ke gallery/<nama>/shot_XXX.jpg.

Contoh:
    python enroll.py --source 0 --name dika --shots 20
    python enroll.py --source 1 --name "ibu" --shots 30 --gallery galeri_saya/

Tips: hadap kamera dari beberapa sudut & ekspresi agar embedding kuat.
Tekan 'q' untuk berhenti lebih awal.
"""

import argparse
import os

import cv2

from camera import CameraSource, parse_source
from face_recognizer import FaceRecognizer


def main():
    ap = argparse.ArgumentParser(description="Daftarkan wajah ke galeri")
    ap.add_argument("--source", required=True,
                    help="0 (kamera laptop), 1+ (USB), rtsp://..., atau file video")
    ap.add_argument("--name", required=True,
                    help="nama orang (jadi nama folder gallery/<nama>/)")
    ap.add_argument("--shots", type=int, default=20,
                    help="jumlah foto yang diambil (default 20)")
    ap.add_argument("--gallery", default="gallery/",
                    help="folder galeri (default gallery/)")
    ap.add_argument("--no-show", action="store_true",
                    help="tanpa preview GUI")
    args = ap.parse_args()

    name = args.name.strip().replace(" ", "_")
    out_dir = os.path.join(args.gallery, name)
    os.makedirs(out_dir, exist_ok=True)
    start_idx = len([f for f in os.listdir(out_dir)
                     if f.lower().endswith((".jpg", ".jpeg", ".png"))])

    print("[enroll] memuat model InsightFace (pertama kali unduh ~300 MB)...")
    fr = FaceRecognizer()

    saved = 0
    skipped = 0
    try:
        with CameraSource(parse_source(args.source)) as cam:
            while saved < args.shots:
                frame = cam.read()
                if frame is None:
                    print("[enroll] stream selesai.")
                    break
                faces = fr.app.get(frame)
                if faces:
                    face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) *
                               (f.bbox[3] - f.bbox[1]))
                    x1, y1, x2, y2 = (int(v) for v in face.bbox)
                    # Perlebar crop (margin 30%) agar deteksi ulang saat
                    # enroll_from_gallery tidak gagal pada crop yang terlalu pas.
                    fw, fh = frame.shape[1], frame.shape[0]
                    mx, my = int((x2 - x1) * 0.3), int((y2 - y1) * 0.3)
                    x1, y1 = max(0, x1 - mx), max(0, y1 - my)
                    x2, y2 = min(fw, x2 + mx), min(fh, y2 + my)
                    crop = frame[y1:y2, x1:x2]
                    if crop.size > 0:
                        path = os.path.join(
                            out_dir, f"shot_{start_idx + saved:03d}.jpg")
                        cv2.imwrite(path, crop)
                        saved += 1
                        print(f"[enroll] tersimpan {saved}/{args.shots}: {path}")
                    status = f"OK {saved}/{args.shots}"
                    color = (0, 255, 0)
                else:
                    skipped += 1
                    status = f"cari wajah... ({saved}/{args.shots})"
                    color = (0, 0, 255)

                if not args.no_show:
                    cv2.putText(frame, status, (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
                    cv2.imshow("enroll - tekan q untuk berhenti", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
    except KeyboardInterrupt:
        print("\n[enroll] dihentikan pengguna.")
    finally:
        if not args.no_show:
            cv2.destroyAllWindows()

    print(f"[enroll] selesai: {saved} foto tersimpan di {out_dir} "
          f"({skipped} frame tanpa wajah dilewati).")


if __name__ == "__main__":
    main()
