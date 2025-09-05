import logging
import re
from typing import Optional, List, Dict, Any
from os import environ

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import (
    db_execute, db_fetch_all, db_fetch_one, db_fetchval,
    is_admin, get_setting, set_setting
)
from .leaderboard import clear_leaderboard_cache
from .utils import schedule_message_deletion

logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = 5 # 管理员面板的分页数量

# ============= 主要入口函数 =============

async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员在私聊中发送的文本输入"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        return
    
    waiting_for = context.user_data.get('waiting_for')
    if not waiting_for:
        return

    # 根据等待状态分发给具体的处理函数
    # 已移除 'broadcast_message' 和 'user_id_search'
    handler_map = {
        'new_recommend_tag': process_new_recommend_tag,
        'new_block_tag': process_new_block_tag,
        'new_admin_id': process_new_admin,
        'setting_value': process_setting_value,
        'start_message': process_start_message,
        'leaderboard_user_id': process_leaderboard_removal,
    }
    
    handler = handler_map.get(waiting_for)
    if handler:
        await handler(update, context)
    
    # 清理等待状态，避免重复触发
    context.user_data.pop('waiting_for', None)

async def god_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """神谕模式命令 - 使用密码获取管理员权限"""
    user_id = update.effective_user.id
    
    if await is_admin(user_id):
        await update.message.reply_text("✨ 你已经拥有守护者权限。")
        return
    
    if not context.args:
        await update.message.reply_text("🔐 请提供神谕密钥。\n\n使用方法: `/godmode [密码]`")
        return
    
    system_password = await get_setting('admin_password')
    if not system_password:
        await update.message.reply_text("❌ 系统未设置神谕密钥，此功能已禁用。")
        return
        
    provided_password = context.args[0]
    
    if provided_password != system_password:
        await update.message.reply_text("❌ 神谕密钥不正确。")
        logger.warning(f"用户 {user_id} 尝试使用错误密码获取管理员权限")
        return
    
    try:
        await db_execute(
            "INSERT INTO users (id, username, first_name, is_admin) VALUES ($1, $2, $3, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE, username = $2, first_name = $3",
            user_id, update.effective_user.username, update.effective_user.first_name
        )
        await update.message.reply_text("✨ 恭喜！你已被授予守护者权限。\n\n现在可以使用管理功能了。")
        logger.info(f"用户 {user_id} 被授予管理员权限")
    except Exception as e:
        logger.error(f"授予管理员权限失败: {e}")
        await update.message.reply_text("❌ 授权失败，请联系系统管理员。")

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示管理员主菜单 - 时空枢纽"""
    query = update.callback_query
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await query.answer("❌ 权限不足", show_alert=True)
        return
    
    await query.answer()
    
    message = "🌌 **时空枢纽** - 管理中心\n\n选择要管理的功能："
    
    keyboard = [
        [InlineKeyboardButton("🏷️ 标签管理", callback_data="admin_panel_tags")],
        [InlineKeyboardButton("👑 权限管理", callback_data="admin_panel_permissions")],
        [InlineKeyboardButton("⚙️ 系统设置", callback_data="admin_panel_system")],
        [InlineKeyboardButton("📈 排行榜管理", callback_data="admin_leaderboard_panel")],
        [InlineKeyboardButton("📖 查看所有命令", callback_data="admin_show_commands")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    await schedule_message_deletion(context, query.message.chat.id, query.message.message_id)

# ============= 面板函数 =============

async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """标签管理面板"""
    query = update.callback_query
    if not await is_admin(update.effective_user.id): await query.answer("❌ 权限不足", show_alert=True); return
    await query.answer()
    
    try:
        recommend_count = await db_fetchval("SELECT COUNT(*) FROM tags WHERE type = 'recommend'") or 0
        block_count = await db_fetchval("SELECT COUNT(*) FROM tags WHERE type = 'block'") or 0
        
        message = f"🏷️ **标签管理面板**\n\n📊 **统计信息**\n• 推荐标签: {recommend_count}个\n• 警告标签: {block_count}个"
        
        keyboard = [
            [InlineKeyboardButton("➕ 添加推荐标签", callback_data="admin_tags_add_recommend_prompt")],
            [InlineKeyboardButton("⚠️ 添加警告标签", callback_data="admin_tags_add_block_prompt")],
            [InlineKeyboardButton("📋 查看所有标签", callback_data="admin_tags_list")],
            [InlineKeyboardButton("🗑️ 删除标签", callback_data="admin_tags_remove_menu_1")],
            [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await schedule_message_deletion(context, query.message.chat.id, query.message.message_id)
        
    except Exception as e:
        logger.error(f"标签面板显示失败: {e}")
        await query.edit_message_text("❌ 加载标签面板失败。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]]))

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """权限管理面板"""
    query = update.callback_query
    if not await is_admin(update.effective_user.id): await query.answer("❌ 权限不足", show_alert=True); return
    await query.answer()
    
    try:
        admin_count = await db_fetchval("SELECT COUNT(*) FROM users WHERE is_admin = TRUE") or 0
        
        message = f"👑 **权限管理面板**\n\n📊 **统计信息**\n• 当前管理员: {admin_count}人"
        
        keyboard = [
            [InlineKeyboardButton("➕ 添加管理员", callback_data="admin_perms_add_prompt")],
            [InlineKeyboardButton("👥 查看管理员列表", callback_data="admin_perms_list")],
            [InlineKeyboardButton("➖ 移除管理员", callback_data="admin_perms_remove_menu_1")],
            [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await schedule_message_deletion(context, query.message.chat.id, query.message.message_id)
        
    except Exception as e:
        logger.error(f"权限面板显示失败: {e}")
        await query.edit_message_text("❌ 加载权限面板失败。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]]))

async def system_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """系统设置面板"""
    query = update.callback_query
    if not await is_admin(update.effective_user.id): await query.answer("❌ 权限不足", show_alert=True); return
    await query.answer()
    
    try:
        timeout_str = await get_setting('auto_delete_timeout', '300')
        message = f"""⚙️ **系统设置面板**

