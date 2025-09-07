import logging
import os
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

async def check_if_user_is_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if the user is a member of the required group, if specified."""
    group_id = os.getenv("GROUP_ID")
    if not group_id:
        return True  # No group requirement set

    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=group_id, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        else:
            group_invite_link = os.getenv("GROUP_INVITE_LINK", "")
            message = f"您需要先加入我们的指定群组才能使用此机器人。"
            if group_invite_link:
                message += f"\n请通过此链接加入: {group_invite_link}"
            else:
                message += f"\n请联系管理员获取群组链接。"
            await update.message.reply_text(message)
            return False
    except BadRequest:
        logger.error(f"Error checking chat member. Is the GROUP_ID ({group_id}) correct and the bot an admin there?")
        await update.message.reply_text("机器人配置错误，无法验证您的成员身份，请联系管理员。")
        return False
    except Exception as e:
        logger.error(f"An unexpected error occurred in check_if_user_is_member: {e}", exc_info=True)
        await update.message.reply_text("发生未知错误，请稍后再试。")
        return False

async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the current conversation."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("操作已取消。")
    else:
        await update.message.reply_text("操作已取消。")
    
    # Clean up any lingering conversation state
    context.user_data.clear()
    return ConversationHandler.END
