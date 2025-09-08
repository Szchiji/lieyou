import logging
import asyncio
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

from database import init_db, save_user, get_user

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

# 尝试导入 bot_handlers，如果失败则定义基本功能
try:
    from bot_handlers.query_handler import handle_query
    from bot_handlers.admin import admin_panel, handle_admin_callback
    from bot_handlers.common import get_user_display_name
    from bot_handlers.start import start_command
    # 使用导入的 start_command
    start = start_command
except ImportError as e:
    logger.warning(f"Could not import bot_handlers: {e}")
    logger.info("Using fallback handlers")
    
    # Fallback implementations
    def get_user_display_name(user):
        """Get display name for user."""
        if hasattr(user, 'username') and user.username:
            return f"@{user.username}"
        name = user.first_name or ""
        if hasattr(user, 'last_name') and user.last_name:
            name += f" {user.last_name}"
        return name.strip() or "Unknown User"
    
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
    
    async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle queries - basic implementation."""
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            
            if query.data == "show_help":
                help_text = """
❓ *帮助信息*

*查询用户信誉*
• 在群组中 @用户名
• 转发用户的消息
• 回复用户的消息

*评价用户*
• 点击查询结果下方的按钮
• 选择合适的标签

*其他功能*
• 📊 查看排行榜
• ❤️ 我的收藏
"""
                await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN)
            elif query.data == "show_leaderboard":
                await query.edit_message_text("📊 排行榜功能开发中...")
            elif query.data == "show_my_favorites":
                await query.edit_message_text("❤️ 收藏功能开发中...")
            else:
                await query.edit_message_text("功能开发中...")
        else:
            # Handle message queries
            message = update.message
            if message:
                await message.reply_text("🔍 查询功能开发中...")
    
    async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Admin panel."""
        user = update.effective_user
        if user.id != ADMIN_USER_ID:
            await update.message.reply_text("❌ 您没有权限访问管理面板")
            return
        
        await update.message.reply_text("🔧 管理面板开发中...")
    
    async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle admin callbacks."""
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("管理功能开发中...")

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
