import logging
from telegram import Update
from telegram.ext import ContextTypes
from database import save_user, promote_virtual_user
from bot_handlers.menu import show_private_main_menu

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await save_user(user)
    try:
        await promote_virtual_user(user)
    except Exception as e:
        logger.warning(f"promote_virtual_user failed: {e}")
    name = (user.first_name or "用户").replace('*','').replace('_','').replace('`','')
    await update.message.reply_text(f"👋 欢迎，{name}！直接发送 @用户名 可查询并评价。")
    await show_private_main_menu(update, context)