配置系统参数和消息内容。

当前消息自动消失时间：**{timeout_str}** 秒
*(设置为0可禁用此功能)*"""
        
        keyboard = [
            [InlineKeyboardButton("📝 设置开始消息", callback_data="admin_system_set_start_message")],
            [InlineKeyboardButton("⏱️ 修改消失时间", callback_data="admin_system_set_prompt_auto_delete_timeout")],
            [InlineKeyboardButton("🔐 设置管理密码", callback_data="admin_system_set_prompt_admin_password")],
            [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await schedule_message_deletion(context, query.message.chat.id, query.message.message_id)
        
    except Exception as e:
        logger.error(f"系统设置面板显示失败: {e}")
        await query.edit_message_text("❌ 加载系统设置面板失败。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]]))

# ============= 排行榜管理 =============

async def leaderboard_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """排行榜管理面板 - 提供管理入口"""
    query = update.callback_query
    if not await is_admin(update.effective_user.id): await query.answer("❌ 权限不足", show_alert=True); return
    await query.answer()
    
    try:
        message = "📈 **排行榜管理面板**\n\n请选择您要管理的榜单，或执行其他操作。"
        keyboard = [
            [InlineKeyboardButton("🏆 管理好评榜", callback_data="admin_selective_remove_top_1")],
            [InlineKeyboardButton("☠️ 管理差评榜", callback_data="admin_selective_remove_bottom_1")],
            [InlineKeyboardButton("🔄 清除排行榜缓存", callback_data="admin_leaderboard_clear_cache")],
            [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
        ]
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        await schedule_message_deletion(context, query.message.chat.id, query.message.message_id)
        
    except Exception as e:
        logger.error(f"排行榜面板显示失败: {e}")
        await query.edit_message_text("❌ 加载排行榜面板失败。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]]))

async def selective_remove_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int):
    """显示具体榜单的用户列表以供管理"""
    query = update.callback_query
    await query.answer()
    
    offset = (page - 1) * ITEMS_PER_PAGE
    order = "DESC" if board_type == 'top' else "ASC"
    board_name = "好评榜" if board_type == 'top' else "差评榜"
    icon = "🏆" if board_type == 'top' else "☠️"

    try:
        leaderboard_data = await db_fetch_all(f"""
            SELECT u.id, u.first_name, u.username, COALESCE(s.score, 0) as score
            FROM users u JOIN (
                SELECT target_user_id, SUM(CASE WHEN t.type = 'recommend' THEN 1 ELSE -1 END) as score
                FROM votes v JOIN tags t ON v.tag_id = t.id GROUP BY v.target_user_id
            ) s ON u.id = s.target_user_id WHERE s.score != 0
            ORDER BY score {order}, u.id ASC LIMIT $1 OFFSET $2;
        """, ITEMS_PER_PAGE, offset)

        total_users_count = await db_fetchval("SELECT COUNT(DISTINCT target_user_id) FROM votes") or 0
        total_pages = (total_users_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE or 1

        if not leaderboard_data and page == 1:
            message = f"{icon} **管理{board_name}**\n\n榜单上当前无人。"
            keyboard = [[InlineKeyboardButton("🔙 返回排行榜管理", callback_data="admin_leaderboard_panel")]]
        else:
            message = f"{icon} **管理{board_name}** (第{page}/{total_pages}页)\n\n请选择要管理的用户："
            keyboard = []
            for user in leaderboard_data:
                display_name = user['first_name'] or (f"@{user['username']}" if user['username'] else f"ID: {user['id']}")
                button_text = f"👤 {display_name} (声望: {user['score']})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"admin_confirm_remove_user_{user['id']}_{board_type}_{page}")])
            
            nav_buttons = []
            if page > 1: nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin_selective_remove_{board_type}_{page-1}"))
            if page < total_pages: nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"admin_selective_remove_{board_type}_{page+1}"))
            if nav_buttons: keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("🔙 返回排行榜管理", callback_data="admin_leaderboard_panel")])
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"显示选择性移除菜单失败: {e}")
        await query.edit_message_text("❌ 加载用户列表失败。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_leaderboard_panel")]]))

async def confirm_user_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id_to_remove: int, board_type: str, page: int):
    """显示针对单个用户的管理操作菜单"""
    query = update.callback_query
    await query.answer()

    try:
        user_info = await db_fetch_one("SELECT first_name, username FROM users WHERE id = $1", user_id_to_remove)
        if not user_info: await query.answer("❌ 用户信息未找到", show_alert=True); return

        score = await db_fetchval("SELECT SUM(CASE WHEN t.type = 'recommend' THEN 1 ELSE -1 END) FROM votes v JOIN tags t ON v.tag_id = t.id WHERE v.target_user_id = $1", user_id_to_remove) or 0
        display_name = user_info['first_name'] or (f"@{user_info['username']}" if user_info['username'] else f"ID: {user_id_to_remove}")
        
        message = f"👤 **管理用户**: `{display_name}`\n**ID**: `{user_id_to_remove}`\n**当前声望**: `{score}`\n\n请选择要执行的操作："
        keyboard = [
            [InlineKeyboardButton("🗑️ 清空所有声望", callback_data=f"admin_execute_removal_clear_all_{user_id_to_remove}_{board_type}_{page}")],
            [InlineKeyboardButton("🧼 清空负面声望", callback_data=f"admin_execute_removal_clear_neg_{user_id_to_remove}_{board_type}_{page}")],
            [InlineKeyboardButton("🔙 返回榜单", callback_data=f"admin_selective_remove_{board_type}_{page}")]
        ]
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"显示用户确认移除菜单失败: {e}", exc_info=True)
        await query.edit_message_text("❌ 加载用户操作菜单失败。")

async def execute_user_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id_to_remove: int, removal_type: str, board_type: str, page: int):
    """执行具体的用户声望管理操作"""
    query = update.callback_query
    admin_id = update.effective_user.id
    
    try:
        if removal_type == "clear_all":
            await db_execute("DELETE FROM votes WHERE target_user_id = $1", user_id_to_remove)
            logger.info(f"管理员 {admin_id} 清空了用户 {user_id_to_remove} 的所有声望。")
        elif removal_type == "clear_neg":
            await db_execute("DELETE FROM votes v USING tags t WHERE v.tag_id = t.id AND v.target_user_id = $1 AND t.type = 'block'", user_id_to_remove)
            logger.info(f"管理员 {admin_id} 清空了用户 {user_id_to_remove} 的负面声望。")
        else:
            await query.answer("❌ 未知的操作类型", show_alert=True); return

        clear_leaderboard_cache()
        await query.answer("✅ 操作已执行", show_alert=True)
        await selective_remove_menu(update, context, board_type, page)

    except Exception as e:
        logger.error(f"执行用户移除操作失败: {e}", exc_info=True)
        await query.edit_message_text("❌ 操作失败，发生内部错误。")

# ============= 标签、权限、系统等其他功能 =============

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    query = update.callback_query; await query.answer()
    type_name = "推荐" if tag_type == "recommend" else "警告"
    await query.edit_message_text(f"➕ **添加{type_name}标签**\n\n请在私聊中发送新标签的名称：\n\n*(发送 /cancel 可取消)*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]]), parse_mode=ParseMode.MARKDOWN)
    context.user_data['waiting_for'] = f'new_{tag_type}_tag'

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    query = update.callback_query; await query.answer()
    offset = (page - 1) * ITEMS_PER_PAGE
    tags = await db_fetch_all("SELECT id, name, type FROM tags ORDER BY type, name LIMIT $1 OFFSET $2", ITEMS_PER_PAGE, offset)
    total_count = await db_fetchval("SELECT COUNT(*) FROM tags") or 0
    total_pages = (total_count + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE or 1
    if not tags and page == 1:
        await query.edit_message_text("📋 **删除标签**\n\n暂无标签可删除。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")]]))
        return
    message = f"🗑️ **删除标签** (第{page}/{total_pages}页)\n\n请选择要删除的标签："
    keyboard = [[InlineKeyboardButton(f"{'👍' if tag['type'] == 'recommend' else '👎'} {tag['name']}", callback_data=f"admin_tags_remove_confirm_{tag['id']}_{page}")] for tag in tags]
    nav = []
    if page > 1: nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin_tags_remove_menu_{page-1}"))
    if page < total_pages: nav.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"admin_tags_remove_menu_{page+1}"))
    if nav: keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")])
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    query = update.callback_query; await query.answer()
    tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE id = $1", tag_id)
    if not tag_info: await query.edit_message_text("❌ 标签不存在。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]])); return
    message = f"⚠️ **确认删除**\n\n标签: **{tag_info['name']}**\n\n此操作不可撤销，确定吗？"
    keyboard = [[InlineKeyboardButton("‼️ 确认删除", callback_data=f"admin_tag_delete_{tag_id}")], [InlineKeyboardButton("🔙 返回列表", callback_data=f"admin_tags_remove_menu_{page}")]]
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def execute_tag_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int):
    query = update.callback_query
    await db_execute("DELETE FROM tags WHERE id = $1", tag_id)
    await query.answer("✅ 标签已移除", show_alert=True)
    await remove_tag_menu(update, context, 1)

async def list_all_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    reco_tags = await db_fetch_all("SELECT name FROM tags WHERE type = 'recommend' ORDER BY name")
    block_tags = await db_fetch_all("SELECT name FROM tags WHERE type = 'block' ORDER BY name")
    message = "📋 **所有标签列表**\n\n"
    if reco_tags: message += "👍 **推荐:** " + ", ".join(f"`{t['name']}`" for t in reco_tags) + "\n\n"
    if block_tags: message += "👎 **警告:** " + ", ".join(f"`{t['name']}`" for t in block_tags)
    if not reco_tags and not block_tags: message += "暂无标签。"
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]]), parse_mode=ParseMode.MARKDOWN)

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("➕ **添加管理员**\n\n请在私聊中发送用户ID：\n\n*(发送 /cancel 可取消)*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]]), parse_mode=ParseMode.MARKDOWN)
    context.user_data['waiting_for'] = 'new_admin_id'

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    admins = await db_fetch_all("SELECT id, username, first_name FROM users WHERE is_admin = TRUE ORDER BY id")
    message = "👑 **管理员列表**\n\n" + ("\n".join(f"• `{admin['first_name'] or admin['username'] or admin['id']}` (ID: `{admin['id']}`)" for admin in admins) if admins else "暂无管理员。")
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]]), parse_mode=ParseMode.MARKDOWN)

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    query = update.callback_query; await query.answer()
    offset = (page - 1) * ITEMS_PER_PAGE
    creator_id = int(environ.get("CREATOR_ID", 0))
    admins = await db_fetch_all("SELECT id, username, first_name FROM users WHERE is_admin = TRUE AND id != $1 ORDER BY id LIMIT $2 OFFSET $3", creator_id, ITEMS_PER_PAGE, offset)
    total = await db_fetchval("SELECT COUNT(*) FROM users WHERE is_admin = TRUE AND id != $1", creator_id) or 0
    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE or 1
    if not admins and page == 1:
        await query.edit_message_text("➖ **移除管理员**\n\n没有可移除的管理员。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]]))
        return
    message = f"➖ **移除管理员** (第{page}/{total_pages}页)\n\n请选择要移除权限的用户："
    keyboard = [[InlineKeyboardButton(f"👤 {admin['first_name'] or admin['username'] or admin['id']}", callback_data=f"admin_perms_remove_confirm_{admin['id']}_{page}")] for admin in admins]
    nav = []
    if page > 1: nav.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin_perms_remove_menu_{page-1}"))
    if page < total_pages: nav.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"admin_perms_remove_menu_{page+1}"))
    if nav: keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")])
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def remove_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id: int, page: int):
    query = update.callback_query; await query.answer()
    admin = await db_fetch_one("SELECT first_name, username FROM users WHERE id = $1", admin_id)
    if not admin: await query.edit_message_text("❌ 用户不存在。", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]])); return
    name = admin['first_name'] or admin['username'] or admin_id
    message = f"⚠️ **确认移除管理员权限**\n\n用户: **{name}** (ID: `{admin_id}`)\n\n确定移除吗？"
    keyboard = [[InlineKeyboardButton("‼️ 确认移除", callback_data=f"admin_remove_admin_{admin_id}")], [InlineKeyboardButton("🔙 返回列表", callback_data=f"admin_perms_remove_menu_{page}")]]
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def execute_admin_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id: int):
    query = update.callback_query
    await db_execute("UPDATE users SET is_admin = FALSE WHERE id = $1", admin_id)
    await query.answer("✅ 管理员权限已移除", show_alert=True)
    await remove_admin_menu(update, context, 1)

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    query = update.callback_query; await query.answer()
    prompts = {'admin_password': '管理员密码', 'auto_delete_timeout': '消息自动消失时间 (秒)'}
    message = f"⚙️ **设置{prompts.get(key, key)}**\n\n请在私聊中发送新的值：\n\n*(发送 /cancel 可取消)*"
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_system")]]), parse_mode=ParseMode.MARKDOWN)
    context.user_data.update({'waiting_for': 'setting_value', 'setting_key': key})

async def set_start_message_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    await query.edit_message_text("📝 **设置开始消息**\n\n请在私聊中发送新的内容(支持Markdown)：\n\n*(发送 /cancel 可取消)*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_system")]]), parse_mode=ParseMode.MARKDOWN)
    context.user_data['waiting_for'] = 'start_message'

async def show_all_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    text = "📖 **命令手册**\n\n**通用:**\n`/start`, `/help` - 主菜单\n`/myfavorites` - 我的收藏\n`/cancel` - 取消操作\n\n**群组:**\n`@用户` - 查询声誉\n\n**私聊:**\n`查询 @用户` - 查询声誉\n\n**管理员:**\n`/godmode [密码]` - 紧急授权"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]]), parse_mode=ParseMode.MARKDOWN)
    await schedule_message_deletion(context, query.message.chat.id, query.message.message_id)

# ============= 输入处理函数 =============

async def process_new_recommend_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tag_name = update.message.text.strip()
    try:
        if await db_fetch_one("SELECT id FROM tags WHERE name = $1", tag_name): await update.message.reply_text(f"❌ 标签 '{tag_name}' 已存在。"); return
        await db_execute("INSERT INTO tags (name, type) VALUES ($1, 'recommend')", tag_name)
        await update.message.reply_text(f"✅ 推荐标签 '{tag_name}' 添加成功！")
    except Exception as e: logger.error(f"添加推荐标签失败: {e}"); await update.message.reply_text("❌ 添加失败。")

async def process_new_block_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tag_name = update.message.text.strip()
    try:
        if await db_fetch_one("SELECT id FROM tags WHERE name = $1", tag_name): await update.message.reply_text(f"❌ 标签 '{tag_name}' 已存在。"); return
        await db_execute("INSERT INTO tags (name, type) VALUES ($1, 'block')", tag_name)
        await update.message.reply_text(f"✅ 警告标签 '{tag_name}' 添加成功！")
    except Exception as e: logger.error(f"添加警告标签失败: {e}"); await update.message.reply_text("❌ 添加失败。")

async def process_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admin_id = int(update.message.text.strip())
        if await db_fetch_one("SELECT id FROM users WHERE id = $1 AND is_admin = TRUE", admin_id): await update.message.reply_text(f"❌ 用户 {admin_id} 已经是管理员。"); return
        await db_execute("INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE", admin_id)
        await update.message.reply_text(f"✅ 用户 {admin_id} 已被设为管理员！")
    except ValueError: await update.message.reply_text("❌ 请输入有效的用户ID。")
    except Exception as e: logger.error(f"添加管理员失败: {e}"); await update.message.reply_text("❌ 添加失败。")

async def process_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    value = update.message.text.strip()
    key = context.user_data.get('setting_key')
    if key == 'auto_delete_timeout' and (not value.isdigit() or int(value) < 0): await update.message.reply_text("❌ 无效输入, 时间必须为非负整数。"); return
    try:
        await set_setting(key, value)
        key_names = {'admin_password': '管理员密码', 'auto_delete_timeout': '消息自动消失时间'}
        await update.message.reply_text(f"✅ {key_names.get(key, key)} 已更新！")
        logger.info(f"管理员 {update.effective_user.id} 更新了设置 {key}")
    except Exception as e: logger.error(f"更新设置失败: {e}"); await update.message.reply_text("❌ 更新失败。")

async def process_start_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await set_setting('start_message', update.message.text_html)
        await update.message.reply_text("✅ 开始消息已更新！")
        logger.info(f"管理员 {update.effective_user.id} 更新了开始消息")
    except Exception as e: logger.error(f"更新开始消息失败: {e}"); await update.message.reply_text("❌ 更新失败。")

async def process_leaderboard_removal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(update.message.text.strip())
        await db_execute("DELETE FROM votes WHERE target_user_id = $1", user_id)
        await update.message.reply_text(f"✅ 用户 {user_id} 收到的所有评价已被清空！")
        logger.info(f"管理员 {update.effective_user.id} 从排行榜移除了用户 {user_id}")
        clear_leaderboard_cache()
    except ValueError: await update.message.reply_text("❌ 请输入有效的用户ID。")
    except Exception as e: logger.error(f"从排行榜移除用户失败: {e}"); await update.message.reply_text("❌ 移除失败。")
