# Fase 1 — Prototipe Deteksi Orang + Tracking

Pipeline sederhana yang jalan di laptop: **baca frame → deteksi orang
(YOLO11n) → tracking ID stabil (ByteTrack) → event dedup → JSONL**.

Nanti Boss tinggal pilih sumber kamera lewat `--source`, tanpa ubah kode.

## Instalasi (disarankan venv)

```bash
cd fase-1-prototype
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Saat pertama dijalankan, model `yolo11n.pt` otomatis diunduh (~6 MB).

## Contoh perintah

```bash
# Kamera laptop
python main.py --source 0

# Kamera USB (coba 1, 2, ... bila 0 adalah kamera internal)
python main.py --source 1

# Kamera IP via RTSP (ada reconnect otomatis bila putus)
python main.py --source rtsp://user:password@192.168.1.10:554/stream1 --no-show

# File video
python main.py --source rekaman.mp4 --log kejadian.jsonl

# Threshold confidence lebih ketat + tanpa GUI (headless / server)
python main.py --source 0 --conf 0.6 --no-show
```

Tekan `q` pada jendela video untuk keluar.

## Event log (JSONL)

Setiap baris satu event JSON:

```json
{"ts": "2026-11-02T09:30:12.123456+00:00", "type": "person_entered", "track_id": 3}
{"ts": "2026-11-02T09:31:05.654321+00:00", "type": "person_left", "track_id": 3, "missing_frames": 30}
```

- `person_entered` — emit **sekali** saat ID orang baru pertama terlihat.
- `person_left` — emit **sekali** saat ID hilang selama N frame
  berturut-turut (default 30, ubah via `--leave-after`).
- Ada cooldown antar event sejenis agar log tidak spam.

## Keterbatasan prototipe

- Hanya mendeteksi kelas `person`; belum ada face recognition,
  belum ada notifikasi Telegram, belum ada deskripsi kejadian.
- ByteTrack kadang memberi ID baru bila orang hilang lama dari frame
  (ID switch) — wajar untuk prototipe.
- Performa tergantung hardware; YOLO11n ringan, tapi di CPU lama
  frame rate bisa rendah. Bila ada GPU NVIDIA, otomatis dipakai (cuda).
- Belum diuji dengan kamera fisik (hanya video sintetis di VM).

## Langkah Fase 2 berikutnya

1. Face recognition (InsightFace) di atas crop wajah tiap track ID.
2. Verifikasi VLM lokal untuk deskripsi kejadian Bahasa Indonesia.
3. Notifikasi Telegram cerdas (foto + deskripsi, anti-spam, perintah dua arah).
4. Secret via environment variable (`.env`), bukan hardcode.
