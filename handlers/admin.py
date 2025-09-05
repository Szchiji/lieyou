import logging
import re
from typing import Optional, List, Dict, Any
import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import (
    db_transaction, db_execute, db_fetch_all, db_fetch_one, db_fetchval,
    update_user_activity, is_admin, get_setting, set_setting,
    add_mottos_batch, get_all_mottos
)

logger = logging.getLogger(__name__)

# ============= 主要导入函数 =============

async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员输入"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        return
    
    waiting_for = context.user_data.get('waiting_for')
    
    if waiting_for == 'new_tag_name':
        await process_new_tag(update, context)
    elif waiting_for == 'admin_password':
        await process_password_change(update, context)
    elif waiting_for == 'user_id_search':
        await process_user_search(update, context)
    elif waiting_for == 'motto_content':
        await process_motto_input(update, context)
    elif waiting_for == 'broadcast_message':
        await process_broadcast_input(update, context)
    elif waiting_for == 'new_recommend_tag':
        await process_new_recommend_tag(update, context)
    elif waiting_for == 'new_block_tag':
        await process_new_block_tag(update, context)
    elif waiting_for == 'new_admin_id':
        await process_new_admin(update, context)
    elif waiting_for == 'setting_value':
        await process_setting_value(update, context)
    elif waiting_for == 'start_message':
        await process_start_message(update, context)
    elif waiting_for == 'leaderboard_user_id':
        await process_leaderboard_removal(update, context)

