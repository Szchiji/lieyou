import logging
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from database import get_setting, is_admin

logger = logging.getLogger(__name__)

async def send_membership_error(update: Update):
    """发送要求加入群组的错误消息。"""
    chat_link = await get_setting('MANDATORY_CHAT_LINK')
    if not chat_link:
        error_text = "❌ **操作失败**\n\n您需要先加入我们的官方指定群组，才能使用本机器人。请联系管理员获取群组链接。"
        reply_markup = None
    else:
        error_text = "❌ **操作失败**\n\n您需要先加入我们的官方指定群组，才能使用本机器人。"
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🚀 点击加入", url=chat_link)
        ]])

    if update.callback_query:
        await update.callback_query.answer("您需要先加入官方群组。", show_alert=True)
        try:
            # Try to edit the message. If it fails (e.g., message too old), send a new one.
            await update.callback_query.edit_message_text(error_text, reply_markup=reply_markup)
        except BadRequest:
            await update.effective_chat.send_message(error_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(error_text, reply_markup=reply_markup)


def membership_required(func):
    """
    一个装饰器，用于检查用户是否在指定的群组中。
    管理员和GOD用户不受此限制。
    如果未设置强制群组，则不进行检查。
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        
        # 1. 检查是否为管理员，如果是则直接放行
        if await is_admin(user_id):
            return await func(update, context, *args, **kwargs)

        # 2. 获取强制群组ID，如果未设置则直接放行
        chat_id_str = await get_setting('MANDATORY_CHAT_ID')
        if not chat_id_str:
            return await func(update, context, *args, **kwargs)

        # 3. 检查成员资格
        try:
            member = await context.bot.get_chat_member(chat_id=chat_id_str, user_id=user_id)
            if member.status in ['creator', 'administrator', 'member']:
                # 用户是群成员，放行
                return await func(update, context, *args, **kwargs)
            else:
                # 用户不在群组中或状态不符 (e.g., 'left', 'kicked')
                logger.warning(f"用户 {user_id} 尝试操作但因成员状态 '{member.status}' 被拒绝。")
                await send_membership_error(update)
                return
        except BadRequest as e:
            # 机器人可能已被移出群组，或ID错误
            logger.error(f"检查群成员资格时出错 (chat_id: {chat_id_str}): {e}")
            await send_membership_error(update) # 仍然向用户显示错误，提示联系管理员
            return
        except Exception as e:
            logger.error(f"检查群成员资格时发生未知错误: {e}")
            await send_membership_error(update)
            return

    return wrapper
