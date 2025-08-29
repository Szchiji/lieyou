import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction

logger = logging.getLogger(__name__)

async def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员。"""
    async with db_transaction() as conn:
        user = await conn.fetchrow("SELECT is_admin FROM users WHERE id = $1", user_id)
        return user and user['is_admin']

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示设置菜单，仅限管理员。"""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("抱歉，你没有权限访问此功能。")
        return

    async with db_transaction() as conn:
        delay_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'auto_close_delay'")
        cache_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
    
    delay = int(delay_row['value'])
    cache_ttl = int(cache_row['value'])

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
    """提示管理员输入新设置的值。"""
    query = update.callback_query
    prompts = {
        'delay': "请输入新的*评价后消息自动关闭时间* (单位: 秒)。\n\n输入 `-1` 代表永不关闭。",
        'cache': "请输入新的*排行榜缓存时间* (单位: 秒)。\n\n建议值为 `300` (5分钟)。"
    }
    await query.edit_message_text(
        text=prompts[setting_type],
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ 取消", callback_data="admin_settings_menu")]])
    )
    context.user_data['next_step'] = f'set_{setting_type}'

async def process_setting_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员输入的设置值。"""
    if 'next_step' not in context.user_data: return

    setting_key_map = { 'set_delay': 'auto_close_delay', 'set_cache': 'leaderboard_cache_ttl' }
    setting_key = setting_key_map.get(context.user_data.get('next_step'))
    
    if not setting_key: return

    del context.user_data['next_step'] # 清理状态

    try:
        value = int(update.message.text)
        async with db_transaction() as conn:
            await conn.execute("UPDATE settings SET value = $1 WHERE key = $2", str(value), setting_key)
        
        await update.message.reply_text(f"✅ 设置 `{setting_key}` 已更新为 `{value}`。")
        # 返回设置菜单
        await settings_menu(update, context)

    except (ValueError, TypeError):
        await update.message.reply_text("❌ 输入无效，请输入一个整数。")
    except Exception as e:
        logger.error(f"更新设置时出错: {e}")
        await update.message.reply_text("❌ 更新设置时发生内部错误。")

# (其他管理员命令 set_admin, list_tags, add_tag, remove_tag 保持不变)
async def set_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ...
    pass
# ...
