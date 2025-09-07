import logging
import asyncpg
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from math import ceil

from database import (
    db_execute, db_fetch_all, db_fetch_one, get_or_create_user, 
    db_fetch_val, is_admin, get_or_create_target, set_setting, get_setting
)
from . import leaderboard as leaderboard_handlers

logger = logging.getLogger(__name__)
ADMIN_PAGE_SIZE = 5

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示主管理面板。"""
    user = update.effective_user
    if not await is_admin(user.id):
        if update.callback_query:
            await update.callback_query.answer("🚫 您不是管理员。", show_alert=True)
        else:
            await update.message.reply_text("🚫 您不是管理员。")
        return

    text = "⚙️ **管理员面板**\n\n请选择您要管理的项目："
    keyboard = [
        [InlineKeyboardButton("👑 管理员列表", callback_data="admin_add")],
        [InlineKeyboardButton("🔖 标签管理", callback_data="admin_tags")],
        [InlineKeyboardButton("🏆 排行榜管理", callback_data="admin_leaderboard")],
        [InlineKeyboardButton("🚪 入群设置", callback_data="admin_membership")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def leaderboard_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示排行榜管理面板。"""
    if not await is_admin(update.effective_user.id): return
    
    text = "🏆 **排行榜管理**\n\n您可以手动清除排行榜的缓存，以便立即看到最新数据。"
    keyboard = [
        [InlineKeyboardButton("🔄 清除排行榜缓存", callback_data="admin_clear_lb_cache")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理私聊中的文本和转发消息，用于管理员操作。"""
    user = update.effective_user
    if not await is_admin(user.id):
        return

    action = context.user_data.get('next_action')
    if not action:
        return

    # 处理入群设置的转发消息
    if action == 'set_mandatory_chat' and update.message.forward_from_chat:
        chat = update.message.forward_from_chat
        await set_setting('MANDATORY_CHAT_ID', str(chat.id))
        del context.user_data['next_action']
        await update.message.reply_text(
            f"✅ 绑定成功！\n**群组/频道名称：** {chat.title}\n**ID:** `{chat.id}`\n\n"
            "现在，请为我提供一个该群组/频道的**邀请链接**...",
        )
        context.user_data['next_action'] = 'set_invite_link'
        return
    
    if update.message.forward_from_chat:
        await update.message.reply_text("🤔 我现在不需要转发消息哦。请根据提示输入文本。")
        return

    text = update.message.text.strip()

    if action == 'add_admin':
        try:
            # 尝试将输入视为ID
            user_to_add_id = int(text)
            user_to_add = await context.bot.get_chat(user_to_add_id)
            tg_user = user_to_add
        except (ValueError, TypeError):
            # 否则视为username
            username = text.lstrip('@')
            try:
                user_record = await get_or_create_target(username)
                if not user_record.get('id'):
                    await update.message.reply_text(f"❌ 找不到用户 @{username} 或该用户未与机器人互动过。请确保对方已私聊启动过机器人。")
                    return
                tg_user = await context.bot.get_chat(user_record['id'])
            except Exception as e:
                await update.message.reply_text(f"❌ 添加管理员失败: {e}")
                return

        user_db_record = await get_or_create_user(tg_user)
        await db_execute("INSERT INTO admins (user_pkid, added_by_pkid) VALUES ($1, $2) ON CONFLICT (user_pkid) DO NOTHING", user_db_record['pkid'], (await get_or_create_user(user))['pkid'])
        await update.message.reply_text(f"✅ 管理员 @{tg_user.username} 添加成功！")
        del context.user_data['next_action']
        await admin_panel(update, context)

    elif action.startswith('add_tag_'):
        tag_type = action.split('_')[-1]
        try:
            await db_execute("INSERT INTO tags (name, type) VALUES ($1, $2)", text, tag_type)
            await update.message.reply_text(f"✅ 标签 “{text}” 添加成功！")
        except asyncpg.UniqueViolationError:
            await update.message.reply_text(f"❌ 标签 “{text}” 已存在。")
        del context.user_data['next_action']
        await manage_tags(update, context)

    elif action == 'set_invite_link':
        if text.startswith('https://t.me/'):
            await set_setting('MANDATORY_CHAT_LINK', text)
            await update.message.reply_text(f"✅ 邀请链接已更新为：\n{text}")
            del context.user_data['next_action']
            await membership_settings(update, context) # 返回设置菜单
        else:
            await update.message.reply_text("❌ 格式错误，请输入一个有效的 `https://t.me/...` 链接。")
        return

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示添加/移除管理员的菜单。"""
    if not await is_admin(update.effective_user.id): return
    context.user_data['next_action'] = 'add_admin'
    text = "请输入要添加为管理员的用户的 `@username` 或 Telegram ID。\n\n您也可以点击下方按钮移除现有管理员。"
    keyboard = [
        [InlineKeyboardButton("移除管理员", callback_data="admin_remove_menu_1")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """显示可移除的管理员列表（分页）。"""
    if not await is_admin(update.effective_user.id): return
    admins = await db_fetch_all("SELECT u.pkid, u.username, u.id FROM users u JOIN admins a ON u.pkid = a.user_pkid ORDER BY u.username")
    total_pages = ceil(len(admins) / ADMIN_PAGE_SIZE) if admins else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * ADMIN_PAGE_SIZE
    admins_on_page = admins[offset : offset + ADMIN_PAGE_SIZE]

    text = f"请选择要移除的管理员 (第 {page}/{total_pages} 页):"
    keyboard = []
    for admin in admins_on_page:
        keyboard.append([InlineKeyboardButton(f"@{admin['username'] or admin['id']}", callback_data=f"admin_remove_confirm_{admin['pkid']}")])

    pagination_row = []
    if page > 1: pagination_row.append(InlineKeyboardButton("⬅️", callback_data=f"admin_remove_menu_{page-1}"))
    if page < total_pages: pagination_row.append(InlineKeyboardButton("➡️", callback_data=f"admin_remove_menu_{page+1}"))
    if pagination_row: keyboard.append(pagination_row)
    
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_add")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_pkid_to_remove: int):
    """确认并执行移除管理员的操作。"""
    if not await is_admin(update.effective_user.id): return
    admin_to_remove = await db_fetch_one("SELECT username, id FROM users WHERE pkid = $1", user_pkid_to_remove)
    
    god_user_id = os.environ.get("GOD_USER_ID")
    if god_user_id and str(admin_to_remove['id']) == god_user_id:
        await update.callback_query.answer("🚫 不能移除 GOD 用户！", show_alert=True)
        return

    await db_execute("DELETE FROM admins WHERE user_pkid = $1", user_pkid_to_remove)
    await update.callback_query.answer(f"✅ 管理员 @{admin_to_remove['username']} 已被移除。", show_alert=True)
    await remove_admin_menu(update, context, 1)

async def manage_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示标签管理菜单。"""
    if not await is_admin(update.effective_user.id): return
    text = "🔖 **标签管理**\n\n请选择操作："
    keyboard = [
        [InlineKeyboardButton("➕ 添加推荐标签", callback_data="admin_add_tag_recommend")],
        [InlineKeyboardButton("➕ 添加警告标签", callback_data="admin_add_tag_block")],
        [InlineKeyboardButton("➖ 移除推荐标签", callback_data="admin_remove_tag_menu_recommend_1")],
        [InlineKeyboardButton("➖ 移除警告标签", callback_data="admin_remove_tag_menu_block_1")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def add_tag(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    """提示用户输入新标签的名称。"""
    if not await is_admin(update.effective_user.id): return
    context.user_data['next_action'] = f'add_tag_{tag_type}'
    type_text = "推荐" if tag_type == 'recommend' else "警告"
    text = f"请输入要添加的“{type_text}”标签名称 (例如: 靠谱, 骗子)。"
    keyboard = [[InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_tags")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str, page: int = 1):
    """显示可移除的标签列表（分页）。"""
    if not await is_admin(update.effective_user.id): return
    tags = await db_fetch_all("SELECT pkid, name FROM tags WHERE type = $1 ORDER BY name", tag_type)
    total_pages = ceil(len(tags) / ADMIN_PAGE_SIZE) if tags else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * ADMIN_PAGE_SIZE
    tags_on_page = tags[offset : offset + ADMIN_PAGE_SIZE]

    type_text = "推荐" if tag_type == 'recommend' else "警告"
    text = f"请选择要移除的“{type_text}”标签 (第 {page}/{total_pages} 页):"
    keyboard = []
    for tag in tags_on_page:
        count = await db_fetch_val("SELECT COUNT(*) FROM evaluations WHERE tag_pkid = $1", tag['pkid'])
        keyboard.append([InlineKeyboardButton(f"{tag['name']} ({count}次使用)", callback_data=f"admin_remove_tag_confirm_{tag['pkid']}")])

    pagination_row = []
    if page > 1: pagination_row.append(InlineKeyboardButton("⬅️", callback_data=f"admin_remove_tag_menu_{tag_type}_{page-1}"))
    if page < total_pages: pagination_row.append(InlineKeyboardButton("➡️", callback_data=f"admin_remove_tag_menu_{tag_type}_{page+1}"))
    if pagination_row: keyboard.append(pagination_row)
    
    keyboard.append([InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_tags")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_pkid: int):
    """确认并执行移除标签的操作。"""
    if not await is_admin(update.effective_user.id): return
    tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE pkid = $1", tag_pkid)
    await db_execute("DELETE FROM tags WHERE pkid = $1", tag_pkid)
    await update.callback_query.answer(f"✅ 标签“{tag_info['name']}”已移除。", show_alert=True)
    await remove_tag_menu(update, context, tag_info['type'], 1)

async def membership_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示入群设置面板。"""
    if not await is_admin(update.effective_user.id): return
    
    chat_id = await get_setting('MANDATORY_CHAT_ID')
    chat_link = await get_setting('MANDATORY_CHAT_LINK')
    
    text = "🚪 **入群设置**\n\n此功能可以强制用户必须加入指定群组/频道后才能使用机器人。\n\n"
    keyboard = []

    if not chat_id:
        text += "**当前状态：** 未开启\n\n要开启此功能，请**转发一条来自目标公开群组/频道的消息**到这里，我将自动识别它。"
        context.user_data['next_action'] = 'set_mandatory_chat'
        keyboard.append([InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")])
    else:
        text += f"**当前状态：** 已开启\n**绑定群组/频道 ID：** `{chat_id}`\n**邀请链接：** {chat_link or '未设置'}\n\n您可以转发新消息来更改绑定的群组，或点击按钮更新邀请链接。"
        context.user_data['next_action'] = 'set_mandatory_chat' # 允许随时转发新消息来更改
        keyboard.append([InlineKeyboardButton("更新邀请链接", callback_data="admin_set_link")])
        keyboard.append([InlineKeyboardButton("❌ 关闭此功能", callback_data="admin_clear_membership")])
        keyboard.append([InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")])

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: # This happens after a text/forward message
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def set_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示用户输入新的邀请链接。"""
    if not await is_admin(update.effective_user.id): return
    context.user_data['next_action'] = 'set_invite_link'
    text = "请输入新的邀请链接 (例如: `https://t.me/your_group_link`)。"
    keyboard = [[InlineKeyboardButton("🔙 返回入群设置", callback_data="admin_membership")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def clear_membership_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清除强制入群的设置。"""
    if not await is_admin(update.effective_user.id): return
    await set_setting('MANDATORY_CHAT_ID', None)
    await set_setting('MANDATORY_CHAT_LINK', None)
    await update.callback_query.answer("✅ 强制入群功能已关闭。", show_alert=True)
    await membership_settings(update, context)
