# Deploy: jalan otomatis saat boot (systemd, Linux)

## Pasang service

```bash
# 1. Sesuaikan user & path di sakato-monitor.service bila username-mu bukan 'dikaaj'
#    (cari semua kemunculan 'dikaaj' dan '/home/dikaaj')

# 2. Copy unit file & aktifkan
sudo cp deploy/sakato-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sakato-monitor.service

# 3. Cek status & log
systemctl status sakato-monitor.service
journalctl -u sakato-monitor.service -f
```

## Berhenti / restart

```bash
sudo systemctl stop sakato-monitor.service
sudo systemctl restart sakato-monitor.service
sudo systemctl disable sakato-monitor.service   # matikan auto-start
```

## Catatan

- Service memakai `.venv` di `prototype/` dan file `.env` di folder yang sama.
  Pastikan `pip install -r requirements.txt` sudah dijalankan sebelumnya.
- Mosquitto sebaiknya jalan juga (atau biarkan program reconnect otomatis
  saat broker tersedia — pola graceful sudah bawaan).
- Log event harian tersimpan di `~/sakato-smart-monitor/logs/events-YYYYMMDD.jsonl`
  (via `--log-dir`); log service-nya di journald (`journalctl`).
- Untuk Ollama (VLM + agent LLM), pasang service Ollama terpisah:
  `ollama serve` biasanya sudah auto-start setelah install via skrip resmi.
- Kamera USB yang dicabut/dicolok ulang: service akan retry (restart on-failure);
  untuk RTSP, `CameraSource` sudah punya reconnect otomatis.
