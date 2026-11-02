# Sakato Smart Monitor

AI-powered smart home monitoring, managed by an agent. Local-first: semua
inference jalan di perangkat sendiri, tidak ada video yang dikirim ke cloud.

Evolusi dari [Sistem-Monitoring-Berbasis-Opencv-dan-Telegram](https://github.com/dikaandrajoni/Sistem-Monitoring-Berbasis-Opencv-dan-Telegram)
(Haar cascade + LBPH, 2021) menjadi arsitektur modern:

```
Kamera IP --RTSP--> Frigate (deteksi orang/objek, YOLO)
                        |
                        +--MQTT--> Home Assistant (otomasi: lampu, sirene, kunci)
                        |
                        +--event--> Face Recognition (InsightFace)
                        |               |
                        |               v
                        +--------> Agent LLM (deskripsi kejadian bhs Indonesia,
                                   query bahasa natural, ringkasan harian,
                                   arm/disarm, investigasi)
                                        |
                                        v
                                   Telegram (notif + perintah dua arah)
```

## Status

Fase 0 (riset) selesai. Lihat [docs/RESEARCH_AND_PLAN.md](docs/RESEARCH_AND_PLAN.md)
untuk temuan riset, perbandingan arsitektur, dan plan Fase 0-5.

## Struktur repo

```
frigate/            konfigurasi Frigate NVR (config.example.yml)
home-assistant/     konfigurasi Home Assistant (MQTT, automasi)
agent/              agent LLM pengelola (tools, prompt, event store)
docs/               riset & plan
docker-compose.yml  orkestrasi lokal: frigate + mosquitto + home-assistant
```

## Mulai cepat (Fase 1)

1. Copy `.env.example` menjadi `.env`, isi nilai yang dibutuhkan.
2. Copy `frigate/config.example.yml` menjadi `frigate/config.yml`,
   sesuaikan alamat RTSP kamera.
3. `docker compose up -d`
4. Buka Frigate UI di `http://localhost:5000`.

## Keamanan

- Jangan pernah commit file `.env` atau token asli. Semua secret lewat
  environment variable (lihat `.env.example`).
- Repo ini tidak menyimpan data wajah / rekaman. Itu data runtime lokal.

## Lisensi

MIT (lihat LICENSE bila sudah ditambahkan).
