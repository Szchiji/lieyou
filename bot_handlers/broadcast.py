import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import database

logger = logging.getLogger(__name__)

# Conversation states
TYPING_BROADCAST, CONFIRM_BROADCAST = range(2)

async def prompt_for_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks the admin to send the broadcast content."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("请发送您想广播的内容 (可以是文本、图片、视频等)。")
    return TYPING_BROADCAST

async def get_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the broadcast content and asks for confirmation."""
    context.user_data['broadcast_message'] = update.message
    
    keyboard = [
        [
            InlineKeyboardButton("确认发送", callback_data='broadcast_confirm'),
            InlineKeyboardButton("取消", callback_data='broadcast_cancel')
        ]
    ]
    await update.message.reply_text("您确定要向所有用户广播这条消息吗？", reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM_BROADCAST

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the admin's confirmation choice."""
    query = update.callback_query
    await query.answer()
    
    choice = query.data.split('_')[1]
    if choice == 'cancel':
        await query.edit_message_text("广播已取消。")
        del context.user_data['broadcast_message']
        return ConversationHandler.END
    
    # Confirmed, proceed to send
    await query.edit_message_text("正在发送广播，请稍候...")
    await send_broadcast(update, context)
    del context.user_data['broadcast_message']
    return ConversationHandler.END

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches all users and sends the broadcast message to them."""
    message_to_send = context.user_data.get('broadcast_message')
    if not message_to_send:
        return

    db_pool = await database.get_pool()
    async with db_pool.acquire() as conn:
        users = await conn.fetch("SELECT user_id FROM users")
    
    sent_count = 0
    failed_count = 0
    for user in users:
        try:
            await context.bot.copy_message(
                chat_id=user['user_id'],
                from_chat_id=message_to_send.chat_id,
                message_id=message_to_send.message_id
            )
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast to user {user['user_id']}: {e}")
            failed_count += 1
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"广播发送完毕。\n成功: {sent_count}\n失败: {failed_count}"
    )
