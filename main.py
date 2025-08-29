import logging
import uvicorn
from os import environ
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from fastapi import FastAPI

# (导入部分保持不变)
from database import init_pool, create_tables
from handlers.reputation import handle_nomination, button_handler as reputation_button_handler
from handlers.leaderboard import get_top_board, get_bottom_board, show_leaderboard
from handlers.admin import set_admin, list_tags, add_tag, remove_tag
from handlers.favorites import my_favorites, handle_favorite_button

# (日志和环境变量设置保持不变)
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get("PORT", "10000"))
WEBHOOK_URL = f"{environ.get('RENDER_EXTERNAL_URL')}/{TOKEN}" if environ.get('RENDER_EXTERNAL_URL') else None
CREATOR_ID = environ.get("CREATOR_ID")

# --- 核心业务逻辑 ---
# (grant_creator_admin_privileges, start, help_command 保持不变)
async def grant_creator_admin_privileges(app: Application):
    if not CREATOR_ID: return
    try:
        await app.bot.get_me() # 确保bot已连接
        async with create_tables(): # 确保表已创建
            # ... 您的管理员授权逻辑
            pass
    except Exception as e:
        logger.error(f"授予创世神权限时出错: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好！我是万物信誉机器人。使用 /help 查看所有命令。")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... 您的帮助命令逻辑
    pass

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """统一的按钮回调调度中心。"""
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action_type = data[0]
    try:
        if action_type in ["vote", "tag"]:
            await reputation_button_handler(update, context)
        elif action_type == "leaderboard":
            if data[1] == "noop": return
            await show_leaderboard(update, context, board_type=data[1], page=int(data[2]))
        elif action_type in ["fav", "query"]:
            await handle_favorite_button(update, context)
        # --- 核心改造：处理“返回”按钮 ---
        elif action_type == "back" and data[1] == "to" and data[2] == "favs":
            await my_favorites(update, context, from_button=True)
        else:
            logger.warning(f"收到未知的按钮回调数据: {query.data}")
    except Exception as e:
        logger.error(f"处理按钮回调 {query.data} 时发生错误: {e}", exc_info=True)

# --- 最终的、绝对稳定的 PTB + FastAPI 集成 ---
ptb_app = Application.builder().token(TOKEN).build()

# (注册处理器部分保持不变)
ptb_app.add_handler(MessageHandler(filters.Regex("^查询"), handle_nomination))
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("help", help_command))
ptb_app.add_handler(CommandHandler("top", get_top_board))
ptb_app.add_handler(MessageHandler(filters.Regex("^/红榜$"), get_top_board))
ptb_app.add_handler(CommandHandler("bottom", get_bottom_board))
ptb_app.add_handler(MessageHandler(filters.Regex("^/黑榜$"), get_bottom_board))
ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
ptb_app.add_handler(CommandHandler("setadmin", set_admin))
ptb_app.add_handler(CommandHandler("listtags", list_tags))
ptb_app.add_handler(CommandHandler("addtag", add_tag))
ptb_app.add_handler(CommandHandler("removetag", remove_tag))
ptb_app.add_handler(CallbackQueryHandler(all_button_handler))

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    await create_tables()
    await grant_creator_admin_privileges(ptb_app)
    await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
    async with ptb_app:
        await ptb_app.start()
        yield
        await ptb_app.stop()

fastapi_app = FastAPI(lifespan=lifespan)

@fastapi_app.post(f"/{TOKEN}")
async def process_telegram_update(update: dict):
    await ptb_app.update_queue.put(Update.de_json(update, ptb_app.bot))
    return {"ok": True}

def main():
    if not all([TOKEN, WEBHOOK_URL]):
        logger.critical("❌ 致命错误: 环境变量 TELEGRAM_BOT_TOKEN 或 RENDER_EXTERNAL_URL 未设置。")
        return
    uvicorn.run(fastapi_app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
