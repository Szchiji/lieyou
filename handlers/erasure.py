import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db_execute, get_or_create_user

logger = logging.getLogger(__name__)

async def request_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Asks the user to confirm data deletion."""
    query = update.callback_query
    text = (
        "⚠️ **警告：数据删除请求** ⚠️\n\n"
        "您确定要删除所有与您相关的数据吗？这将包括：\n"
        "- 您自己的用户档案\n"
        "- 您对他人的所有评价\n"
        "- 您所有的收藏记录\n"
        "- 您收到的所有评价\n\n"
        "**此操作不可逆转！**"
    )
    keyboard = [
        [InlineKeyboardButton("🔴 是的，我确定要删除", callback_data="confirm_data_erasure")],
        [InlineKeyboardButton("🟢 不，我点错了", callback_data="cancel_data_erasure")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes all data associated with the user."""
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    
    if not user:
        await query.edit_message_text("❌ 未找到您的用户数据，可能已被删除。")
        return

    try:
        await db_execute("DELETE FROM users WHERE pkid = $1", user['pkid'])
        await query.edit_message_text("✅ 您的所有数据已成功从本机器人数据库中永久删除。")
        logger.info(f"User with pkid {user['pkid']} (ID: {query.from_user.id}) has been erased.")
    except Exception as e:
        logger.error(f"删除用户数据失败 (pkid: {user['pkid']}): {e}", exc_info=True)
        await query.edit_message_text("❌ 删除数据时发生严重错误。请联系管理员。")

async def cancel_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the data deletion request and returns to the main menu."""
    from .admin import start_command # 避免循环导入
    await start_command(update, context)
