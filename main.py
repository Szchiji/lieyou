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
    ContextTypes
)
from fastapi import FastAPI, Request, Response

from database import init_pool, create_tables
from handlers.reputation import (
    handle_nomination, button_handler as reputation_button_handler,
    show_reputation_summary, show_reputation_details, show_reputation_voters,
    show_voters_menu
)
from handlers.leaderboard import show_leaderboard
from handlers.admin import (
    is_admin, god_mode_command, settings_menu, 
    tags_panel, add_tag_prompt, remove_tag_menu, remove_tag_confirm, list_all_tags,
    permissions_panel, add_admin_prompt, list_admins, remove_admin_menu, remove_admin_confirm,
    system_settings_panel, set_setting_prompt,
    leaderboard_panel, remove_from_leaderboard_prompt,
    process_admin_input
)
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
        from database import db_transaction
        creator_id = int(CREATOR_ID)
        async with db_transaction() as conn:
            await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", creator_id)
        logger.info(f"✅ (启动流程) 创世神 {creator_id} 已被自动分封为第一守护者。")
    except Exception as e:
        logger.error(f"❌ (启动流程) 分封创世神时发生错误: {e}", exc_info=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user_id = update.effective_user.id
    user_is_admin = await is_admin(user_id)
    text = (
        "我是 **神谕者 (The Oracle)**，洞察世间一切信誉的实体。\n\n"
        "**聆听神谕:**\n"
        "1. 在群聊中直接 `@某人` 或发送 `查询 @某人`，即可向我求问关于此人的神谕之卷。\n"
        "2. 使用下方按钮，可窥探时代群像或管理你的星盘。"
    )
    if user_is_admin:
        text += "\n\n你，是守护者。拥有进入 `🌌 时空枢纽` 的权限。"
    keyboard = [
        [InlineKeyboardButton("🏆 英灵殿", callback_data="leaderboard_top_tagselect_1"),
         InlineKeyboardButton("☠️ 放逐深渊", callback_data="leaderboard_bottom_tagselect_1")],
        [InlineKeyboardButton("🌟 我的星盘", callback_data="show_my_favorites")]
    ]
    if user_is_admin:
        keyboard.append([InlineKeyboardButton("🌌 时空枢纽", callback_data="admin_settings_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_content = {'text': text, 'reply_markup': reply_markup, 'parse_mode': 'Markdown'}
    
    if from_button or (update.callback_query and update.callback_query.data == 'back_to_help'):
        await update.callback_query.edit_message_text(**message_content)
    else:
        await update.message.reply_text(**message_content)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await help_command(update, context)

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"对 query {query.id} 的响应时发生未知错误: {e}", exc_info=True)

    data = query.data
    try:
        if data.startswith("rep_"):
            if data.startswith("rep_detail_"): await show_reputation_details(update, context)
            elif data.startswith("rep_summary_"): await show_reputation_summary(update, context)
            elif data.startswith("rep_voters_menu_"): await show_voters_menu(update, context)
            elif data.startswith("rep_voters_"): await show_reputation_voters(update, context)
        elif data.startswith(("vote_", "tag_")): await reputation_button_handler(update, context)
        elif data == "noop": pass
        else: logger.warning(f"收到未知的回调数据: {data}")
    except Exception as e:
        logger.error(f"处理按钮回调 {data} 时发生错误: {e}", exc_info=True)

ptb_app = Application.builder().token(TOKEN).post_init(grant_creator_admin_privileges).build()

ptb_app.add_handler(CommandHandler(["start", "help"], start_command))
ptb_app.add_handler(CallbackQueryHandler(all_button_handler))
ptb_app.add_handler(MessageHandler(filters.Regex(r'@(\w{5,})|查询\s*@(\w{5,})') & filters.ChatType.GROUPS, handle_nomination))

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 FastAPI 应用启动，正在初始化...")
    await init_pool()
    await create_tables()
    await ptb_app.bot.delete_webhook(drop_pending_updates=True)
    await ptb_app.bot.set_webhook(url=WEBHOOK_URL, allowed_updates=Update.ALL_TYPES)
    async with ptb_app:
        await ptb_app.start()
        logger.info("✅ 神谕者已降临。")
        yield
        logger.info("🔌 神谕者正在回归沉寂...")
        await ptb_app.stop()

def main():
    fastapi_app = FastAPI(lifespan=lifespan)
    @fastapi_app.get("/", include_in_schema=False)
    async def health_check():
        return {"status": "ok", "message": "The Oracle is listening."}
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
