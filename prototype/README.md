# Fase 5 — VLM deskripsi kejadian + hardening

Pipeline lengkap: deteksi orang (YOLO11) → tracking (ByteTrack) →
face recognition (InsightFace) → **deskripsi VLM (Ollama)** → Telegram +
MQTT + JSONL.

Pipeline Fase 2 (YOLO11n + ByteTrack + InsightFace + Telegram) ditambah:

1. **Publisher MQTT (`mqtt_publisher.py`, paho-mqtt)** — setiap event
   di-publish ke `sakato/monitor/<camera>/event` sebagai JSON; status
   (online, armed, jumlah orang terlihat) di-publish retain ke
   `sakato/monitor/<camera>/status` setiap N frame.
2. **Contoh integrasi Home Assistant** — automasi siap pakai di
   `home-assistant/automations.example.yaml` + sensor template di
   `configuration.example.yaml` + panduan di `home-assistant/README.md`.

Telegram tetap jalan seperti Fase 2 — MQTT adalah jalur kedua untuk
otomasi rumah (lampu, sirene, notifikasi HA), bukan pengganti Telegram.

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
# --- MQTT (Fase 3, opsional) ---
MQTT_HOST=localhost
MQTT_PORT=1883
# MQTT_USER=
# MQTT_PASSWORD=
```

File `.env` otomatis dibaca saat program mulai (python-dotenv).
Bila variabel Telegram/MQTT kosong, fitur terkait nonaktif dengan
peringatan — program tetap jalan.

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
# Tanpa Telegram/MQTT (mode uji)
python main.py --source 0 --gallery gallery/

# Lengkap: Telegram + MQTT + VLM aktif
python main.py --source 0 --gallery gallery/ --telegram --mqtt --describe --camera-name teras_depan

# Headless + log harian
python main.py --source 0 --gallery gallery/ --telegram --mqtt --no-show --log-dir logs/
```

Flag tambahan: `--face-threshold` (default 0.6), `--notify-cooldown` (default
300 dtk), `--mqtt-status-every` (publish status tiap N frame, default 150),
`--conf`, `--log` (path eksplisit, tanpa rotasi), `--log-dir` (rotasi harian
`events-YYYYMMDD.jsonl`), `--describe`, `--vlm-model`.

## Deskripsi VLM (Fase 5, opsional)

```bash
ollama pull moondream:1.8b   # ±1.7 GB, sekali saja
# alternatif lebih akurat (lebih berat): ollama pull qwen2.5vl:3b
```

Dengan `--describe`, event penting (`person_entered` saat armed) dikirim ke
VLM lokal yang menulis 1-2 kalimat Bahasa Indonesia, mis. "Seorang pria
berjaket merah berdiri di depan pintu." Deskripsi dikerjakan di **thread
latar** (pipeline tidak diblokir, timeout 60 dtk), lalu ditempel ke:

- caption Telegram (baris 🔍),
- payload MQTT (`"description"` di event `face_known`/`face_unknown`),
- `events.jsonl` (event `face_description`).

Model via env `VLM_MODEL` atau flag `--vlm-model`. Tanpa Ollama → deskripsi
otomatis nonaktif, program tetap jalan normal.

## Jalan otomatis saat boot (systemd)

Lihat [`../deploy/README.md`](../deploy/README.md) — service
`sakato-monitor.service`: auto-start, restart on-failure, log harian.

## Perintah Telegram

| Perintah | Fungsi |
|---|---|
| `/start` | daftar perintah |
| `/status` | status notifikasi, event hari ini, kamera |
| `/snapshot` | kirim foto frame terakhir |
| `/arm` | aktifkan notifikasi |
| `/disarm` | matikan notifikasi |
| `/mute <menit>` | bisukan sementara, mis. `/mute 30` |

## MQTT — topik & payload

Jalankan broker dulu (pilih salah satu):

```bash
# Docker:
docker run -d --name mosquitto -p 1883:1883 \
  -v $(pwd)/../mosquitto/config:/mosquitto/config:ro \
  eclipse-mosquitto:2

# atau install langsung (Linux Mint / Ubuntu):
sudo apt install -y mosquitto
sudo systemctl start mosquitto
```

Lalu intip event yang lewat:

```bash
mosquitto_sub -h localhost -t "sakato/monitor/#" -v
```

**Topik event** `sakato/monitor/<camera>/event` (tidak retain):

```json
{"ts": "2026-11-02T10:00:01+00:00", "type": "person_entered", "track_id": 3, "camera": "teras_depan"}
{"ts": "2026-11-02T10:00:02+00:00", "type": "face_unknown", "track_id": 3, "camera": "teras_depan", "name": "Unknown", "similarity": 0.31}
{"ts": "2026-11-02T10:00:03+00:00", "type": "face_known", "track_id": 4, "camera": "teras_depan", "name": "dika", "similarity": 0.87}
{"ts": "2026-11-02T10:05:01+00:00", "type": "person_left", "track_id": 3, "camera": "teras_depan"}
```

**Topik status** `sakato/monitor/<camera>/status` (retain — subscriber baru
langsung dapat nilai terakhir):

```json
{"ts": "2026-11-02T10:00:05+00:00", "camera": "teras_depan", "online": true, "armed": true, "visible": 2}
```

Bila broker tidak ada saat program mulai: peringatan dicetak **sekali**,
program tetap jalan, dan koneksi dicoba ulang otomatis di background.

## Home Assistant

Contoh siap pakai ada di `home-assistant/`:
ikuti `home-assistant/README.md` (pasang integrasi MQTT → tambah sensor →
paste automasi via UI).

## Event log (JSONL)

Sama seperti Fase 2, plus info wajah di console:

```
[event] person_entered track_id=3
[face] track #3 -> dika (0.87)
```

## Keterbatasan (Fase 5)

- MQTT tanpa TLS/auth secara default — aman untuk jaringan rumah sendiri,
  **aktifkan `password_file` di mosquitto.conf sebelum expose ke internet**
  (caranya sudah dikomentari di file config; `mosquitto/config/passwd`
  sudah di-`.gitignore`).
- Event `face_known`/`face_unknown` hanya dikirim saat `person_entered`
  (tidak diulang tiap frame) — HA yang butuh "masih ada orang" pakai topik
  `status` (`visible`).
- **Anti-spoofing lemah**: `buffalo_l` tidak punya liveness detection yang kuat.
  Foto cetak / layar HP wajah terdaftar DAPAT menipu sistem. Jangan jadikan
  satu-satunya kunci akses tanpa faktor kedua.
- Threshold 0.6 adalah titik awal — sesuaikan dengan pencahayaan rumah.
- Deskripsi VLM menambah jeda notifikasi (waktu inference, bisa 10-60 dtk di
  CPU) — notifikasi dikirim setelah deskripsi siap agar caption lengkap.
- Event Frigate (`frigate/*`) belum masuk pipeline sakato — lihat
  [`../docs/DEPLOY_FRIGATE.md`](../docs/DEPLOY_FRIGATE.md).

## Rencana lanjutan (di luar Fase 0-5)

1. Penerjemah `frigate/*` → `sakato/monitor/*` agar Frigate jadi sumber
   deteksi multi-kamera penuh.
2. Dashboard web custom bila UI Frigate + HA belum cukup.
3. TLS untuk MQTT + autentikasi penuh sebelum akses dari internet.
4. Event store SQLite + riwayat klip per event.
