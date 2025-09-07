import logging
import os
import asyncio
import re
import uvicorn
from fastapi import FastAPI

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram import Update

# 从您的专业模块中导入所有处理器
from bot_handlers import (
    admin as admin_handlers,
    favorites as favorites_handlers,
    leaderboard as leaderboard_handlers,
    reputation as reputation_handlers,
    help as help_handlers,
    utils as utils_handlers,
)
import database

# --- 初始化 ---
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Web服务器，用于Render健康检查 ---
web_app = FastAPI()
@web_app.get("/")
async def health_check():
    return {"status": "Bot is running"}

# --- 主程序 ---
async def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("请设置 TELEGRAM_TOKEN 环境变量")

    application = Application.builder().token(token).build()

    # --- 注册处理器 (使用正则表达式精确匹配) ---
    
    # 1. 命令处理器
    application.add_handler(CommandHandler("start", help_handlers.send_help_message))
    application.add_handler(CommandHandler("bang", leaderboard_handlers.leaderboard_command))
    application.add_handler(CommandHandler("admin", admin_handlers.admin_panel))
    application.add_handler(CommandHandler("myfav", favorites_handlers.my_favorites))

    # 2. 消息处理器
    # - 处理私聊中的文本，用于管理员输入
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, admin_handlers.handle_private_message))
    # - 处理转发消息，用于绑定群组
    application.add_handler(MessageHandler(filters.FORWARDED & filters.ChatType.PRIVATE, admin_handlers.handle_private_message))
    # - 处理 @username 查询
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r'@(\w+)'), reputation_handlers.handle_query))
    
    # 3. 回调查询处理器 (精确匹配，不再使用脆弱的调度器)
    
    # 导航
    application.add_handler(CallbackQueryHandler(help_handlers.send_help_message, pattern=r'^back_to_help$'))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: reputation_handlers.back_to_rep_card(u, c, target_pkid=int(c.match.group(1)), target_username=c.match.group(2)),
        pattern=r'^back_to_rep_card_(\d+)_(.+)$'
    ))

    # 声誉系统
    application.add_handler(CallbackQueryHandler(
        lambda u, c: reputation_handlers.vote_menu(u, c, target_pkid=int(c.match.group(2)), vote_type=c.match.group(1), target_username=c.match.group(3)),
        pattern=r'^vote_(recommend|block)_(\d+)_(.+)$'
    ))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: reputation_handlers.process_vote(u, c, target_pkid=int(c.match.group(1)), tag_pkid=int(c.match.group(2)), target_username=c.match.group(3)),
        pattern=r'^process_vote_(\d+)_(\d+)_(.+)$'
    ))

    # 收藏夹
    application.add_handler(CallbackQueryHandler(
        lambda u, c: favorites_handlers.my_favorites(u, c, page=int(c.match.group(1))),
        pattern=r'^my_favorites_(\d+)$'
    ))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: favorites_handlers.add_favorite(u, c, target_pkid=int(c.match.group(1)), target_username=c.match.group(2)),
        pattern=r'^add_favorite_(\d+)_(.+)$'
    ))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: favorites_handlers.remove_favorite(u, c, target_pkid=int(c.match.group(1)), target_username=c.match.group(2)),
        pattern=r'^remove_favorite_(\d+)_(.+)$'
    ))

    # 排行榜
    application.add_handler(CallbackQueryHandler(leaderboard_handlers.show_leaderboard_menu, pattern=r'^leaderboard_menu$'))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: leaderboard_handlers.get_leaderboard_page(u, c, leaderboard_type=c.match.group(1), page=int(c.match.group(2))),
        pattern=r'^leaderboard_(recommend|block|score|popularity)_(\d+)$'
    ))

    # 统计
    application.add_handler(CallbackQueryHandler(
        lambda u, c: utils_handlers.show_user_stats(u, c, target_pkid=int(c.match.group(1)), page=int(c.match.group(2)), target_username=c.match.group(3)),
        pattern=r'^stats_user_(\d+)_(\d+)_(.+)$'
    ))
    
    # 管理员
    application.add_handler(CallbackQueryHandler(admin_handlers.admin_panel, pattern=r'^admin_panel$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.add_admin, pattern=r'^admin_add$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.manage_tags, pattern=r'^admin_tags$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.leaderboard_panel, pattern=r'^admin_leaderboard$'))
    application.add_handler(CallbackQueryHandler(leaderboard_handlers.clear_leaderboard_cache, pattern=r'^admin_clear_lb_cache$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.membership_settings, pattern=r'^admin_membership$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.set_invite_link, pattern=r'^admin_set_link$'))
    application.add_handler(CallbackQueryHandler(admin_handlers.clear_membership_settings, pattern=r'^admin_clear_membership$'))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: admin_handlers.add_tag(u, c, tag_type=c.match.group(1)),
        pattern=r'^admin_add_tag_(recommend|block)$'
    ))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: admin_handlers.remove_admin_menu(u, c, page=int(c.match.group(1))),
        pattern=r'^admin_remove_menu_(\d+)$'
    ))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: admin_handlers.confirm_remove_admin(u, c, user_pkid_to_remove=int(c.match.group(1))),
        pattern=r'^admin_remove_confirm_(\d+)$'
    ))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: admin_handlers.remove_tag_menu(u, c, tag_type=c.match.group(1), page=int(c.match.group(2))),
        pattern=r'^admin_remove_tag_menu_(recommend|block)_(\d+)$'
    ))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: admin_handlers.confirm_remove_tag(u, c, tag_pkid=int(c.match.group(1))),
        pattern=r'^admin_remove_tag_confirm_(\d+)$'
    ))
    
    # --- 启动 ---
    async with application:
        await database.init_db()
        logger.info("数据库初始化完成。")

        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("机器人 Polling 已启动。")

        # 启动 web 服务器
        port = int(os.environ.get("PORT", 10000))
        config = uvicorn.Config(web_app, host="0.0.0.0", port=port, log_level="info")
        server = uvicorn.Server(config)
        
        logger.info(f"健康检查服务器将在端口 {port} 上启动。")
        await server.serve()

        logger.info("Web 服务器已停止，正在关闭机器人...")
        await application.updater.stop()
        await application.stop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("机器人已关闭。")
