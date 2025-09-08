import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import database

logger = logging.getLogger(__name__)

# --- Conversation States ---
(
    TYPING_TAG_NAME, SELECTING_TAG_TYPE,
    TYPING_BUTTON_NAME, SELECTING_BUTTON_ACTION,
    TYPING_USERNAME_TO_HIDE, TYPING_USERNAME_TO_UNHIDE,
    TYPING_BROADCAST, CONFIRM_BROADCAST
) = range(8)

# --- Main Admin Panel ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays the main admin panel."""
    query = update.callback_query
    if query:
        await query.answer()

    keyboard = [
        [InlineKeyboardButton("管理标签", callback_data='admin_manage_tags')],
        [InlineKeyboardButton("管理菜单按钮", callback_data='admin_menu_buttons')],
        [InlineKeyboardButton("用户管理", callback_data='admin_user_management')],
        [InlineKeyboardButton("发送广播", callback_data='admin_broadcast')],
        [InlineKeyboardButton("关闭", callback_data='cancel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = "👑 *管理员面板*\n\n请选择您要执行的操作："
    
    if query:
        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    return 0

# --- Tag Management ---
async def manage_tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Shows tag management options."""
    query = update.callback_query
    await query.answer()

    tags = await database.db_fetch_all("SELECT id, name, type FROM tags ORDER BY name")
    keyboard = []
    if tags:
        for tag in tags:
            keyboard.append([InlineKeyboardButton(f"❌ {tag['name']} ({tag['type']})", callback_data=f"admin_delete_tag_{tag['id']}")])
    
    keyboard.append([InlineKeyboardButton("➕ 添加新标签", callback_data='admin_add_tag_prompt')])
    keyboard.append([InlineKeyboardButton("返回", callback_data='admin_panel')])
    
    await query.edit_message_text("标签管理:", reply_markup=InlineKeyboardMarkup(keyboard))
    return 0

async def delete_tag_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Deletes a tag."""
    query = update.callback_query
    tag_id = int(query.data.split('_')[-1])
    await database.db_execute("DELETE FROM tags WHERE id = $1", tag_id)
    await query.answer("标签已删除", show_alert=True)
    return await manage_tags_panel(update, context)

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Prompts admin to enter a new tag name."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("请输入新标签的名称 (例如 '技术问题'):")
    return TYPING_TAG_NAME

async def handle_new_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the new tag name and asks for its type."""
    context.user_data['new_tag_name'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("加分标签", callback_data='tag_type_positive')],
        [InlineKeyboardButton("减分标签", callback_data='tag_type_negative')],
        [InlineKeyboardButton("取消", callback_data='cancel')]
    ]
    await update.message.reply_text("请选择标签类型:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING_TAG_TYPE

async def handle_tag_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saves the new tag to the database."""
    query = update.callback_query
    tag_type = query.data.split('_')[-1]
    tag_name = context.user_data.get('new_tag_name')

    if not tag_name:
        await query.answer("发生错误，请重试。", show_alert=True)
        return await admin_panel(update, context)

    await database.db_execute("INSERT INTO tags (name, type) VALUES ($1, $2)", tag_name, tag_type)
    await query.answer("标签已成功添加！", show_alert=True)
    del context.user_data['new_tag_name']
    
    await query.edit_message_text("返回标签管理...")
    return await manage_tags_panel(update, context)

# --- Menu Button Management (stubs for now) ---
async def manage_menu_buttons_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("菜单按钮管理功能正在开发中...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data='admin_panel')]]))
    return 0
async def delete_menu_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: return 0
async def toggle_menu_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: return 0
async def reorder_menu_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: return 0
async def add_menu_button_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: return TYPING_BUTTON_NAME
async def handle_new_menu_button_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: return SELECTING_BUTTON_ACTION
async def handle_new_menu_button_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int: return 0


# --- User Management ---
async def user_management_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays user management options."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("隐藏用户", callback_data='admin_hide_user_prompt')],
        [InlineKeyboardButton("取消隐藏用户", callback_data='admin_unhide_user_prompt')],
        [InlineKeyboardButton("返回", callback_data='admin_panel')]
    ]
    await query.edit_message_text("用户管理:", reply_markup=InlineKeyboardMarkup(keyboard))
    return 0

async def prompt_for_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks for a username to hide or unhide."""
    query = update.callback_query
    action = query.data.split('_')[1]
    context.user_data['user_action'] = action
    
    if action == 'hide':
        await query.edit_message_text("请输入要隐藏的用户的 @username (不带@):")
        return TYPING_USERNAME_TO_HIDE
    else:
        await query.edit_message_text("请输入要取消隐藏的用户的 @username (不带@):")
        return TYPING_USERNAME_TO_UNHIDE

async def set_user_hidden_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sets the is_hidden flag for a user."""
    username = update.message.text.lstrip('@')
    action = context.user_data.get('user_action')
    is_hidden = True if action == 'hide' else False

    result = await database.db_execute("UPDATE users SET is_hidden = $1 WHERE username ILIKE $2", is_hidden, username)

    if result and int(result.split()[-1]) > 0:
        await update.message.reply_text(f"用户 @{username} 的状态已更新。")
    else:
        await update.message.reply_text(f"找不到用户 @{username}。")
        
    del context.user_data['user_action']
    await admin_panel(update, context)
    return ConversationHandler.END

# --- Broadcast Functionality ---
async def prompt_for_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks the admin for the broadcast message content."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("请输入您想广播的消息内容 (支持文本、图片、文件等)。\n发送 /cancel 取消。")
    return TYPING_BROADCAST

async def get_broadcast_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the broadcast message and asks for confirmation."""
    context.user_data['broadcast_message'] = update.message
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认发送", callback_data='broadcast_send'),
            InlineKeyboardButton("❌ 取消", callback_data='broadcast_cancel')
        ]
    ]
    await update.message.reply_text("请预览您的广播消息。是否确认发送给所有用户？", reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM_BROADCAST

async def confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Sends the broadcast or cancels it."""
    query = update.callback_query
    await query.answer()
    
    action = query.data.split('_')[1]
    
    if action == 'cancel':
        await query.edit_message_text("广播已取消。")
        del context.user_data['broadcast_message']
        await admin_panel(update, context)
        return ConversationHandler.END

    broadcast_message = context.user_data.get('broadcast_message')
    if not broadcast_message:
        await query.edit_message_text("发生错误，找不到广播消息，请重试。")
        await admin_panel(update, context)
        return ConversationHandler.END

    await query.edit_message_text("正在发送广播...")
    
    all_users = await database.db_fetch_all("SELECT id FROM users")
    sent_count = 0
    failed_count = 0

    for user in all_users:
        try:
            await context.bot.copy_message(
                chat_id=user['id'],
                from_chat_id=broadcast_message.chat_id,
                message_id=broadcast_message.message_id
            )
            sent_count += 1
        except Exception as e:
            logger.warning(f"Failed to send broadcast to user {user['id']}: {e}")
            failed_count += 1
            
    await query.edit_message_text(f"广播发送完毕！\n\n✅ 成功: {sent_count}\n❌ 失败: {failed_count}")
    
    del context.user_data['broadcast_message']
    await admin_panel(update, context)
    return ConversationHandler.END


# --- General Cancel Action ---
async def cancel_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current operation and returns to the admin panel."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("操作已取消。")
    else:
        await update.message.reply_text("操作已取消。")
    
    keys_to_clear = ['new_tag_name', 'user_action', 'broadcast_message']
    for key in keys_to_clear:
        if key in context.user_data:
            del context.user_data[key]

    await admin_panel(update, context)
    return ConversationHandler.END
