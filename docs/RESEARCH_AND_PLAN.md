# Riset & Rencana: Upgrade Sistem Monitoring Rumah → Smart Home AI yang Dikelola Agent

Tanggal: 2 November 2026
Tujuan: mengevolusi repo lama `Sistem-Monitoring-Berbasis-Opencv-dan-Telegram` (Haar cascade + LBPH + telepot) menjadi sistem monitoring rumah cerdas berbasis AI modern, dikelola oleh agent AI, 100% pemrosesan lokal (privacy-first).

Status eksperimen: ini masih eksperimen Boss, bukan sistem produksi. Plan di bawah dirancang supaya bisa berhenti di fase mana pun dan tetap punya sesuatu yang jalan.

---

## 1. Ringkasan Eksekutif Riset

| # | Temuan |
|---|--------|
| 1 | **Frigate NVR + Home Assistant adalah stack DIY paling matang (2025–2026).** Frigate open-source, deteksi objek lokal real-time (Coral TPU / Hailo / OpenVINO / NVIDIA GPU), event-based recording, MQTT native ke Home Assistant. Versi terbaru v0.16.4 (Jan 2026). Alternatif (ZoneMinder, motionEye, Shinobi) kalah di deteksi AI + integrasi HA. |
| 2 | **Deteksi orang tidak lagi pakai Haar cascade.** Default produksi 2026: YOLO11/YOLO26 (nano/small) di edge — YOLO11n ~48 ms di CPU ONNX, jauh lebih cepat di Hailo-8/Jetson. Haar cascade & LBPH tertinggal puluhan poin akurasi; pengganti face recognition modern: **InsightFace** (99.86% LFW, self-host gratis, MIT) untuk akurasi maksimal, **DeepFace** (ArcFace ~99.4%, API Python termudah) untuk prototipe cepat. Keduanya punya anti-spoofing (wajib di 2026 — foto cetak bisa menipu LBPH/Haar). |
| 3 | **Tracking antar-frame sekarang standar & murah.** ByteTrack adalah default praktis untuk real-time (100+ FPS di GPU modern, tanpa model Re-ID tambahan, ID stabil). Occlusion berat → BoT-SORT/Deep OC-SORT (ada model appearance ringan). Library siap pakai: `ultralytics` (built-in tracker), `boxmot`, `supervision` (zona/polygon). |
| 4 | **VLM kecil lokal bisa mendeskripsikan kejadian dalam Bahasa Indonesia.** Moondream2 (~1.9B, jalan di CPU/RPi), Qwen2.5-VL 3B / Qwen3-VL 2B (Q4 ~4–6 GB VRAM, Ollama one-command). Pola arsitektur yang benar 2026: **detektor cepat (YOLO) sebagai trigger → VLM sebagai verifikator lapis kedua** yang menulis deskripsi ("pria berjaket merah masuk lewat pintu samping, 21:04"). VLM tidak dipakai sebagai detektor real-time (terlalu lambat). |
| 5 | **"Dikelola agent" sudah ada polanya di industri.** Home Assistant 2025+ punya integrasi Ollama conversation agent (function calling ke semua entity HA), AI Tasks terjadwal, dan dukungan MCP. Pola agentic alarm triage 2026: MCP server membungkus API event VMS/NVR → agent LLM bisa ditanya ("siapa yang datang jam 3 sore?"), investigasi event, korelasikan dengan log akses/jadwal, kasih ringkasan harian, dan eskalasi. Benchmark HomeSec-Bench menunjukkan model lokal 9B (Qwen) hanya selisih ~4 poin dari model cloud — privasi penuh, biaya API nol. |

---

## 2. Hasil Riset per Topik

### 2.1 Deteksi orang/objek di edge

