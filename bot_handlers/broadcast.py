import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
import database
from .admin import check_admin, admin_panel

logger = logging.getLogger(__name__)

# --- Conversation States ---
TYPING_BROADCAST, CONFIRM_BROADCAST = range(20, 22) # Use a new range

# --- Broadcast Flow ---
async def prompt_for_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the broadcast conversation."""
    if not await check_admin(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "请输入您要广播的消息内容。\n\n"
        "您可以发送文本、图片、文件等任何格式的消息。\n"
        "发送 /cancel 可随时取消。"
    )
    return TYPING_BROADCAST

async def get_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the broadcast message and asks for confirmation."""
    if not await check_admin(update): return ConversationHandler.END
    
    # Store the entire message object to be able to copy it later
    context.user_data['broadcast_message'] = update.message
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 是的，立即发送", callback_data="broadcast_send"),
            InlineKeyboardButton("❌ 算了，取消", callback_data="broadcast_cancel"),
        ]
    ]
    await update.message.reply_text(
        "☝️ 这就是您要发送的消息。\n\n**您确定要将此消息广播给所有用户吗？此操作无法撤销！**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return CONFIRM_BROADCAST

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the final confirmation (send or cancel)."""
    if not await check_admin(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()

    if query.data == 'broadcast_send':
        await query.edit_message_text("正在准备发送广播，请稍候...")
        await send_broadcast(update, context)
        # Go back to admin panel
        query.data = "admin_panel"
        await admin_panel(update, context)
    else: # broadcast_cancel
        await query.edit_message_text("广播已取消。")
        context.user_data.clear()
    
    return ConversationHandler.END

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches all users and sends the broadcast message to them."""
    message_to_send = context.user_data.get('broadcast_message')
    if not message_to_send:
        logger.error("Broadcast message not found in user_data.")
        return

    all_users = await database.db_fetch_all("SELECT id FROM users")
    if not all_users:
        logger.info("No users found to send broadcast to.")
        return
    
    success_count = 0
    failure_count = 0
    
    for user in all_users:
        try:
            # Use copy_message to forward any type of content
            await context.bot.copy_message(
                chat_id=user['id'],
                from_chat_id=message_to_send.chat_id,
                message_id=message_to_send.message_id
            )
            success_count += 1
        except Exception as e:
            failure_count += 1
            logger.warning(f"Failed to send broadcast to user {user['id']}: {e}")

    final_report = (
        f"📢 **广播发送完毕**\n\n"
        f"✅ 成功发送: {success_count} 人\n"
        f"❌ 发送失败: {failure_count} 人"
    )
    # Send report to the admin who initiated it
    await context.bot.send_message(
        chat_id=update.effective_user.id, 
        text=final_report,
        parse_mode='Markdown'
    )
    context.user_data.clear()
