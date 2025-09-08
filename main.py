import logging
import asyncio
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

from database import init_db, save_user, get_user
from bot_handlers.start import start_command
from bot_handlers.admin import admin_panel, handle_admin_callback
from bot_handlers.common import get_user_display_name
from bot_handlers.reputation import handle_reputation_query
from bot_handlers.menu import handle_menu_callback
from bot_handlers.leaderboard import show_leaderboard_handler

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get bot token from environment
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    logger.error("BOT_TOKEN not found in environment variables!")
    exit(1)

# Get admin user ID
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID', 0))

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route queries to appropriate handlers."""
    if update.callback_query:
        query = update.callback_query
        data = query.data
        
        # Route based on callback data
        if data.startswith("admin_"):
            await handle_admin_callback(update, context)
        elif data.startswith("rate_") or data.startswith("tag_"):
            await handle_reputation_query(update, context)
        elif data in ["show_leaderboard", "show_my_favorites", "show_help"]:
            await handle_menu_callback(update, context)
        else:
            await query.answer("功能开发中...")
    else:
        # Handle message queries (mentions, forwards, replies)
        await handle_reputation_query(update, context)

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TOKEN).build()
    
    # Message handlers
    # Handle @mentions in groups
    application.add_handler(MessageHandler(
        filters.Entity("mention") & filters.ChatType.GROUPS,
        handle_query
    ))
    
    # Handle forwarded messages in groups
    application.add_handler(MessageHandler(
        filters.FORWARDED & filters.ChatType.GROUPS, 
        handle_query
    ))
    
    # Handle replies in groups
    application.add_handler(MessageHandler(
        filters.REPLY & filters.ChatType.GROUPS, 
        handle_query
    ))
    
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("leaderboard", show_leaderboard_handler))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(handle_query))
    
    # Error handler
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, context.error)
        
        # 通知用户
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "❌ 抱歉，处理您的请求时出现错误。请稍后再试。"
                )
            except:
                pass
    
    application.add_error_handler(error_handler)
    
    # Initialize database
    async def post_init(application: Application) -> None:
        await init_db()
        logger.info("Database initialized")
    
    # Shutdown handler
    async def post_shutdown(application: Application) -> None:
        from database import close_db
        await close_db()
        logger.info("Database connection closed")
    
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    # Run the bot
    logger.info("Starting bot...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    # Check required environment variables
    required_vars = ['BOT_TOKEN', 'ADMIN_USER_ID']
    if os.getenv('DATABASE_URL'):
        logger.info("Using DATABASE_URL for database connection")
    else:
        required_vars.extend(['DB_USER', 'DB_PASSWORD', 'DB_NAME', 'DB_HOST', 'DB_PORT'])
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please check your .env file")
        exit(1)
    
    # Run the bot
    main()
