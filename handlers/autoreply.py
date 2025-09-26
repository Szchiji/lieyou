from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes
from utils import get_db, admin_required

# 设置自动回复
@admin_required
async def set_autoreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        keyword = context.args[0]
        reply = " ".join(context.args[1:])
        db = await get_db()
        await db.execute(
            "INSERT INTO autoreplies(keyword, reply) VALUES($1, $2) ON CONFLICT (keyword) DO UPDATE SET reply=$2",
            keyword, reply
        )
        await update.message.reply_text(f"设置自动回复：{keyword} -> {reply}")
    except Exception:
        await update.message.reply_text("用法: /setautoreply 关键词 回复内容")

@admin_required
async def del_autoreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        keyword = context.args[0]
        db = await get_db()
        await db.execute("DELETE FROM autoreplies WHERE keyword=$1", keyword)
        await update.message.reply_text(f"已删除关键词：{keyword}")
    except Exception:
        await update.message.reply_text("用法: /delautoreply 关键词")

@admin_required
async def list_autoreply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = await get_db()
    rows = await db.fetch("SELECT keyword, reply FROM autoreplies ORDER BY keyword")
    if not rows:
        await update.message.reply_text("暂无自动回复规则。")
        return
    lines = [f"{i+1}. {r['keyword']} → {r['reply']}" for i, r in enumerate(rows)]
    await update.message.reply_text("\n".join(lines))

async def reply_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    db = await get_db()
    rows = await db.fetch("SELECT keyword, reply FROM autoreplies")
    for r in rows:
        if r["keyword"] in text:
            await update.message.reply_text(r["reply"])
            break

def register(application):
    application.add_handler(CommandHandler("setautoreply", set_autoreply))
    application.add_handler(CommandHandler("delautoreply", del_autoreply))
    application.add_handler(CommandHandler("listautoreply", list_autoreply))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_message))
