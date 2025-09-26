from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, CallbackQueryHandler, ContextTypes
from utils import is_admin

def main_menu_markup(page=1):
    if page == 1:
        keyboard = [
            [InlineKeyboardButton("🎁 抽奖", callback_data="menu_lottery"),
             InlineKeyboardButton("🔗 邀请链接", callback_data="menu_invite")],
            [InlineKeyboardButton("🐲 接龙", callback_data="menu_dragon"),
             InlineKeyboardButton("📊 统计", callback_data="menu_stats")],
            [InlineKeyboardButton("💬 自动回复", callback_data="menu_autoreply"),
             InlineKeyboardButton("⏰ 定时消息", callback_data="menu_schedule")],
            [InlineKeyboardButton("🛡️ 验证", callback_data="menu_verify"),
             InlineKeyboardButton("👋 进群欢迎", callback_data="menu_welcome")],
            [InlineKeyboardButton("🗑️ 反垃圾", callback_data="menu_antispam"),
             InlineKeyboardButton("🔄 反刷屏", callback_data="menu_antiflood")],
            [InlineKeyboardButton("🚫 违禁词", callback_data="menu_banword"),
             InlineKeyboardButton("🔍 检查", callback_data="menu_check")],
            [InlineKeyboardButton("💎 积分", callback_data="menu_point"),
             InlineKeyboardButton("🧑‍🦱 新成员限制", callback_data="menu_newlimit")],
            [InlineKeyboardButton("📅 打卡系统", callback_data="menu_checkin")],
            [InlineKeyboardButton("➡️ 下一页", callback_data="main_menu_2")],
            [InlineKeyboardButton("🔄 切换群", callback_data="menu_switch"),
             InlineKeyboardButton("🇨🇳 Language", callback_data="menu_lang")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("⬅️ 上一页", callback_data="main_menu_1")],
            [InlineKeyboardButton("🔄 切换群", callback_data="menu_switch"),
             InlineKeyboardButton("🇨🇳 Language", callback_data="menu_lang")]
        ]
    return InlineKeyboardMarkup(keyboard)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not await is_admin(user_id, chat_id):
        # 非管理员提示
        if hasattr(update, "message") and update.message:
            await update.message.reply_text("⚠️ 只有管理员才能使用本菜单。")
        elif hasattr(update, "callback_query") and update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text("⚠️ 只有管理员才能使用本菜单。")
        return

    group_title = update.effective_chat.title if update.effective_chat else "本群"
    txt = f"设置【<b>{group_title}</b>】群组，选择要更改的项目"
    page = 1
    if hasattr(update, "callback_query") and update.callback_query:
        cb = update.callback_query
        await cb.answer()
        if cb.data == "main_menu_2":
            page = 2
        elif cb.data == "main_menu_1":
            page = 1
        await cb.edit_message_text(txt, reply_markup=main_menu_markup(page), parse_mode='HTML')
    else:
        await update.message.reply_text(txt, reply_markup=main_menu_markup(page), parse_mode='HTML')

async def handle_menu_checkin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "📅 <b>打卡系统</b>\n\n"
        "• 会员每日可通过发送“打卡”完成签到。\n"
        "• /today_checkins 查看今日已打卡名单。\n"
        "• 发送地区名可查该地区今日打卡情况。\n"
        "• 管理员可在会员管理菜单查看更多打卡统计。"
    )
    if hasattr(update, "callback_query") and update.callback_query:
        cb = update.callback_query
        await cb.answer()
        await cb.edit_message_text(txt, parse_mode='HTML')
    else:
        await update.message.reply_text(txt, parse_mode='HTML')

def register(application):
    application.add_handler(CommandHandler("start", show_main_menu))
    application.add_handler(CommandHandler("menu", show_main_menu))
    application.add_handler(CommandHandler("help", show_main_menu))
    application.add_handler(CallbackQueryHandler(show_main_menu, pattern="^main_menu_[12]$"))
    application.add_handler(CallbackQueryHandler(handle_menu_checkin, pattern="^menu_checkin$"))
