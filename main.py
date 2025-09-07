import logging
import os
import sys
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# --- 强制修正 Python 路径 (双重保险) ---
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 在所有其他导入之前加载环境变量
load_dotenv()

# 导入数据库初始化函数
from database import init_db

# --- 导入处理程序模块 (使用新名称) ---
import bot_handlers.start
import bot_handlers.admin
import bot_handlers.favorites
import bot_handlers.leaderboard
import bot_handlers.reputation
import bot_handlers.statistics

# 配置日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """记录错误并向用户发送技术问题通知。"""
    logger.error("Exception while handling an update:", exc_info=context.error)

async def main() -> None:
    """配置并启动机器人。"""
    logger.info("程序开始启动...")
    
    # --- 环境变量 ---
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        logger.critical("TELEGRAM_BOT_TOKEN 环境变量未设置！")
        return
    
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    port = int(os.environ.get("PORT", 8443))

    # --- 初始化 ---
    await init_db()
    
    # 我们使用 `builder` 来配置 application，但暂时不 `build`
    builder = Application.builder().token(telegram_token)
    
    # --- 注册处理程序 ---
    builder.add_handler(CommandHandler("start", bot_handlers.start.start))
    builder.add_handler(CommandHandler("help", bot_handlers.start.help_command))
    builder.add_handler(CommandHandler("admin", bot_handlers.admin.admin_panel))
    builder.add_handler(CommandHandler("bang", bot_handlers.leaderboard.leaderboard_command))
    builder.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP),
        bot_handlers.reputation.handle_query
    ))
    builder.add_handler(MessageHandler(
        (filters.TEXT | filters.FORWARDED) & ~filters.COMMAND & filters.ChatType.PRIVATE,
        bot_handlers.admin.handle_private_message
    ))
    builder.add_handler(CallbackQueryHandler(bot_handlers.start.help_command, pattern=r"^help$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.start.back_to_help, pattern=r"^back_to_help$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.reputation.back_to_rep_card(u, c, int(c.match.group(1)), c.match.group(2)), pattern=r"^back_to_rep_card_(\d+)_(\w+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.reputation.vote_menu(u, c, int(c.match.group(2)), c.match.group(1), c.match.group(3)), pattern=r"^vote_(\w+)_(\d+)_(\w+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.reputation.process_vote(u, c, int(c.match.group(1)), int(c.match.group(2)), c.match.group(3)), pattern=r"^process_vote_(\d+)_(\d+)_(\w+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.favorites.my_favorites(u, c, int(c.match.group(1))), pattern=r"^my_favorites_(\d+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.favorites.add_favorite(u, c, int(c.match.group(1)), c.match.group(2)), pattern=r"^add_favorite_(\d+)_(\w+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.favorites.remove_favorite(u, c, int(c.match.group(1)), c.match.group(2)), pattern=r"^remove_favorite_(\d+)_(\w+)$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.leaderboard.show_leaderboard_menu, pattern=r"^leaderboard_menu$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.leaderboard.leaderboard_command, pattern=r"^leaderboard_menu_simple$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.leaderboard.get_leaderboard_page(u, c, c.match.group(1), int(c.match.group(2))), pattern=r"^leaderboard_(\w+)_(\d+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.statistics.show_user_statistics(u, c, int(c.match.group(1)), int(c.match.group(2)), c.match.group(3)), pattern=r"^stats_user_(\d+)_(\d+)_(\w+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.statistics.navigate_stats(u, c, int(c.match.group(1)), int(c.match.group(2)), c.match.group(3), c.match.group(4)), pattern=r"^stats_nav_(\d+)_(\d+)_(\w+)_(\w+)$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.admin.admin_panel, pattern=r"^admin_panel$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.admin.add_admin, pattern=r"^admin_add$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.remove_admin_menu(u, c, int(c.match.group(1))), pattern=r"^admin_remove_menu_(\d+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.confirm_remove_admin(u, c, int(c.match.group(1))), pattern=r"^admin_remove_confirm_(\d+)$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.admin.manage_tags, pattern=r"^admin_tags$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.add_tag(u, c, c.match.group(1)), pattern=r"^admin_add_tag_(\w+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.remove_tag_menu(u, c, c.match.group(1), int(c.match.group(2))), pattern=r"^admin_remove_tag_menu_(\w+)_(\d+)$"))
    builder.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.confirm_remove_tag(u, c, int(c.match.group(1))), pattern=r"^admin_remove_tag_confirm_(\d+)$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.admin.leaderboard_panel, pattern=r"^admin_leaderboard$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.leaderboard.clear_leaderboard_cache, pattern=r"^admin_clear_lb_cache$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.admin.membership_settings, pattern=r"^admin_membership$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.admin.set_invite_link, pattern=r"^admin_set_link$"))
    builder.add_handler(CallbackQueryHandler(bot_handlers.admin.clear_membership_settings, pattern=r"^admin_clear_membership$"))
    builder.add_error_handler(error_handler)
    
    # --- 启动模式 ---
    if render_url:
        # --- Webhook 模式 (用于 Render) ---
        # 我们将手动控制启动/关闭流程，不再使用 run_webhook
        webhook_path = f"/{telegram_token}"
        webhook_url = f"{render_url}{webhook_path}"
        
        # 1. 构建 application
        application = builder.build()
        
        # 2. 初始化应用，设置 webhook
        await application.initialize()
        await application.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
        
        # 3. 启动一个简单的 web server 来接收消息
        # 关键：我们把 application 作为一个回调函数传给 web server
        from telegram.ext import Updater, Application as WebhookApplication
        
        # 创建一个假的 updater 来复用它的 web server
        # 这是一个技巧，利用库的内部组件来避免冲突
        class NoUpdater(Updater):
            def __init__(self, application: WebhookApplication):
                super().__init__(bot=application.bot, update_queue=application.update_queue)

            def start_polling(self, *args, **kwargs): pass
            def start_webhook(self, *args, **kwargs): pass
            def stop(self): pass

        updater = NoUpdater(application)
        updater.start_webhook(listen="0.0.0.0", port=port, url_path=webhook_path)
        logger.info(f"Webhook 服务器已在 0.0.0.0:{port} 上启动")

        # 4. 让应用保持运行状态
        await application.start()
        logger.info("应用程序已在 Webhook 模式下启动，并开始接收更新。")
        
        # 5. 保持主协程运行，直到被外部停止
        while True:
            await asyncio.sleep(3600)

    else:
        # --- 轮询模式 (用于本地开发) ---
        logger.info("未检测到 RENDER_EXTERNAL_URL，将使用轮询模式启动。")
        application = builder.build()
        await application.run_polling()
        logger.info("应用程序已在轮询模式下启动。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("程序被手动中断。")
