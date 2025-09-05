import logging
import re
from os import environ
from contextlib import asynccontextmanager
import uvicorn # 导入 uvicorn

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ApplicationBuilder
)
from telegram.constants import ParseMode

# 加载环境变量
load_dotenv()

# 设置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# 导入数据库和所有处理器
from database import init_db, get_pool, get_setting
from handlers.reputation import handle_query, vote_menu, process_vote, back_to_rep_card, send_reputation_card
from handlers.leaderboard import leaderboard_menu, refresh_leaderboard, admin_clear_leaderboard_cache
from handlers.favorites import add_favorite, remove_favorite, my_favorites_list
from handlers.stats import user_stats_menu
from handlers.erasure import request_data_erasure, confirm_data_erasure, cancel_data_erasure
from handlers.admin import (
    god_mode_command, settings_menu, process_admin_input,
    tags_panel, permissions_panel, system_settings_panel, leaderboard_panel,
    add_tag_prompt, remove_tag_menu, remove_tag_confirm, execute_tag_deletion, list_all_tags,
    add_admin_prompt, list_admins, remove_admin_menu, remove_admin_confirm, execute_admin_removal,
    set_setting_prompt, set_start_message_prompt, show_all_commands,
    selective_remove_menu, confirm_user_removal, execute_user_removal
)

TELEGRAM_BOT_TOKEN = environ["TELEGRAM_BOT_TOKEN"]
RENDER_EXTERNAL_URL = environ.get("RENDER_EXTERNAL_URL")

