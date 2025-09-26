from telegram import Update
from telegram.ext import MessageHandler, CommandHandler, ContextTypes, filters
from utils import get_db, today_str

async def checkin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    today = today_str()
    db = await get_db()
    exists = await db.fetchval("SELECT 1 FROM checkins WHERE user_id=$1 AND chat_id=$2 AND day=$3", user_id, chat_id, today)
    if exists:
        await update.message.reply_text("今日已经打卡过，无需重复打卡")
    else:
        await db.execute(
            "INSERT INTO checkins(user_id, chat_id, day) VALUES($1, $2, $3)",
            user_id, chat_id, today
        )
        await update.message.reply_text("打卡成功")

async def today_checkins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    today = today_str()
    db = await get_db()
    rows = await db.fetch("SELECT user_id FROM checkins WHERE chat_id=$1 AND day=$2", chat_id, today)
    if not rows:
        await update.message.reply_text("今天还没有人打卡哦～")
        return
    lines = [f"{i+1}. 用户ID：{r['user_id']}" for i, r in enumerate(rows)]
    await update.message.reply_text('\n'.join(lines))

def register(application):
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^打卡$"), checkin_message))
    application.add_handler(CommandHandler("today_checkins", today_checkins))
