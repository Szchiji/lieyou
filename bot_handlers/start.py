from telegram import Update
from telegram.ext import ContextTypes
from bot_handlers.menu import show_private_main_menu
from database import save_user
import logging

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user = update.effective_user
    
    # Save user to database
    await save_user(user)
    
    # 安全地获取用户名，避免特殊字符问题
    user_name = user.first_name or "用户"
    # 移除可能导致 Markdown 解析问题的字符
    user_name = user_name.replace('*', '').replace('_', '').replace('`', '').replace('[', '').replace(']', '')
    
    # Welcome message - 不使用 parse_mode
    welcome_message = f"👋 欢迎使用猎友信誉查询机器人，{user_name}！"
    
    await update.message.reply_text(welcome_message)
    
    # Show main menu
    await show_private_main_menu(update, context)
