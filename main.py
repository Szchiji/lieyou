import logging
import os
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

# 在所有其他导入之前加载环境变量
load_dotenv()

# 导入数据库初始化函数
from database import init_db

# --- 导入处理程序模块 ---
# 这是解决循环导入问题的关键：逐个、明确地导入每个模块。
from handlers import start
from handlers import admin
from handlers import favorites
from handlers import leaderboard
from handlers import reputation
from handlers import statistics
# utils 不需要在这里导入，因为它被其他 handlers 模块内部使用

# 配置日志
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """记录错误并向用户发送技术问题通知。"""
    logger.error("Exception while handling an update:", exc_info=context.error)
    # 如果可能，可以尝试通知用户
    if isinstance(update, Update) and update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="抱歉，处理您的请求时遇到了一个内部错误。"
        )

async def main() -> None:
    """启动机器人。"""
    logger.info("程序开始启动...")
    
    # 检查环境变量
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not telegram_token:
        logger.critical("TELEGRAM_BOT_TOKEN 环境变量未设置！")
        return
    
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    
    logger.info(".env 文件已加载 (如果存在)。")
    logger.info("TELEGRAM_BOT_TOKEN 已加载。")
    if render_url:
        logger.info(f"RENDER_EXTERNAL_URL 已加载: {render_url}")

    # 初始化数据库
    try:
        await init_db()
    except Exception as e:
        logger.critical(f"数据库初始化失败，程序无法启动: {e}")
        return

    # 创建应用
    application = Application.builder().token(telegram_token).build()

    # --- 注册命令处理 ---
    application.add_handler(CommandHandler("start", start.start))
    application.add_handler(CommandHandler("help", start.help_command))
    application.add_handler(CommandHandler("admin", admin.admin_panel))
    application.add_handler(CommandHandler("bang", leaderboard.leaderboard_command)) # 榜单命令

    # --- 注册消息处理 ---
    # 核心功能：处理包含 @username 的文本消息
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUPS | filters.ChatType.SUPERGROUP),
        reputation.handle_query
    ))
    # 在私聊中处理管理员添加/标签添加/入群设置的文本和转发输入
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.FORWARDED) & ~filters.COMMAND & filters.ChatType.PRIVATE,
        admin.handle_private_message
    ))

    # --- 注册回调查询处理 (按钮点击) ---
    # 主菜单
    application.add_handler(CallbackQueryHandler(start.help_command, pattern=r"^help$"))
    application.add_handler(CallbackQueryHandler(start.back_to_help, pattern=r"^back_to_help$"))

    # 声誉系统
    application.add_handler(CallbackQueryHandler(lambda u, c: reputation.back_to_rep_card(u, c, int(c.match.group(1)), c.match.group(2)), pattern=r"^back_to_rep_card_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: reputation.vote_menu(u, c, int(c.match.group(2)), c.match.group(1), c.match.group(3)), pattern=r"^vote_(\w+)_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: reputation.process_vote(u, c, int(c.match.group(1)), int(c.match.group(2)), c.match.group(3)), pattern=r"^process_vote_(\d+)_(\d+)_(\w+)$"))
    
    # 收藏夹
    application.add_handler(CallbackQueryHandler(lambda u, c: favorites.my_favorites(u, c, int(c.match.group(1))), pattern=r"^my_favorites_(\d+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: favorites.add_favorite(u, c, int(c.match.group(1)), c.match.group(2)), pattern=r"^add_favorite_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: favorites.remove_favorite(u, c, int(c.match.group(1)), c.match.group(2)), pattern=r"^remove_favorite_(\d+)_(\w+)$"))

    # 排行榜
    application.add_handler(CallbackQueryHandler(leaderboard.show_leaderboard_menu, pattern=r"^leaderboard_menu$"))
    application.add_handler(CallbackQueryHandler(leaderboard.leaderboard_command, pattern=r"^leaderboard_menu_simple$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: leaderboard.get_leaderboard_page(u, c, c.match.group(1), int(c.match.group(2))), pattern=r"^leaderboard_(\w+)_(\d+)$"))

    # 统计
    application.add_handler(CallbackQueryHandler(lambda u, c: statistics.show_user_statistics(u, c, int(c.match.group(1)), int(c.match.group(2)), c.match.group(3)), pattern=r"^stats_user_(\d+)_(\d+)_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: statistics.navigate_stats(u, c, int(c.match.group(1)), int(c.match.group(2)), c.match.group(3), c.match.group(4)), pattern=r"^stats_nav_(\d+)_(\d+)_(\w+)_(\w+)$"))

    # 管理员
    application.add_handler(CallbackQueryHandler(admin.admin_panel, pattern=r"^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin.add_admin, pattern=r"^admin_add$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: admin.remove_admin_menu(u, c, int(c.match.group(1))), pattern=r"^admin_remove_menu_(\d+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: admin.confirm_remove_admin(u, c, int(c.match.group(1))), pattern=r"^admin_remove_confirm_(\d+)$"))
    application.add_handler(CallbackQueryHandler(admin.manage_tags, pattern=r"^admin_tags$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: admin.add_tag(u, c, c.match.group(1)), pattern=r"^admin_add_tag_(\w+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: admin.remove_tag_menu(u, c, c.match.group(1), int(c.match.group(2))), pattern=r"^admin_remove_tag_menu_(\w+)_(\d+)$"))
    application.add_handler(CallbackQueryHandler(lambda u, c: admin.confirm_remove_tag(u, c, int(c.match.group(1))), pattern=r"^admin_remove_tag_confirm_(\d+)$"))
    application.add_handler(CallbackQueryHandler(admin.leaderboard_panel, pattern=r"^admin_leaderboard$"))
    application.add_handler(CallbackQueryHandler(leaderboard.clear_leaderboard_cache, pattern=r"^admin_clear_lb_cache$"))
    
    # 新增的管理员回调：入群设置
    application.add_handler(CallbackQueryHandler(admin.membership_settings, pattern=r"^admin_membership$"))
    application.add_handler(CallbackQueryHandler(admin.set_invite_link, pattern=r"^admin_set_link$"))
    application.add_handler(CallbackQueryHandler(admin.clear_membership_settings, pattern=r"^admin_clear_membership$"))

    # 注册错误处理
    application.add_error_handler(error_handler)

    # 启动机器人
    if render_url:
        # 使用 Webhook 模式 (适用于 Render 等平台)
        port = int(os.environ.get("PORT", 8443))
        # 我们需要一个简单的web server来响应Render的健康检查
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading

        class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'Bot is running')

        httpd = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
        
        # 在单独的线程中运行HTTP服务器
        http_thread = threading.Thread(target=httpd.serve_forever)
        http_thread.daemon = True
        http_thread.start()
        logger.info(f"健康检查服务器正在 0.0.0.0:{port} 上运行")

        # 设置并运行Telegram应用
        await application.bot.set_webhook(url=f"{render_url}/telegram")
        logger.info(f"Webhook 已设置为 {render_url}/telegram")
        async with application:
             await application.start()
             logger.info("应用程序已启动 (Webhook模式)")
             await application.running
    else:
        # 使用轮询模式 (适用于本地开发)
        logger.info("未检测到 RENDER_EXTERNAL_URL，将使用轮询模式启动。")
        await application.run_polling()

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("程序被手动中断。")