- **YOLOv11/YOLO26** adalah default produksi 2026 (Ultralytics merilis YOLO26 Jan 2026, NMS-free, edge-first; YOLO26x 57.5% mAP@50–95 COCO). YOLOv12 (attention-centric) unggul di scene ramai. Untuk 1–4 kamera rumah: varian **nano/small** sudah lebih dari cukup.
- **RT-DETR**: setara YOLO di latency yang sama, lebih baik untuk oklusi/crowded — tapi ekosistem deployment edge (ONNX/TensorRT/Hailo) lebih matang untuk YOLO.
- **Frigate NVR**: satu container Docker, baca RTSP, deteksi hanya pada substream resolusi rendah (hemat), simpan rekaman hanya saat ada event, publish event ke MQTT (`frigate/events`), WebRTC live view, zona & mask per kamera. Support akselerator: Coral TPU, Hailo, OpenVINO (Intel iGPU), NVIDIA GPU, ONNX CPU.
- Upgrade dari Haar: YOLO di 640×480 bisa ~20 ms/inferensi di Coral (~$40–60) dan jauh lebih cepat di Hailo-8 (26 TOPS).

### 2.2 Face recognition modern

| Library | Akurasi (LFW) | Kelebihan | Cocok untuk |
|---|---|---|---|
| **InsightFace** | 99.86% (SOTA open-source) | RetinaFace/SCRFD detection + ArcFace, ONNX GPU/CPU, anti-spoofing | Produksi akhir, akurasi maksimal |
| **DeepFace** | ~99.4% (ArcFace backend) | `pip install deepface`, 20+ model, API 3 baris, anti-spoofing flag | Prototipe cepat Fase 2 |
| MediaPipe Face | ~98%+ | 60+ FPS, ringan untuk edge | Fallback jika hardware pas-pasan |

Catatan penting: LBPH (repo lama) tidak punya anti-spoofing — foto wajah yang dicetak bisa lolos. DeepFace/InsightFace 2025+ punya liveness check. Database wajah disimpan sebagai embedding (vektor angka), bukan foto mentah — lebih hemat & lebih privat.

### 2.3 Tracking antar-frame & re-identification

- **ByteTrack**: default praktis real-time — tidak butuh model appearance, stabil, cepat. Ideal untuk "orang yang sama jangan di-notif berulang".
- **OC-SORT / BoT-SORT / Deep OC-SORT**: lebih stabil saat oklusi (orang lewat di balik tiang), BoT-SORT punya kompensasi gerak kamera (berguna kalau kamera PTZ/bergerak).
- **Person Re-ID ringan (OSNet)**: mengenali orang yang sama antar-kamera atau setelah keluar-masuk frame — ByteTrack sendiri tidak bisa re-ID setelah track hilang.
- Praktisnya: pakai tracker bawaan `ultralytics` (`model.track(persist=True)`) di Fase 1; naik ke BoT-SORT + Re-ID ringan di Fase 5.

### 2.4 VLM kecil lokal untuk deskripsi kejadian

| Model | Ukuran | Kebutuhan | Cocok untuk |
|---|---|---|---|
| **Moondream2** | ~1.9B | CPU / 2–4 GB | Caption cepat di hardware kecil (RPi) |
| **Qwen2.5-VL 3B** (Q4) | 3B | ~4–6 GB VRAM | Deskripsi + JSON terstruktur via Ollama |
| **Qwen3-VL 2B** | 2B | Edge, Apache 2.0 | Visual agent ringan, long-video reasoning |
| Qwen2.5-VL 7B (Q4) | 7B | ~8–10 GB VRAM | Kualitas terbaik untuk server/laptop GPU |

Pola yang benar: **detektor (YOLO) = mata yang selalu melek → VLM = otak yang dipanggil hanya saat ada event penting** untuk menulis deskripsi Bahasa Indonesia + skor ancaman. Contoh output: "21:04 — 1 orang tak dikenal (pria, jaket merah) memasuki zona TERAS_DEPAN dari arah kiri, membawa tas. Confidence face: tidak cocok database."

### 2.5 Integrasi smart home (Home Assistant + MQTT)

