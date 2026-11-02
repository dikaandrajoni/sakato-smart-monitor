"""Face recognition dengan InsightFace (model buffalo_l).

Alur:
    1. enroll_from_gallery("gallery/") -> rata-rata embedding per orang.
    2. identify(face_crop) -> (nama | "Unknown", cosine similarity).

Model buffalo_l diunduh otomatis (~300 MB) saat pertama kali dipakai dan
disimpan di ~/.insightface. Semua inference lokal (CPU), tanpa cloud.

CATATAN ANTI-SPOOFING: buffalo_l TIDAK punya liveness detection yang kuat.
Foto cetak / tampilan layar wajah orang terdaftar DAPAT menipu sistem ini.
Jangan pakai sebagai satu-satunya kunci akses (mis. buka pintu) tanpa
faktor kedua.
"""

import os

import cv2
import numpy as np

try:
    from insightface.app import FaceAnalysis
except ImportError:  # pesan error yang ramah bila dependensi belum diinstall
    FaceAnalysis = None


def cosine_similarity(a, b):
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class FaceRecognizer:
    def __init__(self, model_name="buffalo_l", threshold=0.6,
                 det_size=(640, 640)):
        """
        threshold: cosine similarity minimum agar dianggap cocok
                   (default 0.6; naikkan bila false-positive mengganggu,
                   turunkan bila wajah sulit dikenali).
        """
        if FaceAnalysis is None:
            raise RuntimeError(
                "insightface belum terinstall. Jalankan: pip install -r requirements.txt")
        self.threshold = threshold
        self.app = FaceAnalysis(name=model_name,
                                providers=["CPUExecutionProvider"])
        self.app.prepare(ctx_id=0, det_size=det_size)
        self.gallery = {}  # nama -> embedding (sudah dinormalisasi)

    # ---------- internal ----------

    def _embedding(self, img_bgr):
        """Embedding wajah TERBESAR pada gambar, atau None bila tak ada wajah."""
        faces = self.app.get(img_bgr)
        if not faces:
            return None
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) *
                   (f.bbox[3] - f.bbox[1]))
        emb = np.asarray(face.normed_embedding, dtype=np.float64)
        norm = np.linalg.norm(emb)
        return emb / norm if norm > 0 else None

    # ---------- API publik ----------

    def enroll_from_gallery(self, gallery_dir, cache_path=None):
        """Baca gallery/<nama>/*.jpg -> rata-rata embedding per orang.

        Mengembalikan dict {nama: jumlah_foto}. Bila cache_path diberikan,
        embedding disimpan/dimuat dari .npz agar start berikutnya cepat.
        """
        self.gallery = {}
        counts = {}
        if not os.path.isdir(gallery_dir):
            return counts

        # Coba pakai cache bila galeri tidak berubah.
        cache_ok = False
        if cache_path and os.path.isfile(cache_path):
            try:
                data = np.load(cache_path, allow_pickle=True)
                newest = 0.0
                for root, _, files in os.walk(gallery_dir):
                    for f in files:
                        newest = max(newest,
                                     os.path.getmtime(os.path.join(root, f)))
                if float(data["built_at"]) >= newest:
                    self.gallery = {k: data[k] for k in data.files
                                    if k != "built_at"}
                    counts = {k: int(data[k + "__n"]) for k in data.files
                              if k.endswith("__n")}
                    cache_ok = True
            except Exception:
                cache_ok = False

        if not cache_ok:
            for name in sorted(os.listdir(gallery_dir)):
                person_dir = os.path.join(gallery_dir, name)
                if not os.path.isdir(person_dir):
                    continue
                embs = []
                skipped = 0
                for fname in sorted(os.listdir(person_dir)):
                    if not fname.lower().endswith((".jpg", ".jpeg", ".png")):
                        continue
                    img = cv2.imread(os.path.join(person_dir, fname))
                    if img is None:
                        continue
                    emb = self._embedding(img)
                    if emb is not None:
                        embs.append(emb)
                    else:
                        skipped += 1
                if skipped:
                    print(f"[gallery] {skipped} foto {name} tanpa wajah "
                          f"terdeteksi, dilewati.")
                if embs:
                    mean_emb = np.mean(embs, axis=0)
                    mean_emb /= np.linalg.norm(mean_emb)
                    self.gallery[name] = mean_emb
                    counts[name] = len(embs)

            if cache_path and self.gallery:
                payload = {"built_at": np.array(
                    max(os.path.getmtime(os.path.join(r, f))
                        for r, _, fs in os.walk(gallery_dir) for f in fs))}
                for name, emb in self.gallery.items():
                    payload[name] = emb
                    payload[name + "__n"] = np.array(counts[name])
                np.savez(cache_path, **payload)

        return counts

    def identify(self, face_crop_bgr):
        """Kembalikan (nama | "Unknown", similarity).

        - Galeri kosong            -> ("Unknown", 0.0)
        - Tidak ada wajah di crop  -> ("Unknown", 0.0)
        - Similarity < threshold   -> ("Unknown", similarity)
        """
        if not self.gallery:
            return "Unknown", 0.0
        emb = self._embedding(face_crop_bgr)
        if emb is None:
            return "Unknown", 0.0
        best_name, best_sim = "Unknown", 0.0
        for name, g_emb in self.gallery.items():
            sim = cosine_similarity(emb, g_emb)
            if sim > best_sim:
                best_name, best_sim = name, sim
        if best_sim >= self.threshold:
            return best_name, best_sim
        return "Unknown", best_sim

    def has_faces(self, img_bgr):
        """True bila ada minimal satu wajah terdeteksi (untuk enroll)."""
        return len(self.app.get(img_bgr)) > 0
