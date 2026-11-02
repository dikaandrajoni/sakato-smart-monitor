# Fase 2 — Face Recognition + Notifikasi Telegram Cerdas

Pipeline Fase 1 (YOLO11n + ByteTrack + event dedup) ditambah:

1. **Face recognition (InsightFace, model `buffalo_l`)** — tiap `person_entered`
   di-crop wajahnya dan dicocokkan ke galeri. Semua inference lokal (CPU).
2. **Notifikasi Telegram cerdas (python-telegram-bot v21)** — orang tak dikenal
   → foto + caption (waktu, kamera, track ID, kemiripan); orang dikenal →
   dicatat saja. Anti-spam: cooldown per track ID + perintah `/mute`.
3. **Perintah bot dua arah**: `/status`, `/snapshot`, `/arm`, `/disarm`,
   `/mute <menit>`.

---

## ⚠️ PENTING: buat bot Telegram BARU

**Token bot di repo lama (2021) SUDAH BOCOR** — ia pernah di-hardcode di repo
publik. **Jangan pernah pakai lagi.** Revoke di @BotFather, lalu buat baru:

1. Chat ke **@BotFather** di Telegram → `/newbot`
2. Ikuti langkahnya (nama + username bot) → dapat **token baru**
3. Cari tahu chat ID kamu: chat ke **@userinfobot** → dapat angka ID
4. Buat file `.env` di folder `prototype/` (JANGAN di-commit):

```bash
TELEGRAM_BOT_TOKEN=isi_token_baru_di_sini
TELEGRAM_CHAT_ID=isi_angka_chat_id_di_sini
```

Lalu jalankan dengan `set -a; source .env; set +a` (Linux/macOS) atau isi
manual sebagai environment variable di Windows, sebelum `python main.py`.

Token HANYA dibaca dari environment. Tidak ada default, tidak ada hardcode.
Bila kosong, notifier nonaktif dengan peringatan — program tetap jalan.

## Instalasi

```bash
cd prototype
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Saat pertama dijalankan, model `yolo11n.pt` (~6 MB) dan `buffalo_l`
(~300 MB) otomatis diunduh. buffalo_l tersimpan di `~/.insightface`.

## Daftarkan wajah (enroll)

```bash
python enroll.py --source 0 --name dika --shots 20
```

- `--source`: `0` (kamera laptop), `1` (USB), `rtsp://...`, atau file video
- `--name`: nama orang (jadi folder `gallery/dika/`)
- `--shots`: jumlah foto (default 20)

Tips: ambil dari beberapa sudut & ekspresi, pencahayaan cukup. Ulangi perintah
untuk tiap orang. Hasil: `gallery/<nama>/shot_000.jpg`, dst.

## Menjalankan monitor

```bash
# Tanpa Telegram (mode uji)
python main.py --source 0 --gallery gallery/

# Lengkap: Telegram aktif
python main.py --source 0 --gallery gallery/ --telegram --camera-name teras_depan

# Headless + hanya notifikasi orang tak dikenal (default)
python main.py --source 0 --gallery gallery/ --telegram --no-show

# Termasuk notifikasi orang yang dikenal
python main.py --source 0 --gallery gallery/ --telegram --notify-known
```

Flag tambahan: `--face-threshold` (default 0.6 — naikkan bila sering salah
mengenali), `--notify-cooldown` detik (default 300), `--conf`, `--log`.

Tanpa folder `gallery/` yang valid, semua orang dianggap Unknown dan
face recognition dimatikan otomatis.

## Perintah Telegram

| Perintah | Fungsi |
|---|---|
| `/start` | daftar perintah |
| `/status` | status notifikasi, event hari ini, kamera |
| `/snapshot` | kirim foto frame terakhir |
| `/arm` | aktifkan notifikasi |
| `/disarm` | matikan notifikasi |
| `/mute <menit>` | bisukan sementara, mis. `/mute 30` |

## Event log (JSONL)

Sama seperti Fase 1, plus info wajah di console:

```
[event] person_entered track_id=3
[face] track #3 -> dika (0.87)
```

## Keterbatasan Fase 2

- **Anti-spoofing lemah**: `buffalo_l` tidak punya liveness detection yang kuat.
  Foto cetak / layar HP wajah terdaftar DAPAT menipu sistem. Jangan jadikan
  satu-satunya kunci akses (mis. buka pintu) tanpa faktor kedua.
- Threshold 0.6 adalah titik awal — sesuaikan dengan kondisi pencahayaan rumah.
- ByteTrack kadang ganti ID bila orang hilang lama dari frame (ID switch);
  wajah dikenali ulang sebagai track baru.
- InsightFace di CPU: tambah ~50–150 ms per wajah. Di laptop kentang,
  pertimbangkan `--conf` lebih tinggi agar crop wajah lebih sedikit.
- Notifikasi Unknown memakai crop wajah dari bbox YOLO — bila wajah kecil /
  blur, kemiripan rendah dan wajar jadi Unknown.
- Belum ada deskripsi kejadian Bahasa Indonesia (itu Fase 3/4 dengan VLM).

## Rencana Fase 3

1. Integrasi **Home Assistant via MQTT** (gantikan notifier langsung):
   Frigate-style event topic, automasi lampu/sirene.
2. **VLM lokal** (Moondream2 / Qwen2.5-VL via Ollama) untuk deskripsi kejadian
   Bahasa Indonesia sebagai verifikator lapis kedua.
3. Event store SQLite + riwayat klip per event.
4. Mode multi-kamera (`--camera-name` per sumber).
