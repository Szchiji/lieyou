import logging
import json
from typing import List, Dict, Any, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_fetch_one, db_fetch_all, db_execute, db_transaction

logger = logging.getLogger(__name__)

async def is_admin(user_id: int) -> bool:
    """检查用户是否为管理员"""
    try:
        result = await db_fetch_one("SELECT is_admin FROM users WHERE id = $1", user_id)
        return bool(result and result['is_admin'])
    except Exception as e:
        logger.error(f"检查管理员状态失败: {e}", exc_info=True)
        return False

async def god_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """超级管理员模式，允许首次启动时设置管理员"""
    try:
        from os import environ
        creator_id = environ.get("CREATOR_ID")
        
        if not creator_id:
            await update.message.reply_text("❌ 创世神ID未配置，无法使用此功能。")
            return
        
        user_id = update.effective_user.id
        if str(user_id) != creator_id:
            await update.message.reply_text("❌ 你不是创世神，无权访问。")
            return
            
        # 为创世神授予管理员权限
        async with db_transaction() as conn:
            await conn.execute(
                """
                INSERT INTO users (id, is_admin) 
                VALUES ($1, TRUE) 
                ON CONFLICT (id) DO UPDATE SET is_admin = TRUE
                """, 
                int(creator_id)
            )
            
        await update.message.reply_text("✅ 创世神权限已恢复！你可以使用管理员功能了。")
    except Exception as e:
        logger.error(f"设置创世神权限失败: {e}", exc_info=True)
        await update.message.reply_text("❌ 设置权限时发生错误，请查看日志。")

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示管理员设置菜单"""
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 你不是管理员，无权访问此菜单。", show_alert=True)
        return
    
    keyboard = [
        [InlineKeyboardButton("🏷️ 标签管理", callback_data="admin_panel_tags")],
        [InlineKeyboardButton("👥 权限管理", callback_data="admin_panel_permissions")],
        [InlineKeyboardButton("⚙️ 系统设置", callback_data="admin_panel_system")],
        [InlineKeyboardButton("🏆 排行榜管理", callback_data="admin_leaderboard_panel")],
        [InlineKeyboardButton("📋 命令列表", callback_data="admin_show_all_commands")],
        [InlineKeyboardButton("« 返回", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🌌 **时空枢纽**\n\n请选择要管理的功能：",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            "🌌 **时空枢纽**\n\n请选择要管理的功能：",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

#
# 标签管理
#

async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """标签管理面板"""
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 你不是管理员", show_alert=True)
        return
        
    keyboard = [
        [InlineKeyboardButton("➕ 添加推荐标签", callback_data="admin_tags_add_recommend_prompt")],
        [InlineKeyboardButton("➕ 添加警告标签", callback_data="admin_tags_add_block_prompt")],
        [InlineKeyboardButton("➕ 添加箴言", callback_data="admin_tags_add_quote_prompt")],
        [InlineKeyboardButton("➕ 批量添加箴言", callback_data="admin_tags_add_multiple_quotes")],
        [InlineKeyboardButton("❌ 移除标签", callback_data="admin_tags_remove_menu_1")],
        [InlineKeyboardButton("📋 查看所有标签", callback_data="admin_tags_list")],
        [InlineKeyboardButton("« 返回设置菜单", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "🏷️ **标签管理**\n\n请选择操作：",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    """添加标签提示"""
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 你不是管理员", show_alert=True)
        return
    
    context.user_data['next_action'] = f"add_tag_{tag_type}"
    
    type_desc = "推荐" if tag_type == "recommend" else "警告" if tag_type == "block" else "箴言"
    await update.callback_query.edit_message_text(
        f"请发送要添加的{type_desc}标签内容\n\n"
        f"你可以随时使用 /cancel 取消操作。",
        reply_markup=None
    )

async def add_multiple_quotes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """批量添加箴言提示"""
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 你不是管理员", show_alert=True)
        return
    
    context.user_data['next_action'] = "add_multiple_quotes"
    
    await update.callback_query.edit_message_text(
        "请发送要批量添加的箴言内容，每行一条\n\n"
        "例如:\n箴言1\n箴言2\n箴言3\n\n"
        "你可以随时使用 /cancel 取消操作。",
        reply_markup=None
    )

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """移除标签菜单"""
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 你不是管理员", show_alert=True)
        return
    
    # 获取所有标签
    page_size = 5
    offset = (page - 1) * page_size
    
    tags = await db_fetch_all(
        """
        SELECT id, tag_type, content
        FROM tags
        ORDER BY tag_type, id
        LIMIT $1 OFFSET $2
        """,
        page_size, offset
    )
    
    total_count = await db_fetch_one("SELECT COUNT(*) FROM tags")
    total_count = total_count[0] if total_count else 0
    total_pages = (total_count + page_size - 1) // page_size
    
    # 生成标签列表
    keyboard = []
    for tag in tags:
        tag_id = tag['id']
        tag_type = "👍" if tag['tag_type'] == 'recommend' else "👎" if tag['tag_type'] == 'block' else "📜"
        content = tag['content']
        if len(content) > 20:
            content = content[:17] + "..."
        keyboard.append([InlineKeyboardButton(f"{tag_type} {content}", callback_data=f"admin_tags_remove_confirm_{tag_id}_{page}")])
    
    # 分页按钮
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton("« 上一页", callback_data=f"admin_tags_remove_menu_{page-1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("下一页 »", callback_data=f"admin_tags_remove_menu_{page+1}"))
    if nav_row:
        keyboard.append(nav_row)
    
    # 返回按钮
    keyboard.append([InlineKeyboardButton("« 返回标签管理", callback_data="admin_panel_tags")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"❌ **移除标签**\n\n"
        f"请选择要移除的标签 (第 {page}/{total_pages} 页):",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    """确认移除标签"""
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 你不是管理员", show_alert=True)
        return
    
    # 获取标签信息
    tag = await db_fetch_one("SELECT tag_type, content FROM tags WHERE id = $1", tag_id)
    if not tag:
        await update.callback_query.answer("❌ 标签不存在", show_alert=True)
        return
    
    tag_type_desc = "推荐" if tag['tag_type'] == 'recommend' else "警告" if tag['tag_type'] == 'block' else "箴言"
    content = tag['content']
    
    keyboard = [
        [InlineKeyboardButton("⚠️ 确认移除", callback_data=f"admin_confirm_remove_tag_{tag_id}")],
        [InlineKeyboardButton("« 返回", callback_data=f"admin_tags_remove_menu_{page}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"❓ **确认移除标签**\n\n"
        f"类型: {tag_type_desc}\n"
        f"内容: {content}\n\n"
        f"⚠️ 警告: 移除标签后，所有使用该标签的评价将被删除！",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def list_all_tags(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """列出所有标签"""
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 你不是管理员", show_alert=True)
        return
    
    # 获取所有标签
    tags = await db_fetch_all(
        """
        SELECT tag_type, content, 
            (SELECT COUNT(*) FROM reputation WHERE tag_id = tags.id) as usage_count
        FROM tags
        ORDER BY tag_type, content
        """
    )
    
    # 按类型分组
    recommend_tags = []
    block_tags = []
    quote_tags = []
    
    for tag in tags:
        entry = f"{tag['content']} ({tag['usage_count']}次)"
        if tag['tag_type'] == 'recommend':
            recommend_tags.append(entry)
        elif tag['tag_type'] == 'block':
            block_tags.append(entry)
        elif tag['tag_type'] == 'quote':
            quote_tags.append(entry)
    
    # 生成标签列表
    text = "📋 **所有标签列表**\n\n"
    
    text += "👍 **推荐标签**:\n"
    if recommend_tags:
        text += "\n".join(f"- {tag}" for tag in recommend_tags)
    else:
        text += "无"
    text += "\n\n"
    
    text += "👎 **警告标签**:\n"
    if block_tags:
        text += "\n".join(f"- {tag}" for tag in block_tags)
    else:
        text += "无"
    text += "\n\n"
    
    text += "📜 **箴言**:\n"
    if quote_tags:
        text += "\n".join(f"- {tag}" for tag in quote_tags[:10])
        if len(quote_tags) > 10:
            text += f"\n...等共 {len(quote_tags)} 条"
    else:
        text += "无"
    
    keyboard = [[InlineKeyboardButton("« 返回标签管理", callback_data="admin_panel_tags")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

#
# 权限管理
#

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """权限管理面板"""
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 你不是管理员", show_alert=True)
        return
        
    keyboard = [
        [InlineKeyboardButton("➕ 添加管理员", callback_data="admin_perms_add_prompt")],
        [InlineKeyboardButton("❌ 移除管理员", callback_data="admin_perms_remove_menu")],
        [InlineKeyboardButton("📋 查看所有管理员", callback_data="admin_perms_list")],
        [InlineKeyboardButton("« 返回设置菜单", callback_data="admin_settings_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        "👥 **权限管理**\n\n请选择操作：",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加管理员提示"""
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 你不是管理员", show_alert=True)
        return
    
    context.user_data['next_action'] = "add_admin"
    
    await update.callback_query.edit_message_text(
        "请发送要添加为管理员的
