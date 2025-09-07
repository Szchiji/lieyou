import logging
import asyncpg
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from math import ceil

from database import db_execute, db_fetch_all, db_fetch_one, get_or_create_user, db_fetch_val, is_admin, get_or_create_target, set_setting, get_setting

logger = logging.getLogger(__name__)
ADMIN_PAGE_SIZE = 5

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示管理员主面板。"""
    user = update.effective_user
    if not await is_admin(user.id):
        if update.callback_query: await update.callback_query.answer("🚫 您不是管理员。", show_alert=True)
        else: await update.message.reply_text("🚫 您不是管理员。")
        return

    text = "⚙️ **管理员面板**\n\n请选择您要管理的项目："
    keyboard = [
        [InlineKeyboardButton("👑 管理员列表", callback_data="admin_add")],
        [InlineKeyboardButton("🔖 标签管理", callback_data="admin_tags")],
        [InlineKeyboardButton("🏆 排行榜管理", callback_data="admin_leaderboard")],
        [InlineKeyboardButton("🚪 入群设置", callback_data="admin_membership")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]
    ]
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示添加/移除管理员的界面。"""
    if not await is_admin(update.effective_user.id): return
    context.user_data['next_action'] = 'add_admin'
    text = "请输入要添加为管理员的用户的 `@username` 或 Telegram ID。\n\n您也可以点击下方按钮移除现有管理员。"
    keyboard = [[InlineKeyboardButton("移除管理员", callback_data="admin_remove_menu_1")], [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """分页显示可移除的管理员列表。"""
    if not await is_admin(update.effective_user.id): return
    admins = await db_fetch_all("""
        SELECT u.pkid, u.username, u.id FROM users u
        JOIN admins a ON u.pkid = a.user_pkid
        ORDER BY u.username
    """)
    total_pages = ceil(len(admins) / ADMIN_PAGE_SIZE) if admins else 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * ADMIN_PAGE_SIZE
    admins_on_page = admins[offset : offset + ADMIN_PAGE_SIZE]
    
    text = f"请选择要移除的管理员 (第 {page}/{total_pages} 页):"
    keyboard = []
    for admin in admins_on_page:
        keyboard.append([InlineKeyboardButton(f"@{admin['username'] or admin['id']}", callback_data=f"admin_remove_confirm_{admin['pkid']}")])
    
    pagination = []
    if page > 1: pagination.append(InlineKeyboardButton("⬅️", callback_data=f"admin_remove_menu_{page-1}"))
    if page < total_pages: pagination.append(InlineKeyboardButton("➡️", callback_data=f"admin_remove_menu_{page+1}"))
    if pagination: keyboard.append(pagination)

    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_add")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_pkid_to_remove: int):
    """确认移除管理员。"""
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
    """提示用户输入要添加的标签名。"""
    if not await is_admin(update.effective_user.id): return
    context.user_data['next_action'] = f'add_tag_{tag_type}'
    type_text = "推荐" if tag_type == 'recommend' else "警告"
    text = f"请输入要添加的“{type_text}”标签名称 (例如: 靠谱, 骗子)。"
    keyboard = [[InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_tags")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str, page: int = 1):
    """分页显示可移除的标签列表。"""
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

    pagination = []
    if page > 1: pagination.append(InlineKeyboardButton("⬅️", callback_data=f"admin_remove_tag_menu_{tag_type}_{page-1}"))
    if page < total_pages: pagination.append(InlineKeyboardButton("➡️", callback_data=f"admin_remove_tag_menu_{tag_type}_{page+1}"))
    if pagination: keyboard.append(pagination)
    
    keyboard.append([InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_tags")])
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_remove_tag(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_pkid: int):
    """确认移除标签。"""
    if not await is_admin(update.effective_user.id): return
    tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE pkid = $1", tag_pkid)
    await db_execute("DELETE FROM tags WHERE pkid = $1", tag_pkid)
    await update.callback_query.answer(f"✅ 标签“{tag_info['name']}”已移除。", show_alert=True)
    await remove_tag_menu(update, context, tag_info['type'], 1)

async def leaderboard_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示排行榜管理面板。"""
    if not await is_admin(update.effective_user.id): return
    text = "🏆 **排行榜管理**\n\n您可以手动清除排行榜的缓存，以便立即看到最新数据。"
    keyboard = [
        [InlineKeyboardButton("🔄 清除排行榜缓存", callback_data="admin_clear_lb_cache")],
        [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
    ]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def membership_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示入群设置面板。"""
    if not await is_admin(update.effective_user.id): return
    
    chat_id = await get_setting('MANDATORY_CHAT_ID')
    chat_link = await get_setting('MANDATORY_CHAT_LINK')
    
    text = "🚪 **入群设置**\n\n此功能可以强制用户必须加入指定群组/频道后才能使用机器人。\n\n"
    if not chat_id:
        text += "**当前状态：** 未开启\n\n"
        text += "要开启此功能，请**转发一条来自目标公开群组/频道的消息**到这里，我将自动识别它。"
        keyboard = [[InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]]
    else:
        text += f"**当前状态：** 已开启\n"
        text += f"**绑定群组/频道 ID：** `{chat_id}`\n"
        text += f"**邀请链接：** {chat_link or '未设置'}\n\n"
        text += "您可以转发新消息来更改绑定的群组，或输入新链接来更新邀请链接。"
        keyboard = [
            [InlineKeyboardButton("更新邀请链接", callback_data="admin_set_link")],
            [InlineKeyboardButton("❌ 关闭此功能", callback_data="admin_clear_membership")],
            [InlineKeyboardButton("🔙 返回管理面板", callback_data="admin_panel")]
        ]
    
    context.user_data['next_action'] = 'set_mandatory_chat'
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def set_invite_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示管理员输入邀请链接。"""
    if not await is_admin(update.effective_user.id): return
    context.user_data['next_action'] = 'set_invite_link'
    text = "请输入新的邀请链接 (例如: `https://t.me/your_group_link`)。"
    keyboard = [[InlineKeyboardButton("🔙 返回入群设置", callback_data="admin_membership")]]
    await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def clear_membership_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """清除强制入群的设置。"""
    if not await is_admin(update.effective_user.id): return
    await set_setting('MANDATORY_CHAT_ID', '')
    await set_setting('MANDATORY_CHAT_LINK', '')
    await update.callback_query.answer("✅ 强制入群功能已关闭。", show_alert=True)
    await membership_settings(update, context)

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员在私聊中发送的文本和转发的消息。"""
    if not await is_admin(update.effective_user.id): return
    
    action = context.user_data.get('next_action')
    if not action: return

    # 处理转发消息以设置群ID
    if action == 'set_mandatory_chat' and update.message.forward_from_chat:
        chat = update.message.forward_from_chat
        await set_setting('MANDATORY_CHAT_ID', str(chat.id))
        del context.user_data['next_action']
        await update.message.reply_text(
            f"✅ 绑定成功！\n"
            f"**群组/频道名称：** {chat.title}\n"
            f"**ID:** `{chat.id}`\n\n"
            f"现在，请为我提供一个该群组/频道的**邀请链接** (例如 `https://t.me/joinchat/...` 或 `https://t.me/public_channel`)，否则用户将无法加入。"
        )
        context.user_data['next_action'] = 'set_invite_link'
        return
    
    # 如果是其他action，但收到了转发消息，可以给个提示
    if update.message.forward_from_chat:
        await update.message.reply_text("🤔 我现在不需要转发消息哦。请根据提示输入文本。")
        return

    text = update.message.text.strip()

    # 处理输入的邀请链接
    if action == 'set_invite_link':
        if text.startswith('https://t.me/'):
            await set_setting('MANDATORY_CHAT_LINK', text)
            await update.message.reply_text(f"✅ 邀请链接已更新为：\n{text}")
            del context.user_data['next_action']
            await membership_settings(update, context) # 显示更新后的状态
        else:
            await update.message.reply_text("❌ 格式错误，请输入一个有效的 `https://t.me/...` 链接。")
        return

    # 处理添加管理员
    if action == 'add_admin':
        target_user = None
        if text.isdigit():
            user_id = int(text)
            target_user_record = await db_fetch_one("SELECT * FROM users WHERE id = $1", user_id)
            if not target_user_record:
                await update.message.reply_text(f"❌ 找不到 ID 为 {user_id} 的用户。请确保该用户已与机器人开始对话。")
                return
            target_user = target_user_record
        elif text.startswith('@'):
            username = text[1:].lower()
            target_user = await get_or_create_target(username)
        else:
            await update.message.reply_text("❌ 格式错误。请输入 `@username` 或数字 ID。")
            return
        
        if not target_user:
            await update.message.reply_text("❌ 找不到目标用户。")
            return

        await db_execute("INSERT INTO admins (user_pkid, added_by_pkid) VALUES ($1, $2) ON CONFLICT (user_pkid) DO NOTHING",
                         target_user['pkid'], (await get_or_create_user(update.effective_user))['pkid'])
        await update.message.reply_text(f"✅ @{target_user['username']} 已被添加为管理员。")
        del context.user_data['next_action']
        await admin_panel(update, context) # 返回主管理菜单
        return

    # 处理添加标签
    if action.startswith('add_tag_'):
        tag_type = action.split('_')[-1]
        tag_name = text
        if len(tag_name) > 50:
            await update.message.reply_text("❌ 标签太长了，请保持在50个字符以内。")
            return
        try:
            await db_execute("INSERT INTO tags (name, type) VALUES ($1, $2)", tag_name, tag_type)
            await update.message.reply_text(f"✅ 标签“{tag_name}”已添加。")
        except asyncpg.UniqueViolationError:
            await update.message.reply_text(f"❌ 标签“{tag_name}”已存在。")
        except Exception as e:
            logger.error(f"添加标签失败: {e}")
            await update.message.reply_text("❌ 添加标签时发生错误。")
        
        del context.user_data['next_action']
        await manage_tags(update, context) # 返回标签管理菜单
        return