async def god_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """神谕模式命令 - 使用密码获取管理员权限"""
    user_id = update.effective_user.id
    
    # 更新用户活动
    await update_user_activity(user_id, update.effective_user.username, update.effective_user.first_name)
    
    # 检查是否已经是管理员
    if await is_admin(user_id):
        await update.message.reply_text("✨ 你已经拥有守护者权限。")
        return
    
    # 检查是否提供了密码
    if not context.args:
        await update.message.reply_text("🔐 请提供神谕密钥。\n\n使用方法: `/godmode 密码`")
        return
    
    # 获取系统密码
    system_password = await get_setting('admin_password') or "oracleadmin"
    provided_password = context.args[0]
    
    if provided_password != system_password:
        await update.message.reply_text("❌ 神谕密钥不正确。")
        logger.warning(f"用户 {user_id} 尝试使用错误密码获取管理员权限")
        return
    
    # 授予管理员权限
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
    """显示管理员设置菜单"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    message = "🌌 **时空枢纽** - 管理中心\n\n选择要管理的功能："
    
    keyboard = [
        [InlineKeyboardButton("🏷️ 标签管理", callback_data="admin_panel_tags")],
        [InlineKeyboardButton("📝 便签管理", callback_data="admin_panel_mottos")],
        [InlineKeyboardButton("👑 权限管理", callback_data="admin_panel_permissions")],
        [InlineKeyboardButton("⚙️ 系统设置", callback_data="admin_panel_system")],
        [InlineKeyboardButton("🏆 排行榜管理", callback_data="admin_leaderboard_panel")],
        [InlineKeyboardButton("📋 查看所有命令", callback_data="admin_show_commands")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# ============= 面板函数 =============

async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """标签面板 - 显示标签管理界面"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    try:
        await update.callback_query.answer()
        
        # 获取标签统计
        recommend_count = await db_fetchval("SELECT COUNT(*) FROM tags WHERE type = 'recommend'")
        block_count = await db_fetchval("SELECT COUNT(*) FROM tags WHERE type = 'block'")
        
        message = f"""🏷️ **标签管理面板**

📊 **统计信息**
• 推荐标签: {recommend_count}个
• 警告标签: {block_count}个
• 总标签数: {recommend_count + block_count}个
"""
        
        keyboard = [
            [InlineKeyboardButton("➕ 添加推荐标签", callback_data="admin_tags_add_recommend_prompt")],
            [InlineKeyboardButton("⚠️ 添加警告标签", callback_data="admin_tags_add_block_prompt")],
            [InlineKeyboardButton("📋 查看所有标签", callback_data="admin_tags_list")],
            [InlineKeyboardButton("🗑️ 删除标签", callback_data="admin_tags_remove_menu_1")],
            [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"标签面板显示失败: {e}")
        await update.callback_query.edit_message_text(
            "❌ 加载标签面板失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]])
        )

async def mottos_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """便签面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    try:
        await update.callback_query.answer()
        
        # 获取便签统计
        total_mottos = await db_fetchval("SELECT COUNT(*) FROM mottos")
        
        message = f"""📝 **便签管理面板**

📊 **统计信息**
• 总便签数: {total_mottos}个
"""
        
        keyboard = [
            [InlineKeyboardButton("➕ 添加便签", callback_data="admin_add_motto_prompt")],
            [InlineKeyboardButton("📋 查看所有便签", callback_data="admin_list_mottos")],
            [InlineKeyboardButton("🗑️ 删除便签", callback_data="admin_remove_motto_menu_1")],
            [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"便签面板显示失败: {e}")
        await update.callback_query.edit_message_text(
            "❌ 加载便签面板失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]])
        )

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """权限面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    try:
        await update.callback_query.answer()
        
        # 获取管理员统计
        admin_count = await db_fetchval("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
        
        message = f"""👑 **权限管理面板**

📊 **统计信息**
• 当前管理员: {admin_count}人
"""
        
        keyboard = [
            [InlineKeyboardButton("➕ 添加管理员", callback_data="admin_perms_add_prompt")],
            [InlineKeyboardButton("👥 查看管理员列表", callback_data="admin_perms_list")],
            [InlineKeyboardButton("➖ 移除管理员", callback_data="admin_perms_remove_menu")],
            [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"权限面板显示失败: {e}")
        await update.callback_query.edit_message_text(
            "❌ 加载权限面板失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]])
        )

async def system_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """系统设置面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    try:
        await update.callback_query.answer()
        
        message = """⚙️ **系统设置面板**

配置系统参数和消息内容。
"""
        
        keyboard = [
            [InlineKeyboardButton("📝 设置开始消息", callback_data="admin_system_set_start_message")],
            [InlineKeyboardButton("🔐 设置管理密码", callback_data="admin_system_set_prompt_admin_password")],
            [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"系统设置面板显示失败: {e}")
        await update.callback_query.edit_message_text(
            "❌ 加载系统设置面板失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]])
        )

async def leaderboard_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """排行榜管理面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    try:
        await update.callback_query.answer()
        
        message = """🏆 **排行榜管理面板**

管理排行榜数据和缓存。
"""
        
        keyboard = [
            [InlineKeyboardButton("🗑️ 从排行榜移除用户", callback_data="admin_leaderboard_remove_prompt")],
            [InlineKeyboardButton("🔄 清除缓存", callback_data="admin_leaderboard_clear_cache")],
            [InlineKeyboardButton("📊 选择性移除", callback_data="admin_selective_remove_menu")],
            [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"排行榜面板显示失败: {e}")
        await update.callback_query.edit_message_text(
            "❌ 加载排行榜面板失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]])
        )

# ============= 标签管理功能 =============

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    """添加标签提示"""
    query = update.callback_query
    await query.answer()
    
    type_name = "推荐" if tag_type == "recommend" else "警告"
    
    message = f"➕ **添加{type_name}标签**\n\n请发送标签名称："
    
    keyboard = [
        [InlineKeyboardButton("❌ 取消", callback_data="admin_panel_tags")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置状态等待用户输入
    context.user_data['waiting_for'] = f'new_{tag_type}_tag'
    context.user_data['tag_type'] = tag_type

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    """标签删除菜单"""
    query = update.callback_query
    await query.answer()
    
    try:
        # 获取所有标签，分页显示
        per_page = 10
        offset = (page - 1) * per_page
        
        tags = await db_fetch_all(
            "SELECT id, name, type FROM tags ORDER BY type, name LIMIT $1 OFFSET $2",
            per_page, offset
        )
        
        total_count = await db_fetchval("SELECT COUNT(*) FROM tags")
        total_pages = (total_count + per_page - 1) // per_page
        
        if not tags:
            message = "📋 **删除标签**\n\n暂无标签可删除。"
            keyboard = [[InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")]]
        else:
            message = f"🗑️ **删除标签** (第{page}/{total_pages}页)\n\n请选择要删除的标签："
            
            keyboard = []
            for tag in tags:
                type_emoji = "✅" if tag['type'] == 'recommend' else "⚠️"
                keyboard.append([InlineKeyboardButton(
                    f"{type_emoji} {tag['name']}",
                    callback_data=f"admin_tags_remove_confirm_{tag['id']}_{page}"
                )])
            
            # 分页按钮
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin_tags_remove_menu_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"admin_tags_remove_menu_{page+1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"显示标签删除菜单失败: {e}")
        await query.edit_message_text(
            "❌ 加载标签列表失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]])
        )

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    """确认删除标签"""
    query = update.callback_query
    await query.answer()
    
    try:
        # 获取标签信息
        tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE id = $1", tag_id)
        
        if not tag_info:
            await query.edit_message_text(
                "❌ 标签不存在或已被删除。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")
                ]]),
                parse_mode='Markdown'
            )
            return
        
        type_name = "推荐" if tag_info['type'] == 'recommend' else "警告"
        message = f"⚠️ **确认删除{type_name}标签**\n\n标签名称: **{tag_info['name']}**\n\n此操作不可撤销，确定要删除吗？"
        
        keyboard = [
            [InlineKeyboardButton("✅ 确认删除", callback_data=f"admin_tag_delete_{tag_id}")],
            [InlineKeyboardButton("❌ 取消", callback_data=f"admin_tags_remove_menu_{page}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"确认删除标签失败: {e}")
        await query.edit_message_text(
            "❌ 操作失败，请重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")
            ]]),
            parse_mode='Markdown'
        )

async def list_all_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有标签"""
    query = update.callback_query
    await query.answer()
    
    try:
        # 分别获取推荐和警告标签
        recommend_tags = await db_fetch_all(
            "SELECT name FROM tags WHERE type = 'recommend' ORDER BY name"
        )
        block_tags = await db_fetch_all(
            "SELECT name FROM tags WHERE type = 'block' ORDER BY name"
        )
        
        message = "📋 **所有标签列表**\n\n"
        
        if recommend_tags:
            message += "✅ **推荐标签:**\n"
            for tag in recommend_tags:
                message += f"• {tag['name']}\n"
            message += "\n"
        
        if block_tags:
            message += "⚠️ **警告标签:**\n"
            for tag in block_tags:
                message += f"• {tag['name']}\n"
        
        if not recommend_tags and not block_tags:
            message += "暂无标签。"
        
        keyboard = [[InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"查看标签列表失败: {e}")
        await query.edit_message_text(
            "❌ 获取标签列表失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]])
        )

# ============= 便签管理功能 =============

async def add_motto_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加便签提示"""
    query = update.callback_query
    await query.answer()
    
    message = "➕ **添加便签**\n\n请发送便签内容："
    
    keyboard = [
        [InlineKeyboardButton("❌ 取消", callback_data="admin_panel_mottos")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置状态等待用户输入
    context.user_data['waiting_for'] = 'motto_content'

async def list_mottos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有便签"""
    query = update.callback_query
    await query.answer()
    
    try:
        mottos = await db_fetch_all("SELECT id, content FROM mottos ORDER BY id")
        
        if not mottos:
            message = "📋 **所有便签列表**\n\n暂无便签。"
        else:
            message = "📋 **所有便签列表**\n\n"
            for motto in mottos:
                content_preview = motto['content'][:50] + ('...' if len(motto['content']) > 50 else '')
                message += f"**{motto['id']}.** {content_preview}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 返回便签管理", callback_data="admin_panel_mottos")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"查看便签列表失败: {e}")
        await query.edit_message_text(
            "❌ 获取便签列表失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")]])
        )

async def remove_motto_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int):
    """便签删除菜单"""
    query = update.callback_query
    await query.answer()
    
    try:
        # 获取所有便签，分页显示
        per_page = 10
        offset = (page - 1) * per_page
        
        mottos = await db_fetch_all(
            "SELECT id, content FROM mottos ORDER BY id LIMIT $1 OFFSET $2",
            per_page, offset
        )
        
        total_count = await db_fetchval("SELECT COUNT(*) FROM mottos")
        total_pages = (total_count + per_page - 1) // per_page
        
        if not mottos:
            message = "📋 **删除便签**\n\n暂无便签可删除。"
            keyboard = [[InlineKeyboardButton("🔙 返回便签管理", callback_data="admin_panel_mottos")]]
        else:
            message = f"🗑️ **删除便签** (第{page}/{total_pages}页)\n\n请选择要删除的便签："
            
            keyboard = []
            for motto in mottos:
                content_preview = motto['content'][:30] + ('...' if len(motto['content']) > 30 else '')
                keyboard.append([InlineKeyboardButton(
                    f"{motto['id']}. {content_preview}",
                    callback_data=f"admin_motto_delete_confirm_{motto['id']}_{page}"
                )])
            
            # 分页按钮
            nav_buttons = []
            if page > 1:
                nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"admin_remove_motto_menu_{page-1}"))
            if page < total_pages:
                nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"admin_remove_motto_menu_{page+1}"))
            
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            keyboard.append([InlineKeyboardButton("🔙 返回便签管理", callback_data="admin_panel_mottos")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"显示便签删除菜单失败: {e}")
        await query.edit_message_text(
            "❌ 加载便签列表失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")]])
        )

async def confirm_motto_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, motto_id: int, page: int):
    """确认删除便签"""
    query = update.callback_query
    await query.answer()
    
    try:
        # 获取便签信息
        motto = await db_fetch_one("SELECT content FROM mottos WHERE id = $1", motto_id)
        
        if not motto:
            await query.edit_message_text(
                "❌ 便签不存在或已被删除。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")
                ]]),
                parse_mode='Markdown'
            )
            return
        
        content_preview = motto['content'][:100] + ('...' if len(motto['content']) > 100 else '')
        message = f"⚠️ **确认删除便签**\n\n便签内容: **{content_preview}**\n\n此操作不可撤销，确定要删除吗？"
        
        keyboard = [
            [InlineKeyboardButton("✅ 确认删除", callback_data=f"admin_motto_delete_{motto_id}")],
            [InlineKeyboardButton("❌ 取消", callback_data=f"admin_remove_motto_menu_{page}")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"确认删除便签失败: {e}")
        await query.edit_message_text(
            "❌ 操作失败，请重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")
            ]]),
            parse_mode='Markdown'
        )

async def execute_motto_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, motto_id: int):
    """执行便签删除"""
    query = update.callback_query
    
    try:
        # 获取便签信息
        motto = await db_fetch_one("SELECT content FROM mottos WHERE id = $1", motto_id)
        
        if not motto:
            await query.edit_message_text(
                "❌ 便签不存在或已被删除。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")
                ]]),
                parse_mode='Markdown'
            )
            return
        
        # 删除便签
        await db_execute("DELETE FROM mottos WHERE id = $1", motto_id)
        
        content_preview = motto['content'][:50] + ('...' if len(motto['content']) > 50 else '')
        message = f"✅ **便签删除成功**\n\n便签 **{content_preview}** 已被删除。"
        
        keyboard = [[InlineKeyboardButton("🔙 返回便签管理", callback_data="admin_panel_mottos")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        logger.info(f"管理员 {update.effective_user.id} 删除了便签 {motto_id}")
        
    except Exception as e:
        logger.error(f"删除便签失败: {e}")
        await query.edit_message_text(
            "❌ 删除便签失败，请重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")
            ]]),
            parse_mode='Markdown'
        )

# ============= 权限管理功能 =============

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加管理员提示"""
    query = update.callback_query
    await query.answer()
    
    message = "➕ **添加管理员**\n\n请发送要添加为管理员的用户ID："
    
    keyboard = [
        [InlineKeyboardButton("❌ 取消", callback_data="admin_panel_permissions")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置状态等待用户输入
    context.user_data['waiting_for'] = 'new_admin_id'

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看管理员列表"""
    query = update.callback_query
    await query.answer()
    
    try:
        admins = await db_fetch_all(
            "SELECT id, username, first_name FROM users WHERE is_admin = TRUE ORDER BY id"
        )
        
        if not admins:
            message = "👑 **管理员列表**\n\n暂无管理员。"
        else:
            message = "👑 **管理员列表**\n\n"
            for admin in admins:
                name = admin['first_name'] or admin['username'] or f"用户{admin['id']}"
                message += f"👤 **{name}** (ID: {admin['id']})\n"
        
        keyboard = [[InlineKeyboardButton("🔙 返回权限管理", callback_data="admin_panel_permissions")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"查看管理员列表失败: {e}")
        await query.edit_message_text(
            "❌ 获取管理员列表失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]])
        )

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """移除管理员菜单"""
    query = update.callback_query
    await query.answer()
    
    try:
        admins = await db_fetch_all(
            "SELECT id, username, first_name FROM users WHERE is_admin = TRUE ORDER BY id"
        )
        
        if not admins:
            message = "➖ **移除管理员**\n\n暂无管理员可移除。"
            keyboard = [[InlineKeyboardButton("🔙 返回权限管理", callback_data="admin_panel_permissions")]]
        else:
            message = "➖ **移除管理员**\n\n请选择要移除管理员权限的用户："
            
            keyboard = []
            for admin in admins:
                name = admin['first_name'] or admin['username'] or f"用户{admin['id']}"
                keyboard.append([InlineKeyboardButton(
                    f"👤 {name} (ID: {admin['id']})",
                    callback_data=f"admin_perms_remove_confirm_{admin['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔙 返回权限管理", callback_data="admin_panel_permissions")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"显示移除管理员菜单失败: {e}")
        await query.edit_message_text(
            "❌ 加载管理员列表失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]])
        )

async def remove_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id: int):
    """确认移除管理员"""
    query = update.callback_query
    await query.answer()
    
    try:
        # 获取管理员信息
        admin_info = await db_fetch_one(
            "SELECT username, first_name FROM users WHERE id = $1 AND is_admin = TRUE",
            admin_id
        )
        
        if not admin_info:
            await query.edit_message_text(
                "❌ 用户不存在或不是管理员。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")
                ]]),
                parse_mode='Markdown'
            )
            return
        
        name = admin_info['first_name'] or admin_info['username'] or f"用户{admin_id}"
        message = f"⚠️ **确认移除管理员权限**\n\n用户: **{name}** (ID: {admin_id})\n\n确定要移除此用户的管理员权限吗？"
        
        keyboard = [
            [InlineKeyboardButton("✅ 确认移除", callback_data=f"admin_remove_admin_{admin_id}")],
            [InlineKeyboardButton("❌ 取消", callback_data="admin_perms_remove_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"确认移除管理员失败: {e}")
        await query.edit_message_text(
            "❌ 操作失败，请重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")
            ]]),
            parse_mode='Markdown'
        )

# ============= 系统设置功能 =============

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str):
    """设置参数提示"""
    query = update.callback_query
    await query.answer()
    
    key_names = {
        'admin_password': '管理员密码',
    }
    
    key_name = key_names.get(key, key)
    message = f"⚙️ **设置{key_name}**\n\n请发送新的{key_name}："
    
    keyboard = [
        [InlineKeyboardButton("❌ 取消", callback_data="admin_panel_system")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置状态等待用户输入
    context.user_data['waiting_for'] = 'setting_value'
    context.user_data['setting_key'] = key

async def set_start_message_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置开始消息提示"""
    query = update.callback_query
    await query.answer()
    
    message = "📝 **设置开始消息**\n\n请发送新的开始消息内容："
    
    keyboard = [
        [InlineKeyboardButton("❌ 取消", callback_data="admin_panel_system")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置状态等待用户输入
    context.user_data['waiting_for'] = 'start_message'

async def show_all_commands(update: Update, context: ContextTypes.DEFAULT_TYPE, from_command: bool = False):
    """显示所有管理员命令"""
    commands_text = """📋 **管理员命令大全**

🔐 **权限管理**
• `/godmode <密码>` - 获取管理员权限

📝 **快速命令**
• `/commands` - 显示此帮助
• `/cancel` - 取消当前操作
• `/myfavorites` - 查看我的收藏

🌌 **管理面板**
• 使用 "时空枢纽" 按钮访问完整的管理功能
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回管理中心", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_content = {
        'text': commands_text,
        'reply_markup': reply_markup,
        'parse_mode': ParseMode.MARKDOWN
    }
    
    if from_command:
        await update.message.reply_text(**message_content)
    else:
        await update.callback_query.edit_message_text(**message_content)

# ============= 排行榜管理功能 =============

async def remove_from_leaderboard_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """从排行榜移除用户提示"""
    query = update.callback_query
    await query.answer()
    
    message = "🗑️ **从排行榜移除用户**\n\n请发送要移除的用户ID："
    
    keyboard = [
        [InlineKeyboardButton("❌ 取消", callback_data="admin_leaderboard_panel")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置状态等待用户输入
    context.user_data['waiting_for'] = 'leaderboard_user_id'

async def selective_remove_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int):
    """选择性移除菜单"""
    query = update.callback_query
    await query.answer()
    
    try:
        # 模拟获取排行榜用户数据
        message = f"📊 **选择性移除** - {board_type.upper()}榜 (第{page}页)\n\n暂无用户数据。"
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回排行榜管理", callback_data="admin_leaderboard_panel")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"显示选择性移除菜单失败: {e}")
        await query.edit_message_text(
            "❌ 加载用户列表失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_leaderboard_panel")]])
        )

async def confirm_user_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id_to_remove: int, board_type: str, page: int):
    """确认用户移除"""
    query = update.callback_query
    await query.answer()
    
    message = f"⚠️ **确认移除用户**\n\n用户ID: {user_id_to_remove}\n\n请选择移除类型："
    
    keyboard = [
        [InlineKeyboardButton("🗑️ 仅移除已收到评价", callback_data=f"admin_remove_user_received_{user_id_to_remove}_{board_type}_{page}")],
        [InlineKeyboardButton("💥 移除所有相关数据", callback_data=f"admin_remove_user_all_{user_id_to_remove}_{board_type}_{page}")],
        [InlineKeyboardButton("❌ 取消", callback_data=f"admin_selective_remove_{board_type}_{page}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def execute_user_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id_to_remove: int, removal_type: str, board_type: str, page: int):
    """执行用户移除"""
    query = update.callback_query
    
    try:
        if removal_type == "received":
            # 只移除用户收到的评价
            await db_execute("DELETE FROM votes WHERE target_id = $1", user_id_to_remove)
            message = f"✅ **移除成功**\n\n已移除用户 {user_id_to_remove} 收到的所有评价。"
        elif removal_type == "all":
            # 移除用户的所有相关数据
            await db_execute("DELETE FROM votes WHERE target_id = $1 OR voter_id = $1", user_id_to_remove)
            await db_execute("DELETE FROM favorites WHERE user_id = $1", user_id_to_remove)
            message = f"✅ **移除成功**\n\n已移除用户 {user_id_to_remove} 的所有相关数据。"
        else:
            message = "❌ 无效的移除类型。"
        
        keyboard = [[InlineKeyboardButton("🔙 返回排行榜管理", callback_data="admin_leaderboard_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"管理员 {update.effective_user.id} 执行了用户 {user_id_to_remove} 的{removal_type}移除")
        
    except Exception as e:
        logger.error(f"执行用户移除失败: {e}")
        await query.edit_message_text(
            "❌ 移除失败，请重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_leaderboard_panel")
            ]]),
            parse_mode='Markdown'
        )

# ============= 输入处理函数 =============

async def process_new_recommend_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新推荐标签输入"""
    if context.user_data.get('waiting_for') != 'new_recommend_tag':
        return
    
    tag_name = update.message.text.strip()
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        # 检查标签是否已存在
        existing_tag = await db_fetch_one(
            "SELECT id FROM tags WHERE name = $1",
            tag_name
        )
        
        if existing_tag:
            await update.message.reply_text(f"❌ 标签 '{tag_name}' 已存在。")
            return
        
        # 添加新标签
        await db_execute(
            "INSERT INTO tags (name, type, created_by) VALUES ($1, 'recommend', $2)",
            tag_name, user_id
        )
        
        await update.message.reply_text(f"✅ 推荐标签 '{tag_name}' 添加成功！")
        
        # 清除等待状态
        context.user_data.pop('waiting_for', None)
        context.user_data.pop('tag_type', None)
        
    except Exception as e:
        logger.error(f"添加推荐标签失败: {e}")
        await update.message.reply_text("❌ 添加标签失败，请稍后重试。")

async def process_new_block_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新警告标签输入"""
    if context.user_data.get('waiting_for') != 'new_block_tag':
        return
    
    tag_name = update.message.text.strip()
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        # 检查标签是否已存在
        existing_tag = await db_fetch_one(
            "SELECT id FROM tags WHERE name = $1",
            tag_name
        )
        
        if existing_tag:
            await update.message.reply_text(f"❌ 标签 '{tag_name}' 已存在。")
            return
        
        # 添加新标签
        await db_execute(
            "INSERT INTO tags (name, type, created_by) VALUES ($1, 'block', $2)",
            tag_name, user_id
        )
        
        await update.message.reply_text(f"✅ 警告标签 '{tag_name}' 添加成功！")
        
        # 清除等待状态
        context.user_data.pop('waiting_for', None)
        context.user_data.pop('tag_type', None)
        
    except Exception as e:
        logger.error(f"添加警告标签失败: {e}")
        await update.message.reply_text("❌ 添加标签失败，请稍后重试。")

async def process_motto_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理便签输入"""
    if context.user_data.get('waiting_for') != 'motto_content':
        return
    
    content = update.message.text.strip()
    user_id = update.effective_user.id
    
    try:
        await db_execute(
            "INSERT INTO mottos (content, created_by) VALUES ($1, $2)",
            content, user_id
        )
        
        await update.message.reply_text(f"✅ 便签添加成功！")
        context.user_data.pop('waiting_for', None)
        
    except Exception as e:
        logger.error(f"添加便签失败: {e}")
        await update.message.reply_text("❌ 添加便签失败，请稍后重试。")

async def process_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新管理员输入"""
    if context.user_data.get('waiting_for') != 'new_admin_id':
        return
    
    admin_id_text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        admin_id = int(admin_id_text)
        
        # 检查用户是否已经是管理员
        existing_admin = await db_fetch_one(
            "SELECT id FROM users WHERE id = $1 AND is_admin = TRUE",
            admin_id
        )
        
        if existing_admin:
            await update.message.reply_text(f"❌ 用户 {admin_id} 已经是管理员。")
            return
        
        # 添加管理员权限
        await db_execute(
            "INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE",
            admin_id
        )
        
        await update.message.reply_text(f"✅ 用户 {admin_id} 已被添加为管理员！")
        
        # 清除等待状态
        context.user_data.pop('waiting_for', None)
        
    except ValueError:
        await update.message.reply_text("❌ 请输入有效的用户ID（数字）。")
    except Exception as e:
        logger.error(f"添加管理员失败: {e}")
        await update.message.reply_text("❌ 添加管理员失败，请稍后重试。")

async def process_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理设置值输入"""
    if context.user_data.get('waiting_for') != 'setting_value':
        return
    
    value = update.message.text.strip()
    key = context.user_data.get('setting_key')
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        await set_setting(key, value)
        
        key_names = {
            'admin_password': '管理员密码',
        }
        
        key_name = key_names.get(key, key)
        await update.message.reply_text(f"✅ {key_name}已更新！")
        
        # 清除等待状态
        context.user_data.pop('waiting_for', None)
        context.user_data.pop('setting_key', None)
        
        logger.info(f"管理员 {user_id} 更新了设置 {key}")
        
    except Exception as e:
        logger.error(f"更新设置失败: {e}")
        await update.message.reply_text("❌ 更新设置失败，请稍后重试。")

async def process_start_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理开始消息输入"""
    if context.user_data.get('waiting_for') != 'start_message':
        return
    
    message = update.message.text.strip()
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        await set_setting('start_message', message)
        await update.message.reply_text("✅ 开始消息已更新！")
        
        # 清除等待状态
        context.user_data.pop('waiting_for', None)
        
        logger.info(f"管理员 {user_id} 更新了开始消息")
        
    except Exception as e:
        logger.error(f"更新开始消息失败: {e}")
        await update.message.reply_text("❌ 更新开始消息失败，请稍后重试。")

async def process_leaderboard_removal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理排行榜移除输入"""
    if context.user_data.get('waiting_for') != 'leaderboard_user_id':
        return
    
    user_id_text = update.message.text.strip()
    admin_id = update.effective_user.id
    
    if not await is_admin(admin_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        user_id = int(user_id_text)
        
        # 移除用户的所有评价
        result = await db_execute("DELETE FROM votes WHERE target_id = $1", user_id)
        
        await update.message.reply_text(f"✅ 用户 {user_id} 已从排行榜中移除！")
        
        # 清除等待状态
        context.user_data.pop('waiting_for', None)
        
        logger.info(f"管理员 {admin_id} 从排行榜移除了用户 {user_id}")
        
    except ValueError:
        await update.message.reply_text("❌ 请输入有效的用户ID（数字）。")
    except Exception as e:
        logger.error(f"从排行榜移除用户失败: {e}")
        await update.message.reply_text("❌ 移除失败，请稍后重试。")

# ============= 通用处理函数 =============

async def process_new_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新标签输入（兼容旧版本）"""
    waiting_for = context.user_data.get('waiting_for')
    if waiting_for == 'new_recommend_tag':
        await process_new_recommend_tag(update, context)
    elif waiting_for == 'new_block_tag':
        await process_new_block_tag(update, context)

async def process_broadcast_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理广播输入（占位符）"""
    if context.user_data.get('waiting_for') != 'broadcast_message':
        return
    
    await update.message.reply_text("📢 广播功能正在开发中...")
    context.user_data.pop('waiting_for', None)

async def process_password_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理密码修改（兼容旧版本）"""
    if context.user_data.get('waiting_for') != 'admin_password':
        return
    
    new_password = update.message.text.strip()
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        await set_setting('admin_password', new_password)
        await update.message.reply_text("✅ 管理员密码已更新！")
        
        context.user_data.pop('waiting_for', None)
        logger.info(f"管理员 {user_id} 修改了系统密码")
        
    except Exception as e:
        logger.error(f"修改密码失败: {e}")
        await update.message.reply_text("❌ 修改失败，请稍后重试。")

async def process_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户搜索（占位符）"""
    if context.user_data.get('waiting_for') != 'user_id_search':
        return
    
    search_term = update.message.text.strip()
    await update.message.reply_text("🔍 用户搜索功能正在开发中...")
    context.user_data.pop('waiting_for', None)

# ============= 导出所有函数 =============
__all__ = [
    # 主要导入函数
    'god_mode_command',
    'settings_menu', 
    'process_admin_input',
    
    # 面板函数
    'tags_panel', 
    'mottos_panel',
    'permissions_panel', 
    'system_settings_panel', 
    'leaderboard_panel',
    
    # 标签管理功能
    'add_tag_prompt', 
    'remove_tag_menu', 
    'remove_tag_confirm', 
    'list_all_tags',
    
    # 便签管理功能
    'add_motto_prompt',
    'list_mottos',
    'remove_motto_menu',
    'confirm_motto_deletion',
    'execute_motto_deletion',

    # 权限管理功能
    'add_admin_prompt', 
    'list_admins', 
    'remove_admin_menu', 
    'remove_admin_confirm',
    
    # 系统设置功能  
    'set_setting_prompt', 
    'set_start_message_prompt', 
    'show_all_commands',
    
    # 排行榜管理功能
    'remove_from_leaderboard_prompt',
    'selective_remove_menu',
    'confirm_user_removal',
    'execute_user_removal',
    
    # 输入处理函数
    'process_new_recommend_tag',
    'process_new_block_tag',
    'process_motto_input',
    'process_new_admin',
    'process_setting_value',
    'process_start_message',
    'process_leaderboard_removal',
    'process_new_tag',
    'process_broadcast_input',
    'process_password_change',
    'process_user_search'
]
