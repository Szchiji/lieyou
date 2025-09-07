import logging
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from database import get_setting

logger = logging.getLogger(__name__)

async def send_membership_error(update: Update):
    """发送要求加入群组的错误消息。"""
    chat_link = await get_setting('MANDATORY_CHAT_LINK')
    if not chat_link:
        # 如果没有设置链接，只发送文本提示
        error_text = "❌ **操作失败**\n\n您需要先加入我们的官方指定群组，才能使用本机器人。请联系管理员获取群组链接。"
        reply_markup = None
    else:
        error_text = "❌ **操作失败**\n\n您需要先加入我们的官方指定群组，才能使用本机器人。"
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🚀 点击加入", url=chat_link)
        ]])

    if update.callback_query:
        # 对按钮点击做出回应，并发送新消息或编辑原消息
        await update.callback_query.answer("您需要先加入官方群组。", show_alert=True)
        # 尝试编辑消息，如果失败（例如消息太旧），则发送新消息
        try:
            await update.callback_query.edit_message_text(error_text, reply_markup=reply_markup)
        except BadRequest:
            await update.effective_chat.send_message(error_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(error_text, reply_markup=reply_markup)


def membership_required(func):
    """
    一个装饰器，用于检查用户是否在指定的群组中。
    如果不在，则发送错误消息并阻止函数执行。
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        # 管理员可以无视此限制
        from database import is_admin # 延迟导入以避免循环依赖
        if await is_admin(update.effective_user.id):
            return await func(update, context, *args, **kwargs)

        chat_id_str = await get_setting('MANDATORY_CHAT_ID')
        # 如果没有设置强制入群，则直接通过
        if not chat_id_str:
            return await func(update, context, *args, **kwargs)

        try:
            member = await context.bot.get_chat_member(chat_id=chat_id_str, user_id=update.effective_user.id)
            if member.status in ['creator', 'administrator', 'member']:
                # 检查通过，执行原始函数
                return await func(update, context, *args, **kwargs)
            else:
                # 用户状态不合格（例如 'left' 或 'kicked'）
                await send_membership_error(update)
                return
        except BadRequest as e:
            # 如果机器人不在该群组，或群组ID错误，或用户不存在
            logger.error(f"检查群成员资格时出错 (chat_id: {chat_id_str}): {e}")
            if "Chat not found" in str(e):
                 # 可以选择通知管理员，chat_id 设置错误
                 pass
            # 向用户发送通用错误，但不暴露内部信息
            await send_membership_error(update)
            return
        except Exception as e:
            logger.error(f"检查群成员资格时发生未知错误: {e}")
            await send_membership_error(update) # 发送标准错误提示
            return

    return wrapper
