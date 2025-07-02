import asyncio
import sqlite3
from typing import Dict, List, Tuple

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from pysnmp.hlapi import SnmpEngine, CommunityData, UdpTransportTarget, ContextData, ObjectType, ObjectIdentity, getCmd, setCmd

from cable_diag import run_cable_diag

DB_PATH = "switches.db"
user_search_cache: Dict[int, List[Tuple[str, str, str, str]]] = {}
DEFAULT_PORT = "1/0/1"
BOT_TOKEN = "YOUR_BOT_TOKEN"  # ← вставь реальный токен


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Используй команды:\n"
        "/search <ip/имя/адрес> — поиск коммутаторов\n"
        "/diagnose <номер> <порт?> — кабельная диагностика"
    )


# ---------------------------------------------------------------------------
# /search
# ---------------------------------------------------------------------------
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Формат: /search <ip/имя/адрес>")
        return

    query = " ".join(context.args)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ip, name, descr, loc FROM switches
        WHERE ip LIKE ? OR name LIKE ? OR loc LIKE ?
        """,
        (f"%{query}%",) * 3,
    )
    results = cursor.fetchall()
    conn.close()

    if not results:
        await update.message.reply_text("❌ Ничего не найдено.")
        return

    user_search_cache[update.effective_user.id] = results

    text = "🔎 Найдено:\n\n" + "".join(
        f"{idx}. {ip} | {name} | {descr} | {loc}\n"
        for idx, (ip, name, descr, loc) in enumerate(results[:20], 1)
    )
    text += "\n✳️ /diagnose <номер> <порт?>"

    await update.message.reply_text(text)


# ---------------------------------------------------------------------------
# /diagnose
# ---------------------------------------------------------------------------
async def diagnose_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_search_cache:
        await update.message.reply_text("⚠️ Сначала сделай /search")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("❗ Формат: /diagnose <номер> <порт?>")
        return

    idx = int(context.args[0]) - 1
    port = context.args[1] if len(context.args) > 1 else DEFAULT_PORT

    records = user_search_cache[user_id]
    if idx < 0 or idx >= len(records):
        await update.message.reply_text("🚫 Неверный номер из /search")
        return

    ip, name, descr, loc = records[idx]

    # ---------- Определяем семейство по описанию модели ----------
    descr_clean = descr.upper().replace("-", "").replace("_", "").strip()
    if "SNR" in descr_clean:
        family = "snr"
    elif any(prefix in descr_clean for prefix in ("DCS", "DES", "DGS")):
        family = "dlink"
    else:
        await update.message.reply_text(f"😕 Модель не поддерживается: {descr}")
        return
    # --------------------------------------------------------------

    await update.message.reply_text(
        f"📡 Запускаю кабельную диагностику на {name} ({ip}), порт {port}…"
    )

    loop = asyncio.get_running_loop()
    result: str = await loop.run_in_executor(None, run_cable_diag, ip, port, family)

    await update.message.reply_text(f"📊 Результат диагностики:\n{result}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    app = ApplicationBuilder().token("7940417537:AAFVqzuYTPEIWo7JbEMwAS92c2sjFyEGGjY").build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("diagnose", diagnose_command))

    print("✅ SNMP‑бот запущен…")
    app.run_polling()


if __name__ == "__main__":
    main()
