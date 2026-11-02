# Agent pengelola (Fase 4)

Lapisan "otak" sistem: LLM agent yang mengelola monitoring lewat tools,
bukan sekadar script if/else.

## Kemampuan target

- Query bahasa natural: "siapa yang datang jam 3 sore?", "tampilkan semua
  orang tak dikenal minggu ini"
- Investigasi event: ambil klip, minta deskripsi VLM, simpulkan
- Perintah: arm/disarm zona, nyalakan lampu/sirene, bisukan notifikasi
- Proaktif: ringkasan harian via Telegram, eskalasi bila pola mencurigakan
  (mis. orang tak dikenal mondar-mandir > 5 menit)

## Prinsip anti-halusinasi

Agent HANYA boleh menjawab identitas / fakta kejadian dari hasil tool
(`query_events`, `get_clip`, `describe_clip`, `identify_face`).
Tanpa hasil tool = jawab "tidak tahu".

## Tools yang direncanakan

| Tool | Sumber data |
|---|---|
| `query_events` | event store (SQLite) dari MQTT Frigate |
| `get_clip` | Frigate API `/api/events/<id>/clip.mp4` |
| `describe_clip` | VLM lokal (Moondream2 / Qwen2.5-VL via Ollama) |
| `identify_face` | InsightFace vs galeri wajah terdaftar |
| `ha_call` | Home Assistant service call (lampu, sirene, notifikasi) |
| `telegram_send` | Bot Telegram (teks, foto, video, inline button) |

## Stack rencana

- Python, MQTT (paho-mqtt), SQLite event store
- LLM: Ollama lokal (Qwen 2.5 / Llama 3.x) atau API cloud opsional
- Telegram: python-telegram-bot (pengganti telepot yang sudah usang)

Struktur kode menyusul di Fase 4. Sampai saat itu, direktori ini berisi
desain saja.
