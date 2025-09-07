import logging
import os
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
import database
from .menu import AVAILABLE_ACTIONS

logger = logging.getLogger(__name__)

# --- Conversation States ---
(
    TYPING_TAG_NAME, SELECTING_TAG_TYPE,
    TYPING_BUTTON_NAME, SELECTING_BUTTON_ACTION,
    TYPING_USERNAME_TO_HIDE, TYPING_USERNAME_TO_UNHIDE
) = range(6)

# --- Admin Check ---
async def check_admin(update: Update) -> bool:
    """Checks if the user is an admin."""
    user = update.effective_user
    is_admin = await database.db_fetch_val("SELECT is_admin FROM users WHERE id = $1", user.id)
    if not is_admin:
        if update.callback_query:
            await update.callback_query.answer("您没有权限执行此操作。", show_alert=True)
        else:
            await update.message.reply_text("您没有权限执行此操作。")
        return False
    return True

# --- Main Admin Panel ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main admin panel."""
    if not await check_admin(update): return
    
    keyboard = [
        [InlineKeyboardButton("✏️ 管理标签", callback_data="admin_manage_tags")],
        [InlineKeyboardButton("🔧 管理底部按钮", callback_data="admin_menu_buttons")],
        [InlineKeyboardButton("👤 用户管理", callback_data="admin_user_management")],
        [InlineKeyboardButton("📢 发送广播", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="show_private_main_menu")]
    ]
    
    text = "⚙️ **管理员面板**\n请选择要管理的项目："
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# --- Tag Management ---
async def manage_tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    query = update.callback_query
    await query.answer()
    
    tags = await database.db_fetch_all("SELECT pkid, name, type, is_active FROM tags ORDER BY type, name")
    
    text = "✏️ **标签管理**\n"
    keyboard = [[InlineKeyboardButton("➕ 添加新标签", callback_data="admin_add_tag_prompt")]]
    
    if tags:
        for tag in tags:
            status_icon = "✅" if tag['is_active'] else "❌"
            type_icon = "👍" if tag['type'] == 'recommend' else "👎"
            text += f"\n{type_icon} {tag['name']} ({'激活' if tag['is_active'] else '禁用'})"
            keyboard.append([InlineKeyboardButton(f"{status_icon} {tag['name']}", callback_data=f"admin_toggle_tag_{tag['pkid']}"),
                             InlineKeyboardButton("🗑️ 删除", callback_data=f"admin_delete_tag_{tag['pkid']}")])
    else:
        text += "\n暂无标签。"
        
    keyboard.append([InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin(update): return ConversationHandler.END
    await update.callback_query.message.reply_text("请输入新标签的名称（例如：靠谱/骗子）：\n\n发送 /cancel 可随时取消。")
    return TYPING_TAG_NAME

async def handle_new_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin(update): return ConversationHandler.END
    context.user_data['new_tag_name'] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("👍 推荐", callback_data="tag_type_recommend")],
        [InlineKeyboardButton("👎 警告", callback_data="tag_type_warn")],
    ]
    await update.message.reply_text("请选择此标签的类型：", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING_TAG_TYPE

async def handle_tag_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin(update): return ConversationHandler.END
    query = update.callback_query
    tag_type = query.data.split('_')[2]
    tag_name = context.user_data.get('new_tag_name')

    if not tag_name:
        await query.message.reply_text("发生错误，请重新开始。")
        return ConversationHandler.END

    try:
        await database.db_execute("INSERT INTO tags (name, type) VALUES ($1, $2)", tag_name, tag_type)
        await query.message.reply_text(f"✅ 标签 '{tag_name}' ({tag_type}) 已成功添加！")
    except Exception as e:
        logger.error(f"Error adding new tag: {e}")
        await query.message.reply_text("❌ 添加失败，可能标签名称已存在。")
    
    context.user_data.clear()
    # Go back to the manage tags panel
    query.data = "admin_manage_tags"
    await manage_tags_panel(update, context)
    return ConversationHandler.END

async def delete_tag_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    query = update.callback_query
    tag_pkid = int(query.data.split('_')[3])
    # Note: ON DELETE CASCADE in DB will handle evaluations
    await database.db_execute("DELETE FROM tags WHERE pkid = $1", tag_pkid)
    await query.answer("🗑️ 标签已删除")
    query.data = "admin_manage_tags"
    await manage_tags_panel(update, context)

# --- Menu Button Management ---
async def manage_menu_buttons_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This logic is very similar to tag management, omitted for brevity but would include:
    # - Listing buttons with status and reorder arrows
    # - Add, toggle, delete, reorder functionality
    await update.callback_query.edit_message_text("菜单按钮管理功能正在开发中...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel")]]))

# --- User Management ---
async def user_management_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the user management panel."""
    if not await check_admin(update): return
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("👤 添加用户到隐身名单", callback_data="admin_hide_user_prompt")],
        [InlineKeyboardButton("👀 从隐身名单中恢复用户", callback_data="admin_unhide_user_prompt")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
    ]
    await query.edit_message_text(
        "👤 **用户管理**\n\n进入隐身名单的用户将无法被查询，并从所有排行榜中移除。",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def prompt_for_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompts for a username to hide or unhide."""
    if not await check_admin(update): return ConversationHandler.END
    query = update.callback_query
    action = query.data.split('_')[1]  # 'hide' or 'unhide'
    context.user_data['user_manage_action'] = action
    
    state_map = {'hide': TYPING_USERNAME_TO_HIDE, 'unhide': TYPING_USERNAME_TO_UNHIDE}
    prompt_text = "好的，请发送您要【隐藏】的用户的 @username：" if action == 'hide' else "好的，请发送您要【恢复】的用户的 @username："
    
    await query.message.reply_text(prompt_text + "\n\n发送 /cancel 可随时取消。")
    return state_map[action]

async def set_user_hidden_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sets the hidden status for a given username."""
    if not await check_admin(update): return ConversationHandler.END
    
    username = update.message.text.strip()
    if username.startswith('@'):
        username = username[1:]
        
    action = context.user_data.get('user_manage_action')
    set_to_hidden = (action == 'hide')
    
    user_pkid = await database.db_fetch_val("SELECT pkid FROM users WHERE username = $1", username)
    
    if not user_pkid:
        await update.message.reply_text(f"❌ 未找到用户 @{username}，请确保该用户与机器人互动过。")
    else:
        await database.db_execute("UPDATE users SET is_hidden = $1 WHERE pkid = $2", set_to_hidden, user_pkid)
        action_text = "隐藏" if set_to_hidden else "恢复"
        await update.message.reply_text(f"✅ 操作成功！用户 @{username} 已被【{action_text}】。")
    
    del context.user_data['user_manage_action']
    # Can't call user_management_panel directly as it needs a callback_query
    await update.message.reply_text("返回用户管理菜单...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("👤 用户管理", callback_data="admin_user_management")]]))
    return ConversationHandler.END

# Note: The menu button management is complex and has been stubbed for now.
# Implementing it fully would involve similar ConversationHandlers for adding buttons
# and callback handlers for reordering, toggling, and deleting.
