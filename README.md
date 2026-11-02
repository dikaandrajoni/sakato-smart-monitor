# Sakato Smart Monitor

AI-powered smart home monitoring, **dikelola oleh agent**. Local-first: semua
inference jalan di perangkat sendiri, tidak ada video yang dikirim ke cloud.

Evolusi dari [Sistem-Monitoring-Berbasis-Opencv-dan-Telegram](https://github.com/dikaandrajoni/Sistem-Monitoring-Berbasis-Opencv-dan-Telegram)
(Haar cascade + LBPH, 2021) menjadi arsitektur modern:

```
Kamera --RTSP/USB--> Deteksi orang (YOLO11) + Tracking (ByteTrack)
                        |
                        +--> Face Recognition (InsightFace: dikenal vs Unknown)
                        |
                        +--MQTT--> Home Assistant (otomasi: lampu, sirene)
                        |
                        +--> Agent LLM (tanya jawab bhs Indonesia, ringkasan
                        |       harian, eskalasi, arm/disarm, investigasi)
                        |               |
                        |               v
                        +--> Telegram (notif foto + perintah dua arah)
```

## Status fase

| Fase | Isi | Status |
|------|-----|--------|
| 0 | Riset + plan (`docs/RESEARCH_AND_PLAN.md`) | ✅ selesai |
| 1 | Prototipe deteksi orang + tracking (YOLO11 + ByteTrack) | ✅ selesai |
| 2 | Face recognition (InsightFace) + Telegram cerdas | ✅ selesai |
| 3 | MQTT + contoh automasi Home Assistant | ✅ selesai |
| 4 | Agent LLM pengelola (event store, tanya jawab, digest) | ✅ selesai |
| 5 | Frigate penuh, VLM deskripsi klip, hardening | ⏳ berikutnya |

## Struktur repo

```
prototype/          kode utama Fase 1-3 (deteksi, face rec, Telegram, MQTT)
agent/              agent LLM Fase 4 (event store, tools, chat, digest)
frigate/            konfigurasi Frigate NVR (untuk Fase 5)
home-assistant/     contoh automasi + sensor HA
mosquitto/          konfigurasi broker MQTT
docs/               riset & plan Fase 0-5
docker-compose.yml  orkestrasi: mosquitto + frigate + home-assistant + agent
```

## Panduan instalasi (Linux — teruji di Linux Mint)

```bash
# 1. Dependensi sistem
sudo apt install -y python3-venv python3-pip libgl1 mosquitto mosquitto-clients
sudo systemctl start mosquitto

# 2. Clone & venv
git clone https://github.com/dikaandrajoni/sakato-smart-monitor.git
cd sakato-smart-monitor/prototype
python3 -m venv .venv
source .venv/bin/activate

# 3. (Opsional, hemat ~600MB) torch CPU-only dulu — lewati bila ada GPU NVIDIA
pip uninstall -y torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 4. Install
pip install -r requirements.txt
```

> **Windows:** sama, tapi aktivasi venv pakai `.venv\Scripts\Activate.ps1`
> (bila ditolak: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` dulu).

## Panduan pakai

### 1. Test deteksi (Fase 1)

```bash
python main.py --source 0        # 0 = webcam laptop, 1+ = USB, atau rtsp://... / file.mp4
```

Jendela video muncul dengan kotak + ID tiap orang. Tekan `q` untuk keluar.
Event tercatat di `events.jsonl`.

### 2. Daftarkan wajah (Fase 2)

```bash
python enroll.py --source 0 --name dika --shots 20
```

Ikuti panduan di jendela (hijau = tersimpan, merah = cari wajah).
Tips: beberapa sudut & ekspresi biar akurat. Ulangi per orang.

### 3. Bot Telegram (Fase 2)

Buat bot **baru** via [@BotFather](https://t.me/BotFather) (`/newbot`) —
token lama 2021 sudah bocor publik, wajib `/revoke`. Lalu isi file `.env`
di folder `prototype/` (otomatis terbaca, tidak perlu export):

```
TELEGRAM_BOT_TOKEN=token-baru-dari-botfather
TELEGRAM_CHAT_ID=id-chat-kamu
```

Chat ID: kirim "hi" ke bot, buka
`https://api.telegram.org/bot<TOKEN>/getUpdates`, ambil angka `id`.

```bash
python main.py --source 0 --gallery gallery/ --telegram --camera-name teras_depan
```

Perintah bot: `/status` `/snapshot` `/arm` `/disarm` `/mute <menit>`.
Orang tak dikenal → foto + info ke Telegram. Orang dikenal → dicatat diam-diam.

### 4. MQTT + Home Assistant (Fase 3)

```bash
# Terminal 1: intip event yang lewat
mosquitto_sub -h localhost -t "sakato/monitor/#" -v

# Terminal 2: jalankan dengan MQTT
python main.py --source 0 --gallery gallery/ --mqtt --camera-name teras_depan
```

Topik: `sakato/monitor/<kamera>/event` (JSON: ts, type, track_id, name,
similarity) dan `sakato/monitor/<kamera>/status` (retain).
Contoh automasi siap pakai + cara pasang ada di [`home-assistant/README.md`](home-assistant/README.md).

### 5. Agent LLM (Fase 4)

```bash
# Sekali saja: install Ollama + model (~4.7 GB)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b

# Coba tanya jawab dulu
cd ../agent && pip install -r requirements.txt
python -m agent.agent --chat
```

Contoh: "siapa yang datang jam 3 sore?", "ringkasan hari ini".
Butuh event mengalir: jalankan prototype dengan `--mqtt` + mosquitto jalan.
Tanpa Ollama pun bisa — otomatis mode fallback (perintah: ringkasan, status,
cari, arm, disarm). Service penuh: `python -m agent.agent`.

## Troubleshooting

| Gejala | Solusi |
|--------|--------|
| `python3: can't open file '.../pip'` | Ketik `pip install ...`, bukan `python3 pip install` |
| `cv2.imshow is not implemented` | `pip uninstall -y opencv-python-headless && pip install --force-reinstall opencv-python` |
| Ultralytics minta `lap`, suruh rerun | Install otomatis; jalankan ulang perintahnya |
| `[telegram] NONAKTIF` | Isi `.env` di folder `prototype/` (token + chat ID), lalu `git pull` versi terbaru |
| Download > 1GB | Normal sekali saja (torch, model YOLO ±6MB, InsightFace ±300MB, Ollama ±4.7GB). Hemat: torch CPU-only (langkah 3 di atas) |
| Kamera hitam di `--source 0` | Coba `--source 1`; cek `ls /dev/video*` |

## Keamanan

- Jangan pernah commit `.env` atau token asli (sudah di-`.gitignore`).
- Token bot lama (repo 2021) dianggap bocor — revoke via BotFather.
- Repo ini tidak menyimpan data wajah / rekaman; itu data runtime lokal.
- Untuk produksi: aktifkan `password_file` di Mosquitto (lihat komentar di
  `mosquitto/config/mosquitto.conf`).

## Lisensi

MIT.
