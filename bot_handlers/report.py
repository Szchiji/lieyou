import logging
from telegram import Update
from telegram.ext import ContextTypes
from database import get_user_reputation

logger = logging.getLogger(__name__)

async def generate_my_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rep = await get_user_reputation(user_id)
    text = (
        "📋 *我的报告*\n\n"
        f"信誉分：{rep['score']}\n"
        f"👍 推荐：{rep['recommendations']}   👎 警告：{rep['warnings']}\n"
        "常见标签：\n"
    )
    if rep['tags']:
        for t in rep['tags']:
            text += f"• {t['name']} ({t['count']}次)\n"
    else:
        text += "暂无标签\n"
    await update.message.reply_text(text, parse_mode="Markdown")
