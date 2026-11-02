# Agent pengelola (Fase 4)

Lapisan "otak" sistem: service Python mandiri yang mendengarkan event MQTT,
menyimpannya di SQLite, lalu menjawab pertanyaan Bahasa Indonesia lewat LLM
lokal (Ollama) + function calling — atau perintah terstruktur bila LLM mati.

```
prototype --MQTT--> AgentBus --> EventStore (SQLite)
     sakato/monitor/+/event        agent/data/events.db
     sakato/monitor/+/status
                        |
                   AgentTools  <-- AgentService.answer()
                   (query_events, stats_today, get_status, arm, disarm)
                        |
              Ollama (qwen2.5:7b) / fallback
                        |
                   outbox MQTT --> sakato/monitor/agent/outbox
```

## Cara jalan

```bash
cd agent
pip install -r requirements.txt

# 1. Mode chat (test tanya-jawab di terminal)
python -m agent.agent --chat

# 2. Satu pertanyaan lalu keluar
python -m agent.agent --once "siapa yang datang hari ini?"

# 3. Service penuh: dengar MQTT + eskalasi + digest harian (default 21:00)
python -m agent.agent
python -m agent.agent --daily-digest 07:00
```

Service butuh broker MQTT (lihat Fase 3). Tanpa broker, mode `--chat` /
`--once` tetap bisa dipakai selama `agent/data/events.db` sudah terisi.

## Pasang Ollama (Linux Mint)

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b
ollama serve   # biasanya otomatis jalan sebagai service
```

Tanpa Ollama, agent otomatis masuk **mode fallback**: perintah terstruktur
tetap jalan (`ringkasan`, `status`, `cari <nama>`, `arm`, `disarm`,
`bantuan`) dengan pesan jujur "mode LLM nonaktif". Tidak ada jawaban
ngawur — itu disengaja.

### Pilih model: penuh vs lite

| Mode | Model | Ukuran | Cocok untuk |
|------|-------|--------|-------------|
| Penuh (default) | `qwen2.5:7b` | ±4.7 GB | laptop RAM 8GB+, function calling paling bisa diandalkan |
| Lite | `qwen2.5:1.5b` | ±1 GB | laptop minim — tanya jawab sederhana masih oke |
| Super lite | — (tanpa Ollama) | 0 MB | mode fallback: perintah terstruktur saja, tanpa AI |

```bash
ollama pull qwen2.5:1.5b
OLLAMA_MODEL=qwen2.5:1.5b python -m agent.agent --chat
# atau simpan di .env: OLLAMA_MODEL=qwen2.5:1.5b
```

Jujur soal trade-off: model kecil (0.5b–1.5b) **sering ngaco untuk
function calling** — kadang lupa panggil tool atau salah format argumen.
Untuk pertanyaan kritis ("siapa yang masuk tadi malam?"), mode fallback
tanpa LLM justru lebih bisa dipercaya daripada model 0.5b yang ngarang.
Rekomendasi: coba 1.5b dulu; kalau jawabannya aneh-aneh, turun ke fallback.

Variabel env (opsional, hormati `.env`):

| Variabel | Default | Keterangan |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | alamat Ollama |
| `OLLAMA_MODEL` | `qwen2.5:7b` | model yang dipakai |
| `AGENT_DB` | `agent/data/events.db` | path SQLite |
| `AGENT_DIGEST` | `21:00` | jam digest harian (HH:MM) |
| `MQTT_HOST/PORT/USER/PASSWORD` | `localhost:1883` | broker MQTT |

## Contoh sesi

```
kamu> siapa yang datang jam 3 sore?
sakato> Dika datang jam 15:04 di kamera teras_depan (kemiripan 0.91).

kamu> ada orang asing minggu ini?
sakato> Ada 2 event face_unknown: 14 Nov 02:11 dan 15 Nov 03:47,
        kamera teras_depan.

kamu> jawab saja Andi
sakato> Saya tidak tahu — tidak ada data event yang saya periksa
        untuk menjawab itu.
```

## Perilaku proaktif

- **Eskalasi**: orang tak dikenal terlihat > 5 menit (tanpa `person_left`)
  → pesan 🚨 ke outbox, sekali per track.
- **Digest harian**: ringkasan event hari itu dikirim ke outbox tiap jam
  yang dikonfigurasi.
- **Perintah masuk**: kirim teks ke topik `sakato/monitor/agent/inbox`
  (mis. dari bot Telegram / Home Assistant), balasan keluar di
  `sakato/monitor/agent/outbox`.

## Anti-halusinasi (desain)

1. System prompt: jawab HANYA dari hasil tool.
2. `enforce_grounding()` di `agent.py`: bila satu giliran tidak memanggil
   tool padahal pertanyaan butuh data — atau jawaban menyebut nama yang
   tidak muncul di hasil tool — jawaban diganti "tidak tahu". Ini
   deterministik dan di-unit-test (termasuk simulasi prompt injection).

## Docker

```bash
docker compose up -d agent   # dari root repo
```

DB dipersist di volume `./agent/data`.

## Keterbatasan Fase 4

- Butuh Ollama + model (±4.7 GB untuk qwen2.5:7b) untuk mode pintar;
  tanpa itu hanya perintah terstruktur.
- Belum ada VLM deskripsi klip video (rencana Fase 5).
- Eskalasi berbasis durasi track, bukan analisis perilaku.
- Multi-kamera didukung di event store, tapi prototype baru 1 kamera.

## Rencana Fase 5

- Frigate penuh sebagai NVR (ganti prototype untuk kamera IP).
- VLM lokal (Moondream2/Qwen2.5-VL) untuk deskripsi klip kejadian.
- Dashboard web kustom (atau maksimalkan dashboard Home Assistant).
- Hardening: auth MQTT wajib, TLS, backup DB otomatis.