- Frigate publish semua event ke MQTT → Home Assistant auto-discovery → sensor per kamera/objek + `media_player` live stream.
- Otomasi contoh: `person terdeteksi di zona PAGAR jam 22:00–05:00` → nyalakan lampu teras + kirim notif kritis; `orang dikenal pulang` → matikan alarm, nyalakan lampu dalam.
- HA 2025.6+ punya **integrasi Ollama native** (Settings → Devices & Services → Ollama → arahkan ke `http://server:11434`), model tool-capable yang terbukti: `qwen2.5:7b`, `qwen3:4b`. Batas praktis: expose <25–50 entity agar model kecil tidak bingung.
- **AI Tasks** (HA 2025): job terjadwal yang dijalankan LLM — mis. "ringkas event keamanan hari ini jam 21:00". **MCP**: HA bisa expose tools ke model eksternal apa pun.

### 2.6 "Dikelola agent": arsitektur asisten AI

Pola industri 2026 (AWS agentic video intelligence, Verkada/Milestone VLM, Ambient.ai):

```
[Kamera] → [Frigate/YOLO: deteksi+tracking] → [Event store: SQLite/Postgres + embedding]
        → [Face rec: InsightFace] → [VLM: deskripsi event] → [MQTT/HA: aksi fisik]
                                                                  ↓
                                    [Agent LLM (Ollama/cloud) + tools: query_event, get_clip,
                                     arm/disarm, ringkasan_harian, eskalasi] ←→ [Telegram/HA chat]
```

Kemampuan agent yang realistis:
- **Tanya jawab natural**: "siapa yang datang jam 3 sore?" → agent query event store (filter waktu + face match) → jawab + lampirkan klip.
- **Investigasi**: "tunjukkan semua orang tak dikenal minggu ini" → RAG di atas event log (embedding deskripsi VLM).
- **Arm/disarm & mode**: "mode malam" → agent set HA alarm + naikkan sensitivitas zona.
- **Ringkasan harian terjadwal** (AI Task / cron): "Hari ini 14 event, 3 orang tak dikenal, 0 eskalasi."
- **Eskalasi darurat**: event skor tinggi (intruder + jam malam + zona dalam) → telepon/panggilan + sirene, bukan cuma chat.
- **Anti-halusinasi**: agent HANYA boleh menjawab dari event store (tool result), dilarang mengarang; setiap klaim "siapa" harus punya face-match score terlampir.

### 2.7 Hardware edge yang realistis (harga pasar global, Okt–Nov 2026)

| Opsi | Compute AI | Harga kisaran | Cocok untuk |
|---|---|---|---|
| **RPi 5 8GB + AI HAT+ 26 TOPS (Hailo-8)** | 26 TOPS INT8 @ ~2.5W | Kit ~$195 (≈ Rp 3,2 jt); HAT saja $160–185 | **Rekomendasi utama**: Frigate multi-kamera, hemat daya, ekosistem RPi matang |
| RPi 5 + AI HAT+ 13 TOPS (Hailo-8L) | 13 TOPS | HAT dari $70 (≈ Rp 1,2 jt + board) | Budget: 1–2 kamera |
| RPi 5 + Google Coral USB | 4 TOPS | ~$30–40 (≈ Rp 500–650 rb) | Paling murah, Frigate klasik |
| **Jetson Orin Nano Super dev kit** | 67 TOPS, Ampere GPU, 8GB | **$399** (naik dari $249 sejak Juli 2026) ≈ Rp 6,6 jt | Power user: YOLO + VLM 3B + LLM 8B dalam satu box |
| Laptop bekas (i5 gen 8+, 8GB RAM) | CPU + OpenVINO/iGPU | Rp 2–3,5 jt | **Fase 1–2 tanpa beli hardware baru** |
| AI HAT+ 2 (Hailo-10H, 40 TOPS INT4, 8GB onboard) | Vision + LLM/VLM lokal | ~$340 kit | Kalau mau LLM+VLM jalan di HAT, bukan di host |

Catatan Indonesia: harga street Tokopedia/Shopee biasanya 10–25% di atas harga USD di atas (kurs ±Rp 16.500). RPi 5 8GB board saja ~Rp 2,5–3 jt; kamera IP WiFi ONVIF (Tapo/Imou) Rp 350–600 rb/unit. **Webcam USB cukup untuk Fase 1**, tapi untuk produksi pilih **kamera IP** (RTSP/ONVIF, PoE lebih stabil, tahan outdoor, tidak mengikat ke satu komputer).

