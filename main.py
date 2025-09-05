import logging
import re
from os import environ
from contextlib import asynccontextmanager
import uvicorn

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, JobQueue
)
from telegram.constants import ParseMode

# --- 日志配置 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info("程序开始启动...")

# --- 加载环境变量 ---
load_dotenv()
logger.info(".env 文件已加载 (如果存在)。")
TELEGRAM_BOT_TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}/webhook"

if not TELEGRAM_BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN 环境变量未设置！")
    exit()
logger.info("TELEGRAM_BOT_TOKEN 已加载。")
if not RENDER_EXTERNAL_URL:
    logger.warning("RENDER_EXTERNAL_URL 环境变量未设置，将使用轮询模式。")
else:
    logger.info(f"RENDER_EXTERNAL_URL 已加载: {RENDER_EXTERNAL_URL}")

# --- 导入所有 Handlers ---
try:
    from database import init_db, get_setting, is_admin
    from handlers.reputation import handle_query, send_reputation_card, vote_menu, process_vote, back_to_rep_card
    from handlers.favorites import add_favorite, remove_favorite, my_favorites
    from handlers.stats import user_stats_menu
    from handlers.erasure import request_data_erasure, confirm_data_erasure, cancel_data_erasure
    from handlers.admin import (
        god_mode_command, process_admin_input, settings_menu,
        tags_panel, add_tag_prompt, list_all_tags, remove_tag_menu, remove_tag_confirm, execute_tag_deletion,
        permissions_panel, add_admin_prompt, list_admins, remove_admin_menu, remove_admin_confirm, execute_admin_removal,
        system_settings_panel, set_start_message_prompt, show_all_commands,
        leaderboard_panel
    )
    # 导入排行榜相关
    from handlers.leaderboard import show_leaderboard_menu, get_leaderboard_page, clear_leaderboard_cache

    logger.info("所有 handlers 和 database 模块已成功导入。")
except ImportError as e:
    logger.critical(f"模块导入失败: {e}", exc_info=True)
    exit()

