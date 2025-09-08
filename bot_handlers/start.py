import logging
from telegram import Update
from telegram.ext import ContextTypes
import database
from .common import check_if_user_is_member
from .menu import show_private_main_menu

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    user = update.effective_user
    logger.info(f"User {user.username} (ID: {user.id}) started the bot.")
    
    # Save/update user info in the database
    await database.save_user(user)

    # If in a private chat, check group membership and show main menu
    if update.message.chat.type == 'private':
        if not await check_if_user_is_member(update, context):
            return
        
        await update.message.reply_text(f"您好，{user.first_name}！欢迎使用声誉机器人。")
        await show_private_main_menu(update, context)
    else:
        await update.message.reply_text("机器人已在此群组激活。请在群聊中使用 @username 进行查询，或私聊我获取更多功能。")
