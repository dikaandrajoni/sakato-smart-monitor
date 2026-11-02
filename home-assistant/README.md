# Home Assistant — contoh konfigurasi sakato-smart-monitor (Fase 3)

File di folder ini:

| File | Fungsi |
|---|---|
| `configuration.example.yaml` | Contoh blok `mqtt:` + sensor "Sakato orang terlihat" untuk `configuration.yaml` |
| `automations.example.yaml` | 2 automasi siap pakai (+1 opsional): lampu teras saat orang tak dikenal, matikan lampu saat sepi 5 menit |

## Cara pasang

### 1. Aktifkan integrasi MQTT di HA
Settings > Devices & services > Add integration > **MQTT**.
Broker = IP mesin tempat mosquitto jalan (mis. IP laptop/RPi), port `1883`.
Bila mosquitto pakai user/password, isi juga.

### 2. Tambah sensor (satu kali)
Copy blok `mqtt.sensor` dari `configuration.example.yaml` ke
`home-assistant/config/configuration.yaml`, sesuaikan nama kamera pada
topik (`teras_depan` → sesuai `--camera-name` kamu), lalu restart HA
(Settings > System > Restart).

### 3. Tambah automasi via UI (disarankan)
Settings > Automations & Scenes > Create automation > titik tiga
(kanan atas) > **Edit in YAML** > paste satu blok dari
`automations.example.yaml` > Save. Ulangi untuk automasi kedua.

Ganti `light.lampu_teras` dengan entity lampu kamu yang sebenarnya
(lihat Settings > Devices & services > Entities).

### 4. Test
Jalankan prototype dengan `--mqtt`, lalu di HA:
Developer Tools > MQTT > Listen to topic `sakato/monitor/#` — event
harus muncul saat ada orang lewat depan kamera.

## Catatan
- Semua file di sini hanya **contoh** (`.example.yaml`) — jangan di-rename
  jadi `.yaml` langsung tanpa penyesuaian entity & nama kamera.
- Tidak ada password/token di file contoh ini.
