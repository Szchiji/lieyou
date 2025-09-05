import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_execute, get_or_create_user

logger = logging.getLogger(__name__)

async def request_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts the user to confirm data erasure."""
    text = (
        "⚠️ **警告：这是一个不可逆的操作！**\n\n"
        "确认删除您的所有数据吗？这将包括：\n"
        "- 您给出的所有评价\n"
        "- 您收到的所有评价\n"
        "- 您的收藏列表\n"
        "- 您的管理员身份（如果适用）\n\n"
        "您的用户记录将被从数据库中彻底移除。"
    )
    keyboard = [
        [InlineKeyboardButton("🔴 是的，确认删除", callback_data="confirm_data_erasure")],
        [InlineKeyboardButton("🟢 不，我再想想", callback_data="cancel_data_erasure")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 核心修正：判断是命令还是回调，并使用正确的方法
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    elif update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def confirm_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Erases user data upon confirmation."""
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    if not user:
        await query.edit_message_text("❌ 找不到您的用户数据，可能已被删除。")
        return
    try:
        await db_execute("DELETE FROM users WHERE pkid = $1", user['pkid'])
        await query.edit_message_text("✅ 您的所有数据已成功从本机器人数据库中删除。感谢您的使用。")
    except Exception as e:
        logger.error(f"删除用户数据失败 (pkid: {user['pkid']}): {e}", exc_info=True)
        await query.edit_message_text("❌ 删除数据时发生严重错误，请联系机器人管理员。")

async def cancel_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels the data erasure process."""
    from main import start_command # 延迟导入以避免循环依赖
    await update.callback_query.answer("操作已取消。")
    await start_command(update, context)
