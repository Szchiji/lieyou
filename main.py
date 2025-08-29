import logging
import uvicorn
from os import environ
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from fastapi import FastAPI, Request, Response

from database import init_pool, create_tables, db_transaction
from handlers.reputation import handle_nomination
from handlers.leaderboard import show_leaderboard
from handlers.admin import set_admin, list_tags, add_tag, remove_tag, is_admin, settings_menu, set_setting_prompt, process_setting_input
from handlers.favorites import my_favorites, handle_favorite_button

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get("PORT", "10000"))
RENDER_URL = environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

async def grant_creator_admin_privileges(app: Application):
    if not CREATOR_ID: return
    try:
        creator_id = int(CREATOR_ID)
        async with db_transaction() as conn:
            # 确保创世神在 users 表中存在，然后再更新权限
            await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", creator_id)
        logger.info(f"✅ 创世神 {creator_id} 已被自动授予管理员权限。")
    except Exception as e:
        logger.error(f"❌ 授予创世神权限时发生错误: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    """
    处理 /help 命令和“返回主菜单”按钮。
    在检查权限前，确保用户已在数据库中注册。
    """
    user_id = update.effective_user.id
    
    # --- 核心黑洞修复：在检查权限之前，先为用户“登记在册”！ ---
    async with db_transaction() as conn:
        await conn.execute("INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
    
    # 现在，我们可以安全地检查权限了
    user_is_admin = await is_admin(user_id)
    
    text = "你好！我是万物信誉机器人。\n\n**使用方法:**\n1. 直接在群里发送 `查询 @任意符号` 来查看或评价一个符号。\n2. 使用下方的按钮来浏览排行榜或你的个人收藏。"
    
    if user_is_admin:
        text += (
            "\n\n--- *管理员面板* ---\n"
            "以下为文本命令，请直接发送:\n"
            "`/setadmin <user_id>`\n"
            "`/listtags`\n"
            "`/addtag <推荐|拉黑> <标签>`\n"
            "`/removetag <标签>`"
        )
    keyboard = [
        [InlineKeyboardButton("🏆 推荐榜", callback_data="show_leaderboard_top_1")],
        [InlineKeyboardButton("☠️ 拉黑榜", callback_data="show_leaderboard_bottom_1")],
        [InlineKeyboardButton("⭐ 我的收藏", callback_data="show_my_favorites")]
    ]
    if user_is_admin:
        keyboard.append([InlineKeyboardButton("⚙️ 世界设置", callback_data="admin_settings_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    if from_button or (update.callback_query and update.callback_query.data == 'back_to_help'):
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# --- start_command 保持不变 ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # help_command 现在已经包含了用户注册逻辑，所以这里可以简化
    await help_command(update, context)

# --- all_button_handler 保持不变 ---
async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action = data[0]
    try:
        if action == "admin":
            if data[1] == "settings" and data[2] == "menu":
                await settings_menu(update, context)
            elif data[1] == "set":
                await set_setting_prompt(update, context, setting_type=data[2])
        elif action == "show":
            if data[1] == "leaderboard":
                await show_leaderboard(update, context, board_type=data[2], page=int(data[3]))
            elif data[1] == "my":
                await my_favorites(update, context)
        elif action == "leaderboard":
            if data[1] == "noop": return
            await show_leaderboard(update, context, board_type=data[1], page=int(data[2]))
        elif action in ["query", "fav"]:
            await handle_favorite_button(update, context)
        elif action == "back":
            if data[1] == "to":
                if data[2] == "help":
                    await help_command(update, context, from_button=True)
                elif data[2] == "favs":
                    await my_favorites(update, context, from_button=True)
                elif data[2] == "leaderboard":
                    await show_leaderboard(update, context, board_type=data[3], page=int(data[4]))
        elif action in ["vote", "tag"]:
            from handlers.reputation import button_handler as reputation_button_handler
            await reputation_button_handler(update, context)
        else:
            logger.warning(f"收到未知的按钮回调数据: {query.data}")
    except Exception as e:
        logger.error(f"处理按钮回调 {query.data} 时发生错误: {e}", exc_info=True)

# --- PTB 应用设置 (保持不变) ---
ptb_app = Application.builder().token(TOKEN).post_init(grant_creator_admin_privileges).build()
ptb_app.add_handler(CommandHandler("start", start_command))
ptb_app.add_handler(CommandHandler("help", help_command))
ptb_app.add_handler(CommandHandler("settings", settings_menu))
ptb_app.add_handler(CommandHandler("top", lambda u, c: show_leaderboard(u, c, 'top', 1)))
ptb_app.add_handler(CommandHandler("bottom", lambda u, c: show_leaderboard(u, c, 'bottom', 1)))
ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
ptb_app.add_handler(CommandHandler("setadmin", set_admin))
ptb_app.add_handler(CommandHandler("listtags", list_tags))
ptb_app.add_handler(CommandHandler("addtag", add_tag))
ptb_app.add_handler(CommandHandler("removetag", remove_tag))
ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, process_setting_input), group=1)
ptb_app.add_handler(MessageHandler(filters.Regex("^查询"), handle_nomination), group=2)

# --- FastAPI 与 PTB 集成 (保持不变) ---
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
