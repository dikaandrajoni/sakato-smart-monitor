# Panduan Instalasi & Setup di Windows

Panduan ini untuk Windows 10/11 (teruji secara logika dari kode; bila ada
yang tidak jalan di mesinmu, laporkan via issue).

## 1. Install dependensi

| Kebutuhan | Cara |
|-----------|------|
| Python 3.10+ | Unduh di [python.org](https://www.python.org/downloads/), **centang "Add python.exe to PATH"** saat install |
| Git | [git-scm.com](https://git-scm.com/download/win) |
| Mosquitto (MQTT) | [mosquitto.org/download](https://mosquitto.org/download/) → install, pilih "install as service" agar jalan otomatis |
| Ollama (untuk agent Fase 4) | [ollama.com/download](https://ollama.com/download) → `OllamaSetup.exe` |

Verifikasi di PowerShell:

```powershell
python --version   # harus 3.10+
git --version
```

## 2. Clone & venv

```powershell
git clone https://github.com/dikaandrajoni/sakato-smart-monitor.git
cd sakato-smart-monitor\prototype
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> Bila PowerShell menolak aktivasi (`execution policy`):
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> .\.venv\Scripts\Activate.ps1
> ```

## 3. Install paket Python

```powershell
# Hemat ~600MB bila tidak ada GPU NVIDIA: torch CPU-only dulu
pip uninstall -y torch torchvision
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements.txt
```

Saat pertama jalan, model ikut terunduh otomatis (sekali saja):
YOLO11n ±6MB, InsightFace buffalo_l ±300MB.

## 4. Jalankan per fase

```powershell
# Fase 1: test deteksi (0 = webcam laptop, 1+ = USB, atau rtsp://... / file.mp4)
python main.py --source 0

# Fase 2a: daftarkan wajah
python enroll.py --source 0 --name dika --shots 20

# Fase 2b: buat file .env di folder prototype/ (Notepad), isi:
#   TELEGRAM_BOT_TOKEN=token-dari-botfather
#   TELEGRAM_CHAT_ID=id-chat-kamu
# (otomatis terbaca, tidak perlu set manual)

# Fase 2c: jalan dengan Telegram
python main.py --source 0 --gallery gallery/ --telegram --camera-name teras_depan

# Fase 3: tambah MQTT (pastikan service Mosquitto jalan)
python main.py --source 0 --gallery gallery/ --mqtt --camera-name teras_depan

# Fase 4: agent (di folder agent/)
cd ..\agent
pip install -r requirements.txt
ollama pull qwen2.5:7b        # ±4.7GB; atau qwen2.5:1.5b (±1GB) untuk laptop minim
python -m agent.agent --chat  # test tanya jawab
```

## 5. Jalan otomatis saat Windows nyala (pengganti systemd)

1. Tekan `Win+R` → ketik `taskschd.msc` → Enter (Task Scheduler).
2. *Create Basic Task* → nama `SakatoMonitor`.
3. Trigger: *When the computer starts*.
4. Action: *Start a program*:
   - Program: `C:\path\ke\sakato-smart-monitor\prototype\.venv\Scripts\python.exe`
   - Arguments: `main.py --source 0 --gallery gallery/ --telegram --mqtt --camera-name teras_depan`
   - Start in: `C:\path\ke\sakato-smart-monitor\prototype`
5. Centang *Run whether user is logged on or not* bila perlu.

## Troubleshooting Windows

| Gejala | Solusi |
|--------|--------|
| `python` tidak dikenal | Install ulang Python dengan centang "Add to PATH", atau pakai `py -3` |
| Kamera hitam di `--source 0` | Coba `--source 1`; cek Device Manager → Cameras |
| `cv2.imshow is not implemented` | `pip uninstall -y opencv-python-headless` lalu `pip install --force-reinstall opencv-python` |
| `[telegram] NONAKTIF` | Pastikan file `.env` ada di folder `prototype/` (bukan root repo) |
| Mosquitto tidak konek | Cek service jalan: `services.msc` → Mosquitto Broker → Start |
| Ollama lambat di CPU lama | Pakai model lite: `ollama pull qwen2.5:1.5b` + `set OLLAMA_MODEL=qwen2.5:1.5b` |

> Catatan: Docker Desktop di Windows bisa menjalankan `docker-compose.yml`
> (Frigate + HA), tapi butuh WSL2 dan RAM lega — untuk eksperimen, prototype
> Python di atas sudah cukup.
