import logging
import re
from os import environ
from contextlib import asynccontextmanager
import uvicorn

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ApplicationBuilder
)
from telegram.constants import ParseMode

# --- 日志配置 ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

logger.info("程序开始启动...")

# --- 加载环境变量 ---
load_dotenv()
logger.info(".env 文件已加载 (如果存在)。")

TELEGRAM_BOT_TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = environ.get("RENDER_EXTERNAL_URL")

if not TELEGRAM_BOT_TOKEN:
    logger.critical("致命错误: 环境变量 TELEGRAM_BOT_TOKEN 未设置！")
    exit()
else:
    logger.info("TELEGRAM_BOT_TOKEN 已加载。")

if not RENDER_EXTERNAL_URL:
    logger.warning("警告: RENDER_EXTERNAL_URL 未设置。如果使用 webhook，机器人将无法接收更新。")
else:
    logger.info(f"RENDER_EXTERNAL_URL 已加载: {RENDER_EXTERNAL_URL}")

# --- 导入模块 ---
try:
    from database import init_db, get_pool, get_setting, get_or_create_user, is_admin
    from handlers.reputation import handle_query, vote_menu, process_vote, back_to_rep_card, send_reputation_card
    from handlers.leaderboard import leaderboard_menu, refresh_leaderboard, admin_clear_leaderboard_cache
    from handlers.favorites import add_favorite, remove_favorite, my_favorites_list
    from handlers.stats import user_stats_menu
    from handlers.erasure import request_data_erasure, confirm_data_erasure, cancel_data_erasure
    # 核心修正：从下面的列表中移除了不存在的 'set_setting_prompt'
    from handlers.admin import (
        god_mode_command, settings_menu, process_admin_input, tags_panel, permissions_panel, 
        system_settings_panel, leaderboard_panel, add_tag_prompt, remove_tag_menu, remove_tag_confirm, 
        execute_tag_deletion, list_all_tags, add_admin_prompt, list_admins, remove_admin_menu, 
        remove_admin_confirm, execute_admin_removal, set_start_message_prompt, 
        show_all_commands, selective_remove_menu, confirm_user_removal, execute_user_removal
    )
    logger.info("所有 handlers 和 database 模块已成功导入。")
except ImportError as e:
    logger.critical(f"模块导入失败: {e}", exc_info=True)
    exit()


# --- 错误处理器 ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("处理更新时发生异常", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="❌ 处理您的请求时发生了一个内部错误，管理员已收到通知。")
        except Exception as e:
            logger.error(f"无法向用户发送错误通知: {e}")

