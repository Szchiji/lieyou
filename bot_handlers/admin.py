import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
import database
from .menu import AVAILABLE_ACTIONS

logger = logging.getLogger(__name__)

# Conversation states
(
    TYPING_TAG_NAME, SELECTING_TAG_TYPE,
    TYPING_BUTTON_NAME, SELECTING_BUTTON_ACTION,
    TYPING_USERNAME_TO_HIDE, TYPING_USERNAME_TO_UNHIDE
) = range(6)


async def is_admin(user_id: int) -> bool:
    """Check if a user is an admin."""
    is_admin_flag = await database.db_fetch_val("SELECT is_admin FROM users WHERE id = $1", user_id)
    return is_admin_flag is True

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the main admin panel."""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        if update.callback_query:
            await update.callback_query.answer("您没有权限。", show_alert=True)
        else:
            await update.message.reply_text("您没有权限访问此功能。")
        return

    text = "⚙️ **管理员面板**"
    keyboard = [
        [InlineKeyboardButton("管理标签", callback_data="admin_manage_tags")],
        [InlineKeyboardButton("管理菜单按钮", callback_data="admin_menu_buttons")],
        [InlineKeyboardButton("用户管理", callback_data="admin_user_management")],
        [InlineKeyboardButton("发送广播", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="show_private_main_menu")],
    ]
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return 0

# --- Tag Management ---

async def manage_tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows tag management options."""
    query = update.callback_query
    await query.answer()
    tags = await database.db_fetch_all("SELECT pkid, name, type, is_active FROM tags ORDER BY type, name")
    
    text = "🏷️ **管理标签**\n\n"
    if not tags:
        text += "还没有任何标签。"
    else:
        for tag in tags:
            status = "✅" if tag['is_active'] else "❌"
            text += f"`{tag['name']}` ({tag['type']}) {status} [ /del_{tag['pkid']} ]\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加新标签", callback_data="admin_add_tag_prompt")],
        [InlineKeyboardButton("🔙 返回管理员面板", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return 0

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts admin to enter a new tag name."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("请输入新标签的名称 (例如 '诚信交易'):")
    return TYPING_TAG_NAME

async def handle_new_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives the new tag name and asks for its type."""
    context.user_data['new_tag_name'] = update.message.text
    keyboard = [
        [
            InlineKeyboardButton("👍 推荐 (Recommend)", callback_data="tag_type_recommend"),
            InlineKeyboardButton("👎 警告 (Warn)", callback_data="tag_type_warn"),
        ],
        [InlineKeyboardButton("取消", callback_data="cancel")]
    ]
    await update.message.reply_text("请选择这个标签的类型:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING_TAG_TYPE

async def handle_tag_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Saves the new tag to the database."""
    query = update.callback_query
    tag_type = query.data.split('_')[2]
    tag_name = context.user_data.get('new_tag_name')

    if not tag_name:
        await query.edit_message_text("发生错误，请重试。")
        return ConversationHandler.END

    try:
        await database.db_execute(
            "INSERT INTO tags (name, type) VALUES ($1, $2)",
            tag_name, tag_type
        )
        await query.edit_message_text(f"✅ 标签 '{tag_name}' ({tag_type}) 已成功添加！")
    except Exception as e:
        logger.error(f"Error adding new tag: {e}")
        await query.edit_message_text(f"添加失败，可能是标签已存在。")
    
    context.user_data.clear()
    await admin_panel(update, context) # Show admin panel again
    return ConversationHandler.END

async def delete_tag_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes a tag."""
    query = update.callback_query
    tag_pkid = int(query.data.split('_')[-1])
    try:
        await database.db_execute("DELETE FROM tags WHERE pkid = $1", tag_pkid)
        await query.answer("🗑️ 标签已删除")
    except Exception as e:
        logger.error(f"Error deleting tag: {e}")
        await query.answer("删除失败", show_alert=True)
    
    await manage_tags_panel(update, context) # Refresh panel
    return 0

# --- Menu Button Management ---

async def manage_menu_buttons_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    buttons = await database.db_fetch_all("SELECT * FROM menu_buttons ORDER BY sort_order ASC, name ASC")
    
    text = "🎛️ **管理菜单按钮**\n"
    if buttons:
        for i, btn in enumerate(buttons):
            status = "✅" if btn['is_active'] else "❌"
            text += f"{btn['sort_order']}. {btn['name']} -> `{btn['action_id']}` {status}\n"
    else:
        text += "没有自定义按钮。"

    keyboard = [
        [InlineKeyboardButton("➕ 添加新按钮", callback_data="admin_add_menu_button_prompt")],
        [InlineKeyboardButton("🔙 返回管理员面板", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return 0

async def add_menu_button_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("请输入新按钮的显示文本 (例如 '查看排行榜'):")
    return TYPING_BUTTON_NAME

async def handle_new_menu_button_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_button_name'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton(f"'{action}'", callback_data=f"action_{action}")]
        for action in AVAILABLE_ACTIONS.keys()
    ]
    keyboard.append([InlineKeyboardButton("取消", callback_data="cancel")])
    
    await update.message.reply_text("请为这个按钮选择一个要执行的动作:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING_BUTTON_ACTION

async def handle_new_menu_button_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action_id = query.data.split('_', 1)[1]
    button_name = context.user_data.get('new_button_name')

    if not button_name:
        await query.edit_message_text("发生错误，请重试。")
        return ConversationHandler.END

    try:
        await database.db_execute(
            "INSERT INTO menu_buttons (name, action_id) VALUES ($1, $2)",
            button_name, action_id
        )
        await query.edit_message_text(f"✅ 按钮 '{button_name}' 已成功添加！")
    except Exception as e:
        logger.error(f"Error adding new menu button: {e}")
        await query.edit_message_text("添加失败。")
        
    context.user_data.clear()
    await admin_panel(update, context)
    return ConversationHandler.END

# Dummy functions for callbacks defined in main.py but not implemented
async def reorder_menu_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("此功能尚未实现", show_alert=True)
    return 0
async def toggle_menu_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("此功能尚未实现", show_alert=True)
    return 0
async def delete_menu_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("此功能尚未实现", show_alert=True)
    return 0

# --- User Management ---
async def user_management_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "👤 **用户管理**\n选择一个操作:"
    keyboard = [
        [InlineKeyboardButton("🙈 隐藏用户", callback_data="admin_hide_user_prompt")],
        [InlineKeyboardButton("🙉 取消隐藏用户", callback_data="admin_unhide_user_prompt")],
        [InlineKeyboardButton("🔙 返回管理员面板", callback_data="admin_panel")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return 0

async def prompt_for_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split('_')[1]
    
    if action == "hide":
        await query.edit_message_text("请输入要隐藏的用户的 @username:")
        return TYPING_USERNAME_TO_HIDE
    elif action == "unhide":
        await query.edit_message_text("请输入要取消隐藏的用户的 @username:")
        return TYPING_USERNAME_TO_UNHIDE

async def set_user_hidden_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.lstrip('@')
    current_state = context.user_data.get('current_state') # This should be set by ConversationHandler

    # A bit of a hack to know if we are hiding or unhiding
    is_hiding = context.user_data.get('hide_action', True) 
    
    res = await database.db_execute(
        "UPDATE users SET is_hidden = $1 WHERE username = $2",
        is_hiding, username
    )
    
    if '1' in res:
        action_text = "隐藏" if is_hiding else "取消隐藏"
        await update.message.reply_text(f"✅ 用户 @{username} 已成功{action_text}。")
    else:
        await update.message.reply_text(f"⚠️ 找不到用户 @{username}。")
        
    await admin_panel(update, context)
    return ConversationHandler.END
