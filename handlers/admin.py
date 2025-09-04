import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction, update_user_activity
from handlers.leaderboard import clear_leaderboard_cache
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
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    text = "🌌 **时空枢纽 (The Nexus)** 🌌\n\n创世神，请选择您要调整的宇宙法则："
    keyboard = [
        [InlineKeyboardButton("🛡️ 守护者圣殿", callback_data="admin_panel_permissions")],
        [InlineKeyboardButton("🔥 箴言熔炉", callback_data="admin_panel_tags")],
        [InlineKeyboardButton("🏺 存在抹除室", callback_data="admin_leaderboard_panel")],
        [InlineKeyboardButton("⚙️ 法则律典", callback_data="admin_panel_system")],
        [InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def leaderboard_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    text = ("🏺 **存在抹除室** 🏺\n\n"
            "此权柄可将一个存在从"英灵殿"与"放逐深渊"中彻底抹除，其所有赞誉与警示都将归于虚无。\n\n"
            "此操作不可逆转，请谨慎使用。")
    keyboard = [
        [InlineKeyboardButton("✍️ 指定要抹除的存在", callback_data="admin_leaderboard_remove_prompt")],
        [InlineKeyboardButton("🔄 清空排行榜缓存", callback_data="admin_leaderboard_clear_cache")],
        [InlineKeyboardButton("⬅️ 返回枢纽", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def remove_from_leaderboard_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    context.user_data['next_action'] = 'remove_from_leaderboard'
    text = "✍️ **指定存在**\n\n请发送您想从时代群像中抹除的存在的完整 `@用户名`。\n(例如: @some_user)\n\n发送 /cancel 可取消。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    # 修正这一行 - 使用正确的引号格式
    text = "🔥 **箴言熔炉 (The Forge)** 🔥\n\n\"在此，你锻造构成神谕的箴言\""
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
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    async with db_transaction() as conn:
        # 查询标签以及每个标签的使用次数
        tags = await conn.fetch("""
            SELECT t.tag_name, t.type, COUNT(v.id) as usage_count
            FROM tags t
            LEFT JOIN votes v ON t.id = v.tag_id
            GROUP BY t.tag_name, t.type
            ORDER BY t.type, t.tag_name
        """)
    
    if not tags:
        text = "📜 **箴言总览**\n\n当前没有任何已锻造的箴言。"
    else:
        recommend_tags = [f"  - `『{escape(t['tag_name'])}』` ({t['usage_count']}次)" for t in tags if t['type'] == 'recommend']
        block_tags = [f"  - `『{escape(t['tag_name'])}』` ({t['usage_count']}次)" for t in tags if t['type'] == 'block']
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
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    context.user_data['next_action'] = f'add_tag_{tag_type}'
    type_text = "赞誉" if tag_type == "recommend" else "警示"
    text = f"✍️ **锻造{type_text}箴言**\n\n请直接发送您想锻造的箴言内容。\n(例如: 言出必行 / 空头支票)\n\n发送 /cancel 可取消。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    async with db_transaction() as conn:
        # 查询标签以及使用次数
        tags = await conn.fetch("""
            SELECT t.id, t.tag_name, t.type, COUNT(v.id) as usage_count
            FROM tags t
            LEFT JOIN votes v ON t.id = v.tag_id
            GROUP BY t.id, t.tag_name, t.type
            ORDER BY t.type, t.tag_name
        """)
    if not tags:
        await update.callback_query.answer("当前没有任何箴言可供销毁。", show_alert=True)
        return
    text = "🗑️ **销毁箴言**\n\n请选择您想销毁的箴言。"
    keyboard, page_size = [], 5
    start, end = (page - 1) * page_size, page * page_size
    for tag in tags[start:end]:
        icon = '👍' if tag['type'] == 'recommend' else '👎'
        usage_text = f" ({tag['usage_count']}次)" if tag['usage_count'] > 0 else ""
        keyboard.append([InlineKeyboardButton(f"{icon} 『{escape(tag['tag_name'])}』{usage_text}", callback_data=f"admin_tags_remove_confirm_{tag['id']}_{page}")])
    page_row = []
    total_pages = (len(tags) + page_size - 1) // page_size or 1
    if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"admin_tags_remove_menu_{page-1}"))
    if total_pages > 1: page_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if end < len(tags): page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"admin_tags_remove_menu_{page+1}"))
    if page_row: keyboard.append(page_row)
    keyboard.append([InlineKeyboardButton("⬅️ 返回熔炉", callback_data="admin_panel_tags")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    async with db_transaction() as conn:
        # 获取标签信息和使用次数
        tag = await conn.fetchrow("""
            SELECT t.tag_name, COUNT(v.id) as usage_count
            FROM tags t
            LEFT JOIN votes v ON t.id = v.tag_id
            WHERE t.id = $1
            GROUP BY t.tag_name
        """, tag_id)
        
        if not tag:
            await update.callback_query.answer("❌ 错误：此箴言已被销毁。", show_alert=True)
            return
        
        # 如果标签已被使用，提供警告
        if tag['usage_count'] > 0:
            confirm_message = f"⚠️ 此箴言已被使用 {tag['usage_count']} 次，销毁后相关记录将被保留但无法查看标签内容。确定要销毁吗？"
            await update.callback_query.answer(confirm_message, show_alert=True)
        
        # 执行删除操作
        await conn.execute("DELETE FROM tags WHERE id = $1", tag_id)
    
    # 清空排行榜缓存
    clear_leaderboard_cache()
    
    await update.callback_query.answer(f"✅ 箴言『{escape(tag['tag_name'])}』已销毁！", show_alert=True)
    await remove_tag_menu(update, context, page=page)

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    # 修正这一行 - 使用正确的引号格式
    text = "🛡️ **守护者圣殿 (The Sanctum)** 🛡️\n\n\"分封或罢黜你的守护者\""
    keyboard = [
        [InlineKeyboardButton("➕ 分封守护者", callback_data="admin_perms_add_prompt")],
        [InlineKeyboardButton("🗑️ 罢黜守护者", callback_data="admin_perms_remove_menu")],
        [InlineKeyboardButton("📜 查看守护者名录", callback_data="admin_perms_list")],
        [InlineKeyboardButton("⬅️ 返回枢纽", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    context.user_data['next_action'] = 'add_admin'
    text = "✍️ **分封守护者**\n\n请直接发送您想分封的用户的 **数字ID**。\n\n发送 /cancel 可取消。"
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    async with db_transaction() as conn:
        # 查询管理员及其活动时间
        admins = await conn.fetch("""
            SELECT id, last_active, username
            FROM users 
            WHERE is_admin = TRUE
            ORDER BY last_active DESC
        """)
    creator_id_int = int(CREATOR_ID) if CREATOR_ID else None
    admin_list = []
    for admin in admins:
        username_text = f" (@{admin['username']})" if admin['username'] else ""
        last_active = admin['last_active'].strftime("%Y-%m-%d %H:%M") if admin['last_active'] else "未知"
        creator_mark = ' (👑 创世神)' if creator_id_int and admin['id'] == creator_id_int else ' (🛡️ 守护者)'
        admin_list.append(f"  - <code>{admin['id']}</code>{username_text}{creator_mark}\n    最后活跃: {last_active}")
    
    text = "📜 <b>守护者名录</b>\n" + ("-"*20) + "\n" + "\n".join(admin_list)
    keyboard = [[InlineKeyboardButton("⬅️ 返回圣殿", callback_data="admin_panel_permissions")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    current_user_id = update.effective_user.id
    creator_id_int = int(CREATOR_ID) if CREATOR_ID else None
    async with db_transaction() as conn:
        # 查询可罢黜的管理员（排除自己和创世神）
        admins = await conn.fetch("""
            SELECT id, username
            FROM users 
            WHERE is_admin = TRUE AND id != $1 AND id != $2
        """, creator_id_int, current_user_id)
    if not admins:
        text, keyboard = "当前没有可供罢黜的守护者。", [[InlineKeyboardButton("⬅️ 返回圣殿", callback_data="admin_panel_permissions")]]
    else:
        text = "🗑️ **罢黜守护者**\n\n请选择您想罢黜的守护者。"
        keyboard = []
        for admin in admins:
            username_text = f" (@{admin['username']})" if admin['username'] else ""
            keyboard.append([InlineKeyboardButton(f"🛡️ 守护者: {admin['id']}{username_text}", callback_data=f"admin_perms_remove_confirm_{admin['id']}")])
        keyboard.append([InlineKeyboardButton("⬅️ 返回圣殿", callback_data="admin_panel_permissions")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def remove_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id_to_remove: int):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    async with db_transaction() as conn:
        # 获取用户名
        user_data = await conn.fetchrow("SELECT username FROM users WHERE id = $1", user_id_to_remove)
        username_text = f" (@{user_data['username']})" if user_data and user_data['username'] else ""
        
        # 执行罢黜操作
        await conn.execute("UPDATE users SET is_admin = FALSE WHERE id = $1", user_id_to_remove)
    
    await update.callback_query.answer(f"✅ 已罢黜守护者 {user_id_to_remove}{username_text}！", show_alert=True)
    await remove_admin_menu(update, context)

async def system_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    async with db_transaction() as conn:
        # 获取所有系统设置
        settings = await conn.fetch("SELECT key, value FROM settings")
    
    # 将设置转换为字典以便查找
    settings_dict = {row['key']: row['value'] for row in settings}
    
    # 获取各项设置，如果不存在则使用默认值
    ttl = int(settings_dict.get('leaderboard_cache_ttl', '300'))
    max_prayers = int(settings_dict.get('max_prayers_per_day', '3'))
    prayer_cooldown = int(settings_dict.get('prayer_cooldown', '3600'))
    
    text = (f"⚙️ **法则律典 (The Codex)** ⚙️\n\n\"调整世界的基础规则\"\n\n"
            f"▶️ **现行法则:**\n"
            f"  - 镜像缓存时间: `{ttl}` 秒\n"
            f"  - 每日最大祷告次数: `{max_prayers}` 次\n"
            f"  - 祷告冷却时间: `{prayer_cooldown}` 秒\n")
    
    keyboard = [
        [InlineKeyboardButton("⚙️ 调整缓存法则", callback_data="admin_system_set_prompt_leaderboard_cache_ttl")],
        [InlineKeyboardButton("⚙️ 调整祷告次数", callback_data="admin_system_set_prompt_max_prayers_per_day")],
        [InlineKeyboardButton("⚙️ 调整祷告冷却", callback_data="admin_system_set_prompt_prayer_cooldown")],
        [InlineKeyboardButton("⬅️ 返回枢纽", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_key: str):
    # 更新用户活动
    await update_user_activity(update.effective_user.id, update.effective_user.username)
    
    context.user_data['next_action'] = f'set_setting_{setting_key}'
    
    # 不同设置的提示文本
    prompts = {
        'leaderboard_cache_ttl': '✍️ **调整缓存法则**\n\n请输入新的镜像缓存秒数 (纯数字)。\n(例如: 600 代表10分钟)\n\n发送 /cancel 可取消。',
        'max_prayers_per_day': '✍️ **调整祷告次数**\n\n请输入用户每日最大祷告次数 (纯数字)。\n(例如: 5)\n\n发送 /cancel 可取消。',
        'prayer_cooldown': '✍️ **调整祷告冷却**\n\n请输入祷告间隔冷却时间，以秒为单位 (纯数字)。\n(例如: 1800 代表30分钟)\n\n发送 /cancel 可取消。'
    }
    
    text = prompts.get(setting_key, "未知的法则项。")
    await update.callback_query.edit_message_text(text, parse_mode='Markdown')

async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_admin(user_id): return
    
    # 更新用户活动
    await update_user_activity(user_id, update.effective_user.username)
    
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
            
            # 清空排行榜缓存
            clear_leaderboard_cache()
            
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
                await conn.execute("""
                    INSERT INTO settings (key, value, updated_at) 
                    VALUES ($1, $2, CURRENT_TIMESTAMP) 
                    ON CONFLICT (key) DO UPDATE 
                    SET value = $2, updated_at = CURRENT_TIMESTAMP
                """, setting_key, new_value)
                
            # 如果是缓存设置，立即清空缓存
            if setting_key == 'leaderboard_cache_ttl':
                clear_leaderboard_cache()
                
            feedback_message = f"✅ 法则 **{setting_key}** 已更新为 `{new_value}`！"
            
        elif next_action == 'remove_from_leaderboard':
            username_to_remove = message_text.lstrip('@')
            async with db_transaction() as conn:
                # 检查用户是否存在
                profile = await conn.fetchrow("SELECT * FROM reputation_profiles WHERE username = $1", username_to_remove)
                if not profile:
                    feedback_message = f"❌ 未在神谕之卷中找到存在 `@{username_to_remove}`。"
                else:
                    # 重置用户声誉计数
                    await conn.execute("""
                        UPDATE reputation_profiles 
                        SET recommend_count = 0, block_count = 0, last_updated = CURRENT_TIMESTAMP
                        WHERE username = $1
                    """, username_to_remove)
                    # 清空排行榜缓存
                    clear_leaderboard_cache()
                    feedback_message = f"✅ 存在 `@{username_to_remove}` 的所有时代印记已被抹除。"
                    
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
