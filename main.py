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
from handlers.leaderboard import show_leaderboard
from handlers.admin import set_admin, list_tags, add_tag, remove_tag
from handlers.favorites import my_favorites, handle_favorite_button

# ... (日志和环境变量设置) ...
load_dotenv()
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
TOKEN = environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(environ.get("PORT", "10000"))
RENDER_URL = environ.get("RENDER_EXTERNAL_URL")
WEBHOOK_URL = f"{RENDER_URL}/{TOKEN}" if RENDER_URL else None
CREATOR_ID = environ.get("CREATOR_ID")

# ... (grant_creator_admin_privileges) ...
async def grant_creator_admin_privileges(app: Application):
    if not CREATOR_ID: return
    try:
        creator_id = int(CREATOR_ID)
        async with db_cursor() as cur:
            await cur.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", creator_id)
        logging.info(f"✅ 创世神 {creator_id} 已被自动授予管理员权限。")
    except Exception as e:
        logging.error(f"❌ 授予创世神权限时发生错误: {e}", exc_info=True)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button: bool = False):
    """
    处理 /help 命令和“返回主菜单”按钮。
    核心改造：为管理员和普通用户显示不同的内容。
    """
    is_admin_user = False
    try:
        async with db_cursor() as cur:
            user_data = await cur.fetchrow("SELECT is_admin FROM users WHERE id = $1", update.effective_user.id)
            if user_data: is_admin_user = user_data['is_admin']
    except Exception as e:
        logging.error(f"查询用户权限时出错: {e}")

    text = "你好！我是万物信誉机器人。\n\n**使用方法:**\n1. 直接在群里发送 `查询 @任意符号` 来查看或评价一个符号。\n2. 使用下方的按钮来浏览排行榜或你的个人收藏。"
    
    if is_admin_user:
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
    
    reply_markup = InlineKeyboardMarkup(keyboard)

    if from_button or (update.callback_query and update.callback_query.data == 'back_to_help'):
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_cursor() as cur:
        await cur.execute("INSERT INTO users (id) VALUES ($1) ON CONFLICT DO NOTHING", update.effective_user.id)
    await help_command(update, context)

async def all_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action = data[0]
    
    try:
        if action == "show":
            if data[1] == "leaderboard":
                await show_leaderboard(update, context, board_type=data[2], page=int(data[3]))
            elif data[1] == "my":
                await my_favorites(update, context)
        elif action == "leaderboard":
            if data[1] == "noop": return
            await show_leaderboard(update, context, board_type=data[1], page=int(data[2]))
        elif action in ["query", "fav"]:
            await handle_favorite_button(update, context)
        elif action == "back" and data[1] == "to":
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
            logging.warning(f"收到未知的按钮回调数据: {query.data}")
    except Exception as e:
        logging.error(f"处理按钮回调 {query.data} 时发生错误: {e}", exc_info=True)

# ... (PTB App, Lifespan, Main) ...
ptb_app = Application.builder().token(TOKEN).post_init(grant_creator_admin_privileges).build()
ptb_app.add_handler(MessageHandler(filters.Regex("^查询"), handle_nomination))
ptb_app.add_handler(CommandHandler("start", start_command))
ptb_app.add_handler(CommandHandler("help", help_command))
# 保留旧的命令作为快捷方式
ptb_app.add_handler(CommandHandler("top", lambda u, c: show_leaderboard(u, c, 'top', 1)))
ptb_app.add_handler(CommandHandler("bottom", lambda u, c: show_leaderboard(u, c, 'bottom', 1)))
ptb_app.add_handler(CommandHandler("myfavorites", my_favorites))
# 管理员命令
ptb_app.add_handler(CommandHandler("setadmin", set_admin))
ptb_app.add_handler(CommandHandler("listtags", list_tags))
ptb_app.add_handler(CommandHandler("addtag", add_tag))
ptb_app.add_handler(CommandHandler("removetag", remove_tag))
ptb_app.add_handler(CallbackQueryHandler(all_button_handler))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ...
    pass
def main():
    # ...
    pass
if __name__ == "__main__":
    # ...
    pass
