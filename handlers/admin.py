import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
from os import environ
from html import escape

logger = logging.getLogger(__name__)
CREATOR_ID = environ.get("CREATOR_ID")

async def god_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """终极咒语，用于授予创世神管理员权限。"""
    user_id = update.effective_user.id
    creator_id_str = environ.get("CREATOR_ID")
    
    if not creator_id_str or user_id != int(creator_id_str):
        await update.message.reply_text("...")
        return
        
    async with db_transaction() as conn:
        await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", user_id)
    
    await update.message.reply_text("👑 终极神权已激活。")

async def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员。"""
    async with db_transaction() as conn:
        user_data = await conn.fetchrow("SELECT is_admin FROM users WHERE id = $1", user_id)
        return user_data and user_data['is_admin']

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示经过美学重塑的“创世神总控制台”。"""
    text = "👑 **创世神 · 总控制台** 👑\n\n请选择您要调整的世界法则："
    keyboard = [
        [InlineKeyboardButton("🛂 权限神殿", callback_data="admin_panel_permissions")],
        [InlineKeyboardButton("🏷️ 标签圣堂", callback_data="admin_panel_tags")],
        [InlineKeyboardButton("⚙️ 法则熔炉", callback_data="admin_panel_system")],
        [InlineKeyboardButton("🌍 返回主世界", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# --- 标签管理 ---
async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示标签管理的二级菜单 - “标签圣堂”。"""
    text = "🏷️ **标签圣堂** 🏷️\n\n“言出法随，定义善恶”"
    keyboard = [
        [InlineKeyboardButton("➕ 新增推荐标签", callback_data="admin_tags_add_recommend_prompt")],
        [InlineKeyboardButton("➕ 新增拉黑标签", callback_data="admin_tags_add_block_prompt")],
        [InlineKeyboardButton("🗑️ 移除现有标签", callback_data="admin_tags_remove_menu_1")],
        [InlineKeyboardButton("📜 查看所有标签", callback_data="admin_tags_list")],
        [InlineKeyboardButton("⬅️ 返回总控制台", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def list_all_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """以美观的格式列出所有已设置的标签。"""
    async with db_transaction() as conn:
        tags = await conn.fetch("SELECT tag_name, type FROM tags ORDER BY type, tag_name")
    
    if not tags:
        text = "🏷️ **标签列表**\n\n当前没有任何已设置的标签。"
    else:
        recommend_tags = [f"  - `{escape(t['tag_name'])}`" for t in tags if t['type'] == 'recommend']
        block_tags = [f"  - `{escape(t['tag_name'])}`" for t in tags if t['type'] == 'block']
        
        text_parts = ["🏷️ <b>标签列表</b>\n" + ("-"*20)]
        if recommend_tags:
            text_parts.append("\n<b>👍 推荐类:</b>")
            text_parts.extend(recommend_tags)
        if block_tags:
            text_parts.append("\n<b>👎 拉黑类:</b>")
            text_parts.extend(block_tags)
        text = "\n".join(text_parts)

    keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data="admin_panel_tags")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    """提示管理员输入新标签的名称。"""
    context.user_data['next_action'] = f'add_tag_{tag_type}'
    type_text = "推荐" if tag_type == "recommend" else "拉黑"
    text = f"✍️ **新增{type_text}标签**\n\n请直接发送您想添加的标签名称。\n(例如: 靠谱 / 骗子)\n\n发送 /cancel 可取消。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """以分页列表显示所有标签，并提供删除按钮。"""
    async with db_transaction() as conn:
        tags = await conn.fetch("SELECT id, tag_name, type FROM tags ORDER BY type, tag_name")
    if not tags:
        await update.callback_query.answer("当前没有任何标签可供移除。", show_alert=True)
        return
    
    text = "🗑️ **移除标签**\n\n请选择您想移除的标签。"
    keyboard, page_size = [], 5
    start, end = (page - 1) * page_size, page * page_size
    
    for tag in tags[start:end]:
        icon = '👍' if tag['type'] == 'recommend' else '👎'
        keyboard.append([InlineKeyboardButton(f"{icon} {escape(tag['tag_name'])}", callback_data=f"admin_tags_remove_confirm_{tag['id']}_{page}")])
    
    page_row = []
    total_pages = (len(tags) + page_size - 1) // page_size
    if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"admin_tags_remove_menu_{page-1}"))
    if total_pages > 1: page_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if end < len(tags): page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"admin_tags_remove_menu_{page+1}"))
    if page_row: keyboard.append(page_row)
    
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data="admin_panel_tags")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    """确认并执行删除标签的操作。"""
    async with db_transaction() as conn:
        tag = await conn.fetchrow("SELECT tag_name FROM tags WHERE id = $1", tag_id)
        if not tag:
            await update.callback_query.answer("❌ 错误：该标签已被移除。", show_alert=True)
            return
        await conn.execute("DELETE FROM tags WHERE id = $1", tag_id)
    await update.callback_query.answer(f"✅ 标签「{escape(tag['tag_name'])}」已移除！", show_alert=True)
    await remove_tag_menu(update, context, page=page)

# --- 权限管理 ---
async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示权限管理的二级菜单 - “权限神殿”。"""
    text = "🛂 **权限神殿** 🛂\n\n“提拔神使，或收回神权”"
    keyboard = [
        [InlineKeyboardButton("➕ 授予神权", callback_data="admin_perms_add_prompt")],
        [InlineKeyboardButton("🗑️ 收回神权", callback_data="admin_perms_remove_menu")],
        [InlineKeyboardButton("📜 查看神使列表", callback_data="admin_perms_list")],
        [InlineKeyboardButton("⬅️ 返回总控制台", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示管理员输入要提拔的用户ID。"""
    context.user_data['next_action'] = 'add_admin'
    text = "✍️ **授予神权**\n\n请直接发送您想提拔的用户的 **数字ID**。\n\n发送 /cancel 可取消。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """以美观的格式列出所有管理员。"""
    async with db_transaction() as conn:
        admins = await conn.fetch("SELECT id FROM users WHERE is_admin = TRUE")
    creator_id_int = int(CREATOR_ID) if CREATOR_ID else None
    admin_list = [f"  - `{admin['id']}`{' (👑 创世神)' if creator_id_int and admin['id'] == creator_id_int else ''}" for admin in admins]
    text = "📜 <b>神使列表</b>\n" + ("-"*20) + "\n" + "\n".join(admin_list)
    keyboard = [[InlineKeyboardButton("⬅️ 返回", callback_data="admin_panel_permissions")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示可移除的管理员列表。"""
    current_user_id, creator_id_int = update.effective_user.id, int(CREATOR_ID) if CREATOR_ID else None
    async with db_transaction() as conn:
        admins = await conn.fetch("SELECT id FROM users WHERE is_admin = TRUE AND id != $1 AND id != $2", creator_id_int, current_user_id)
    if not admins:
        text, keyboard = "当前没有可供移除的神使。", [[InlineKeyboardButton("⬅️ 返回", callback_data="admin_panel_permissions")]]
    else:
        text = "🗑️ **收回神权**\n\n请选择您想收回其权限的神使。"
        keyboard = [[InlineKeyboardButton(f"👤 神使: {admin['id']}", callback_data=f"admin_perms_remove_confirm_{admin['id']}")] for admin in admins]
        keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data="admin_panel_permissions")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def remove_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id_to_remove: int):
    """确认并执行收回管理员权限的操作。"""
    async with db_transaction() as conn:
        await conn.execute("UPDATE users SET is_admin = FALSE WHERE id = $1", user_id_to_remove)
    await update.callback_query.answer(f"✅ 已收回用户 {user_id_to_remove} 的神权！", show_alert=True)
    await remove_admin_menu(update, context)

# --- 系统设置 ---
async def system_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统设置的二级菜单 - “法则熔炉”。"""
    async with db_transaction() as conn:
        ttl_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
    ttl = int(ttl_row['value']) if ttl_row else 300
    text = (f"⚙️ **法则熔炉** ⚙️\n\n“调整世界的基础规则”\n\n"
            f"▶️ **当前法则:**\n"
            f"  - 排行榜缓存: `{ttl}` 秒\n")
    keyboard = [
        [InlineKeyboardButton("⚙️ 更改缓存时间", callback_data="admin_system_set_prompt_leaderboard_cache_ttl")],
        [InlineKeyboardButton("⬅️ 返回总控制台", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_key: str):
    """提示管理员输入新的设置值。"""
    context.user_data['next_action'] = f'set_setting_{setting_key}'
    prompts = {'leaderboard_cache_ttl': '✍️ **更改排行榜缓存**\n\n请输入新的缓存秒数 (纯数字)。\n(例如: 600 代表10分钟)\n\n发送 /cancel 可取消。'}
    text = prompts.get(setting_key, "未知的设置项。")
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

# --- 通用输入处理器 ---
async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员在私聊中发送的文本输入，以完成特定操作。"""
    user_id = update.effective_user.id
    if not await is_admin(user_id): return
    next_action = context.user_data.get('next_action')
    if not next_action: return
    del context.user_data['next_action']
    message_text = update.message.text.strip()
    if message_text == '/cancel':
        await update.message.reply_text("操作已取消。")
        return

    feedback_message = ""
    try:
        if next_action.startswith('add_tag_'):
            tag_type = next_action.split('_')[-1]
            tag_name = message_text
            async with db_transaction() as conn:
                await conn.execute("INSERT INTO tags (tag_name, type) VALUES ($1, $2)", tag_name, tag_type)
            type_text = "推荐" if tag_type == "recommend" else "拉黑"
            feedback_message = f"✅ 新增 **{type_text}** 标签「{tag_name}」成功！"
        elif next_action == 'add_admin':
            new_admin_id = int(message_text)
            async with db_transaction() as conn:
                await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", new_admin_id)
            feedback_message = f"✅ 已成功授予用户 `{new_admin_id}` 神权！"
        elif next_action.startswith('set_setting_'):
            setting_key = next_action[len('set_setting_'):]
            new_value = message_text
            if not new_value.isdigit():
                await update.message.reply_text("❌ 输入无效，必须是纯数字。请重新操作。")
                return
            async with db_transaction() as conn:
                await conn.execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2", setting_key, new_value)
            feedback_message = f"✅ 系统法则 **{setting_key}** 已更新为 `{new_value}`！"
        
        if feedback_message:
            await update.message.reply_text(feedback_message, parse_mode='Markdown')
    except ValueError:
        await update.message.reply_text("❌ 输入格式错误，请输入有效的数字ID。")
    except Exception as e:
        logger.error(f"处理管理员输入 {next_action} 时失败: {e}", exc_info=True)
        if "unique constraint" in str(e).lower():
            await update.message.reply_text("❌ 操作失败：该项目已存在。")
        else:
            await update.message.reply_text(f"❌ 操作失败，发生未知错误。")
```
