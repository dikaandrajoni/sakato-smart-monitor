"""Notifikasi Telegram yang cerdas (python-telegram-bot v21).

- Token & chat ID HANYA dari environment:
      TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
  Tidak ada default, tidak ada hardcode. Bila kosong, notifier NONAKTIF
  dengan peringatan jelas (program utama tetap jalan).
- Perintah: /start /status /snapshot /arm /disarm /mute <menit>
- Orang Unknown -> kirim foto + caption, dengan cooldown per track ID.
- Orang dikenal   -> hanya dicatat (tidak dikirim), kecuali notify_known=True.
- Berjalan di thread terpisah agar tidak memblokir loop deteksi.

Keamanan: JANGAN pernah tulis token di kode / commit ke repo.
Buat bot baru via @BotFather — token lama (repo 2021) SUDAH BOCOR.
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
from datetime import datetime, timezone

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False


class TelegramNotifier:
    def __init__(self, token=None, chat_id=None, cooldown=300,
                 notify_known=False, camera_name="kamera", time_fn=None):
        """
        cooldown     : detik minimum antar notifikasi untuk track ID yang sama.
        notify_known : bila True, orang dikenal juga dikirimi notifikasi teks.
        camera_name  : label kamera untuk caption (mis. "teras_depan").
        time_fn      : injeksi jam (unit test), default time.time.
        """
        import time as _time
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        self.cooldown = cooldown
        self.notify_known_enabled = notify_known
        self.camera_name = camera_name
        self._time = time_fn or _time.time

        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            print("[telegram] NONAKTIF: isi TELEGRAM_BOT_TOKEN dan "
                  "TELEGRAM_CHAT_ID di environment untuk mengaktifkan.")

        self.armed = True
        self.muted_until = 0.0
        self.events_today = 0
        self._today = datetime.now(timezone.utc).date()
        self._last_notify = {}   # track_id -> timestamp
        self._last_frame_jpg = None

        self._loop = None
        self._thread = None
        self._stop_event = threading.Event()
        self._app = None

    # ---------- state ----------

    def _roll_day(self):
        today = datetime.now(timezone.utc).date()
        if today != self._today:
            self._today = today
            self.events_today = 0

    def is_muted(self):
        return self._time() < self.muted_until

    def set_last_frame(self, jpg_bytes):
        """Dipanggil loop utama tiap frame (untuk perintah /snapshot)."""
        self._last_frame_jpg = jpg_bytes

    # ---------- pengiriman (aman thread) ----------

    def _schedule(self, coro):
        if self._loop is not None and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _send_text(self, text):
        """Bisa di-mock pada unit test."""
        if self._app is not None:
            self._schedule(
                self._app.bot.send_message(chat_id=self.chat_id, text=text))

    def _send_photo_bytes(self, photo_bytes, caption):
        """Bisa di-mock pada unit test."""
        if self._app is not None:
            bio = io.BytesIO(photo_bytes)
            bio.name = "frame.jpg"
            self._schedule(self._app.bot.send_photo(
                chat_id=self.chat_id, photo=bio, caption=caption))

    # ---------- API notifikasi (dipanggil loop deteksi) ----------

    def notify_unknown(self, track_id, photo_jpg_bytes, similarity=0.0,
                       description=""):
        """Kirim foto orang tak dikenal. Kembalikan True bila terkirim."""
        if not self.enabled or not self.armed or self.is_muted():
            return False
        now = self._time()
        if now - self._last_notify.get(track_id, float("-inf")) < self.cooldown:
            return False
        self._last_notify[track_id] = now
        self._roll_day()
        self.events_today += 1
        ts = datetime.fromtimestamp(now, tz=timezone.utc).astimezone().strftime(
            "%d %b %Y %H:%M:%S")
        caption = (f"⚠️ Orang tak dikenal terdeteksi\n"
                   f"🕒 {ts}\n"
                   f"🎥 {self.camera_name}\n"
                   f"🆔 track #{track_id}\n"
                   f"📊 kemiripan wajah: {similarity:.2f}")
        if description:  # Fase 5: hasil VLM
            caption += f"\n🔍 {description}"
        self._send_photo_bytes(photo_jpg_bytes, caption)
        return True

    def notify_known(self, name, track_id, similarity=0.0, description=""):
        """Hanya bila notify_known=True; orang dikenal tetap dicatat di log."""
        if not self.enabled or not self.notify_known_enabled:
            return False
        if not self.armed or self.is_muted():
            return False
        self._roll_day()
        self.events_today += 1
        text = (f"✅ {name} terdeteksi (track #{track_id}, "
                f"kemiripan {similarity:.2f})")
        if description:  # Fase 5: hasil VLM
            text += f"\n🔍 {description}"
        self._send_text(text)
        return True

    # ---------- perintah bot ----------

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🤖 Sakato Smart Monitor aktif.\n"
            "Perintah:\n"
            "/status - ringkasan hari ini\n"
            "/snapshot - foto terakhir kamera\n"
            "/arm - aktifkan notifikasi\n"
            "/disarm - matikan notifikasi\n"
            "/mute <menit> - bisukan sementara")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self._roll_day()
        if self.is_muted():
            sisa = int((self.muted_until - self._time()) / 60) + 1
            mute_info = f"dibisukan (~{sisa} mnt lagi)"
        else:
            mute_info = "tidak dibisukan"
        await update.message.reply_text(
            f"📊 Status monitor\n"
            f"• Notifikasi: {'AKTIF 🟢' if self.armed else 'MATI 🔴'}\n"
            f"• {mute_info}\n"
            f"• Event hari ini: {self.events_today}\n"
            f"• Kamera: {self.camera_name}")

    async def _cmd_snapshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self._last_frame_jpg:
            bio = io.BytesIO(self._last_frame_jpg)
            bio.name = "snapshot.jpg"
            await update.message.reply_photo(photo=bio, caption="📸 Snapshot terakhir")
        else:
            await update.message.reply_text("Belum ada frame tersimpan.")

    async def _cmd_arm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.armed = True
        await update.message.reply_text("🟢 Notifikasi DIAKTIFKAN.")

    async def _cmd_disarm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.armed = False
        await update.message.reply_text("🔴 Notifikasi DIMATIKAN.")

    async def _cmd_mute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            menit = int(context.args[0]) if context.args else 0
        except (ValueError, IndexError):
            await update.message.reply_text("Pakai: /mute <menit>  (contoh: /mute 30)")
            return
        if menit <= 0:
            await update.message.reply_text("Pakai: /mute <menit>  (contoh: /mute 30)")
            return
        self.muted_until = self._time() + menit * 60
        await update.message.reply_text(f"🔇 Dibisukan selama {menit} menit.")

    # ---------- lifecycle thread ----------

    def start(self):
        """Jalankan polling bot di thread terpisah. False bila nonaktif."""
        if not self.enabled:
            return False
        if not _TG_AVAILABLE:
            print("[telegram] python-telegram-bot belum terinstall.")
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="telegram-bot")
        self._thread.start()
        print("[telegram] bot berjalan di thread terpisah.")
        return True

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._amain())

    async def _amain(self):
        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("snapshot", self._cmd_snapshot))
        self._app.add_handler(CommandHandler("arm", self._cmd_arm))
        self._app.add_handler(CommandHandler("disarm", self._cmd_disarm))
        self._app.add_handler(CommandHandler("mute", self._cmd_mute))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._stop_event.wait)
        finally:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
