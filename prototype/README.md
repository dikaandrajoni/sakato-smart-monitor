# Fase 3 — MQTT + Home Assistant

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

# Lengkap: Telegram + MQTT aktif
python main.py --source 0 --gallery gallery/ --telegram --mqtt --camera-name teras_depan

# Headless
python main.py --source 0 --gallery gallery/ --telegram --mqtt --no-show
```

Flag tambahan: `--face-threshold` (default 0.6), `--notify-cooldown` (default
300 dtk), `--mqtt-status-every` (publish status tiap N frame, default 150),
`--conf`, `--log`.

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

## Keterbatasan Fase 3

- MQTT tanpa TLS/auth secara default — aman untuk jaringan rumah sendiri,
  **aktifkan `password_file` di mosquitto.conf sebelum expose ke internet**
  (caranya sudah dikomentari di file config).
- Event `face_known`/`face_unknown` hanya dikirim saat `person_entered`
  (tidak diulang tiap frame) — HA yang butuh "masih ada orang" pakai topik
  `status` (`visible`).
- **Anti-spoofing lemah**: `buffalo_l` tidak punya liveness detection yang kuat.
  Foto cetak / layar HP wajah terdaftar DAPAT menipu sistem. Jangan jadikan
  satu-satunya kunci akses tanpa faktor kedua.
- Threshold 0.6 adalah titik awal — sesuaikan dengan pencahayaan rumah.

## Rencana Fase 4

1. **Frigate NVR penuh** (gantikan prototype sebagai sumber deteksi
   multi-kamera): `docker-compose.yml` sudah menyiapkan service-nya.
2. **VLM lokal** (Moondream2 / Qwen2.5-VL via Ollama) untuk deskripsi kejadian
   Bahasa Indonesia sebagai verifikator lapis kedua.
3. **Agent LLM pengelola** — query bahasa natural atas event store, investigasi
   klip, perintah arm/disarm (lihat `agent/README.md` di root repo).
4. Event store SQLite + riwayat klip per event.
