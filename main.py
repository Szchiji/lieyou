import asyncio
import logging
import os
from dotenv import load_dotenv
from telegram import Update, MessageEntity
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters

import database
from bot_handlers.start import start
from bot_handlers.common import cancel_action
from bot_handlers.menu import show_private_main_menu, private_menu_callback_handler
from bot_handlers.reputation import handle_query, reputation_callback_handler, tag_callback_handler
from bot_handlers.leaderboard import show_leaderboard_callback_handler, leaderboard_type_callback_handler
from bot_handlers.report import generate_my_report
from bot_handlers.admin import (
    admin_panel, manage_tags_panel, manage_menu_buttons_panel, 
    user_management_panel, delete_tag_callback, toggle_tag_callback,
    add_tag_prompt, handle_new_tag, handle_tag_type_selection,
    prompt_for_username, set_user_hidden_status,
    TYPING_TAG_NAME, SELECTING_TAG_TYPE, 
    TYPING_USERNAME_TO_HIDE, TYPING_USERNAME_TO_UNHIDE
)
from bot_handlers.broadcast import (
    prompt_for_broadcast, get_broadcast_content, confirm_broadcast,
    TYPING_BROADCAST, CONFIRM_BROADCAST
)
from bot_handlers.monitoring import run_suspicion_monitor

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def error_handler(update: Update, context):
    """Handle errors caused by updates."""
    try:
        logger.error(f"Exception while handling an update: {context.error}")
        
        # 发送用户友好的错误消息
        if update and update.effective_message:
            try:
                # 不使用 parse_mode 避免二次错误
                await update.effective_message.reply_text(
                    "❌ 抱歉，处理您的请求时出现错误。请稍后再试。"
                )
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")
                
        # 如果是 callback query，也要 answer 避免加载圈
        if update and update.callback_query:
            try:
                await update.callback_query.answer("出错了，请稍后再试", show_alert=True)
            except Exception as e:
                logger.error(f"Failed to answer callback query: {e}")
                
    except Exception as e:
        logger.error(f"Error in error handler: {e}")

async def post_init(application: Application) -> None:
    """Initialize bot after startup."""
    try:
        await database.init_db()
        
        # Start background monitoring task
        asyncio.create_task(run_suspicion_monitor(application.bot))
        
        logger.info("Bot initialization completed!")
    except Exception as e:
        logger.error(f"Failed to initialize bot: {e}")
        raise

def main() -> None:
    """Start the bot."""
    # 检查必要的环境变量
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN not found in environment variables!")
        return
    
    # Create the Application
    application = Application.builder().token(bot_token).post_init(post_init).build()

    # Add error handler
    application.add_error_handler(error_handler)

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("myreport", generate_my_report))
    application.add_handler(CommandHandler("cancel", cancel_action))

    # Message handlers
    # Handle @mentions in groups - 修复这里
    application.add_handler(MessageHandler(
        filters.Entity(MessageEntity.MENTION) & filters.ChatType.GROUPS, 
        handle_query
    ))
    
    # 也可以处理 text_mention (点击用户名的 mention)
    application.add_handler(MessageHandler(
        filters.Entity(MessageEntity.TEXT_MENTION) & filters.ChatType.GROUPS,
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
    
    # Handle menu button presses in private chats
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        private_menu_callback_handler
    ))

    # Callback query handlers
    # Admin panel
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(manage_tags_panel, pattern="^admin_manage_tags$"))
    application.add_handler(CallbackQueryHandler(manage_menu_buttons_panel, pattern="^admin_menu_buttons$"))
    application.add_handler(CallbackQueryHandler(user_management_panel, pattern="^admin_user_management$"))
    
    # Tag management
    application.add_handler(CallbackQueryHandler(delete_tag_callback, pattern="^admin_delete_tag_"))
    application.add_handler(CallbackQueryHandler(toggle_tag_callback, pattern="^admin_toggle_tag_"))
    
    # Main menu
    application.add_handler(CallbackQueryHandler(show_private_main_menu, pattern="^show_private_main_menu$"))
    
    # Leaderboard
    application.add_handler(CallbackQueryHandler(show_leaderboard_callback_handler, pattern="^show_leaderboard_public$"))
    application.add_handler(CallbackQueryHandler(leaderboard_type_callback_handler, pattern="^lb_"))
    
    # Reputation
    application.add_handler(CallbackQueryHandler(reputation_callback_handler, pattern="^rep_"))
    application.add_handler(CallbackQueryHandler(tag_callback_handler, pattern="^tag_"))

    # Conversation handlers
    # Tag creation
    tag_creation_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_tag_prompt, pattern="^admin_add_tag_prompt$")],
        states={
            TYPING_TAG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_tag)],
            SELECTING_TAG_TYPE: [CallbackQueryHandler(handle_tag_type_selection, pattern="^tag_type_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_action)]
    )
    application.add_handler(tag_creation_conv)

    # User hiding/unhiding
    user_hide_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(prompt_for_username, pattern="^admin_hide_user_prompt$"),
            CallbackQueryHandler(prompt_for_username, pattern="^admin_unhide_user_prompt$")
        ],
        states={
            TYPING_USERNAME_TO_HIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
            TYPING_USERNAME_TO_UNHIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)]
        },
        fallbacks=[CommandHandler("cancel", cancel_action)]
    )
    application.add_handler(user_hide_conv)

    # Broadcast
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(prompt_for_broadcast, pattern="^admin_broadcast$")],
        states={
            TYPING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, get_broadcast_content)],
            CONFIRM_BROADCAST: [CallbackQueryHandler(confirm_broadcast, pattern="^broadcast_")]
        },
        fallbacks=[CommandHandler("cancel", cancel_action)]
    )
    application.add_handler(broadcast_conv)

    # Run the bot
    logger.info("Starting bot...")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True  # 忽略启动前的消息
    )

if __name__ == '__main__':
    main()
