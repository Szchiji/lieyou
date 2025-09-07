import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import get_or_create_user, is_admin
from .utils import membership_required

logger = logging.getLogger(__name__)

async def get_main_menu(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """根据用户是否为管理员生成主菜单。"""
    
    text = (
        "你好！我是猎优伴侣，一个基于社区共识的声誉查询机器人。\n\n"
        "**基本用法：**\n"
        "在群聊中发送 `@username 推荐` 或 `@username 警告` 即可开始对某人进行评价。\n\n"
        "请选择以下功能："
    )

    keyboard_buttons = [
        [InlineKeyboardButton("🏆 排行榜", callback_data="leaderboard_menu")],
        [InlineKeyboardButton("❤️ 我的收藏", callback_data="my_favorites_1")],
    ]

    # 如果用户是管理员，添加管理员面板按钮
    if await is_admin(user_id):
        keyboard_buttons.append([InlineKeyboardButton("⚙️ 管理员面板", callback_data="admin_panel")])
    
    return text, InlineKeyboardMarkup(keyboard_buttons)

@membership_required
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /start 命令，欢迎用户并显示主菜单。"""
    user = update.effective_user
    logger.info(f"用户 {user.id} (@{user.username}) 执行了 /start")

    try:
        # 尝试创建用户，确保用户在数据库中
        await get_or_create_user(user)
    except ValueError as e:
        # 如果用户没有用户名，则无法创建，发送提示
        await update.message.reply_text(f"❌ 欢迎！但在开始之前，请先为您的Telegram账户设置一个用户名。")
        return
    except Exception as e:
        logger.error(f"为用户 {user.id} 创建记录时出错: {e}")
        await update.message.reply_text("❌ 处理您的请求时发生了一个数据库错误。")
        return

    text, reply_markup = await get_main_menu(user.id)
    await update.message.reply_text(text, reply_markup=reply_markup)

@membership_required
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /help 命令和 'help' 回调，显示主菜单。"""
    user = update.effective_user
    text, reply_markup = await get_main_menu(user.id)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

@membership_required
async def back_to_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """作为回调处理函数，返回主菜单。"""
    await help_command(update, context)