### 2.8 Pola bot Telegram modern (pengganti telepot)

- `telepot` sudah usang — ganti ke **`python-telegram-bot` v22+** (async, Bot API 9.x) atau `aiogram`.
- Pola notifikasi Frigate+Telegram yang terbukti (komunitas HA): kirim **foto snapshot saat event mulai → edit caption yang sama saat event selesai** (chat rapi, tidak spam); kirim **klip video ke grup/channel terpisah tanpa notifikasi** sebagai arsip.
- **Inline keyboard** per notifikasi: [🔇 Bisukan 1 jam] [✅ Kenali wajah ini] [📹 Lihat live] [🚨 Eskalasi] — callback langsung eksekusi aksi.
- **Anti-spam**: cooldown per zona/orang (mis. 1 notif per orang per 15 menit), dedup event lintas kamera (orang sama di 2 kamera = 1 notif), prioritas (silent vs bunyi), quiet hours.
- Token & chat_id **wajib** dari environment variable / secret manager — tidak pernah hardcode (pelajaran dari repo lama).

### 2.9 Privasi: local-first

- Semua inference (deteksi, face rec, VLM, LLM agent) jalan di perangkat rumah — tidak ada frame wajah ke cloud.
- Database wajah = embedding terenkripsi di disk lokal; retensi klip otomatis (mis. hapus >30 hari kecuali event penting).
- Pengecualian sadar: kalau pakai LLM cloud (Claude/GPT) untuk agent, yang dikirim hanya **teks deskripsi event + metadata**, tidak pernah foto wajah. Opsi full-lokal tetap tersedia (Qwen 7–9B di Jetson/laptop GPU).
- Catatan regulasi: face recognition untuk keamanan rumah pribadi = penggunaan personal, tapi tetap bijak: beri tahu anggota rumah, jangan arahkan kamera ke properti tetangga.

---

## 3. Perbandingan Opsi Arsitektur

| Aspek | **A. Frigate + Home Assistant + Agent LLM (REKOMENDASI)** | B. Pipeline Python custom (evolusi repo lama) | C. Hybrid: custom detector + HA |
|---|---|---|---|
| Deteksi & tracking | Frigate (YOLO, multi-kamera, zona) — tinggal konfigurasi YAML | Tulis sendiri: OpenCV + ultralytics + tracker | Custom service deteksi, event via MQTT ke HA |
| Face recognition | Service terpisah (InsightFace) yang subscribe event Frigate | Modul dalam pipeline | Sama seperti A |
| VLM deskripsi | Service/worker yang dipanggil per event penting | Modul dalam pipeline | Sama seperti A |
| Otomasi fisik | Home Assistant (ribuan integrasi, UI dashboard) | Tulis sendiri (GPIO/MQTT manual) | Home Assistant |
| Agent pengelola | HA Ollama conversation + AI Tasks + custom MCP/tools | Bot Telegram + LLM dengan tool manual | Kombinasi |
| Notifikasi | HA Telegram integration / bot custom python-telegram-bot | Bot custom | Bot custom |
| Effort awal | Rendah–sedang (instalasi + YAML) | Tinggi (bangun NVR mini sendiri) | Sedang |
| Fleksibilitas eksperimen | Sedang (terikat konvensi Frigate) | **Tinggi** (kode milik sendiri) | Tinggi |
| Multi-kamera | Sangat baik (desain untuk itu) | Harus bangun sendiri (threading, sinkronisasi) | Baik |
| Biaya software | Rp 0 (semua open-source) | Rp 0 | Rp 0 |
| Ketergantungan cloud | Nol (opsional untuk LLM agent) | Nol | Nol |
| Risiko | Belajar konvensi Frigate/HA di awal | Reinvent the wheel; bug konkruensi; waktu lama | Dua sistem untuk dirawat |

