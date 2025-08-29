import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
from os import environ

logger = logging.getLogger(__name__)
CREATOR_ID = environ.get("CREATOR_ID")

# is_admin 和 settings_menu 函数保持不变
async def is_admin(user_id: int) -> bool:
    async with db_transaction() as conn:
        user_data = await conn.fetchrow("SELECT is_admin FROM users WHERE id = $1", user_id)
        return user_data and user_data['is_admin']

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "👑 **创世神面板** 👑\n\n请选择您要管理的领域："
    keyboard = [
        [InlineKeyboardButton("🛂 权限管理", callback_data="admin_panel_permissions")],
        [InlineKeyboardButton("🏷️ 标签管理", callback_data="admin_panel_tags")],
        [InlineKeyboardButton("⚙️ 系统设置", callback_data="admin_panel_system")],
        [InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# --- 标签管理面板 (已完成，保持不变) ---
async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🏷️ **标签管理** 🏷️\n\n在这里，您可以创造、查看和删除用于评价的标签。"
    keyboard = [
        [InlineKeyboardButton("➕ 新增推荐标签", callback_data="admin_tags_add_recommend_prompt")],
        [InlineKeyboardButton("➕ 新增拉黑标签", callback_data="admin_tags_add_block_prompt")],
        [InlineKeyboardButton("🗑️ 移除标签", callback_data="admin_tags_remove_menu_1")],
        [InlineKeyboardButton("⬅️ 返回神面板", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# --- “神权进化”第三阶段核心：可视化的“权限圣殿” ---

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main menu for permission management."""
    text = "🛂 **权限管理** 🛂\n\n在这里，您可以授予或收回其他用户的管理员神权。"
    keyboard = [
        [InlineKeyboardButton("➕ 授予神权", callback_data="admin_perms_add_prompt")],
        [InlineKeyboardButton("🗑️ 收回神权", callback_data="admin_perms_remove_menu")],
        [InlineKeyboardButton("📜 查看神使", callback_data="admin_perms_list")],
        [InlineKeyboardButton("⬅️ 返回神面板", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompts the admin to enter a user ID for promotion."""
    context.user_data['next_action'] = 'add_admin'
    text = "您正在 **授予神权**。\n\n请直接在聊天框中发送您想提拔的用户的 **数字 ID**。\n\n发送 /cancel 可以取消操作。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all current admins."""
    async with db_transaction() as conn:
        admins = await conn.fetch("SELECT id FROM users WHERE is_admin = TRUE")
    
    if not admins:
        text = "当前除您之外，没有其他神使。"
    else:
        creator_id_int = int(CREATOR_ID) if CREATOR_ID else None
        admin_list = []
        for admin in admins:
            admin_id = admin['id']
            note = ""
            if creator_id_int and admin_id == creator_id_int:
                note = " (创世神)"
            admin_list.append(f"- `{admin_id}`{note}")
        text = "📜 **神使列表** 📜\n\n" + "\n".join(admin_list)
        
    keyboard = [[InlineKeyboardButton("⬅️ 返回权限管理", callback_data="admin_panel_permissions")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a list of other admins with demotion buttons."""
    current_user_id = update.effective_user.id
    creator_id_int = int(CREATOR_ID) if CREATOR_ID else None
    
    async with db_transaction() as conn:
        # 排除创世神和自己
        admins = await conn.fetch("SELECT id FROM users WHERE is_admin = TRUE AND id != $1 AND id != $2", creator_id_int, current_user_id)

    if not admins:
        text = "当前没有可供移除的神使。"
        keyboard = [[InlineKeyboardButton("⬅️ 返回权限管理", callback_data="admin_panel_permissions")]]
    else:
        text = "🗑️ **收回神权** 🗑️\n\n请选择您想收回其权限的神使。"
        keyboard = []
        for admin in admins:
            admin_id = admin['id']
            keyboard.append([InlineKeyboardButton(f"神使: {admin_id}", callback_data=f"admin_perms_remove_confirm_{admin_id}")])
        keyboard.append([InlineKeyboardButton("⬅️ 返回权限管理", callback_data="admin_panel_permissions")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def remove_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id_to_remove: int):
    """Demotes the selected user."""
    async with db_transaction() as conn:
        await conn.execute("UPDATE users SET is_admin = FALSE WHERE id = $1", user_id_to_remove)
    
    await update.callback_query.answer(f"✅ 已成功收回用户 {user_id_to_remove} 的神权！", show_alert=True)
    # 刷新列表
    await remove_admin_menu(update, context)

# --- “神权进化”第三阶段核心：可视化的“法则熔炉” ---

async def system_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main menu for system settings."""
    async with db_transaction() as conn:
        ttl_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
    
    ttl = int(ttl_row['value']) if ttl_row else 300
    
    text = (f"⚙️ **系统设置** ⚙️\n\n在这里，您可以调整世界的物理法则。\n\n"
            f"▶️ **当前法则:**\n"
            f"- 排行榜缓存时间: `{ttl}` 秒\n")

    keyboard = [
        [InlineKeyboardButton("⚙️ 更改缓存时间", callback_data="admin_system_set_prompt_leaderboard_cache_ttl")],
        [InlineKeyboardButton("⬅️ 返回神面板", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_key: str):
    """Prompts the admin to enter a new value for a setting."""
    context.user_data['next_action'] = f'set_setting_{setting_key}'
    
    prompts = {
        'leaderboard_cache_ttl': '您正在更改 **排行榜缓存时间**。\n\n请输入新的缓存秒数（纯数字，例如 600 代表10分钟）。'
    }
    text = prompts.get(setting_key, "未知的设置项。") + "\n\n发送 /cancel 可以取消操作。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

# --- 通用输入处理器 ---
async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes text input from an admin based on the stored user state."""
    user_id = update.effective_user.id
    if not await is_admin(user_id): return

    next_action = context.user_data.get('next_action')
    if not next_action: return

    # 清除状态，避免重复执行
    del context.user_data['next_action']
    
    message_text = update.message.text.strip()
    if message_text == '/cancel':
        await update.message.reply_text("操作已取消。")
        return

    try:
        if next_action.startswith('add_tag_'):
            tag_type = next_action.split('_')[-1]
            tag_name = message_text
            async with db_transaction() as conn:
                await conn.execute("INSERT INTO tags (tag_name, type) VALUES ($1, $2)", tag_name, tag_type)
            await update.message.reply_text(f"✅ 新增 **{tag_type}** 标签「{tag_name}」成功！", parse_mode='Markdown')

        elif next_action == 'add_admin':
            new_admin_id = int(message_text)
            async with db_transaction() as conn:
                await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", new_admin_id)
            await update.message.reply_text(f"✅ 已成功授予用户 `{new_admin_id}` 神权！", parse_mode='Markdown')

        elif next_action.startswith('set_setting_'):
            setting_key = next_action[len('set_setting_'):]
            new_value = message_text
            # 验证必须是数字
            if not new_value.isdigit():
                await update.message.reply_text("❌ 输入无效，必须是纯数字。请重新操作。")
                return
            async with db_transaction() as conn:
                await conn.execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2", setting_key, new_value)
            await update.message.reply_text(f"✅ 系统法则 **{setting_key}** 已更新为 `{new_value}`！", parse_mode='Markdown')

    except ValueError:
        await update.message.reply_text("❌ 输入格式错误，请输入有效的数字ID。")
    except Exception as e:
        logger.error(f"处理管理员输入 {next_action} 时失败: {e}")
        if "unique constraint" in str(e).lower():
            await update.message.reply_text("❌ 操作失败：该项目已存在。")
        else:
            await update.message.reply_text(f"❌ 操作失败，发生未知错误。")

# (标签管理相关的函数 add_tag_prompt, remove_tag_menu, remove_tag_confirm 保持不变)
async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    context.user_data['next_action'] = f'add_tag_{tag_type}'
    type_text = "推荐" if tag_type == "recommend" else "拉黑"
    text = f"您正在新增 **{type_text}** 标签。\n\n请直接在聊天框中发送您想添加的标签名称。\n\n发送 /cancel 可以取消操作。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    async with db_transaction() as conn:
        tags = await conn.fetch("SELECT id, tag_name, type FROM tags ORDER BY type, tag_name")
    if not tags:
        await update.callback_query.answer("当前没有任何标签可供移除。", show_alert=True)
        return
    text = "🗑️ **移除标签** 🗑️\n\n请选择您想移除的标签。点击按钮即可删除。"
    keyboard = []
    page_size = 5
    start = (page - 1) * page_size
    end = start + page_size
    tags_on_page = tags[start:end]
    for tag in tags_on_page:
        icon = "👍" if tag['type'] == 'recommend' else "👎"
        button_text = f"{icon} {tag['tag_name']}"
        callback_data = f"admin_tags_remove_confirm_{tag['id']}_{page}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
    page_row = []
    if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"admin_tags_remove_menu_{page-1}"))
    if end < len(tags): page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"admin_tags_remove_menu_{page+1}"))
    if page_row: keyboard.append(page_row)
    keyboard.append([InlineKeyboardButton("⬅️ 返回标签管理", callback_data="admin_panel_tags")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    async with db_transaction() as conn:
        tag = await conn.fetchrow("SELECT tag_name FROM tags WHERE id = $1", tag_id)
        if not tag:
            await update.callback_query.answer("错误：该标签已被移除。", show_alert=True)
            return
        await conn.execute("DELETE FROM tags WHERE id = $1", tag_id)
    await update.callback_query.answer(f"✅ 标签「{tag['tag_name']}」已成功移除！", show_alert=True)
    await remove_tag_menu(update, context, page=page)
