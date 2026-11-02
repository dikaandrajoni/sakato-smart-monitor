# Deploy Frigate (NVR) — mesin terpisah / Raspberry Pi

Frigate adalah NVR modern: rekam 24/7 berbasis event, deteksi objek lokal,
web UI di port 5000. Di arsitektur sakato-smart-monitor, Frigate berperan
sebagai **perekam & detektor cadangan** — notifikasi cerdas tetap dari
pipeline `prototype/` + `agent/`.

## 1. Siapkan mesin

- Raspberry Pi 5 (+ AI HAT bila ada) atau PC/laptop Linux apa saja.
- Install Docker: https://docs.docker.com/engine/install/
- Satu jaringan dengan broker MQTT (atau jalankan mosquitto di mesin ini juga).

## 2. Ambil repo & konfigurasi

```bash
git clone https://github.com/dikaandrajoni/sakato-smart-monitor.git
cd sakato-smart-monitor

# Isi .env (jangan commit!)
cp .env.example .env
nano .env
#   MQTT_HOST=<ip broker, mis. 192.168.1.5>
#   MQTT_PORT=1883
#   MQTT_USER= / MQTT_PASSWORD=   (bila broker pakai auth)
#   CAMERA_1_RTSP=rtsp://user:pass@192.168.1.10:554/stream1

# Konfigurasi Frigate
cp frigate/config.example.yml frigate/config.yml
nano frigate/config.yml
#   - sesuaikan path RTSP tiap kamera
#   - pilih detector: cpu (lambat) / edgetpu (Coral) / hailo (AI HAT)
#   - atur zona & retain sesuai kebutuhan
```

## 3. Jalankan

```bash
# Hanya Frigate + Mosquitto (tanpa HA/agent bila belum perlu):
docker compose up -d mosquitto frigate

# Atau semua layanan:
docker compose up -d
```

Buka **http://&lt;ip-mesin&gt;:5000** untuk Web UI Frigate
(live view, timeline event, putar klip).

## 4. Hubungkan ke pipeline sakato

- Pastikan `MQTT_HOST` di `.env` menunjuk ke broker yang sama dengan
  yang dipakai `prototype/main.py --mqtt` dan `agent/`.
- **Mapping topik** (jangan diubah — format payload beda):
  - Frigate → `frigate/<kamera>/...` (untuk UI & automasi HA standar)
  - Pipeline sakato → `sakato/monitor/<kamera>/event|status` (untuk agent,
    Telegram, automasi contoh di `home-assistant/`)
- Verifikasi: `mosquitto_sub -h <broker> -t "frigate/#" -v` harus
  menampilkan event saat ada gerakan.

## 5. Operasional

```bash
docker compose logs -f frigate      # lihat log
docker compose restart frigate      # restart
docker compose down                 # hentikan semua
```

Rekaman tersimpan di `./frigate/storage` (retain default 7 hari mode motion —
ubah di `config.yml`). Backup folder ini bila rekaman penting.

## Keterbatasan saat ini

- Event Frigate **belum** otomatis masuk pipeline sakato (butuh penerjemah
  `frigate/*` → `sakato/monitor/*`) — itu rencana lanjutan, bukan Fase 5.
  Untuk sekarang, Frigate = perekam + dashboard, pipeline prototype = otak.