# --- 主命令处理 ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示主菜单"""
    user = update.effective_user
    message = update.effective_message or update.callback_query.message
    
    start_message = await get_setting("start_message", "欢迎使用神谕者机器人！")
    
    keyboard = [
        [InlineKeyboardButton("❤️ 我的收藏", callback_data="my_favorites_1")],
        [InlineKeyboardButton("🏆 排行榜", callback_data="leaderboard_menu")],
        [InlineKeyboardButton("🗑️ 删除我的数据", callback_data="request_data_erasure")]
    ]
    
    if await is_admin(user.id):
        keyboard.append([InlineKeyboardButton("⚙️ 管理面板", callback_data="admin_settings_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await message.edit_text(start_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(start_message, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

# --- 按钮回调总路由 ---
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """解析所有回调查询并分发到对应的处理器"""
    query = update.callback_query
    await query.answer()
    data = query.data

    # 定义回调路由
    # --- 核心修正：使用正确的函数名和回调格式 ---
    routes = {
        r"^my_favorites_(\d+)$": (lambda p: my_favorites(update, context, int(p[0]))),
        r"^add_favorite_(\d+)_(.*)$": (lambda p: add_favorite(update, context, int(p[0]), p[1])),
        r"^remove_favorite_(\d+)_(.*)$": (lambda p: remove_favorite(update, context, int(p[0]), p[1])),
        
        r"^vote_recommend_(\d+)_(.*)$": (lambda p: vote_menu(update, context, int(p[0]), 'recommend', p[1])),
        r"^vote_block_(\d+)_(.*)$": (lambda p: vote_menu(update, context, int(p[0]), 'block', p[1])),
        r"^process_vote_(\d+)_(\d+)_(.*)$": (lambda p: process_vote(update, context, int(p[0]), int(p[1]), p[2])),
        r"^back_to_rep_card_(\d+)_(.*)$": (lambda p: back_to_rep_card(update, context, int(p[0]), p[1])),
        
        r"^stats_user_(\d+)_(\d+)_(.*)$": (lambda p: user_stats_menu(update, context, int(p[0]), int(p[1]), p[2])),
        
        r"^request_data_erasure$": (lambda p: request_data_erasure(update, context)),
        r"^confirm_data_erasure$": (lambda p: confirm_data_erasure(update, context)),
        r"^cancel_data_erasure$": (lambda p: cancel_data_erasure(update, context)),
        
        r"^admin_settings_menu$": (lambda p: settings_menu(update, context)),
        r"^admin_panel_tags$": (lambda p: tags_panel(update, context)),
        r"^admin_panel_permissions$": (lambda p: permissions_panel(update, context)),
        r"^admin_panel_system$": (lambda p: system_settings_panel(update, context)),
        r"^admin_leaderboard_panel$": (lambda p: leaderboard_panel(update, context)),
        
        r"^admin_tags_add_recommend_prompt$": (lambda p: add_tag_prompt(update, context, 'recommend')),
        r"^admin_tags_add_block_prompt$": (lambda p: add_tag_prompt(update, context, 'block')),
        r"^admin_tags_list$": (lambda p: list_all_tags(update, context)),
        r"^admin_tags_remove_menu_(\d+)$": (lambda p: remove_tag_menu(update, context, int(p[0]))),
        r"^admin_tags_remove_confirm_(\d+)_(\d+)$": (lambda p: remove_tag_confirm(update, context, int(p[0]), int(p[1]))),
        r"^admin_tag_delete_(\d+)$": (lambda p: execute_tag_deletion(update, context, int(p[0]))),

        r"^admin_perms_add_prompt$": (lambda p: add_admin_prompt(update, context)),
        r"^admin_perms_list$": (lambda p: list_admins(update, context)),
        r"^admin_perms_remove_menu_(\d+)$": (lambda p: remove_admin_menu(update, context, int(p[0]))),
        r"^admin_perms_remove_confirm_(\d+)_(\d+)$": (lambda p: remove_admin_confirm(update, context, int(p[0]), int(p[1]))),
        r"^admin_remove_admin_(\d+)$": (lambda p: execute_admin_removal(update, context, int(p[0]))),

        r"^admin_system_set_start_message$": (lambda p: set_start_message_prompt(update, context)),
        r"^admin_show_commands$": (lambda p: show_all_commands(update, context)),
        r"^admin_leaderboard_clear_cache$": (lambda p: clear_leaderboard_cache(update, context)),

        r"^leaderboard_menu$": (lambda p: show_leaderboard_menu(update, context)),
        r"^leaderboard_(\w+)_(\d+)$": (lambda p: get_leaderboard_page(update, context, p[0], int(p[1]))),
        
        r"^back_to_help$": (lambda p: start_command(update, context)),
    }

    for pattern, handler in routes.items():
        match = re.fullmatch(pattern, data)
        if match:
            try:
                await handler(match.groups())
                return
            except Exception as e:
                logger.error(f"处理回调 '{data}' 时发生异常: {e}", exc_info=True)
                return
    
    logger.warning(f"未找到回调 '{data}' 的处理器。")

# --- 错误处理 ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("捕获到未处理的异常:", exc_info=context.error)

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
    ptb_app.add_handler(CommandHandler("godmode", god_mode_command, filters=filters.ChatType.PRIVATE))
    ptb_app.add_handler(CommandHandler("cancel", lambda u,c: u.message.reply_text("操作已取消。") if 'waiting_for' in c.user_data and c.user_data.pop('waiting_for') else None, filters=filters.ChatType.PRIVATE))
    ptb_app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, process_admin_input))
    
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE), handle_query))
    ptb_app.add_handler(CallbackQueryHandler(button_callback_handler))
    logger.info("所有 Telegram 处理器已添加。")

    logger.info("正在初始化数据库...")
    try:
        await init_db()
    except Exception as e:
        logger.critical(f"数据库初始化失败: {e}", exc_info=True)
        raise

    if RENDER_EXTERNAL_URL:
        logger.info(f"正在设置 Webhook 到 {WEBHOOK_URL}...")
        await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
        logger.info("Webhook 设置成功。")
    
    async with ptb_app:
        await ptb_app.start()
        logger.info("PTB Application 已启动。")
        yield
        logger.info("FastAPI lifespan: 关闭中...")
        await ptb_app.stop()
        logger.info("PTB Application 已停止。")

# --- FastAPI 应用实例 ---
app = FastAPI(lifespan=lifespan)

@app.post("/webhook")
async def process_telegram_update(request: Request):
    """处理来自 Telegram 的 Webhook 请求"""
    if ptb_app:
        body = await request.json()
        update = Update.de_json(body, ptb_app.bot)
        await ptb_app.process_update(update)
    return Response(status_code=200)

@app.get("/")
def index():
    return {"status": "神谕者机器人正在运行..."}

# --- 本地开发时运行 ---
if __name__ == "__main__":
    if RENDER_EXTERNAL_URL:
        logger.warning("在本地运行时检测到 RENDER_EXTERNAL_URL，将尝试使用 Webhook。")
        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        logger.info("未检测到 RENDER_EXTERNAL_URL，将以轮询模式启动...")
        ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        ptb_app.add_error_handler(error_handler)
        
        # 添加处理器
        ptb_app.add_handler(CommandHandler("start", start_command))
        ptb_app.add_handler(CommandHandler("help", start_command))
        ptb_app.add_handler(CommandHandler("godmode", god_mode_command, filters=filters.ChatType.PRIVATE))
        ptb_app.add_handler(CommandHandler("cancel", lambda u, c: u.message.reply_text("操作已取消。") if 'waiting_for' in c.user_data and c.user_data.pop('waiting_for') else None, filters=filters.ChatType.PRIVATE))
        ptb_app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, process_admin_input))
        ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & (filters.UpdateType.MESSAGE | filters.UpdateType.EDITED_MESSAGE), handle_query))
        ptb_app.add_handler(CallbackQueryHandler(button_callback_handler))

        init_db_sync = uvicorn.run(init_db) # 本地运行时同步初始化
        
        logger.info("开始轮询...")
        ptb_app.run_polling()
