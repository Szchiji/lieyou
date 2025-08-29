import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction

logger = logging.getLogger(__name__)

async def is_admin(user_id: int) -> bool:
    """Checks if a user is an admin."""
    async with db_transaction() as conn:
        user = await conn.fetchrow("SELECT is_admin FROM users WHERE id = $1", user_id)
        return user and user['is_admin']

# --- Settings ---
async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the settings menu, admin only."""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("抱歉，你没有权限访问此功能。")
        return

    async with db_transaction() as conn:
        delay_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'auto_close_delay'")
        cache_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
    
    delay = int(delay_row['value']) if delay_row else -1
    cache_ttl = int(cache_row['value']) if cache_row else 300

    delay_text = f"{delay}秒" if delay > 0 else "永不"
    cache_text = f"{cache_ttl}秒"

    text = (
        f"⚙️ *世界设置*\n\n"
        f"当前设置:\n"
        f"‐ 评价后消息自动关闭: *{delay_text}*\n"
        f"‐ 排行榜缓存时间: *{cache_text}*\n\n"
        f"选择要修改的设置:"
    )
    keyboard = [
        [InlineKeyboardButton("⏱️ 修改自动关闭时间", callback_data="admin_set_delay")],
        [InlineKeyboardButton("💾 修改排行榜缓存", callback_data="admin_set_cache")],
        [InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_type: str):
    """Prompts the admin to enter a new value for a setting."""
    query = update.callback_query
    prompts = {
        'delay': "请输入新的*评价后消息自动关闭时间* (单位: 秒)。\n\n输入 `-1` 代表永不关闭。",
        'cache': "请输入新的*排行榜缓存时间* (单位: 秒)。\n\n建议值为 `300` (5分钟)。"
    }
    await query.edit_message_text(
        text=prompts[setting_type],
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 取消", callback_data="admin_settings_menu")]])
    )
    context.user_data['next_step'] = f'set_{setting_type}'

async def process_setting_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes the admin's text input for a setting."""
    if 'next_step' not in context.user_data: return

    setting_key_map = { 'set_delay': 'auto_close_delay', 'set_cache': 'leaderboard_cache_ttl' }
    setting_key = setting_key_map.get(context.user_data.get('next_step'))
    
    if not setting_key: return

    del context.user_data['next_step']

    try:
        value = int(update.message.text)
        async with db_transaction() as conn:
            await conn.execute("UPDATE settings SET value = $1 WHERE key = $2", str(value), setting_key)
        
        await update.message.reply_text(f"✅ 设置 `{setting_key}` 已更新为 `{value}`。")
        await settings_menu(update, context)

    except (ValueError, TypeError):
        await update.message.reply_text("❌ 输入无效，请输入一个整数。")
    except Exception as e:
        logger.error(f"更新设置时出错: {e}")
        await update.message.reply_text("❌ 更新设置时发生内部错误。")


# --- Tag and Admin Management ---
async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets a user as an admin."""
    if not await is_admin(update.effective_user.id): return
    try:
        target_user_id = int(context.args[0])
        async with db_transaction() as conn:
            await conn.execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", target_user_id)
        await update.message.reply_text(f"✅ 用户 {target_user_id} 已被设置为管理员。")
    except (IndexError, ValueError):
        await update.message.reply_text("使用方法: /setadmin <user_id>")

async def list_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all available tags."""
    if not await is_admin(update.effective_user.id): return
    async with db_transaction() as conn:
        tags = await conn.fetch("SELECT tag_name, type FROM tags ORDER BY type, tag_name")
    if not tags:
        await update.message.reply_text("系统中还没有任何标签。")
        return
    
    recommend_tags = [f"`{t['tag_name']}`" for t in tags if t['type'] == 'recommend']
    block_tags = [f"`{t['tag_name']}`" for t in tags if t['type'] == 'block']
    
    text = "*系统标签列表*\n\n"
    text += "👍 *推荐标签*:\n" + (", ".join(recommend_tags) if recommend_tags else "无") + "\n\n"
    text += "👎 *拉黑标签*:\n" + (", ".join(block_tags) if block_tags else "无")
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def add_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a new tag."""
    if not await is_admin(update.effective_user.id): return
    try:
        tag_type_map = {'推荐': 'recommend', '拉黑': 'block'}
        tag_type = tag_type_map.get(context.args[0])
        tag_name = context.args[1]
        if not tag_type: raise ValueError("类型错误")
        
        async with db_transaction() as conn:
            await conn.execute("INSERT INTO tags (tag_name, type) VALUES ($1, $2) ON CONFLICT DO NOTHING", tag_name, tag_type)
        await update.message.reply_text(f"✅ 标签 `{tag_name}` 已作为 '{context.args[0]}' 类型添加。")
    except (IndexError, ValueError):
        await update.message.reply_text("使用方法: /addtag <推荐|拉黑> <标签名>")

async def remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes a tag."""
    if not await is_admin(update.effective_user.id): return
    try:
        tag_name = context.args[0]
        async with db_transaction() as conn:
            await conn.execute("DELETE FROM tags WHERE tag_name = $1", tag_name)
        await update.message.reply_text(f"✅ 标签 `{tag_name}` 已被移除。")
    except IndexError:
        await update.message.reply_text("使用方法: /removetag <标签名>")
