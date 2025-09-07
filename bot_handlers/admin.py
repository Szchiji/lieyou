import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
import database
from .menu import AVAILABLE_ACTIONS # 我们需要这个列表来让管理员选择功能

logger = logging.getLogger(__name__)

# --- Conversation States (imported by main.py) ---
# 我们将复用之前定义的state
(
    TYPING_TAG_NAME, SELECTING_TAG_TYPE,
    TYPING_BUTTON_NAME, SELECTING_BUTTON_ACTION,
    TYPING_USERNAME_TO_HIDE, TYPING_USERNAME_TO_UNHIDE
) = range(6)

# --- Reusable Admin Check ---
async def check_admin(update: Update) -> bool:
    """Checks if the user is an admin. Replies and returns False if not."""
    user = update.effective_user
    is_admin_flag = await database.db_fetch_val("SELECT is_admin FROM users WHERE id = $1", user.id)
    if not is_admin_flag:
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
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return 0

# --- Tag Management (No changes needed here, keeping it for context) ---
async def manage_tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    query = update.callback_query
    await query.answer()
    
    tags = await database.db_fetch_all("SELECT pkid, name, type, is_active FROM tags ORDER BY type, name")
    
    text = "✏️ **标签管理**"
    keyboard = [[InlineKeyboardButton("➕ 添加新标签", callback_data="admin_add_tag_prompt")]]
    
    if tags:
        for tag in tags:
            status_icon = "✅" if tag['is_active'] else "❌"
            type_icon = "👍" if tag['type'] == 'recommend' else "👎"
            keyboard.append([InlineKeyboardButton(f"{status_icon} {type_icon} {tag['name']}", callback_data=f"admin_toggle_tag_{tag['pkid']}"),
                             InlineKeyboardButton("🗑️ 删除", callback_data=f"admin_delete_tag_{tag['pkid']}")])
    else:
        text += "\n\n暂无标签。"
        
    keyboard.append([InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return 0

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("请输入新标签的名称（例如：靠谱/骗子）：\n\n发送 /cancel 可随时取消。")
    return TYPING_TAG_NAME

async def handle_new_tag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin(update): return ConversationHandler.END
    context.user_data['new_tag_name'] = update.message.text.strip()
    keyboard = [
        [InlineKeyboardButton("👍 推荐 (Recommend)", callback_data="tag_type_recommend")],
        [InlineKeyboardButton("👎 警告 (Warn)", callback_data="tag_type_warn")],
        [InlineKeyboardButton("取消", callback_data="cancel")]
    ]
    await update.message.reply_text("请选择此标签的类型：", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING_TAG_TYPE

async def handle_tag_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    tag_type = query.data.split('_')[2]
    tag_name = context.user_data.get('new_tag_name')

    if not tag_name:
        await query.message.reply_text("发生错误，请重新开始。")
        return ConversationHandler.END

    try:
        await database.db_execute("INSERT INTO tags (name, type) VALUES ($1, $2)", tag_name, tag_type)
        await query.message.reply_text(f"✅ 标签 '{tag_name}' ({tag_type}) 已成功添加！")
    except Exception as e:
        logger.error(f"Error adding new tag: {e}", exc_info=True)
        await query.message.reply_text("❌ 添加失败，可能标签名称已存在。")
    
    context.user_data.clear()
    query.data = "admin_manage_tags"
    await manage_tags_panel(update, context)
    return ConversationHandler.END

async def delete_tag_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    query = update.callback_query
    tag_pkid = int(query.data.split('_')[-1])
    await database.db_execute("DELETE FROM tags WHERE pkid = $1", tag_pkid)
    await query.answer("🗑️ 标签已删除")
    query.data = "admin_manage_tags"
    await manage_tags_panel(update, context)
    return 0

# --- Menu Button Management (IMPLEMENTED) ---

async def manage_menu_buttons_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the interactive menu button management panel."""
    if not await check_admin(update): return
    query = update.callback_query
    await query.answer()

    buttons = await database.db_fetch_all("SELECT pkid, name, action_id, is_active, sort_order FROM menu_buttons ORDER BY sort_order ASC")

    text = "🔧 **管理底部按钮**\n\n您可以在这里调整主菜单的按钮。"
    keyboard = [[InlineKeyboardButton("➕ 添加新按钮", callback_data="admin_add_menu_button_prompt")]]

    if buttons:
        for i, btn in enumerate(buttons):
            status_icon = "✅" if btn['is_active'] else "❌"
            
            # Create a row of buttons for each menu item
            row = [
                InlineKeyboardButton(f"{status_icon} {btn['name']}", callback_data=f"toggle_menu_{btn['pkid']}"),
                InlineKeyboardButton("🗑️", callback_data=f"delete_menu_{btn['pkid']}")
            ]
            # Add reorder buttons (up/down arrows)
            if i > 0: # Can't move the first item up
                row.append(InlineKeyboardButton("⬆️", callback_data=f"reorder_menu_{btn['pkid']}_up"))
            if i < len(buttons) - 1: # Can't move the last item down
                row.append(InlineKeyboardButton("⬇️", callback_data=f"reorder_menu_{btn['pkid']}_down"))
            
            keyboard.append(row)
    else:
        text += "\n\n暂无自定义按钮。"

    keyboard.append([InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    return 0


async def add_menu_button_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to add a new menu button."""
    if not await check_admin(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("请输入新按钮的显示文本 (例如 '查看排行榜'):\n\n发送 /cancel 可随时取消。")
    return TYPING_BUTTON_NAME


async def handle_new_menu_button_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the button name and asks for the action."""
    if not await check_admin(update): return ConversationHandler.END
    context.user_data['new_button_name'] = update.message.text.strip()
    
    keyboard = []
    for action_id, callback_data in AVAILABLE_ACTIONS.items():
        keyboard.append([InlineKeyboardButton(f"执行: {action_id}", callback_data=f"action_{action_id}")])
    
    keyboard.append([InlineKeyboardButton("取消", callback_data="cancel")])
    
    await update.message.reply_text("请为这个按钮选择一个要执行的动作:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING_BUTTON_ACTION


async def handle_new_menu_button_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the action and saves the new button to the database."""
    if not await check_admin(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    
    action_id = query.data.split('action_', 1)[1]
    button_name = context.user_data.get('new_button_name')

    if not button_name:
        await query.message.reply_text("发生错误，请重新开始。")
        return ConversationHandler.END

    try:
        # Get the highest sort_order and add 1
        max_sort_order = await database.db_fetch_val("SELECT MAX(sort_order) FROM menu_buttons")
        new_sort_order = (max_sort_order or 0) + 1
        
        await database.db_execute(
            "INSERT INTO menu_buttons (name, action_id, sort_order) VALUES ($1, $2, $3)",
            button_name, action_id, new_sort_order
        )
        await query.message.reply_text(f"✅ 按钮 '{button_name}' 已成功添加！")
    except Exception as e:
        logger.error(f"Error adding new menu button: {e}", exc_info=True)
        await query.message.reply_text("❌ 添加失败，请检查日志。")
        
    context.user_data.clear()
    query.data = "admin_menu_buttons"
    await manage_menu_buttons_panel(update, context)
    return ConversationHandler.END


async def delete_menu_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes a menu button."""
    if not await check_admin(update): return
    query = update.callback_query
    button_pkid = int(query.data.split('_')[-1])
    
    await database.db_execute("DELETE FROM menu_buttons WHERE pkid = $1", button_pkid)
    await query.answer("🗑️ 按钮已删除")
    
    # Refresh the panel
    query.data = "admin_menu_buttons"
    await manage_menu_buttons_panel(update, context)
    return 0


async def toggle_menu_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles the active status of a menu button."""
    if not await check_admin(update): return
    query = update.callback_query
    button_pkid = int(query.data.split('_')[-1])
    
    await database.db_execute(
        "UPDATE menu_buttons SET is_active = NOT is_active WHERE pkid = $1",
        button_pkid
    )
    await query.answer("✅ 状态已切换")
    
    # Refresh the panel
    query.data = "admin_menu_buttons"
    await manage_menu_buttons_panel(update, context)
    return 0


async def reorder_menu_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Moves a menu button up or down in the sort order."""
    if not await check_admin(update): return
    query = update.callback_query
    
    _, _, pkid_str, direction = query.data.split('_')
    pkid_to_move = int(pkid_str)

    # Use a transaction to ensure atomicity
    async with (await database.get_pool()).acquire() as conn:
        async with conn.transaction():
            # Get the button to move
            button_to_move = await conn.fetchrow("SELECT pkid, sort_order FROM menu_buttons WHERE pkid = $1", pkid_to_move)
            if not button_to_move:
                await query.answer("错误：找不到按钮。", show_alert=True)
                return

            current_sort_order = button_to_move['sort_order']
            
            # Find the button to swap with
            if direction == 'up':
                # Find the button with the highest sort_order that is less than the current one
                button_to_swap = await conn.fetchrow(
                    "SELECT pkid, sort_order FROM menu_buttons WHERE sort_order < $1 ORDER BY sort_order DESC LIMIT 1",
                    current_sort_order
                )
            else: # direction == 'down'
                # Find the button with the lowest sort_order that is greater than the current one
                button_to_swap = await conn.fetchrow(
                    "SELECT pkid, sort_order FROM menu_buttons WHERE sort_order > $1 ORDER BY sort_order ASC LIMIT 1",
                    current_sort_order
                )

            if not button_to_swap:
                await query.answer("无法移动。", show_alert=True)
                return

            # Swap their sort_order values
            await conn.execute("UPDATE menu_buttons SET sort_order = $1 WHERE pkid = $2", button_to_swap['sort_order'], button_to_move['pkid'])
            await conn.execute("UPDATE menu_buttons SET sort_order = $1 WHERE pkid = $2", button_to_move['sort_order'], button_to_swap['pkid'])

    await query.answer(f"顺序已调整")
    # Refresh the panel
    query.data = "admin_menu_buttons"
    await manage_menu_buttons_panel(update, context)
    return 0


# --- User Management (No changes needed here, keeping it for context) ---
async def user_management_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin(update): return
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("🙈 添加用户到隐身名单", callback_data="admin_hide_user_prompt")],
        [InlineKeyboardButton("🙉 从隐身名单中恢复用户", callback_data="admin_unhide_user_prompt")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
    ]
    await query.edit_message_text(
        "👤 **用户管理**\n\n进入隐身名单的用户将无法被查询，并从所有排行榜中移除。",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown'
    )
    return 0

async def prompt_for_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin(update): return ConversationHandler.END
    query = update.callback_query
    await query.answer()
    action = query.data.split('_')[1]
    context.user_data['user_manage_action'] = action
    
    state_map = {'hide': TYPING_USERNAME_TO_HIDE, 'unhide': TYPING_USERNAME_TO_UNHIDE}
    prompt_text = "好的，请发送您要【隐藏】的用户的 @username：" if action == 'hide' else "好的，请发送您要【恢复】的用户的 @username："
    
    await query.message.reply_text(prompt_text + "\n\n发送 /cancel 可随时取消。")
    return state_map[action]

async def set_user_hidden_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await check_admin(update): return ConversationHandler.END
    
    username = update.message.text.strip().lstrip('@')
    action = context.user_data.get('user_manage_action')
    set_to_hidden = (action == 'hide')
    
    res = await database.db_execute("UPDATE users SET is_hidden = $1 WHERE username ILIKE $2", set_to_hidden, username)
    
    if '1' in (res or ""):
        action_text = "隐藏" if set_to_hidden else "恢复"
        await update.message.reply_text(f"✅ 操作成功！用户 @{username} 已被【{action_text}】。")
    else:
        await update.message.reply_text(f"❌ 未找到用户 @{username}，请确保该用户与机器人互动过，且用户名无误。")
    
    if 'user_manage_action' in context.user_data: del context.user_data['user_manage_action']
    
    query = type('obj', (object,), {'data': 'admin_user_management', 'answer': (lambda: None), 'edit_message_text': update.message.reply_text, 'message': update.message})
    mock_update = type('obj', (object,), {'callback_query': query, 'effective_user': update.effective_user})
    await user_management_panel(mock_update, context)

    return ConversationHandler.END
