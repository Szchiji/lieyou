import logging
import asyncio
import os
from dotenv import load_dotenv
from telegram import Update, User as TelegramUser, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ChatAction, ParseMode

from database import init_db, save_user, get_user
from handlers.query_handler import handle_query
from handlers.admin_handler import admin_panel, handle_admin_callback
from handlers.user_handler import get_user_display_name

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

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await save_user(user)
    
    keyboard = [
        [InlineKeyboardButton("📊 查看排行榜", callback_data="show_leaderboard")],
        [InlineKeyboardButton("❤️ 我的收藏", callback_data="show_my_favorites")],
        [InlineKeyboardButton("❓ 帮助", callback_data="show_help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        f"👋 欢迎使用猎友信誉查询机器人，{get_user_display_name(user)}！\n\n"
        "🔍 *查询用户*：在群组中 @用户名 或转发消息\n"
        "⭐ *评价用户*：点击查询结果下方的按钮\n"
        "📊 *查看排行*：点击下方按钮查看信誉排行榜\n\n"
        "请选择一个操作："
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

def main() -> None:
    """Start the bot."""
    # Create the Application
    application = Application.builder().token(TOKEN).build()
    
    # Message handlers
    # Handle @mentions in groups - 修复这里
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
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^admin_"))
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
