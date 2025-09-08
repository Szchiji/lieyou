import logging
import asyncio
import os
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)
import database
from bot_handlers import *

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Main Application Setup ---
async def main():
    """Start the bot."""
    # --- Environment Variables ---
    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        logger.error("FATAL: BOT_TOKEN environment variable not set.")
        return

    # --- Database Initialization ---
    await database.init_db()

    # --- Application Builder ---
    application = Application.builder().token(bot_token).build()

    # --- Conversation Handler for Admin Panel ---
    admin_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_panel, pattern='^admin_panel$'),
            CallbackQueryHandler(manage_tags_panel, pattern='^admin_manage_tags$'),
            CallbackQueryHandler(add_tag_prompt, pattern='^admin_add_tag_prompt$'),
            CallbackQueryHandler(manage_menu_buttons_panel, pattern='^admin_menu_buttons$'),
            CallbackQueryHandler(user_management_panel, pattern='^admin_user_management$'),
            CallbackQueryHandler(prompt_for_username, pattern='^admin_(hide|unhide)_user_prompt$'),
            CallbackQueryHandler(prompt_for_broadcast, pattern='^admin_broadcast$'),
        ],
        states={
            TYPING_TAG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_tag)],
            SELECTING_TAG_TYPE: [CallbackQueryHandler(handle_tag_type_selection, pattern='^tag_type_')],
            TYPING_USERNAME_TO_HIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
            TYPING_USERNAME_TO_UNHIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
            TYPING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, get_broadcast_content)],
            CONFIRM_BROADCAST: [CallbackQueryHandler(confirm_broadcast, pattern='^broadcast_(send|cancel)$')],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_action, pattern='^cancel$'),
            CommandHandler('cancel', cancel_action)
        ],
        map_to_parent={
            0: 0,
            ConversationHandler.END: ConversationHandler.END
        }
    )

    # --- Handlers ---
    application.add_handler(CommandHandler('start', start))
    application.add_handler(admin_conv)
    application.add_handler(CallbackQueryHandler(delete_tag_callback, pattern=r'^admin_delete_tag_\d+$'))
    application.add_handler(CallbackQueryHandler(reputation_callback_handler, pattern=r'^rep_(up|down)'))
    # THE FIX IS HERE: Corrected CallbackQuery_handler to CallbackQueryHandler
    application.add_handler(CallbackQueryHandler(tag_callback_handler, pattern=r'^tag_\d+$'))
    application.add_handler(CallbackQueryHandler(private_menu_callback_handler, pattern=r'^menu_'))
    application.add_handler(CallbackQueryHandler(show_private_main_menu, pattern=r'^show_private_main_menu$'))
    application.add_handler(CallbackQueryHandler(leaderboard_type_callback_handler, pattern=r'^leaderboard_'))
    application.add_handler(MessageHandler(filters.Entity('mention') & filters.ChatType.GROUPS, handle_query))

    # --- Run the Bot ---
    logger.info("Bot is starting...")
    
    try:
        async with application:
            application.create_task(run_suspicion_monitor())
            
            await application.initialize()
            await application.start()
            await application.updater.start_polling()
            logger.info("Bot has started polling successfully.")
            
            # Keep the application running indefinitely
            await asyncio.Event().wait()

    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot shutdown requested.")
    except Exception as e:
        logger.error(f"An unhandled exception occurred in main run loop: {e}", exc_info=True)
    finally:
        logger.info("Bot shutdown sequence initiated.")
        if application and application.updater and application.updater.is_polling():
            await application.updater.stop()
        if application:
            await application.shutdown()
        logger.info("Bot has been shut down.")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Failed to run the bot at the top level: {e}", exc_info=True)
