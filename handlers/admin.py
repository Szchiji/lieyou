import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from math import ceil

from database import db_execute, db_fetch_all, db_fetch_one, get_or_create_user, db_fetch_val

logger = logging.getLogger(__name__)

# =============================================================================
# GOD MODE COMMAND (WITH DIAGNOSTICS)
# =============================================================================
async def god_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Grants admin rights to the user specified in GOD_MODE_USER_ID env var."""
    user = update.effective_user
    # 确保用户存在于数据库中
    await get_or_create_user(user_id=user.id, username=user.username, first_name=user.first_name)
    
    god_mode_id_str = os.environ.get("GOD_MODE_USER_ID")

    # --- 核心调试日志 ---
    logger.info(f"[GOD MODE] Command received from user_id: {user.id}")
    logger.info(f"[GOD MODE] Environment variable GOD_MODE_USER_ID value: '{god_mode_id_str}'")

    if not god_mode_id_str:
        await update.message.reply_text("❌ `GOD_MODE_USER_ID` 环境变量未配置。")
        logger.warning("[GOD MODE] GOD_MODE_USER_ID is not set in environment.")
        return

    try:
        god_mode_id = int(god_mode_id_str)
    except (ValueError, TypeError):
        await update.message.reply_text(f"❌ `GOD_MODE_USER_ID` 的值 '{god_mode_id_str}' 不是一个有效的数字 ID。")
        logger.error(f"[GOD MODE] Failed to parse GOD_MODE_USER_ID: '{god_mode_id_str}'")
        return

    if user.id == god_mode_id:
        try:
            await db_execute("UPDATE users SET is_admin = TRUE WHERE id = $1", user.id)
            await update.message.reply_text("👑 权限已授予！您现在是管理员。请使用 /start 查看管理面板。")
            logger.info(f"[GOD MODE] Admin rights successfully granted to user_id: {user.id}")
        except Exception as e:
            await update.message.reply_text(f"❌ 数据库操作失败: {e}")
            logger.error(f"[GOD MODE] Database error while granting admin rights: {e}", exc_info=True)
    else:
        await update.message.reply_text("❌ 您无权使用此命令。")
        logger.warning(f"[GOD MODE] Unauthorized attempt. User ID {user.id} does not match GOD MODE ID {god_mode_id}.")


# =============================================================================
# ADMIN INPUT PROCESSING
# =============================================================================
async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text input from admins when in a specific 'waiting_for' state."""
    if 'waiting_for' not in context.user_data:
        return

    state = context.user_data.pop('waiting_for')
    user_input = update.message.text.strip()
    
    if state['type'] == 'add_tag':
        tag_type = state['tag_type']
        try:
            await db_execute("INSERT INTO tags (name, type) VALUES ($1, $2)", user_input, tag_type)
            await update.message.reply_text(f"✅ 成功添加 {'推荐' if tag_type == 'recommend' else '警告'} 标签: `{user_input}`")
        except Exception:
            await update.message.reply_text(f"❌ 添加标签失败，可能因为“{user_input}”已存在。")
        await tags_panel(update, context)

    elif state['type'] == 'add_admin':
        username = user_input.lstrip('@')
        user_record = await get_or_create_user(username=username)
        if user_record:
            await db_execute("UPDATE users SET is_admin = TRUE WHERE pkid = $1", user_record['pkid'])
            await update.message.reply_text(f"✅ 成功将 @{username} 添加为管理员。")
        else:
            await update.message.reply_text(f"❌ 找不到用户 @{username}。请确保对方与机器人互动过。")
        await permissions_panel(update, context)

    elif state['type'] == 'set_start_message':
        await db_execute("INSERT INTO settings (key, value) VALUES ('start_message', $1) ON CONFLICT (key) DO UPDATE SET value = $1", user_input)
        await update.message.reply_text("✅ 新的欢迎语已成功设置。")
        await system_settings_panel(update, context)


