import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction

logger = logging.getLogger(__name__)

# (is_admin 和 settings_menu 函数保持不变)
async def is_admin(user_id: int) -> bool:
    """Checks if a user is an admin."""
    async with db_transaction() as conn:
        user_data = await conn.fetchrow("SELECT is_admin FROM users WHERE id = $1", user_id)
        return user_data and user_data['is_admin']

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the new, interactive admin panel."""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
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
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# --- “神权进化”第二阶段核心：可视化的“标签圣殿” ---

async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main menu for tag management."""
    text = "🏷️ **标签管理** 🏷️\n\n在这里，您可以创造、查看和删除用于评价的标签。"
    keyboard = [
        [InlineKeyboardButton("➕ 新增推荐标签", callback_data="admin_tags_add_recommend_prompt")],
        [InlineKeyboardButton("➕ 新增拉黑标签", callback_data="admin_tags_add_block_prompt")],
        [InlineKeyboardButton("🗑️ 移除标签", callback_data="admin_tags_remove_menu_1")], # 1代表第一页
        [InlineKeyboardButton("⬅️ 返回神面板", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    """Prompts the admin to enter a new tag name and sets user state."""
    type_text = "推荐" if tag_type == "recommend" else "拉黑"
    # 使用 user_data 来“记住”用户接下来要做什么
    context.user_data['next_action'] = f'add_tag_{tag_type}'
    text = f"您正在新增 **{type_text}** 标签。\n\n请直接在聊天框中发送您想添加的标签名称。\n\n发送 /cancel 可以取消操作。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """Displays a paginated list of all tags with delete buttons."""
    async with db_transaction() as conn:
        tags = await conn.fetch("SELECT id, tag_name, type FROM tags ORDER BY type, tag_name")
    
    if not tags:
        await update.callback_query.answer("当前没有任何标签可供移除。", show_alert=True)
        return

    text = "🗑️ **移除标签** 🗑️\n\n请选择您想移除的标签。点击按钮即可删除。"
    keyboard = []
    # (简单的分页逻辑，如果标签过多)
    page_size = 5
    start = (page - 1) * page_size
    end = start + page_size
    tags_on_page = tags[start:end]

    for tag in tags_on_page:
        icon = "👍" if tag['type'] == 'recommend' else "👎"
        button_text = f"{icon} {tag['tag_name']}"
        # 回调数据中包含了要删除的 tag_id，以及返回时需要回到的页码
        callback_data = f"admin_tags_remove_confirm_{tag['id']}_{page}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

    # 分页按钮
    page_row = []
    if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"admin_tags_remove_menu_{page-1}"))
    if end < len(tags): page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"admin_tags_remove_menu_{page+1}"))
    if page_row: keyboard.append(page_row)
    
    keyboard.append([InlineKeyboardButton("⬅️ 返回标签管理", callback_data="admin_panel_tags")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    """Deletes the selected tag and refreshes the removal menu."""
    async with db_transaction() as conn:
        # 获取标签名用于提示
        tag = await conn.fetchrow("SELECT tag_name FROM tags WHERE id = $1", tag_id)
        if not tag:
            await update.callback_query.answer("错误：该标签已被移除。", show_alert=True)
            return
        # 删除标签
        await conn.execute("DELETE FROM tags WHERE id = $1", tag_id)
    
    await update.callback_query.answer(f"✅ 标签「{tag['tag_name']}」已成功移除！", show_alert=True)
    # 刷新列表
    await remove_tag_menu(update, context, page=page)

async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes text input from an admin based on the stored user state."""
    user_id = update.effective_user.id
    if not await is_admin(user_id): return # 安全检查

    next_action = context.user_data.get('next_action')
    if not next_action: return # 如果没有待办事项，则忽略

    # 清除状态，避免重复执行
    del context.user_data['next_action']

    if update.message.text == '/cancel':
        await update.message.reply_text("操作已取消。")
        return

    if next_action.startswith('add_tag_'):
        tag_type = next_action.split('_')[-1]
        tag_name = update.message.text.strip()
        
        if not tag_name:
            await update.message.reply_text("标签名称不能为空，请重新操作。")
            return
            
        try:
            async with db_transaction() as conn:
                await conn.execute("INSERT INTO tags (tag_name, type) VALUES ($1, $2)", tag_name, tag_type)
            await update.message.reply_text(f"✅ 新增 **{tag_type}** 标签「{tag_name}」成功！", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"新增标签失败: {e}")
            if "unique constraint" in str(e).lower():
                await update.message.reply_text("❌ 新增失败：该标签已存在。")
            else:
                await update.message.reply_text(f"❌ 新增失败，发生未知错误。")
