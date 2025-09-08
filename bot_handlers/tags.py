import logging
from telegram import Update
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

async def tag_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles button presses for tagging messages.
    This is triggered when an admin clicks a tag button under a user's message.
    """
    query = update.callback_query
    
    try:
        # callback_data format: e.g., "tag_123" where 123 is the tag_id
        data = query.data.split('_')
        if len(data) < 2 or data[0] != 'tag':
            await query.answer("无效的回调数据。", show_alert=True)
            return

        tag_id = int(data[1])
        
        # The user who clicked the tag button (the admin)
        admin_user = query.from_user

        # The message being tagged is the one the button is attached to.
        # This message is a reply from the bot, containing the original user's message info.
        # The actual user message is the one this bot message is replying to.
        user_message = query.message.reply_to_message
        
        if not user_message:
            await query.answer("无法找到要标记的原始消息。", show_alert=True)
            await query.edit_message_text("错误：找不到原始消息。")
            return

        # Fetch tag info from DB
        tag_info = await database.db_fetch_row("SELECT name, type FROM tags WHERE id = $1", tag_id)
        if not tag_info:
            await query.answer("此标签已不存在。", show_alert=True)
            await query.edit_message_text("错误：标签不存在。")
            return

        # Here you would typically save the tagging event to the database.
        # For example, logging which admin tagged which message with which tag.
        # This part depends on your database schema, let's just log it for now.
        logger.info(
            f"Admin {admin_user.id} tagged message {user_message.message_id} "
            f"from user {user_message.from_user.id} in chat {user_message.chat_id} "
            f"with tag '{tag_info['name']}' (ID: {tag_id})."
        )

        # Give feedback to the admin by editing the message and removing the buttons.
        await query.edit_message_text(
            f"✅ 您已将此消息标记为: **{tag_info['name']}**",
            parse_mode='Markdown'
        )
        # The query.answer() provides a small, temporary pop-up notification.
        await query.answer(f"已标记为: {tag_info['name']}")

    except (IndexError, ValueError):
        await query.answer("回调数据格式错误。", show_alert=True)
        logger.warning(f"Invalid callback data received: {query.data}")
    except Exception as e:
        logger.error(f"Error in tag_callback_handler: {e}", exc_info=True)
        await query.answer("处理标记时发生未知错误。", show_alert=True)
