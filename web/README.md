# Web UI Konfigurasi (multi-kamera)

Atur Sakato Smart Monitor lewat browser — tanpa edit flag CLI.
Kelola **banyak kamera** (laptop / USB / RTSP CCTV / file video), tiap kamera
punya tab sendiri di dashboard: snapshot terakhir (auto-refresh 3 detik),
status, event terfilter, tombol Start/Stop. Bisa juga start/stop semua sekaligus.

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

- **`/`** — dashboard multi-kamera: tab per kamera, masing-masing berisi
  status, **snapshot frame terakhir** (refresh tiap 3 detik via
  `GET /snapshot/<id>`), 10 event terakhir **kamera itu**, 50 baris log
  terakhir, tombol Start/Stop per kamera. Plus tombol Start semua / Stop semua.
- **`/config`** — kelola daftar kamera: tambah (ID + sumber + opsi),
  ubah, hapus, tandai kamera aktif. Validasi sama seperti sebelumnya
  (RTSP wajib `rtsp://`, index USB angka, ID unik huruf/angka/_/-).

> Maksimal wajar **4 kamera aktif bersamaan** — dashboard menampilkan
> peringatan bila lebih (beban CPU).

## API

| Method & path | Fungsi |
|---|---|
| `GET /api/status` | `{cameras: [{id, camera_name, running, events[10], log_tail[50]}], active, running_count}` (+ field lama `running`/`config` untuk kamera aktif) |
| `GET /snapshot/<id>` | JPEG frame terakhir kamera (404 bila belum ada) |
| `GET /api/cameras` | Daftar kamera + kamera aktif |
| `POST /api/cameras` | Tambah kamera (validasi, ID unik) |
| `PUT /api/cameras/<id>` | Ubah kamera (ID tidak bisa diubah) |
| `DELETE /api/cameras/<id>` | Hapus kamera (dihentikan dulu bila jalan) |
| `POST /api/active` | Tandai kamera aktif |
| `POST /api/cameras/<id>/start` | Jalankan pipeline kamera |
| `POST /api/cameras/<id>/stop` | Hentikan pipeline kamera |
| `POST /api/start-all` | Jalankan semua kamera |
| `POST /api/stop-all` | Hentikan semua kamera |
| `POST /api/config`, `POST /api/start`, `POST /api/stop` | Kompatibilitas: operasikan kamera **aktif** |

## Format config (v2) & migrasi

`web/config.json`:

```json
{
  "cameras": [
    {"id": "teras_depan", "camera_type": "laptop", "usb_index": "1",
     "rtsp_url": "", "video_file": "", "camera_name": "Teras Depan",
     "gallery": "gallery/", "telegram": true, "mqtt": false,
     "describe": false, "no_show": true}
  ],
  "active": "teras_depan"
}
```

Config lama format v1 (single kamera) **otomatis dimigrasi** menjadi satu
kamera ber-ID `default` saat dibaca — tidak perlu edit manual.

## Cara kerja snapshot

Saat pipeline distart dari web UI, `prototype/main.py` dijalankan dengan
`--snapshot-file web/snapshots/<id>.jpg` — frame terakhir (berikut kotak
deteksi) ditulis tiap 2 detik. Dashboard menampilkannya via
`GET /snapshot/<id>` dengan refresh 3 detik. Flag `--snapshot-file` juga
bisa dipakai manual dari CLI; default-nya mati (tidak ada perubahan perilaku).

## Batasan

- **Tanpa autentikasi** — hanya untuk LAN rumah. JANGAN expose ke internet
  / port-forward tanpa proteksi.
- Maksimal wajar 4 kamera aktif bersamaan (peringatan otomatis bila lebih).
- `web/config.json` berisi kredensial RTSP — sudah masuk `.gitignore`,
  jangan di-commit manual. `web/snapshots/` & `web/logs/` juga diabaikan.

## Ide lanjutan

- Auth sederhana (token di header) bila perlu diakses di luar LAN.
- Rekam klip video per event, bukan hanya snapshot.
