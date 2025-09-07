import logging
import os
import sys
import re
from datetime import datetime
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
import asyncio

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
    if isinstance(update, Update) and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="抱歉，处理您的请求时遇到了一个内部错误。"
        )

async def main() -> None:
    """启动机器人。"""
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
    application = Application.builder().token(telegram_token).build()

    # --- 注册处理程序 ---
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

    # --- 注册回调查询处理 ---
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
        # Webhook 模式 (用于 Render)
        webhook_path = f"/{telegram_token}" # 使用一个秘密路径
        webhook_url = f"{render_url}{webhook_path}"
        
        logger.info(f"将在 Webhook 模式下启动，监听端口: {port}")
        logger.info(f"设置 Webhook 到: {webhook_url}")
        
        await application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=webhook_path,
            webhook_url=webhook_url
        )
        logger.info("应用程序已在 Webhook 模式下启动。")

    else:
        # 轮询模式 (用于本地开发)
        logger.info("未检测到 RENDER_EXTERNAL_URL，将使用轮询模式启动。")
        await application.run_polling()
        logger.info("应用程序已在轮询模式下启动。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("程序被手动中断。")