# --- 主命令处理器 ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /start 和 /help 命令"""
    # 确保 update.message 存在
    message = update.message or update.callback_query.message
    start_message = await get_setting('start_message', "欢迎使用神谕者机器人！")
    keyboard = [
        [InlineKeyboardButton("🏆 好评榜", callback_data="leaderboard_top_1")],
        [InlineKeyboardButton("☠️ 差评榜", callback_data="leaderboard_bottom_1")],
        [InlineKeyboardButton("❤️ 我的收藏", callback_data="my_favorites_1")],
        [InlineKeyboardButton("⚙️ 管理面板", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(start_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /cancel 命令"""
    if 'waiting_for' in context.user_data:
        del context.user_data['waiting_for']
        await update.message.reply_text("操作已取消。")

# --- 回调查询路由器 ---

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """解析所有回调查询并分发到对应的函数"""
    query = update.callback_query
    await query.answer() # 在开始时应答，避免超时
    data = query.data
    
    # 简单的命令
    simple_handlers = {
        "back_to_help": start_command,
        "admin_settings_menu": settings_menu,
        "admin_panel_tags": tags_panel,
        "admin_panel_permissions": permissions_panel,
        "admin_panel_system": system_settings_panel,
        "admin_leaderboard_panel": leaderboard_panel,
        "admin_leaderboard_clear_cache": admin_clear_leaderboard_cache,
        "admin_tags_list": list_all_tags,
        "admin_perms_list": list_admins,
        "admin_show_commands": show_all_commands,
        "admin_tags_add_recommend_prompt": lambda u, c: add_tag_prompt(u, c, 'recommend'),
        "admin_tags_add_block_prompt": lambda u, c: add_tag_prompt(u, c, 'block'),
        "admin_perms_add_prompt": add_admin_prompt,
        "admin_system_set_start_message": set_start_message_prompt,
        "admin_system_set_prompt_auto_delete_timeout": lambda u, c: set_setting_prompt(u, c, 'auto_delete_timeout'),
        "admin_system_set_prompt_admin_password": lambda u, c: set_setting_prompt(u, c, 'admin_password'),
        "confirm_data_erasure": confirm_data_erasure,
        "cancel_data_erasure": cancel_data_erasure,
    }
    if data in simple_handlers:
        await simple_handlers[data](update, context)
        return

    # 带参数的命令
    patterns = {
        r"leaderboard_(top|bottom)_(\d+)": lambda m: leaderboard_menu(update, context, m[1], int(m[2])),
        r"leaderboard_refresh_(top|bottom)_(\d+)": lambda m: refresh_leaderboard(update, context, m[1], int(m[2])),
        r"my_favorites_(\d+)": lambda m: my_favorites_list(update, context, int(m[1])),
        r"vote_(recommend|block)_(\d+)_(\d+)": lambda m: vote_menu(update, context, int(m[2]), m[1], int(m[3])),
        r"process_vote_(\d+)_(.+)": lambda m: process_vote(update, context, int(m[1]), m[2]),
        r"back_to_rep_card_(\d+)": lambda m: back_to_rep_card(update, context, int(m[1])),
        r"rep_card_query_(\d+)": lambda m: send_reputation_card(query, context, int(m[1])),
        r"add_favorite_(\d+)": lambda m: add_favorite(update, context, int(m[1])),
        r"remove_favorite_(\d+)": lambda m: remove_favorite(update, context, int(m[1])),
        r"stats_user_(\d+)(?:_(\d+))?": lambda m: user_stats_menu(update, context, int(m[1]), int(m[2] or 1)),
        r"admin_tags_remove_menu_(\d+)": lambda m: remove_tag_menu(update, context, int(m[1])),
        r"admin_tags_remove_confirm_(\d+)_(\d+)": lambda m: remove_tag_confirm(update, context, int(m[1]), int(m[2])),
        r"admin_tag_delete_(\d+)": lambda m: execute_tag_deletion(update, context, int(m[1])),
        r"admin_perms_remove_menu_(\d+)": lambda m: remove_admin_menu(update, context, int(m[1])),
        r"admin_perms_remove_confirm_(\d+)_(\d+)": lambda m: remove_admin_confirm(update, context, int(m[1]), int(m[2])),
        r"admin_remove_admin_(\d+)": lambda m: execute_admin_removal(update, context, int(m[1])),
        r"admin_selective_remove_(top|bottom)_(\d+)": lambda m: selective_remove_menu(update, context, m[1], int(m[2])),
        r"admin_confirm_remove_user_(\d+)_(top|bottom)_(\d+)": lambda m: confirm_user_removal(update, context, int(m[1]), m[2], int(m[3])),
        r"admin_execute_removal_(clear_all|clear_neg)_(\d+)_(top|bottom)_(\d+)": lambda m: execute_user_removal(update, context, int(m[2]), m[1], m[3], int(m[4])),
    }
    
    for pattern, handler in patterns.items():
        match = re.fullmatch(pattern, data)
        if match:
            await handler(match.groups())
            return
            
    logger.warning(f"未处理的回调查询: {data}")

# --- FastAPI Web 应用设置 ---

ptb_app = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 启动逻辑 ---
    await init_db()
    
    global ptb_app
    ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 命令处理器
    ptb_app.add_handler(CommandHandler("start", start_command))
    ptb_app.add_handler(CommandHandler("help", start_command))
    ptb_app.add_handler(CommandHandler("myfavorites", lambda u, c: my_favorites_list(u, c, 1)))
    ptb_app.add_handler(CommandHandler("erase_my_data", request_data_erasure))
    ptb_app.add_handler(CommandHandler("cancel", cancel_command, filters=filters.ChatType.PRIVATE))
    ptb_app.add_handler(CommandHandler("godmode", god_mode_command, filters=filters.ChatType.PRIVATE))

    # 消息处理器
    ptb_app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, process_admin_input))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))

    # 回调查询处理器
    ptb_app.add_handler(CallbackQueryHandler(button_callback_handler))

    if RENDER_EXTERNAL_URL:
        await ptb_app.bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/webhook", allowed_updates=Update.ALL_TYPES)
        logger.info(f"Webhook已设置为: {RENDER_EXTERNAL_URL}/webhook")
    
    # 初始化 ptb_app
    await ptb_app.initialize()
    if ptb_app.post_init:
        await ptb_app.post_init(ptb_app)
    
    yield
    # --- 清理逻辑 ---
    if ptb_app.post_shutdown:
        await ptb_app.post_shutdown(ptb_app)
    await ptb_app.shutdown()
    db_pool = await get_pool()
    if db_pool:
        await db_pool.close()
        logger.info("数据库连接池已关闭。")

fastapi_app = FastAPI(lifespan=lifespan)

@fastapi_app.post("/webhook")
async def webhook(request: Request):
    """处理来自Telegram的webhook请求"""
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"处理webhook时出错: {e}", exc_info=True)
        return Response(status_code=500)

@fastapi_app.get("/")
def index():
    return {"status": "ok", "bot": "神谕者机器人正在运行"}

# --- 启动逻辑 ---
# 彻底修改 if __name__ == "__main__" 部分
if __name__ == "__main__":
    # 如果 RENDER_EXTERNAL_URL 存在，说明是在 Render 环境
    # 否则，是在本地开发
    if RENDER_EXTERNAL_URL:
        # 在 Render 上，我们期望由 uvicorn 从 Procfile 启动
        # 这部分代码理论上不应该被执行，但作为一个保险
        logger.info("在生产环境检测到直接运行，将使用 Uvicorn 启动。")
        port = int(environ.get("PORT", 8000))
        uvicorn.run(fastapi_app, host="0.0.0.0", port=port)
    else:
        # 在本地开发，我们使用 polling 模式
        logger.info("未检测到 RENDER_EXTERNAL_URL，以轮询模式在本地启动机器人...")
        
        # 创建一个新的 Application 实例用于轮询
        local_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

        # 注册所有处理器 (与 lifespan 中相同)
        local_app.add_handler(CommandHandler("start", start_command))
        local_app.add_handler(CommandHandler("help", start_command))
        local_app.add_handler(CommandHandler("myfavorites", lambda u, c: my_favorites_list(u, c, 1)))
        local_app.add_handler(CommandHandler("erase_my_data", request_data_erasure))
        local_app.add_handler(CommandHandler("cancel", cancel_command, filters=filters.ChatType.PRIVATE))
        local_app.add_handler(CommandHandler("godmode", god_mode_command, filters=filters.ChatType.PRIVATE))
        local_app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, process_admin_input))
        local_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))
        local_app.add_handler(CallbackQueryHandler(button_callback_handler))

        # 在运行前初始化数据库
        import asyncio
        asyncio.run(init_db())
        
        # 启动轮询
        local_app.run_polling(allowed_updates=Update.ALL_TYPES)