**Rekomendasi: Opsi A untuk sistem produksi rumah; Opsi B hanya untuk Fase 1 sebagai latihan** (memang berguna untuk memahami cara kerja detector+tracker sebelum "naik kelas" ke Frigate). Alasan jujur: membangun NVR multi-kamera yang stabil (reconnect RTSP, buffering, retensi disk, sinkronisasi waktu) adalah pekerjaan berbulan-bulan yang sudah diselesaikan Frigate. Energi Boss lebih baik dipakai di lapisan yang membedakan: face recognition + VLM deskripsi + agent pengelola — tiga hal yang Frigate tidak sediakan out-of-the-box.

---

## 4. Rencana Bertahap

### Fase 0 — Riset & keputusan arsitektur ✅ (selesai, dokumen ini)

- **Tujuan**: paham landscape, pilih stack, tetapkan budget hardware.
- **Kriteria selesai**: dokumen ini dibaca & disetujui Boss.
- **Decision point untuk Boss**: pilih **jalur hardware** — (a) mulai Fase 1–2 di laptop bekas tanpa beli apa-apa, (b) langsung beli RPi 5 + AI HAT+ 26 TOPS, atau (c) Jetson Orin Nano Super untuk all-in-one. Rekomendasi: **(a) dulu**, beli hardware di akhir Fase 2 setelah pipeline terbukti.

### Fase 1 — Prototipe deteksi + tracking di laptop (estimasi 2–4 hari)

- **Tujuan**: ganti Haar cascade dengan YOLO + ByteTrack, buktikan real-time di hardware yang ada.
- **Stack**: Python 3.11+, `ultralytics` (YOLO11n), OpenCV, webcam USB / file video.
- **Lingkup**:
  - Script `detect.py`: baca kamera → YOLO11n deteksi `person` → `model.track(persist=True)` → tampilkan bounding box + track ID stabil.
  - Zona sederhana (polygon via `supervision`): hitung "orang masuk zona TERAS".
  - Ukur FPS di laptop Boss; target ≥10 FPS CPU (cukup untuk prototipe).
  - Perbaiki bug klasik repo lama: loop yang bisa di-break (`q`/ESC), tanpa `sleep(10)` per frame.
- **Kriteria selesai**: video demo 1 menit: 2 orang berjalan, ID track tidak tertukar, counter zona benar, FPS tercatat.
- **Decision point**: FPS <8 di laptop? → putuskan beli akselerator (Coral USB termurah) atau lanjut ke RPi+AI HAT di Fase 2.

### Fase 2 — Face recognition + Telegram cerdas (estimasi 3–5 hari)

- **Tujuan**: kenali wajah anggota rumah, kirim notifikasi Telegram yang pintar (bukan spam).
- **Stack**: DeepFace (prototipe) → InsightFace (final), `python-telegram-bot` v22 async, SQLite event store.
- **Lingkup**:
  - `enroll.py`: daftarkan wajah (5–10 foto/orang, variasi angle) → simpan embedding + nama.
  - Pipeline: YOLO deteksi orang → crop wajah → face embedding → cocokkan database (threshold jelas, mis. cosine distance) → label Dikenal/Tak dikenal.
  - Anti-spoofing aktif (flag bawaan DeepFace/InsightFace).
  - Bot Telegram: token dari **env var**; perintah `/status`, `/siapa` (foto terakhir + identitas); notifikasi dengan **cooldown per orang per zona** (mis. 15 menit) + **inline button** [Bisukan 1 jam] [Tandai dikenal].
  - Event log di SQLite: `timestamp, camera, track_id, label, face_score, snapshot_path`.
- **Kriteria selesai**: demo — wajah Boss dikenali (<2 detik), orang tak dikenal memicu 1 notif + foto (bukan 50 notif), `/siapa` menjawab benar.
- **Decision point untuk Boss**: puas dengan akurasi DeepFace? Kalau butuh lebih akurat/cepat → migrasi ke InsightFace (perlu install ONNX Runtime). **Keputusan beli hardware edge dibuat di sini.**

### Fase 3 — Integrasi Home Assistant + MQTT (estimasi 2–3 hari)

