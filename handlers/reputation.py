from telegram import Update
from telegram.ext import ContextTypes
from database import get_db_cursor
import logging

logger = logging.getLogger(__name__)

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """显示声望最高的猎手排行榜。"""
    logger.info("有人请求排行榜。")
    try:
        with get_db_cursor() as cur:
            cur.execute(
                "SELECT first_name, username, reputation FROM users ORDER BY reputation DESC LIMIT 10"
            )
            leaders = cur.fetchall()

        if not leaders:
            await update.message.reply_text("还没有猎手获得声望，快去狩猎吧！")
            return

        message = "🏆 **猎手声望排行榜** 🏆\n\n"
        for i, leader in enumerate(leaders, 1):
            # 优先显示 first_name，如果不存在则显示 username
            display_name = leader[0] if leader[0] else leader[1]
            message += f"{i}. {display_name} - {leader[2]} 声望\n"

        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"获取排行榜时出错: {e}")
        await update.message.reply_text("获取排行榜失败，数据库发生错误。")
