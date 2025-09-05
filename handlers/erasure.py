import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_execute, db_fetch_one
from .leaderboard import clear_leaderboard_cache

logger = logging.getLogger(__name__)

async def request_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户发送 /erase_my_data 命令，请求数据抹除"""
    user = update.effective_user
    message = (
        "⚠️ **数据抹除请求** ⚠️\n\n"
        "你确定要永久删除所有关于你的数据吗？这将包括：\n"
        "• 你收到的所有好评和差评。\n"
        "• 你给出的所有评价记录。\n"
        "• 你在机器人中的收藏夹。\n"
        "• 你的用户基本信息记录。\n\n"
        "**此操作不可撤销！** 请谨慎确认。"
    )
    keyboard = [
        [InlineKeyboardButton("‼️ 我确认，永久删除我的数据", callback_data="confirm_data_erasure")],
        [InlineKeyboardButton("❌ 取消", callback_data="cancel_data_erasure")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def confirm_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户点击确认按钮，执行数据抹除"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        # 再次确认用户存在
        user_exists = await db_fetch_one("SELECT id FROM users WHERE id = $1", user_id)
        if not user_exists:
            await query.edit_message_text("你的数据已不存在于我们的系统中。")
            return

        # 执行删除
        # 数据库应设置 ON DELETE CASCADE，这样删除 users 表中的用户会自动删除 votes 和 favorites 中的相关记录
        await db_execute("DELETE FROM users WHERE id = $1", user_id)
        
        # 清除缓存
        clear_leaderboard_cache()

        logger.info(f"用户 {user_id} 已成功抹除其所有数据。")
        await query.edit_message_text(
            "✅ **数据已永久删除**\n\n"
            "你所有与本机器人相关的数据均已被清除。感谢你曾经的使用！\n"
            "如果你再次与机器人交互，系统将会为你创建新的记录。"
        )

    except Exception as e:
        logger.error(f"数据抹除失败 (user: {user_id}): {e}", exc_info=True)
        await query.edit_message_text("❌ 操作失败，发生严重错误。请联系机器人管理员。")

async def cancel_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """用户点击取消按钮"""
    query = update.callback_query
    await query.edit_message_text("✅ 操作已取消，你的数据安然无恙。")