# --- 命令和回调处理器 (保持不变) ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message or update.callback_query.message
    await get_or_create_user(user_id=user.id, username=user.username, first_name=user.first_name)
    start_message = await get_setting('start_message', "欢迎使用神谕者机器人！")
    keyboard = [
        [InlineKeyboardButton("🏆 好评榜", callback_data="leaderboard_top_1"), InlineKeyboardButton("☠️ 差评榜", callback_data="leaderboard_bottom_1")],
        [InlineKeyboardButton("❤️ 我的收藏", callback_data="my_favorites_1")],
    ]
    if await is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ 管理面板", callback_data="admin_settings_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 修正 admin.py 中 process_admin_input 后带来的问题
    is_callback = hasattr(update, 'callback_query') and update.callback_query
    if is_callback:
        await message.edit_text(start_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(start_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    await get_or_create_user(user_id=query.from_user.id, username=query.from_user.username, first_name=query.from_user.first_name)
    
    simple_handlers = {
        "back_to_help": start_command, "admin_settings_menu": settings_menu, "admin_panel_tags": tags_panel,
        "admin_panel_permissions": permissions_panel, "admin_panel_system": system_settings_panel,
        "admin_leaderboard_panel": leaderboard_panel, "admin_leaderboard_clear_cache": admin_clear_leaderboard_cache,
        "admin_tags_list": list_all_tags, "admin_perms_list": list_admins, "admin_show_commands": show_all_commands,
        "admin_tags_add_recommend_prompt": lambda u, c: add_tag_prompt(u, c, 'recommend'),
        "admin_tags_add_block_prompt": lambda u, c: add_tag_prompt(u, c, 'block'),
        "admin_perms_add_prompt": add_admin_prompt, "admin_system_set_start_message": set_start_message_prompt,
        "confirm_data_erasure": confirm_data_erasure, "cancel_data_erasure": cancel_data_erasure,
    }
    if data in simple_handlers:
        await simple_handlers[data](update, context); return

    patterns = {
        r"leaderboard_(top|bottom)_(\d+)": lambda m: leaderboard_menu(update, context, m[0], int(m[1])),
        r"leaderboard_refresh_(top|bottom)_(\d+)": lambda m: refresh_leaderboard(update, context, m[0], int(m[1])),
        r"my_favorites_(\d+)": lambda m: my_favorites_list(update, context, int(m[0])),
        r"vote_(recommend|block)_(\d+)_(.*)": lambda m: vote_menu(update, context, int(m[1]), m[0], m[2] or ""),
        r"process_vote_(\d+)_(\d+)_(.*)": lambda m: process_vote(update, context, int(m[0]), int(m[1]), m[2] or ""),
        r"back_to_rep_card_(\d+)_(.*)": lambda m: back_to_rep_card(update, context, int(m[0]), m[1] or ""),
        r"rep_card_query_(\d+)_(.*)": lambda m: send_reputation_card(update, context, int(m[0]), m[1] or ""),
        r"add_favorite_(\d+)_(.*)": lambda m: add_favorite(update, context, int(m[0]), m[1] or ""),
        r"remove_favorite_(\d+)": lambda m: remove_favorite(update, context, int(m[0])),
        r"stats_user_(\d+)_(\d+)_(.*)": lambda m: user_stats_menu(update, context, int(m[0]), int(m[1]), m[2] or ""),
        r"admin_tags_remove_menu_(\d+)": lambda m: remove_tag_menu(update, context, int(m[0])),
        r"admin_tags_remove_confirm_(\d+)_(\d+)": lambda m: remove_tag_confirm(update, context, int(m[0]), int(m[1])),
        r"admin_tag_delete_(\d+)": lambda m: execute_tag_deletion(update, context, int(m[0])),
        r"admin_perms_remove_menu_(\d+)": lambda m: remove_admin_menu(update, context, int(m[0])),
        r"admin_perms_remove_confirm_(\d+)_(\d+)": lambda m: remove_admin_confirm(update, context, int(m[0]), int(m[1])),
        r"admin_remove_admin_(\d+)": lambda m: execute_admin_removal(update, context, int(m[0])),
    }
    
    for pattern, handler in patterns.items():
        match = re.fullmatch(pattern, data)
        if match:
            await handler(match.groups())
            return
            
    logger.warning(f"未找到处理器，或正则表达式不匹配。回调数据: '{data}'")

# --- FastAPI 生命周期 ---
ptb_app = None
@asynccontextmanager
async def lifespan(app: FastAPI):
    global ptb_app
    logger.info("FastAPI lifespan: 启动中...")
    
    logger.info("构建 Telegram Application...")
    ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    ptb_app.add_error_handler(error_handler)
    
    # 添加处理器
    ptb_app.add_handler(CommandHandler("start", start_command))
    ptb_app.add_handler(CommandHandler("help", start_command))
    ptb_app.add_handler(CommandHandler("myfavorites", my_favorites_list, filters=filters.ChatType.PRIVATE))
    ptb_app.add_handler(CommandHandler("erase_my_data", request_data_erasure, filters=filters.ChatType.PRIVATE))
    ptb_app.add_handler(CommandHandler("cancel", lambda u,c: u.message.reply_text("操作已取消。") if 'waiting_for' in c.user_data and c.user_data.pop('waiting_for') else None, filters=filters.ChatType.PRIVATE))
    ptb_app.add_handler(CommandHandler("godmode", god_mode_command, filters=filters.ChatType.PRIVATE))
    ptb_app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, process_admin_input))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_query))
    ptb_app.add_handler(CallbackQueryHandler(button_callback_handler))
    logger.info("所有 Telegram 处理器已添加。")

    try:
        logger.info("正在初始化数据库...")
        await init_db()
        logger.info("数据库初始化成功。")
    except Exception as e:
        logger.critical(f"数据库初始化失败: {e}", exc_info=True)
        # 在实际生产中，这里应该优雅地退出或重试
        raise

    if RENDER_EXTERNAL_URL:
        logger.info(f"正在设置 webhook 到: {RENDER_EXTERNAL_URL}/webhook")
        await ptb_app.bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/webhook", allowed_updates=Update.ALL_TYPES)
        logger.info("Webhook 设置成功。")

    await ptb_app.initialize()
    if hasattr(ptb_app, 'post_init'): await ptb_app.post_init(ptb_app)
    logger.info("PTB Application 初始化完成。")
    
    yield
    
    logger.info("FastAPI lifespan: 关闭中...")
    if hasattr(ptb_app, 'post_shutdown'): await ptb_app.post_shutdown(ptb_app)
    await ptb_app.shutdown()
    db_pool = await get_pool()
    if db_pool: await db_pool.close(); logger.info("数据库连接池已关闭。")
    logger.info("PTB Application 已关闭。")

# --- FastAPI 应用实例 ---
fastapi_app = FastAPI(lifespan=lifespan)
@fastapi_app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
        return Response(status_code=200)
    except Exception as e:
        logger.error(f"处理webhook时出错: {e}", exc_info=True)
        return Response(status_code=500)

@fastapi_app.get("/")
def index(): return {"status": "ok", "bot": "神谕者机器人正在运行"}

if __name__ == "__main__":
    port = int(environ.get("PORT", 8000))
    logger.info(f"服务将在 0.0.0.0:{port} 上启动。")
    uvicorn.run("main:fastapi_app", host="0.0.0.0", port=port, reload=False)
