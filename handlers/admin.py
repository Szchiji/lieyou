import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
from os import environ
from html import escape

logger = logging.getLogger(__name__)
CREATOR_ID = environ.get("CREATOR_ID")

async def god_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    creator_id_str = environ.get("CREATOR_ID")
    if not creator_id_str or user_id != int(creator_id_str):
        await update.message.reply_text("...")
        return
    async with db_transaction() as conn:
        await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", user_id)
    await update.message.reply_text("👑 创世神权限已激活。你现在是第一守护者。")

async def is_admin(user_id: int) -> bool:
    async with db_transaction() as conn:
        user_data = await conn.fetchrow("SELECT is_admin FROM users WHERE id = $1", user_id)
        return user_data and user_data['is_admin']

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🌌 **时空枢纽 (The Nexus)** 🌌\n\n创世神，请选择您要调整的宇宙法则："
    keyboard = [
        [InlineKeyboardButton("🛡️ 守护者圣殿", callback_data="admin_panel_permissions")],
        [InlineKeyboardButton("🔥 箴言熔炉", callback_data="admin_panel_tags")],
        [InlineKeyboardButton("⚙️ 法则律典", callback_data="admin_panel_system")],
        [InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🔥 **箴言熔炉 (The Forge)** 🔥\n\n“在此，你锻造构成神谕的箴言”"
    keyboard = [
        [InlineKeyboardButton("➕ 锻造赞誉箴言", callback_data="admin_tags_add_recommend_prompt")],
        [InlineKeyboardButton("➕ 锻造警示箴言", callback_data="admin_tags_add_block_prompt")],
        [InlineKeyboardButton("🗑️ 销毁现有箴言", callback_data="admin_tags_remove_menu_1")],
        [InlineKeyboardButton("📜 查看所有箴言", callback_data="admin_tags_list")],
        [InlineKeyboardButton("⬅️ 返回枢纽", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def list_all_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_transaction() as conn:
        tags = await conn.fetch("SELECT tag_name, type FROM tags ORDER BY type, tag_name")
    if not tags:
        text = "📜 **箴言总览**\n\n当前没有任何已锻造的箴言。"
    else:
        recommend_tags = [f"  - `『{escape(t['tag_name'])}』`" for t in tags if t['type'] == 'recommend']
        block_tags = [f"  - `『{escape(t['tag_name'])}』`" for t in tags if t['type'] == 'block']
        text_parts = ["📜 <b>箴言总览</b>\n" + ("-"*20)]
        if recommend_tags:
            text_parts.append("\n<b>👍 赞誉类:</b>")
            text_parts.extend(recommend_tags)
        if block_tags:
            text_parts.append("\n<b>👎 警示类:</b>")
            text_parts.extend(block_tags)
        text = "\n".join(text_parts)
    keyboard = [[InlineKeyboardButton("⬅️ 返回熔炉", callback_data="admin_panel_tags")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    context.user_data['next_action'] = f'add_tag_{tag_type}'
    type_text = "赞誉" if tag_type == "recommend" else "警示"
    text = f"✍️ **锻造{type_text}箴言**\n\n请直接发送您想锻造的箴言内容。\n(例如: 言出必行 / 空头支票)\n\n发送 /cancel 可取消。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    async with db_transaction() as conn:
        tags = await conn.fetch("SELECT id, tag_name, type FROM tags ORDER BY type, tag_name")
    if not tags:
        await update.callback_query.answer("当前没有任何箴言可供销毁。", show_alert=True)
        return
    text = "🗑️ **销毁箴言**\n\n请选择您想销毁的箴言。"
    keyboard, page_size = [], 5
    start, end = (page - 1) * page_size, page * page_size
    for tag in tags[start:end]:
        icon = '👍' if tag['type'] == 'recommend' else '👎'
        keyboard.append([InlineKeyboardButton(f"{icon} 『{escape(tag['tag_name'])}』", callback_data=f"admin_tags_remove_confirm_{tag['id']}_{page}")])
    page_row = []
    total_pages = (len(tags) + page_size - 1) // page_size or 1
    if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"admin_tags_remove_menu_{page-1}"))
    if total_pages > 1: page_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if end < len(tags): page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"admin_tags_remove_menu_{page+1}"))
    if page_row: keyboard.append(page_row)
    keyboard.append([InlineKeyboardButton("⬅️ 返回熔炉", callback_data="admin_panel_tags")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    async with db_transaction() as conn:
        tag = await conn.fetchrow("SELECT tag_name FROM tags WHERE id = $1", tag_id)
        if not tag:
            await update.callback_query.answer("❌ 错误：此箴言已被销毁。", show_alert=True)
            return
        await conn.execute("DELETE FROM tags WHERE id = $1", tag_id)
    await update.callback_query.answer(f"✅ 箴言『{escape(tag['tag_name'])}』已销毁！", show_alert=True)
    await remove_tag_menu(update, context, page=page)

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "🛡️ **守护者圣殿 (The Sanctum)** 🛡️\n\n“分封或罢黜你的守护者”"
    keyboard = [
        [InlineKeyboardButton("➕ 分封守护者", callback_data="admin_perms_add_prompt")],
        [InlineKeyboardButton("🗑️ 罢黜守护者", callback_data="admin_perms_remove_menu")],
        [InlineKeyboardButton("📜 查看守护者名录", callback_data="admin_perms_list")],
        [InlineKeyboardButton("⬅️ 返回枢纽", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['next_action'] = 'add_admin'
    text = "✍️ **分封守护者**\n\n请直接发送您想分封的用户的 **数字ID**。\n\n发送 /cancel 可取消。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_transaction() as conn:
        admins = await conn.fetch("SELECT id FROM users WHERE is_admin = TRUE")
    creator_id_int = int(CREATOR_ID) if CREATOR_ID else None
    admin_list = [f"  - `{admin['id']}`{' (👑 创世神)' if creator_id_int and admin['id'] == creator_id_int else ' (🛡️ 守护者)'}" for admin in admins]
    text = "📜 <b>守护者名录</b>\n" + ("-"*20) + "\n" + "\n".join(admin_list)
    keyboard = [[InlineKeyboardButton("⬅️ 返回圣殿", callback_data="admin_panel_permissions")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current_user_id = update.effective_user.id
    creator_id_int = int(CREATOR_ID) if CREATOR_ID else None
    async with db_transaction() as conn:
        admins = await conn.fetch("SELECT id FROM users WHERE is_admin = TRUE AND id != $1 AND id != $2", creator_id_int, current_user_id)
    if not admins:
        text, keyboard = "当前没有可供罢黜的守护者。", [[InlineKeyboardButton("⬅️ 返回圣殿", callback_data="admin_panel_permissions")]]
    else:
        text = "🗑️ **罢黜守护者**\n\n请选择您想罢黜的守护者。"
        keyboard = [[InlineKeyboardButton(f"🛡️ 守护者: {admin['id']}", callback_data=f"admin_perms_remove_confirm_{admin['id']}")] for admin in admins]
        keyboard.append([InlineKeyboardButton("⬅️ 返回圣殿", callback_data="admin_panel_permissions")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def remove_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id_to_remove: int):
    async with db_transaction() as conn:
        await conn.execute("UPDATE users SET is_admin = FALSE WHERE id = $1", user_id_to_remove)
    await update.callback_query.answer(f"✅ 已罢黜守护者 {user_id_to_remove}！", show_alert=True)
    await remove_admin_menu(update, context)

async def system_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with db_transaction() as conn:
        ttl_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
    ttl = int(ttl_row['value']) if ttl_row and ttl_row['value'] else 300
    text = (f"⚙️ **法则律典 (The Codex)** ⚙️\n\n“调整世界的基础规则”\n\n"
            f"▶️ **现行法则:**\n"
            f"  - 镜像缓存时间: `{ttl}` 秒\n")
    keyboard = [
        [InlineKeyboardButton("⚙️ 调整缓存法则", callback_data="admin_system_set_prompt_leaderboard_cache_ttl")],
        [InlineKeyboardButton("⬅️ 返回枢纽", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_key: str):
    context.user_data['next_action'] = f'set_setting_{setting_key}'
    prompts = {'leaderboard_cache_ttl': '✍️ **调整缓存法则**\n\n请输入新的镜像缓存秒数 (纯数字)。\n(例如: 600 代表10分钟)\n\n发送 /cancel 可取消。'}
    text = prompts.get(setting_key, "未知的法则项。")
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            type_text = "赞誉" if tag_type == "recommend" else "警示"
            feedback_message = f"✅ 新的 **{type_text}** 箴言『{tag_name}』已锻造成功！"
        elif next_action == 'add_admin':
            new_admin_id = int(message_text)
            async with db_transaction() as conn:
                await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", new_admin_id)
            feedback_message = f"✅ 已成功分封用户 `{new_admin_id}` 为新的守护者！"
        elif next_action.startswith('set_setting_'):
            setting_key = next_action[len('set_setting_'):]
            new_value = message_text
            if not new_value.isdigit():
                await update.message.reply_text("❌ 输入无效，必须是纯数字。请重新操作。")
                return
            async with db_transaction() as conn:
                await conn.execute("INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2", setting_key, new_value)
            feedback_message = f"✅ 法则 **{setting_key}** 已更新为 `{new_value}`！"
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