- **Tujuan**: sistem menjadi bagian smart home, bukan aplikasi terpisah.
- **Stack**: Home Assistant (Docker/RPi), Mosquitto MQTT, Frigate (mulai diperkenalkan sebagai pengganti script Fase 1 untuk multi-kamera).
- **Lingkup**:
  - Install HA + Mosquitto; pipeline Fase 2 publish event ke MQTT (`rumah/kamera/teras/event`).
  - Otomasi HA: orang tak dikenal di zona PAGAR jam 22:00–05:00 → lampu teras ON + notif prioritas tinggi; anggota rumah pulang → disarm parsial.
  - Dashboard HA: kartu kamera + daftar event terakhir.
  - (Opsional, jika sudah beli RPi) migrasi deteksi ke Frigate di RPi; service face-rec/VLM tetap sebagai worker yang subscribe `frigate/events`.
- **Kriteria selesai**: skenario uji — simulasikan "orang tak dikenal di pagar jam 23:00" → lampu menyala + notif Telegram masuk <5 detik.
- **Decision point**: tetap 1 kamera (script cukup) atau tambah kamera (wajib Frigate)?

### Fase 4 — Agent LLM pengelola (estimasi 5–10 hari, bisa iteratif)

- **Tujuan**: Boss bisa "ngobrol" dengan sistem keamanannya dalam Bahasa Indonesia.
- **Stack**: Ollama (model tool-capable: `qwen2.5:7b` / `qwen3:4b`) di server/laptop; HA Ollama conversation agent; custom tools/MCP: `query_event`, `get_clip`, `arm_system`, `disarm_system`, `ringkasan_harian`.
- **Lingkup**:
  - Event store Fase 2 diperkaya: deskripsi VLM per event penting (Moondream2/Qwen2.5-VL 3B via Ollama) + embedding untuk pencarian semantik.
  - Tools untuk agent (function calling): cari event by waktu/orang/zona, ambil klip, baca status sistem, arm/disarm, subscribe notifikasi.
  - Aturan keras: agent hanya menjawab dari hasil tool (no halusinasi identitas); setiap identifikasi orang mencantumkan skor.
  - AI Task terjadwal: ringkasan harian 21:00 via Telegram ("Hari ini 14 event, 3 tak dikenal, 0 eskalasi").
  - Eskalasi: skor ancaman tinggi → sirene/lampu + telepon (via HA automation), bukan sekadar chat.
- **Kriteria selesai**: 5 skenario tanya jawab lolos — "siapa yang datang jam 3 sore?", "ada orang tak dikenal minggu ini?", "mode malam", "ringkas hari ini", "tunjukkan klip terakhir di pagar" — semua dijawab benar + bukti klip.
- **Decision point**: model lokal cukup pintar? Kalau jawaban ngaco → naikkan ke model 14B / pertimbangkan LLM cloud **hanya untuk teks** (foto tidak pernah ke cloud).

### Fase 5 — Hardening & produksi (estimasi 3–5 hari)

- **Tujuan**: sistem layak jalan 24/7 tanpa diawasi.
- **Lingkup**:
  - Keamanan: semua secret di env/secret manager; tidak ada credential di repo; update dependensi; user Telegram di-whitelist (bot hanya merespons chat_id terdaftar).
  - Multi-kamera: Frigate multi-stream, dedup event lintas kamera (Re-ID ringan / korelasi waktu + zona).
  - Reliabilitas: auto-restart (systemd/Docker restart policy), watchdog koneksi kamera, health check + notif "sistem down".
  - Retensi: hapus klip >30 hari otomatis (kecuali ditandai penting); backup database event mingguan.
  - Dashboard: HA dashboard final + halaman status untuk Boss.
  - Dokumentasi: README lengkap (cara install, enroll wajah, troubleshooting), `requirements.txt` / `docker-compose.yml`.
- **Kriteria selesai**: jalan 7×24 jam tanpa intervensi; uji cabut kabel kamera → notif "kamera offline" <1 menit; audit: tidak ada secret di repo.

---

