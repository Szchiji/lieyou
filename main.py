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
from database import init_db, pool as db_pool

# --- 导入处理程序模块 ---
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
    """记录错误。"""
    logger.error("Exception while handling an update:", exc_info=context.error)

async def post_init(application: Application) -> None:
    """在应用启动后，初始化数据库。"""
    logger.info("应用程序 post_init: 正在初始化数据库...")
    await init_db()
    logger.info("数据库初始化完成。")

async def post_shutdown(application: Application) -> None:
    """在应用关闭前，关闭数据库连接池。"""
    global db_pool
    if db_pool:
        logger.info("应用程序 post_shutdown: 正在关闭数据库连接池...")
        await db_pool.close()
        logger.info("数据库连接池已关闭。")

def main() -> None:
    """配置并启动机器人。这个函数不再是 async。"""
    logger.info("程序开始启动...")
    
    # --- 环境变量 ---
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        logger.critical("TELEGRAM_BOT_TOKEN 环境变量未设置！")
        return
    
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    port = int(os.environ.get("PORT", 8443))

    # 使用 post_init 和 post_shutdown 来安全地管理数据库生命周期
    builder = Application.builder().token(telegram_token)
    builder.post_init(post_init)
    builder.post_shutdown(post_shutdown)
    
    # 1. 构建 Application
    application = builder.build()
    
    # 2. 添加处理程序
    application.add_handler(CommandHandler("start", bot_handlers.start.start))
    application.add_handler(CommandHandler("help", bot_handlers.start.help_command))
    application.add_handler(CommandHandler("admin", bot_handlers.admin.admin_panel))
    application.add_handler(CommandHandler("bang", bot_handlers.leaderboard.leaderboard_command))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP),
        bot_handlers.reputation.handle_query
    ))
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.FORWARDED) & ~filters.COMMAND & filters.ChatType.PRIVATE,
        bot_handlers.admin.handle_private_message
    ))
    application.add_handler(CallbackQueryHandler(bot_handlers.start.help_command, pattern=r"^help$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.start.back_to_help, pattern=r"^back_to_help$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.reputation.back_to_rep_card(u, c, int(c.match.group(1)), c.match.group(2)), pattern=r"^back_to_rep_card_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.reputation.vote_menu(u, c, int(c.match.group(2)), c.match.group(1), c.match.group(3)), pattern=r"^vote_(\w+)_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.reputation.process_vote(u, c, int(c.match.group(1)), int(c.match.group(2)), c.match.group(3)), pattern=r"^process_vote_(\d+)_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.favorites.my_favorites(u, c, int(c.match.group(1))), pattern=r"^my_favorites_(\d+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.favorites.add_favorite(u, c, int(c.match.group(1)), c.match.group(2)), pattern=r"^add_favorite_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.favorites.remove_favorite(u, c, int(c.match.group(1)), c.match.group(2)), pattern=r"^remove_favorite_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.leaderboard.show_leaderboard_menu, pattern=r"^leaderboard_menu$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.leaderboard.leaderboard_command, pattern=r"^leaderboard_menu_simple$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.leaderboard.get_leaderboard_page(u, c, c.match.group(1), int(c.match.group(2))), pattern=r"^leaderboard_(\w+)_(\d+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.statistics.show_user_statistics(u, c, int(c.match.group(1)), int(c.match.group(2)), c.match.group(3)), pattern=r"^stats_user_(\d+)_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.statistics.navigate_stats(u, c, int(c.match.group(1)), int(c.match.group(2)), c.match.group(3), c.match.group(4)), pattern=r"^stats_nav_(\d+)_(\d+)_(\w+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.admin.admin_panel, pattern=r"^admin_panel$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.admin.add_admin, pattern=r"^admin_add$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.remove_admin_menu(u, c, int(c.match.group(1))), pattern=r"^admin_remove_menu_(\d+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.confirm_remove_admin(u, c, int(c.match.group(1))), pattern=r"^admin_remove_confirm_(\d+)$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.admin.manage_tags, pattern=r"^admin_tags$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.add_tag(u, c, c.match.group(1)), pattern=r"^admin_add_tag_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.remove_tag_menu(u, c, c.match.group(1), int(c.match.group(2))), pattern=r"^admin_remove_tag_menu_(\w+)_(\d+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: bot_handlers.admin.confirm_remove_tag(u, c, int(c.match.group(1))), pattern=r"^admin_remove_tag_confirm_(\d+)$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.admin.leaderboard_panel, pattern=r"^admin_leaderboard$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.leaderboard.clear_leaderboard_cache, pattern=r"^admin_clear_lb_cache$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.admin.membership_settings, pattern=r"^admin_membership$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.admin.set_invite_link, pattern=r"^admin_set_link$"))
    application.add_handler(CallbackQueryHandler(bot_handlers.admin.clear_membership_settings, pattern=r"^admin_clear_membership$"))
    application.add_error_handler(error_handler)
    
    # --- 启动模式 ---
    if render_url:
        # Webhook 模式: 将所有控制权交给 application.run_webhook
        webhook_path = f"/{telegram_token}"
        webhook_url = f"{render_url}{webhook_path}"
        
        logger.info(f"将以 Webhook 模式启动，监听 0.0.0.0:{port}")
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            webhook_url=webhook_url,
            allowed_updates=Update.ALL_TYPES
        )
    else:
        # 轮询模式: 将所有控制权交给 application.run_polling
        logger.info("将以轮询模式启动。")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