# =============================================================================
# MAIN ADMIN MENU & PANELS
# =============================================================================
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main admin settings menu."""
    keyboard = [
        [InlineKeyboardButton("🏷️ 标签管理", callback_data="admin_panel_tags")],
        [InlineKeyboardButton("👮‍♀️ 权限管理", callback_data="admin_panel_permissions")],
        [InlineKeyboardButton("⚙️ 系统设置", callback_data="admin_panel_system")],
        [InlineKeyboardButton("🏆 排行榜管理", callback_data="admin_leaderboard_panel")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]
    ]
    await update.callback_query.edit_message_text("⚙️ **管理面板**", reply_markup=InlineKeyboardMarkup(keyboard))

async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the tag management panel."""
    keyboard = [
        [InlineKeyboardButton("➕ 添加推荐标签", callback_data="admin_tags_add_recommend_prompt")],
        [InlineKeyboardButton("➕ 添加警告标签", callback_data="admin_tags_add_block_prompt")],
        [InlineKeyboardButton("➖ 删除标签", callback_data="admin_tags_remove_menu_1")],
        [InlineKeyboardButton("📋 查看所有标签", callback_data="admin_tags_list")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_settings_menu")]
    ]
    await update.callback_query.edit_message_text("🏷️ **标签管理**", reply_markup=InlineKeyboardMarkup(keyboard))

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the permissions management panel."""
    keyboard = [
        [InlineKeyboardButton("➕ 添加管理员", callback_data="admin_perms_add_prompt")],
        [InlineKeyboardButton("➖ 删除管理员", callback_data="admin_perms_remove_menu_1")],
        [InlineKeyboardButton("📋 查看所有管理员", callback_data="admin_perms_list")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_settings_menu")]
    ]
    await update.callback_query.edit_message_text("👮‍♀️ **权限管理**", reply_markup=InlineKeyboardMarkup(keyboard))

async def system_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the system settings panel."""
    keyboard = [
        [InlineKeyboardButton("📝 修改欢迎语", callback_data="admin_system_set_start_message")],
        [InlineKeyboardButton("ℹ️ 查看所有指令", callback_data="admin_show_commands")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_settings_menu")]
    ]
    await update.callback_query.edit_message_text("⚙️ **系统设置**", reply_markup=InlineKeyboardMarkup(keyboard))

async def leaderboard_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the leaderboard management panel."""
    keyboard = [
        [InlineKeyboardButton("🔄 清除排行榜缓存", callback_data="admin_leaderboard_clear_cache")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_settings_menu")]
    ]
    await update.callback_query.edit_message_text("🏆 **排行榜管理**\n\n如果排行榜数据有误，可尝试清除缓存强制刷新。", reply_markup=InlineKeyboardMarkup(keyboard))


# =============================================================================
# TAG MANAGEMENT FUNCTIONS
# =============================================================================
async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    context.user_data['waiting_for'] = {'type': 'add_tag', 'tag_type': tag_type}
    prompt_text = f"请输入要添加的{'推荐' if tag_type == 'recommend' else '警告'}标签名称。\n发送 /cancel 可取消操作。"
    await update.callback_query.message.reply_text(prompt_text)
    await update.callback_query.answer()

async def list_all_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recommend_tags = await db_fetch_all("SELECT name FROM tags WHERE type = 'recommend' ORDER BY name")
    block_tags = await db_fetch_all("SELECT name FROM tags WHERE type = 'block' ORDER BY name")
    
    text = "🏷️ **当前所有标签**\n\n**推荐标签 (👍):**\n"
    text += ", ".join(f"`{t['name']}`" for t in recommend_tags) if recommend_tags else "无"
    text += "\n\n**警告标签 (👎):**\n"
    text += ", ".join(f"`{t['name']}`" for t in block_tags) if block_tags else "无"
    
    keyboard = [[InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    PAGE_SIZE = 10
    total_tags_rec = await db_fetch_one("SELECT COUNT(*) as count FROM tags")
    total_count = total_tags_rec.get('count', 0)
    total_pages = ceil(total_count / PAGE_SIZE) if total_count > 0 else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE

    tags = await db_fetch_all("SELECT id, name, type FROM tags ORDER BY type, name LIMIT $1 OFFSET $2", PAGE_SIZE, offset)
    
    if not tags:
        await update.callback_query.edit_message_text("➖ **删除标签**\n\n没有可删除的标签。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]]))
        return

    keyboard = []
    for tag in tags:
        icon = "👍" if tag['type'] == 'recommend' else "👎"
        keyboard.append([InlineKeyboardButton(f"{icon} {tag['name']}", callback_data=f"admin_tags_remove_confirm_{tag['id']}_{page}")])

    pagination = []
    if page > 1: pagination.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin_tags_remove_menu_{page-1}"))
    if page < total_pages: pagination.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"admin_tags_remove_menu_{page+1}"))
    if pagination: keyboard.append(pagination)

    keyboard.append([InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")])
    await update.callback_query.edit_message_text("➖ **删除标签**\n\n请选择要删除的标签：", reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    tag = await db_fetch_one("SELECT name, type FROM tags WHERE id = $1", tag_id)
    if not tag:
        await update.callback_query.answer("❌ 标签不存在。", show_alert=True)
        return
    
    text = f"⚠️ 确定要删除标签 “{tag['name']}” 吗？\n这将同时删除所有相关的评价记录！此操作不可逆。"
    keyboard = [
        [InlineKeyboardButton("🔴 是的，删除", callback_data=f"admin_tag_delete_{tag_id}")],
        [InlineKeyboardButton("🟢 不，返回", callback_data=f"admin_tags_remove_menu_{page}")]
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def execute_tag_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int):
    await db_execute("DELETE FROM tags WHERE id = $1", tag_id)
    await update.callback_query.answer("✅ 标签已删除。", show_alert=True)
    await remove_tag_menu(update, context, 1)


# =============================================================================
# PERMISSIONS MANAGEMENT FUNCTIONS
# =============================================================================
async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['waiting_for'] = {'type': 'add_admin'}
    await update.callback_query.message.reply_text("请输入要添加为管理员的用户的 @username。\n发送 /cancel 可取消操作。")
    await update.callback_query.answer()

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admins = await db_fetch_all("SELECT username, first_name FROM users WHERE is_admin = TRUE ORDER BY username")
    
    text = "👮‍♀️ **当前所有管理员**\n\n"
    if not admins:
        text += "无"
    else:
        admin_list = []
        for admin in admins:
            display = f"@{admin['username']}" if admin['username'] else admin['first_name']
            admin_list.append(display)
        text += ", ".join(admin_list)
        
    keyboard = [[InlineKeyboardButton("🔙 返回权限管理", callback_data="admin_panel_permissions")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    current_user_id = update.effective_user.id
    PAGE_SIZE = 10
    
    total_admins_rec = await db_fetch_one("SELECT COUNT(*) as count FROM users WHERE is_admin = TRUE AND id != $1", current_user_id)
    total_count = total_admins_rec.get('count', 0)
    total_pages = ceil(total_count / PAGE_SIZE) if total_count > 0 else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * PAGE_SIZE

    admins = await db_fetch_all("SELECT pkid, username, first_name FROM users WHERE is_admin = TRUE AND id != $1 ORDER BY username LIMIT $2 OFFSET $3", current_user_id, PAGE_SIZE, offset)
    
    if not admins:
        await update.callback_query.edit_message_text("➖ **删除管理员**\n\n没有其他可删除的管理员。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]]))
        return

    keyboard = []
    for admin in admins:
        display = f"@{admin['username']}" if admin['username'] else admin['first_name']
        keyboard.append([InlineKeyboardButton(display, callback_data=f"admin_perms_remove_confirm_{admin['pkid']}_{page}")])

    pagination = []
    if page > 1: pagination.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin_perms_remove_menu_{page-1}"))
    if page < total_pages: pagination.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"admin_perms_remove_menu_{page+1}"))
    if pagination: keyboard.append(pagination)

    keyboard.append([InlineKeyboardButton("🔙 返回权限管理", callback_data="admin_panel_permissions")])
    await update.callback_query.edit_message_text("➖ **删除管理员**\n\n请选择要移除其权限的管理员：", reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_pkid: int, page: int):
    admin = await db_fetch_one("SELECT username, first_name FROM users WHERE pkid = $1", admin_pkid)
    if not admin:
        await update.callback_query.answer("❌ 用户不存在。", show_alert=True)
        return
    
    display = f"@{admin['username']}" if admin['username'] else admin['first_name']
    text = f"⚠️ 确定要移除 “{display}” 的管理员权限吗？"
    keyboard = [
        [InlineKeyboardButton("🔴 是的，移除", callback_data=f"admin_remove_admin_{admin_pkid}")],
        [InlineKeyboardButton("🟢 不，返回", callback_data=f"admin_perms_remove_menu_{page}")]
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def execute_admin_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_pkid: int):
    await db_execute("UPDATE users SET is_admin = FALSE WHERE pkid = $1", admin_pkid)
    await update.callback_query.answer("✅ 管理员权限已移除。", show_alert=True)
    await remove_admin_menu(update, context, 1)


# =============================================================================
# SYSTEM SETTINGS FUNCTIONS
# =============================================================================
async def set_start_message_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['waiting_for'] = {'type': 'set_start_message'}
    current_message = await db_fetch_val("SELECT value FROM settings WHERE key = 'start_message'")
    prompt = "请输入新的欢迎语内容，支持 HTML 格式。\n发送 /cancel 可取消。\n\n当前欢迎语：\n"
    await update.callback_query.message.reply_text(prompt)
    if current_message:
        await update.callback_query.message.reply_text(current_message)
    await update.callback_query.answer()

async def show_all_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
ℹ️ **机器人指令列表**

**通用指令:**
`/start` - 显示主菜单
`/help` - 显示主菜单

**私聊指令:**
`/godmode` - (仅限创世神) 授予初始管理员权限
`/cancel` - 取消当前正在进行的操作 (如添加标签)

**群组/私聊查询:**
`@username` - 查询指定用户的声誉卡片
    """
    keyboard = [[InlineKeyboardButton("🔙 返回系统设置", callback_data="admin_panel_system")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
