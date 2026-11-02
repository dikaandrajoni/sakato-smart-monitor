# Web UI Konfigurasi

Atur Sakato Smart Monitor lewat browser — tanpa edit flag CLI.
Pilih sumber kamera (laptop / USB / RTSP CCTV / file video), nama kamera,
Telegram / MQTT / VLM, lalu start/stop pipeline dan pantau event terakhir.

## Cara jalan

```bash
cd web
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Buka **http://localhost:8080** di browser.

> Syarat: venv `prototype/.venv` sudah terinstall (lihat panduan utama repo).
> Web UI memanggil `prototype/.venv/bin/python prototype/main.py` sebagai
> subprocess — jadi install prototype dulu sebelum pakai web UI.

## Halaman

- **`/`** — dashboard: status pipeline (berjalan/berhenti), tombol Start/Stop,
  10 event terakhir dari `prototype/events.jsonl`, 50 baris terakhir
  `web/pipeline.log`. Refresh otomatis tiap 5 detik.
- **`/config`** — form konfigurasi:
  - **Sumber kamera**: dropdown Laptop / USB / RTSP / File.
    Field URL RTSP / path file / index USB muncul sesuai pilihan.
  - Nama kamera, folder galeri wajah.
  - Checkbox: Telegram, MQTT, deskripsi VLM, mode headless (tanpa GUI).
  - Tombol Simpan → validasi (RTSP harus diawali `rtsp://`, index USB harus
    angka) → tersimpan di `web/config.json`.

## API

| Method & path | Fungsi |
|---|---|
| `GET /api/status` | `{running, config, events[10], log_tail[50]}` |
| `POST /api/config` | Simpan config (JSON). 400 bila validasi gagal |
| `POST /api/start` | Jalankan pipeline dari config tersimpan |
| `POST /api/stop` | Hentikan pipeline |

## Batasan

- **Tanpa autentikasi** — hanya untuk LAN rumah. JANGAN expose ke internet
  / port-forward tanpa proteksi.
- Satu pipeline dalam satu waktu (tombol Start ditolak bila sudah jalan).
- `web/config.json` berisi kredensial RTSP — sudah masuk `.gitignore`,
  jangan di-commit manual.
- Snapshot/live video belum ditampilkan di dashboard (ide lanjutan).

## Ide lanjutan

- Tampilkan frame/snapshot terakhir di dashboard (via `--snapshot` periodik).
- Multi-kamera: beberapa pipeline + tab per kamera.
- Auth sederhana (token di header) bila perlu diakses di luar LAN.