## 5. Estimasi Biaya (rupiah, kurs ±16.500, harga street Indonesia +10–25%)

| Paket | Isi | Estimasi |
|---|---|---|
| **Paket Nol Rupiah (Fase 1–2)** | Laptop bekas yang sudah ada + webcam USB | Rp 0 |
| **Paket Hemat** | RPi 5 8GB + Coral USB TPU + 1 kamera IP WiFi + SD card/SSD + PSU 27W | ± Rp 4–5 jt |
| **Paket Rekomendasi** | RPi 5 8GB + AI HAT+ 26 TOPS + 2 kamera IP + SSD NVMe + PSU + casing + kabel | ± Rp 7–9 jt |
| **Paket All-in-One** | Jetson Orin Nano Super + 2–3 kamera IP + SSD + PSU | ± Rp 9–12 jt |
| Operasional | Listrik (RPi ~10W ≈ Rp 15 rb/bulan), internet existing | ~Rp 0 tambahan |

Software: Rp 0 — Frigate, Home Assistant, InsightFace, DeepFace, Ollama, python-telegram-bot semuanya open-source. Tidak ada langganan cloud.

---

## 6. Risiko & Mitigasi

| Risiko | Mitigasi |
|---|---|
| Face recognition salah identifikasi → aksi salah (lampu/sirene) | Threshold konservatif; aksi fisik hanya untuk "tak dikenal + zona sensitif + jam malam"; identifikasi orang selalu butuh skor tinggi |
| Notifikasi spam | Cooldown + dedup + prioritas sejak Fase 2; uji dengan skenario nyata |
| Hardware tidak sampai / mahal di Indonesia | Fase 1–2 jalan di laptop dulu; beli setelah terbukti |
| Model lokal "ngaco" menjawab | Aturan tool-grounding; fallback model lebih besar; opsi cloud hanya untuk teks |
| Kamera mengarah ke tetangga / masalah privasi | Atur zona & mask; beri tahu anggota rumah; simpan data lokal |
| Repo lama punya token bocor | Token lama dianggap kompromi — revoke via BotFather sebelum dipakai ulang |

---

## 7. Referensi

- Frigate NVR (docs & perbandingan): https://www.amireslampanah.com/tutorials/frigate-nvr-ai-detection.html · https://selfhosting.sh/compare/frigate-vs-motioneye/ · https://dev.to/selfhostingsh/frigate-vs-zoneminder-35ji
- YOLO edge benchmark: https://www.forasoft.com/blog/article/machine-learning-realtime-monitoring · https://www.rizwanai.com/yolo-tracker-benchmarks
- Face recognition: https://www.edenai.co/post/top-free-face-compare-tools-apis-and-open-source-models · https://copyprogramming.com/howto/python-how-to-do-face-recognition-in-python
- VLM di edge: https://localaimaster.com/blog/local-ai-vision-tasks · https://learnopencv.com/vlm-on-edge-devices/
- Tracking: https://github.com/manchado53/ai-driven-soccer-analysis/blob/HEAD/related_works.md
- HA + LLM lokal: https://devhandbook.io/blog/2026-04-12-home-assistant-local-ai-agents/ · https://www.aitooldiscovery.com/how-to/home-assistant-local-llm
- Agent untuk video security: https://aws.amazon.com/blogs/machine-learning/agentic-conversational-video-intelligence-built-on-aws/ · https://www.forasoft.com/blog/article/video-surveillance-software-development · HomeSec-Bench: https://raw.githubusercontent.com/red40maxxer/DeepCamera/master/docs/paper/home-security-benchmark.pdf
- Hardware: https://computingforgeeks.com/best-ai-accelerator-raspberry-pi-5/ · https://raspberry.tips/en/raspberrypi-tutorials/raspberry-pi-ai-hat-plus-ai-acceleration · https://www.socketxp.com/iot/nvidia-jetson-nano-vs-raspberry-pi-which-one-is-better-for-your-project/
- Telegram + Frigate: https://community.home-assistant.io/t/frigate-telegram-notifications-perfected-but-with-quite-some-work-on-your-side/870864
