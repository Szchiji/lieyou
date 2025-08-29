import logging
import uvicorn
from os import environ
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from fastapi import FastAPI, Request, Response
from database import init_pool, create_tables, db_cursor
from handlers.reputation import handle_nomination
from handlers.leaderboard import get_top_board, get_bottom_board, show_leaderboard
from handlers.admin import set_admin, list_tags, add_tag, remove_tag
from handlers.favorites import my_favorites, handle_favorite_button

# ... (日志和环境变量设置保持不变) ...
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get("PORT", "10000"))
RENDER_URL = environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

# ... (grant_creator_admin_privileges 和 start 函数保持不变) ...
async def grant_creator_admin_privileges(app: Application):
    if not CREATOR_ID: return
    try:
        creator_id = int(CREATOR_ID)
        async with db_cursor() as cur:
            await cur.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", creator_id)
        logger.info(f"✅ 创世神 {creator_id} 已被自动授予管理员权限。")
    except Exception as e:
        logger.error(f"❌ 授予创世神权限时发生错误: {e}", exc_info=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_cursor() as cur:
        await cur.execute("INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", update.effective_user.id)
    # --- 核心改造：启动时也显示带按钮的帮助菜单 ---
    await help_command(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /help 命令，提供一个完全由按钮组成的、可交互的菜单。"""
    text = (
        "你好！我是万物信誉机器人。\n\n"
        "**使用方法:**\n"
        "1. 直接在群里发送 `查询 @任意符号` 来查看或评价一个符号。\n"
        "2. 使用下方的按钮来浏览排行榜或你的个人收藏。"
    )
    
    # --- 核心革命：将帮助菜单彻底改造为按钮面板 ---
    keyboard = [
        [InlineKeyboardButton("🏆 推荐榜 (/top)", callback_data="show_top_board")],
        [InlineKeyboardButton("☠️ 拉黑榜 (/bottom)", callback_data="show_bottom_board")],
        [InlineKeyboardButton("⭐ 我的收藏 (/myfavorites)", callback_data="show_my_favorites")]
    ]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一的按钮回调调度中心，现在也处理来自帮助菜单的请求。"""
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action_type = data[0]
    
    try:
        # --- 核心改造：处理来自新帮助菜单的按钮点击 ---
        if action_type == "show":
            if data[1] == "top":
                await show_leaderboard(update, context, board_type='top', page=1)
            elif data[1] == "bottom":
                await show_leaderboard(update, context, board_type='bottom', page=1)
            elif data[1] == "my":
                await my_favorites(update, context)
            return

        if action_type in ["vote", "tag"]:
            # 为了处理档案卡上的按钮，我们需要一个独立的处理器
            from handlers.reputation import button_handler as reputation_button_handler
            await reputation_button_handler(update, context)
        elif action_type == "leaderboard":
            if data[1] == "noop": return
            await show_leaderboard(update, context, board_type=data[1], page=int(data[2]))
        elif action_type in ["fav", "query"]:
            await handle_favorite_button(update, context)
        elif action_type == "back" and data[1] == "to" and data[2] == "favs":
            await my_favorites(update, context, from_button=True)
        else:
            logger.warning(f"收到未知的按钮回调数据: {query.data}")
    except Exception as e:
        logger.error(f"处理按钮回调 {query.data} 时发生错误: {e}", exc_info=True)

# ... (ptb_app 注册和 lifespan, main 等函数保持不变) ...
ptb_app = Application.builder().token(TOKEN).post_init(grant_creator_admin_privileges).build()
ptb_app.add_handler(MessageHandler(filters.Regex("^查询"), handle_nomination))
ptb_app.add_handler(CommandHandler(["start", "help"], help_command)) # start 和 help 现在都指向新的菜单
ptb_app.add_handler(CommandHandler("top", get_top_board))
ptb_app.add_handler(MessageHandler(filters.Regex("^/红榜$"), get_top_board))
ptb_app.add_handler(CommandHandler("bottom", get_bottom_board))
ptb_app.add_handler(MessageHandler(filters.Regex("^/黑榜$"), get_bottom_board))
ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
# 管理员命令保持不变
ptb_app.add_handler(CommandHandler("setadmin", set_admin))
ptb_app.add_handler(CommandHandler("listtags", list_tags))
ptb_app.add_handler(CommandHandler("addtag", add_tag))
ptb_app.add_handler(CommandHandler("removetag", remove_tag))
# 注册统一的按钮处理器
ptb_app.add_handler(CallbackQueryHandler(all_button_handler))

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 FastAPI 应用启动，正在初始化...")
    await init_pool()
    await create_tables()
    await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    async with ptb_app:
        await ptb_app.start()
        logger.info("✅ PTB 应用已在后台启动。")
        yield
        logger.info("🔌 FastAPI 应用关闭，正在停止 PTB...")
        await ptb_app.stop()

def main():
    fastapi_app = FastAPI(lifespan=lifespan)
    @fastapi_app.post(f"/{TOKEN}", include_in_schema=False)
    async def process_telegram_update(request: Request):
        try:
            update = Update.de_json(await request.json(), ptb_app.bot)
            await ptb_app.process_update(update)
            return Response(status_code=200)
        except Exception as e:
            logger.error(f"处理 Webhook 更新时发生严重错误: {e}", exc_info=True)
            return Response(status_code=500)
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    if not all([TOKEN, RENDER_URL]):
        logger.critical("❌ 致命错误: 环境变量 TELEGRAM_BOT_TOKEN 或 RENDER_EXTERNAL_URL 未设置。")
    else:
        main()
