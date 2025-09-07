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

# --- 回调查询调度器 (核心) ---
async def callback_query_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    一个统一的调度器，根据回调数据的前缀，分发到不同的处理器。
    这使得代码结构更清晰，并能处理您设计的复杂回调数据。
    """
    query = update.callback_query
    data = query.data
    
    # 匹配模式: command_arg1_arg2_...
    parts = data.split('_')
    command = parts[0]
    args = parts[1:]

    # 管理员相关
    if command == 'admin':
        if args[0] == 'panel': await admin_handlers.admin_panel(update, context)
        elif args[0] == 'add': await admin_handlers.add_admin(update, context)
        elif args[0] == 'tags': await admin_handlers.manage_tags(update, context)
        elif args[0] == 'leaderboard': await admin_handlers.leaderboard_panel(update, context)
        elif args[0] == 'membership': await admin_handlers.membership_settings(update, context)
        elif args[0] == 'set' and args[1] == 'link': await admin_handlers.set_invite_link(update, context)
        elif args[0] == 'clear' and args[1] == 'membership': await admin_handlers.clear_membership_settings(update, context)
        elif args[0] == 'clear' and args[1] == 'lb' and args[2] == 'cache': await leaderboard_handlers.clear_leaderboard_cache(update, context)
        elif args[0] == 'remove' and args[1] == 'menu': await admin_handlers.remove_admin_menu(update, context, page=int(args[2]))
        elif args[0] == 'remove' and args[1] == 'confirm': await admin_handlers.confirm_remove_admin(update, context, user_pkid_to_remove=int(args[2]))
        elif args[0] == 'add' and args[1] == 'tag': await admin_handlers.add_tag(update, context, tag_type=args[2])
        elif args[0] == 'remove' and args[1] == 'tag' and args[2] == 'menu': await admin_handlers.remove_tag_menu(update, context, tag_type=args[3], page=int(args[4]))
        elif args[0] == 'remove' and args[1] == 'tag' and args[2] == 'confirm': await admin_handlers.confirm_remove_tag(update, context, tag_pkid=int(args[3]))

    # 排行榜相关
    elif command == 'leaderboard':
        if len(args) == 0 or args[0] == 'menu': await leaderboard_handlers.show_leaderboard_menu(update, context)
        else: await leaderboard_handlers.get_leaderboard_page(update, context, leaderboard_type=args[0], page=int(args[1]))

    # 评价相关
    elif command == 'vote':
        vote_type = args[0]
        target_pkid = int(args[1])
        target_username = args[2]
        await reputation_handlers.vote_menu(update, context, target_pkid, vote_type, target_username)
    elif command == 'process':
        target_pkid = int(args[1])
        tag_pkid = int(args[2])
        target_username = args[3]
        await reputation_handlers.process_vote(update, context, target_pkid, tag_pkid, target_username)
    
    # 收藏夹相关
    elif command == 'my':
        page = int(args[1]) if len(args) > 1 else 1
        await favorites_handlers.my_favorites(update, context, page)
    elif command == 'add':
        target_pkid = int(args[1])
        target_username = args[2]
        await favorites_handlers.add_favorite(update, context, target_pkid, target_username)
    elif command == 'remove':
        target_pkid = int(args[1])
        target_username = args[2]
        await favorites_handlers.remove_favorite(update, context, target_pkid, target_username)

    # 统计相关
    elif command == 'stats':
        target_pkid = int(args[1])
        page = int(args[2])
        target_username = args[3]
        await utils_handlers.show_user_stats(update, context, target_pkid, page, target_username)

    # 返回导航
    elif command == 'back':
        if args[0] == 'to':
            if args[1] == 'help': await help_handlers.send_help_message(update, context)
            elif args[1] == 'rep' and args[2] == 'card':
                target_pkid = int(args[3])
                target_username = args[4]
                await reputation_handlers.back_to_rep_card(update, context, target_pkid, target_username)

# --- 主程序 ---
async def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("请设置 TELEGRAM_TOKEN 环境变量")

    application = Application.builder().token(token).build()

    # --- 注册处理器 ---
    # 命令处理器
    application.add_handler(CommandHandler("start", help_handlers.send_help_message))
    application.add_handler(CommandHandler("bang", leaderboard_handlers.leaderboard_command))
    application.add_handler(CommandHandler("admin", admin_handlers.admin_panel))
    application.add_handler(CommandHandler("myfav", favorites_handlers.my_favorites))

    # 消息处理器
    # - 处理私聊中的文本，用于管理员输入
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, admin_handlers.handle_private_message))
    # - 处理转发消息，用于绑定群组
    application.add_handler(MessageHandler(filters.FORWARDED & filters.ChatType.PRIVATE, admin_handlers.handle_private_message))
    # - 处理 @username 查询
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r'@(\w+)'), reputation_handlers.handle_query))
    
    # 统一的回调查询处理器
    application.add_handler(CallbackQueryHandler(callback_query_dispatcher))
    
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
