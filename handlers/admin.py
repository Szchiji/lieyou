import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction

logger = logging.getLogger(__name__)

async def is_admin(user_id: int) -> bool:
    """Checks if a user is an admin."""
    async with db_transaction() as conn:
        user_data = await conn.fetchrow("SELECT is_admin FROM users WHERE id = $1", user_id)
        return user_data and user_data['is_admin']

# --- “神权进化”核心：全新的可视化“创世神面板” ---
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Displays the new, interactive admin panel. Replaces the old /settings command.
    This is the central hub for all admin actions.
    """
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        # 理论上，普通用户看不到这个按钮，但这是一个安全保障
        await update.callback_query.answer("抱歉，你没有权限访问此功能。", show_alert=True)
        return

    text = "👑 **创世神面板** 👑\n\n请选择您要管理的领域："
    
    keyboard = [
        [InlineKeyboardButton("🛂 权限管理", callback_data="admin_panel_permissions")],
        [InlineKeyboardButton("🏷️ 标签管理", callback_data="admin_panel_tags")],
        [InlineKeyboardButton("⚙️ 系统设置", callback_data="admin_panel_system")],
        [InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 必须用 edit_message_text，因为这是从按钮回调触发的
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


# --- 以下是旧有的、我们将在后续步骤中继续改造的函数占位符 ---
# (我们暂时保留它们，以确保机器人不会报错)

async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("抱歉，你没有权限访问此功能。")
        return
    # ... (原有逻辑)
    await update.message.reply_text("权限管理功能正在升级为可视化面板...")

async def list_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("抱歉，你没有权限访问此功能。")
        return
    # ... (原有逻辑)
    await update.message.reply_text("标签管理功能正在升级为可视化面板...")

async def add_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("抱歉，你没有权限访问此功能。")
        return
    # ... (原有逻辑)
    await update.message.reply_text("标签管理功能正在升级为可视化面板...")

async def remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("抱歉，你没有权限访问此功能。")
        return
    # ... (原有逻辑)
    await update.message.reply_text("标签管理功能正在升级为可视化面板...")

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_type: str):
    if not await is_admin(update.effective_user.id):
        await update.callback_query.answer("抱歉，你没有权限访问此功能。", show_alert=True)
        return
    # ... (原有逻辑)
    await update.callback_query.message.reply_text("系统设置功能正在升级为可视化面板...")


async def process_setting_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("抱歉，你没有权限访问此功能。")
        return
    # ... (原有逻辑)
    await update.message.reply_text("系统设置功能正在升级为可视化面板...")
