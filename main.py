import logging
import os
import asyncio
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

import database
from bot_handlers import *

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main() -> None:
    """The main entry point for the bot."""
    load_dotenv()
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN not found in environment variables. Bot cannot start.")
        return

    # --- Database Setup ---
    try:
        await database.init_db()
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}. Bot cannot start.", exc_info=True)
        return

    # --- Build the application with post_shutdown hook ---
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_shutdown(database.close_pool)
        .build()
    )

    # --- Conversation Handlers ---
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_panel)],
        states={
            0: [
                CallbackQueryHandler(admin_panel, pattern=r'^admin_panel$'),
                CallbackQueryHandler(manage_tags_panel, pattern=r'^admin_manage_tags$'),
                CallbackQueryHandler(delete_tag_callback, pattern=r'^admin_delete_tag_'),
                CallbackQueryHandler(manage_menu_buttons_panel, pattern=r'^admin_menu_buttons$'),
                CallbackQueryHandler(delete_menu_button_callback, pattern=r'^delete_menu_'),
                CallbackQueryHandler(toggle_menu_button_callback, pattern=r'^toggle_menu_'),
                CallbackQueryHandler(reorder_menu_button_callback, pattern=r'^reorder_menu_'),
                CallbackQueryHandler(user_management_panel, pattern=r'^admin_user_management$'),
                CallbackQueryHandler(add_tag_prompt, pattern=r'^admin_add_tag_prompt$'),
                CallbackQueryHandler(add_menu_button_prompt, pattern=r'^admin_add_menu_button_prompt$'),
                CallbackQueryHandler(prompt_for_username, pattern=r'^admin_hide_user_prompt$'),
                CallbackQueryHandler(prompt_for_username, pattern=r'^admin_unhide_user_prompt$'),
                CallbackQueryHandler(prompt_for_broadcast, pattern=r'^admin_broadcast$'),
            ],
            TYPING_TAG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_tag)],
            SELECTING_TAG_TYPE: [CallbackQueryHandler(handle_tag_type_selection, pattern=r'^tag_type_')],
            TYPING_BUTTON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_menu_button_name)],
            SELECTING_BUTTON_ACTION: [CallbackQueryHandler(handle_new_menu_button_action, pattern=r'^action_')],
            TYPING_USERNAME_TO_HIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
            TYPING_USERNAME_TO_UNHIDE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_user_hidden_status)],
            TYPING_BROADCAST: [MessageHandler(filters.ALL & ~filters.COMMAND, get_broadcast_content)],
            CONFIRM_BROADCAST: [CallbackQueryHandler(confirm_broadcast, pattern=r'^broadcast_')],
        },
        fallbacks=[CommandHandler('cancel', cancel_action), CallbackQueryHandler(cancel_action, pattern=r'^cancel$')],
        allow_reentry=True,
    )

    # --- Register Handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(admin_conv)
    application.add_handler(CommandHandler("myreport", generate_my_report))
    application.add_handler(MessageHandler(filters.Entity("mention") & filters.ChatType.GROUPS, handle_query))
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_menu_callback_handler))
    application.add_handler(CallbackQueryHandler(tag_callback_handler, pattern=r'^tag_'))
    application.add_handler(CallbackQueryHandler(leaderboard_type_callback_handler, pattern=r'^lb_'))
    application.add_handler(CallbackQueryHandler(reputation_callback_handler, pattern=r'^rep_'))
    application.add_handler(CallbackQueryHandler(show_private_main_menu, pattern=r'^show_private_main_menu$'))
    application.add_handler(CallbackQueryHandler(show_leaderboard_callback_handler, pattern=r'^show_leaderboard_public$'))

    # --- ULTIMATE FIX: Run the Bot with manual lifecycle management ---
    # This approach is more robust for PaaS environments like Render.
    try:
        logger.info("Bot is starting with manual lifecycle management...")
        async with application:
            await application.start()
            await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
            logger.info("Bot has started polling successfully.")
            
            # Create background task after the application is fully running
            application.create_task(run_suspicion_monitor(application.bot))
            
            # Keep the application running indefinitely
            await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received. The application will now stop gracefully.")
    finally:
        if application.updater and application.updater.is_running:
            await application.updater.stop()
        if application.running:
            await application.stop()
        logger.info("Bot has been shut down.")


if __name__ == '__main__':
    # The outer try/except is now simpler as the main function handles the lifecycle.
    asyncio.run(main())
