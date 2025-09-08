import os
import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

MENU_BUTTONS = {
    "leaderboard": "📊 排行榜",
    "favorites": "⭐ 我的收藏",
    "report": "📋 我的报告",
    "help": "❓ 帮助",
    "admin": "🔧 管理面板"
}

async def show_private_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = [
        [KeyboardButton(MENU_BUTTONS["leaderboard"]), KeyboardButton(MENU_BUTTONS["favorites"])],
        [KeyboardButton(MENU_BUTTONS["report"]), KeyboardButton(MENU_BUTTONS["help"])]
    ]
    if user_id == ADMIN_USER_ID:
        keyboard.append([KeyboardButton(MENU_BUTTONS["admin"])])
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    if update.message:
        await update.message.reply_text("请选择操作：", reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text("请选择操作：", reply_markup=markup)

async def private_menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    try:
        if text == MENU_BUTTONS["leaderboard"]:
            from bot_handlers.leaderboard import show_leaderboard
            await show_leaderboard(update, context)
        elif text == MENU_BUTTONS["favorites"]:
            from bot_handlers.favorites import show_my_favorites
            await show_my_favorites(update, context)
        elif text == MENU_BUTTONS["report"]:
            from bot_handlers.report import generate_my_report
            await generate_my_report(update, context)
        elif text == MENU_BUTTONS["help"]:
            await show_help(update, context)
        elif text == MENU_BUTTONS["admin"] and uid == ADMIN_USER_ID:
            from bot_handlers.admin import admin_panel
            await admin_panel(update, context)
    except Exception as e:
        logger.error(f"Menu error: {e}", exc_info=True)
        await update.message.reply_text("❌ 处理失败，请稍后再试。")

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ 帮助：\n"
        "• 群 / 私聊发送 @用户名 => 查询并评价\n"
        "• 点 👍/👎 进入多标签选择，勾选后点 完成\n"
        "• 同一评价者对同一用户只有一条记录，重复会覆盖情感并追加标签\n"
        "• ⭐ 收藏 / 📊 排行榜 / 📋 我的报告\n"
        "• 管理员：🔧 面板\n"
    )
    await update.message.reply_text(help_text)
