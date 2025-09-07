import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import database

logger = logging.getLogger(__name__)

# Conversation states for this handler, imported by __init__.py and main.py
TYPING_BROADCAST, CONFIRM_BROADCAST = range(10, 12) # Use a distinct range

async def prompt_for_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks the admin to send the broadcast content."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("请发送您想广播的内容 (可以是文本、图片、视频等)。\n发送 /cancel 可以随时取消。")
    return TYPING_BROADCAST

async def get_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the broadcast content and asks for confirmation."""
    # Store the entire message object to allow for copying any content type
    context.user_data['broadcast_message'] = update.message
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认发送", callback_data='broadcast_confirm'),
            InlineKeyboardButton("❌ 取消", callback_data='broadcast_cancel')
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
        if 'broadcast_message' in context.user_data:
            del context.user_data['broadcast_message']
        return ConversationHandler.END
    
    # Confirmed, proceed to send
    await query.edit_message_text("⏳ 正在后台发送广播，请稍候...完成后您会收到通知。")
    
    # Run the sending task in the background to not block the bot
    asyncio.create_task(send_broadcast(update, context))
    
    return ConversationHandler.END

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fetches all users and sends the broadcast message to them."""
    message_to_send = context.user_data.get('broadcast_message')
    if not message_to_send:
        logger.warning("send_broadcast was called but no message was found in user_data.")
        return

    # Fetch all user IDs from the database using the correct column name 'id'
    users = await database.db_fetch_all("SELECT id FROM users")
    
    sent_count = 0
    failed_count = 0
    for user in users:
        user_id = user['id'] # Use the correct column name 'id'
        try:
            # copy_message is versatile and works for text, photos, videos, etc.
            await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=message_to_send.chat_id,
                message_id=message_to_send.message_id
            )
            sent_count += 1
            # Avoid hitting Telegram's rate limits
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning(f"Failed to send broadcast to user {user_id}: {e}")
            failed_count += 1
    
    # Notify the admin in the original chat once done.
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✅ 广播发送完毕。\n\n成功: {sent_count}\n失败: {failed_count}"
    )

    # Clean up the stored message
    if 'broadcast_message' in context.user_data:
        del context.user_data['broadcast_message']
