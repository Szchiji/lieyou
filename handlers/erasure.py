import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_execute, get_or_create_user

logger = logging.getLogger(__name__)

async def request_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """向用户发送删除数据的确认请求"""
    keyboard = [
        [InlineKeyboardButton("⚠️ 是的，永久删除我的所有数据", callback_data="confirm_data_erasure")],
        [InlineKeyboardButton("取消", callback_data="cancel_data_erasure")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "**警告：这是一个不可逆操作！**\n\n"
        "您确定要永久删除您在本机器人中的所有个人数据吗？这包括：\n"
        "- 您的用户ID和用户名\n"
        "- 您所有的评价记录（作为投票者）\n"
        "- 您收到的所有评价\n"
        "- 您所有的收藏夹记录\n\n"
        "此操作无法撤销。",
        reply_markup=reply_markup
    )

async def confirm_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """确认并执行数据删除"""
    query = update.callback_query
    user = await get_or_create_user(user_id=query.from_user.id)
    if not user:
        await query.edit_message_text("❌ 错误：无法找到您的用户数据。")
        return

    try:
        # 删除与用户相关的所有数据，ON DELETE CASCADE 会自动处理关联表
        await db_execute("DELETE FROM users WHERE pkid = $1", user['pkid'])
        
        # 核心修正：由于缓存已移除，不再需要调用 clear_leaderboard_cache
        
        await query.edit_message_text("✅ 您的所有数据已被成功永久删除。感谢您的使用。")
        logger.info(f"用户 {user['pkid']} ({query.from_user.username}) 已被成功删除。")
        
    except Exception as e:
        logger.error(f"删除用户数据时出错 (pkid: {user['pkid']}): {e}", exc_info=True)
        await query.edit_message_text("❌ 删除数据时发生严重错误，请联系管理员。")

async def cancel_data_erasure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """取消数据删除操作"""
    query = update.callback_query
    await query.edit_message_text("操作已取消，您的数据安然无恙。")
