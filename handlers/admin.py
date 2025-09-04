import logging
import re
from typing import Optional, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import (
    db_transaction, db_execute, db_fetch_all, db_fetch_one, db_fetchval,
    update_user_activity, is_admin, get_setting, set_setting,
    add_mottos_batch, get_all_mottos
)

logger = logging.getLogger(__name__)

async def god_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """神谕模式命令 - 使用密码获取管理员权限"""
    user_id = update.effective_user.id
    
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
            "INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE",
            user_id
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
        [InlineKeyboardButton("📜 箴言便签管理", callback_data="admin_panel_mottos")],
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

# === 标签管理相关函数 ===

async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """标签管理面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取标签统计
    total_tags = await db_fetchval("SELECT COUNT(*) FROM tags")
    recommend_tags = await db_fetchval("SELECT COUNT(*) FROM tags WHERE type = 'recommend'")
    block_tags = await db_fetchval("SELECT COUNT(*) FROM tags WHERE type = 'block'")
    
    message = "🏷️ **标签管理**\n\n"
    message += f"📊 **当前统计**:\n"
    message += f"• 推荐标签: {recommend_tags} 个\n"
    message += f"• 警告标签: {block_tags} 个\n"
    message += f"• 总标签数: {total_tags} 个\n\n"
    message += "选择操作："
    
    keyboard = [
        [
            InlineKeyboardButton("➕ 添加推荐标签", callback_data="admin_tags_add_recommend_prompt"),
            InlineKeyboardButton("➕ 添加警告标签", callback_data="admin_tags_add_block_prompt")
        ],
        [
            InlineKeyboardButton("❌ 删除标签", callback_data="admin_tags_remove_menu_1"),
            InlineKeyboardButton("📋 查看所有标签", callback_data="admin_tags_list")
        ],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
# 接上面的 handlers/admin.py 内容

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str):
    """提示添加标签"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    type_name = "推荐" if tag_type == "recommend" else "警告"
    
    message = f"➕ **添加{type_name}标签**\n\n"
    message += "请发送要添加的标签名称。支持以下格式：\n"
    message += "• 单个标签：`靠谱`\n"
    message += "• 多个标签（用换行或逗号分隔）：\n"
    message += "  ```\n  靠谱\n  诚信\n  专业\n  ```\n"
    message += "• 或者：`靠谱,诚信,专业`\n\n"
    message += "发送 /cancel 取消操作"
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置等待用户输入
    context.user_data['next_action'] = {
        'action': 'add_tags',
        'tag_type': tag_type
    }

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """标签删除菜单"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    per_page = 6
    offset = (page - 1) * per_page
    
    # 获取标签
    tags = await db_fetch_all("""
        SELECT id, name, type FROM tags
        ORDER BY type = 'recommend' DESC, name
        LIMIT $1 OFFSET $2
    """, per_page, offset)
    
    total_tags = await db_fetchval("SELECT COUNT(*) FROM tags")
    total_pages = (total_tags + per_page - 1) // per_page if total_tags > 0 else 1
    
    message = "❌ **删除标签**\n\n选择要删除的标签："
    
    keyboard = []
    
    if not tags:
        message += "\n暂无标签可删除。"
    else:
        # 标签按钮，每行2个
        for i in range(0, len(tags), 2):
            row = []
            for j in range(2):
                if i + j < len(tags):
                    tag = tags[i + j]
                    emoji = "🏅" if tag['type'] == 'recommend' else "⚠️"
                    row.append(InlineKeyboardButton(
                        f"{emoji} {tag['name']}",
                        callback_data=f"admin_tags_remove_confirm_{tag['id']}_{page}"
                    ))
            keyboard.append(row)
        
        # 分页按钮
        if total_pages > 1:
            nav_row = []
            if page > 1:
                nav_row.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"admin_tags_remove_menu_{page-1}"))
            if page < total_pages:
                nav_row.append(InlineKeyboardButton("▶️ 下一页", callback_data=f"admin_tags_remove_menu_{page+1}"))
            if nav_row:
                keyboard.append(nav_row)
    
    # 返回按钮
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id: int, page: int):
    """确认删除标签"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取标签信息和使用统计
    tag_info = await db_fetch_one("SELECT name, type FROM tags WHERE id = $1", tag_id)
    usage_count = await db_fetchval("SELECT COUNT(*) FROM reputations WHERE $1 = ANY(tag_ids)", tag_id)
    
    if not tag_info:
        await update.callback_query.edit_message_text(
            "❌ 标签不存在或已被删除。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data=f"admin_tags_remove_menu_{page}")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    type_name = "推荐" if tag_info['type'] == 'recommend' else "警告"
    
    message = f"⚠️ **确认删除{type_name}标签**\n\n"
    message += f"标签名称: **{tag_info['name']}**\n"
    
    if usage_count > 0:
        message += f"使用次数: **{usage_count}** 次\n\n"
        message += "❗ 删除后，所有使用此标签的评价将失去标签关联。"
    else:
        message += "使用次数: **0** 次\n\n"
        message += "此标签尚未被使用，可以安全删除。"
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认删除", callback_data=f"admin_tag_delete_{tag_id}"),
            InlineKeyboardButton("❌ 取消", callback_data=f"admin_tags_remove_menu_{page}")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def list_all_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有标签"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取所有标签
    tags = await db_fetch_all("SELECT name, type FROM tags ORDER BY type = 'recommend' DESC, name")
    
    message = "📋 **所有标签列表**\n\n"
    
    if not tags:
        message += "暂无标签。"
    else:
        recommend_tags = [tag for tag in tags if tag['type'] == 'recommend']
        block_tags = [tag for tag in tags if tag['type'] == 'block']
        
        if recommend_tags:
            message += "🏅 **推荐标签**:\n"
            for tag in recommend_tags:
                message += f"• {tag['name']}\n"
        
        if block_tags:
            if recommend_tags:
                message += "\n"
            message += "⚠️ **警告标签**:\n"
            for tag in block_tags:
                message += f"• {tag['name']}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# === 箴言便签管理相关函数 ===

async def mottos_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """箴言便签管理面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取便签统计
    total_mottos = await db_fetchval("SELECT COUNT(*) FROM mottos")
    
    message = "📜 **箴言便签管理**\n\n"
    message += f"📊 **当前统计**:\n"
    message += f"• 总便签数: {total_mottos} 条\n\n"
    message += "这些便签会在用户查询时随机显示，为神谕增添智慧。\n\n"
    message += "选择操作："
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加箴言便签", callback_data="admin_add_motto_prompt")],
        [
            InlineKeyboardButton("📋 查看所有便签", callback_data="admin_list_mottos"),
            InlineKeyboardButton("❌ 删除便签", callback_data="admin_remove_motto_menu_1")
        ],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def add_motto_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示添加箴言便签"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    message = "➕ **添加箴言便签**\n\n"
    message += "请发送要添加的便签内容。支持以下格式：\n"
    message += "• 单个便签：`智者仁心，常怀谨慎之思。`\n"
    message += "• 多个便签（每行一个）：\n"
    message += "  ```\n  智者仁心，常怀谨慎之思。\n  信誉如金，一言九鼎。\n  德行天下，人心自明。\n  ```\n\n"
    message += "💡 这些便签会在用户查询时随机显示\n\n"
    message += "发送 /cancel 取消操作"
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置等待用户输入
    context.user_data['next_action'] = {
        'action': 'add_mottos',
    }

async def list_mottos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有箴言便签"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    mottos = await get_all_mottos()
    
    message = "📜 **所有箴言便签**\n\n"
    
    if not mottos:
        message += "暂无便签。"
    else:
        message += f"共有 **{len(mottos)}** 条便签:\n\n"
        for i, motto in enumerate(mottos[:15], 1):  # 显示前15个
            message += f"{i}. {motto['content']}\n"
        
        if len(mottos) > 15:
            message += f"\n... 还有 {len(mottos) - 15} 条便签"
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加更多", callback_data="admin_add_motto_prompt")],
        [InlineKeyboardButton("❌ 删除便签", callback_data="admin_remove_motto_menu_1")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def remove_motto_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """便签删除菜单"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    per_page = 5
    offset = (page - 1) * per_page
    
    # 获取便签
    mottos = await db_fetch_all("""
        SELECT id, content FROM mottos
        ORDER BY created_at DESC
        LIMIT $1 OFFSET $2
    """, per_page, offset)
    
    total_mottos = await db_fetchval("SELECT COUNT(*) FROM mottos")
    total_pages = (total_mottos + per_page - 1) // per_page if total_mottos > 0 else 1
    
    message = "❌ **删除箴言便签**\n\n选择要删除的便签："
    
    keyboard = []
    
    if not mottos:
        message += "\n暂无便签可删除。"
    else:
        # 便签按钮
        for motto in mottos:
            content_preview = motto['content'][:30] + "..." if len(motto['content']) > 30 else motto['content']
            keyboard.append([InlineKeyboardButton(
                content_preview,
                callback_data=f"admin_motto_delete_confirm_{motto['id']}_{page}"
            )])
        
        # 分页按钮
        if total_pages > 1:
            nav_row = []
            if page > 1:
                nav_row.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"admin_remove_motto_menu_{page-1}"))
            if page < total_pages:
                nav_row.append(InlineKeyboardButton("▶️ 下一页", callback_data=f"admin_remove_motto_menu_{page+1}"))
            if nav_row:
                keyboard.append(nav_row)
        
        message += f"\n\n第 {page}/{total_pages} 页"
    
    # 返回按钮
    keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_motto_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, motto_id: int, page: int):
    """确认删除便签"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取便签内容
    motto_info = await db_fetch_one("SELECT content FROM mottos WHERE id = $1", motto_id)
    
    if not motto_info:
        await update.callback_query.edit_message_text(
            "❌ 便签不存在或已被删除。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data=f"admin_remove_motto_menu_{page}")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    message = f"⚠️ **确认删除便签**\n\n"
    message += f"内容: {motto_info['content']}\n\n"
    message += "确认删除此便签吗？"
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认删除", callback_data=f"admin_motto_delete_{motto_id}"),
            InlineKeyboardButton("❌ 取消", callback_data=f"admin_remove_motto_menu_{page}")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def execute_motto_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE, motto_id: int):
    """执行便签删除"""
    query = update.callback_query
    
    try:
        # 获取便签信息
        motto_info = await db_fetch_one("SELECT content FROM mottos WHERE id = $1", motto_id)
        
        if not motto_info:
            await query.edit_message_text(
                "❌ 便签不存在或已被删除。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")
                ]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # 删除便签
        await db_execute("DELETE FROM mottos WHERE id = $1", motto_id)
        
        message = f"✅ **便签删除成功**\n\n已删除便签: {motto_info['content'][:50]}{'...' if len(motto_info['content']) > 50 else ''}"
        
        keyboard = [
            [InlineKeyboardButton("❌ 继续删除", callback_data="admin_remove_motto_menu_1")],
            [InlineKeyboardButton("🔙 返回便签管理", callback_data="admin_panel_mottos")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"管理员 {update.effective_user.id} 删除了便签 (ID: {motto_id})")
        
    except Exception as e:
        logger.error(f"删除便签失败: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ 删除便签失败，请重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )

# === 排行榜管理增强 - 选择性抹除用户 ===

async def leaderboard_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """排行榜管理面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取排行榜统计
    total_users = await db_fetchval("""
        SELECT COUNT(DISTINCT target_id) 
        FROM reputations 
        WHERE target_id IN (
            SELECT target_id FROM reputations 
            GROUP BY target_id 
            HAVING COUNT(*) >= 3
        )
    """) or 0
    
    message = "🏆 **排行榜管理**\n\n"
    message += f"📊 **当前统计**:\n"
    message += f"• 排行榜用户: {total_users} 人\n\n"
    message += "选择操作："
    
    keyboard = [
        [InlineKeyboardButton("🎯 选择性抹除用户", callback_data="admin_selective_remove_menu")],
        [InlineKeyboardButton("❌ 批量移除用户", callback_data="admin_leaderboard_remove_prompt")],
        [InlineKeyboardButton("🔄 清除排行榜缓存", callback_data="admin_leaderboard_clear_cache")],
        [InlineKeyboardButton("📊 排行榜统计", callback_data="admin_leaderboard_stats")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def selective_remove_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str = "top", page: int = 1):
    """选择性抹除菜单"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取排行榜用户（简化版）
    per_page = 8
    offset = (page - 1) * per_page
    
    if board_type == "top":
        users = await db_fetch_all("""
            SELECT 
                u.id, u.username, u.first_name,
                COUNT(*) as total_votes,
                ROUND((COUNT(*) FILTER (WHERE r.is_positive = TRUE)::float / COUNT(*)) * 100) as score
            FROM users u
            JOIN reputations r ON u.id = r.target_id
            GROUP BY u.id, u.username, u.first_name
            HAVING COUNT(*) >= 3
            ORDER BY score DESC, total_votes DESC
            LIMIT $1 OFFSET $2
        """, per_page, offset)
        title = "🏆 英灵殿"
    else:
        users = await db_fetch_all("""
            SELECT 
                u.id, u.username, u.first_name,
                COUNT(*) as total_votes,
                ROUND((COUNT(*) FILTER (WHERE r.is_positive = TRUE)::float / COUNT(*)) * 100) as score
            FROM users u
            JOIN reputations r ON u.id = r.target_id
            GROUP BY u.id, u.username, u.first_name
            HAVING COUNT(*) >= 3
            ORDER BY score ASC, total_votes DESC
            LIMIT $1 OFFSET $2
        """, per_page, offset)
        title = "☠️ 放逐深渊"
    
    total_count = await db_fetchval("""
        SELECT COUNT(*) FROM (
            SELECT r.target_id
            FROM reputations r
            GROUP BY r.target_id
            HAVING COUNT(*) >= 3
        ) as filtered
    """)
    
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    
    message = f"🎯 **选择性抹除 - {title}**\n\n"
    message += "选择要从排行榜中移除的用户："
    
    keyboard = []
    
    if not users:
        message += "\n\n暂无用户。"
    else:
        # 用户按钮
        for user in users:
            name = user['first_name'] or user['username'] or f"用户{user['id']}"
            score_text = f"{user['score']}% ({user['total_votes']}票)"
            keyboard.append([InlineKeyboardButton(
                f"{name} - {score_text}",
                callback_data=f"admin_confirm_remove_user_{user['id']}_{board_type}_{page}"
            )])
    
    # 切换排行榜按钮
    nav_buttons = []
    opposite_type = "bottom" if board_type == "top" else "top"
    opposite_title = "☠️ 放逐深渊" if board_type == "top" else "🏆 英灵殿"
    nav_buttons.append(InlineKeyboardButton(f"切换到{opposite_title}", callback_data=f"admin_selective_remove_{opposite_type}_1"))
    
    # 分页按钮
    if total_pages > 1:
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"admin_selective_remove_{board_type}_{page-1}"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("▶️ 下一页", callback_data=f"admin_selective_remove_{board_type}_{page+1}"))
    
    if nav_buttons:
        # 分成两行，切换按钮单独一行
        keyboard.append([nav_buttons[0]])  # 切换按钮
        if len(nav_buttons) > 1:
            keyboard.append(nav_buttons[1:])  # 分页按钮
    
    # 返回按钮
    keyboard.append([InlineKeyboardButton("🔙 返回排行榜管理", callback_data="admin_leaderboard_panel")])
    
    if total_pages > 1:
        message += f"\n\n第 {page}/{total_pages} 页"
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def confirm_user_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, board_type: str, page: int):
    """确认移除用户"""
    query = update.callback_query
    admin_id = update.effective_user.id
    
    if not await is_admin(admin_id):
        await query.answer("❌ 权限不足", show_alert=True)
        return
    
    await query.answer()
    
    # 获取用户信息和统计
    user_info = await db_fetch_one("""
        SELECT 
            u.username, u.first_name,
            COUNT(r1.*) as received_votes,
            COUNT(r2.*) as given_votes,
            COUNT(f.*) as favorites
        FROM users u
        LEFT JOIN reputations r1 ON u.id = r1.target_id
        LEFT JOIN reputations r2 ON u.id = r2.voter_id
        LEFT JOIN favorites f ON u.id = f.target_id
        WHERE u.id = $1
        GROUP BY u.id, u.username, u.first_name
    """, user_id)
    
    if not user_info:
        await query.edit_message_text(
            "❌ 用户不存在。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data=f"admin_selective_remove_{board_type}_{page}")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    name = user_info['first_name'] or user_info['username'] or f"用户{user_id}"
    
    message = f"⚠️ **确认移除用户**\n\n"
    message += f"用户: **{name}**\n"
    message += f"ID: `{user_id}`\n\n"
    message += f"将要清除的数据:\n"
    message += f"• 收到的评价: {user_info['received_votes']} 条\n"
    message += f"• 给出的评价: {user_info['given_votes']} 条\n"
    message += f"• 收藏记录: {user_info['favorites']} 条\n\n"
    message += "选择清除范围:"
    
    keyboard = [
        [InlineKeyboardButton("📥 只清除收到的评价", callback_data=f"admin_remove_user_received_{user_id}_{board_type}_{page}")],
        [InlineKeyboardButton("🗑️ 清除所有相关数据", callback_data=f"admin_remove_user_all_{user_id}_{board_type}_{page}")],
        [InlineKeyboardButton("❌ 取消", callback_data=f"admin_selective_remove_{board_type}_{page}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def execute_user_removal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, removal_type: str, board_type: str, page: int):
    """执行用户移除"""
    query = update.callback_query
    
    try:
        # 获取用户信息
        user_info = await db_fetch_one("SELECT username, first_name FROM users WHERE id = $1", user_id)
        
        if not user_info:
            await query.edit_message_text(
                "❌ 用户不存在或已被删除。",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 返回", callback_data=f"admin_selective_remove_{board_type}_{page}")
                ]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        name = user_info['first_name'] or user_info['username'] or f"用户{user_id}"
        
        # 执行删除操作
        async with db_transaction() as conn:
            if removal_type == "received":
                # 只删除收到的评价
                received_count = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE target_id = $1", user_id)
                fav_count = await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE target_id = $1", user_id)
                
                await conn.execute("DELETE FROM reputations WHERE target_id = $1", user_id)
                await conn.execute("DELETE FROM favorites WHERE target_id = $1", user_id)
                
                message = f"✅ **用户数据清除完成**\n\n"
                message += f"用户: **{name}**\n"
                message += f"已清除:\n"
                message += f"• 收到的评价: {received_count} 条\n"
                message += f"• 收藏记录: {fav_count} 条\n\n"
                message += "该用户已从排行榜中移除。"
                
            elif removal_type == "all":
                # 删除所有相关数据
                received_count = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE target_id = $1", user_id)
                given_count = await conn.fetchval("SELECT COUNT(*) FROM reputations WHERE voter_id = $1", user_id)
                fav_given = await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE user_id = $1", user_id)
                fav_received = await conn.fetchval("SELECT COUNT(*) FROM favorites WHERE target_id = $1", user_id)
                
                await conn.execute("DELETE FROM reputations WHERE target_id = $1 OR voter_id = $1", user_id)
                await conn.execute("DELETE FROM favorites WHERE user_id = $1 OR target_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
                
                message = f"✅ **用户完全清除完成**\n\n"
                message += f"用户: **{name}**\n"
                message += f"已清除:\n"
                message += f"• 收到的评价: {received_count} 条\n"
                message += f"• 给出的评价: {given_count} 条\n"
                message += f"• 收藏记录: {fav_given + fav_received} 条\n"
                message += f"• 用户资料: 已删除\n\n"
                message += "该用户已完全从系统中清除。"
        
        # 清除缓存
        from handlers.leaderboard import clear_leaderboard_cache
        clear_leaderboard_cache()
        
        keyboard = [
            [InlineKeyboardButton("🎯 继续清理", callback_data=f"admin_selective_remove_{board_type}_{page}")],
            [InlineKeyboardButton("🔙 返回排行榜管理", callback_data="admin_leaderboard_panel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"管理员 {update.effective_user.id} 清除了用户 {user_id} ({removal_type})")
        
    except Exception as e:
        logger.error(f"清除用户失败: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ 清除用户失败，请重试。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data=f"admin_selective_remove_{board_type}_{page}")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )

# 接上面的 handlers/admin.py 内容

# === 权限管理相关函数 ===

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """权限管理面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取管理员统计
    admin_count = await db_fetchval("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
    
    message = "👑 **权限管理**\n\n"
    message += f"📊 **当前统计**:\n"
    message += f"• 管理员数量: {admin_count} 人\n\n"
    message += "选择操作："
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加管理员", callback_data="admin_perms_add_prompt")],
        [
            InlineKeyboardButton("📋 查看管理员", callback_data="admin_perms_list"),
            InlineKeyboardButton("❌ 移除管理员", callback_data="admin_perms_remove_menu")
        ],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示添加管理员"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    message = "➕ **添加管理员**\n\n"
    message += "请发送要授予管理员权限的用户信息。支持以下格式：\n"
    message += "• 用户ID：`123456789`\n"
    message += "• 用户名：`@username`（不含@符号）\n\n"
    message += "⚠️ 请确保用户已经使用过本机器人\n\n"
    message += "发送 /cancel 取消操作"
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置等待用户输入
    context.user_data['next_action'] = {
        'action': 'add_admin',
    }

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有管理员"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    admins = await db_fetch_all("""
        SELECT id, username, first_name, last_activity 
        FROM users 
        WHERE is_admin = TRUE 
        ORDER BY last_activity DESC
    """)
    
    message = "📋 **所有管理员**\n\n"
    
    if not admins:
        message += "暂无管理员。"
    else:
        for i, admin in enumerate(admins, 1):
            display_name = admin['first_name'] or f"@{admin['username']}" if admin['username'] else f"用户{admin['id']}"
            last_activity = admin['last_activity'].strftime('%Y-%m-%d') if admin['last_activity'] else "从未活动"
            message += f"{i}. {display_name} (ID: {admin['id']})\n"
            message += f"   最后活动: {last_activity}\n\n"
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加更多", callback_data="admin_perms_add_prompt")],
        [InlineKeyboardButton("❌ 移除管理员", callback_data="admin_perms_remove_menu")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """移除管理员菜单"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取其他管理员（除了当前用户）
    admins = await db_fetch_all("""
        SELECT id, username, first_name 
        FROM users 
        WHERE is_admin = TRUE AND id != $1
        ORDER BY first_name, username
    """, user_id)
    
    message = "❌ **移除管理员**\n\n"
    
    if not admins:
        message += "没有其他管理员可以移除。"
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]]
    else:
        message += "⚠️ 选择要移除管理员权限的用户："
        
        keyboard = []
        for admin in admins:
            display_name = admin['first_name'] or f"@{admin['username']}" if admin['username'] else f"用户{admin['id']}"
            keyboard.append([InlineKeyboardButton(
                display_name,
                callback_data=f"admin_perms_remove_confirm_{admin['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def remove_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id: int):
    """确认移除管理员"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取管理员信息
    admin_info = await db_fetch_one(
        "SELECT username, first_name FROM users WHERE id = $1 AND is_admin = TRUE",
        admin_id
    )
    
    if not admin_info:
        await update.callback_query.edit_message_text(
            "❌ 用户不存在或不是管理员。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_perms_remove_menu")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    display_name = admin_info['first_name'] or f"@{admin_info['username']}" if admin_info['username'] else f"用户{admin_id}"
    
    message = f"⚠️ **确认移除管理员权限**\n\n"
    message += f"用户: **{display_name}**\n"
    message += f"ID: `{admin_id}`\n\n"
    message += "确认移除此用户的管理员权限吗？"
    
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认移除", callback_data=f"admin_remove_admin_{admin_id}"),
            InlineKeyboardButton("❌ 取消", callback_data="admin_perms_remove_menu")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# === 系统设置相关函数 ===

async def system_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """系统设置面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取当前设置
    min_votes = await get_setting('min_votes_for_leaderboard') or "3"
    leaderboard_size = await get_setting('leaderboard_size') or "10"
    
    message = "⚙️ **系统设置**\n\n"
    message += f"📊 **当前设置**:\n"
    message += f"• 排行榜最低票数: {min_votes}\n"
    message += f"• 排行榜显示数量: {leaderboard_size}\n\n"
    message += "选择要修改的设置："
    
    keyboard = [
        [InlineKeyboardButton("📝 修改开始消息", callback_data="admin_system_set_start_message")],
        [InlineKeyboardButton("🎯 排行榜最低票数", callback_data="admin_system_set_prompt_min_votes_for_leaderboard")],
        [InlineKeyboardButton("📊 排行榜显示数量", callback_data="admin_system_set_prompt_leaderboard_size")],
        [InlineKeyboardButton("🔐 修改管理员密码", callback_data="admin_system_set_prompt_admin_password")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def set_start_message_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """设置开始消息提示"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    current_message = await get_setting('start_message')
    
    message = "📝 **修改开始消息**\n\n"
    message += "当前开始消息:\n"
    message += f"```\n{current_message}\n```\n\n"
    message += "请发送新的开始消息内容：\n"
    message += "• 支持 Markdown 格式\n"
    message += "• 可以使用 **粗体** 和 *斜体*\n"
    message += "• 使用 `代码` 格式\n\n"
    message += "发送 /cancel 取消操作"
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_system")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置等待用户输入
    context.user_data['next_action'] = {
        'action': 'set_start_message',
    }

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_key: str):
    """设置系统设置提示"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    current_value = await get_setting(setting_key)
    
    setting_info = {
        'min_votes_for_leaderboard': {
            'name': '排行榜最低票数',
            'description': '用户需要收到多少票才能进入排行榜',
            'example': '3'
        },
        'leaderboard_size': {
            'name': '排行榜显示数量', 
            'description': '每页显示多少个用户',
            'example': '10'
        },
        'admin_password': {
            'name': '管理员密码',
            'description': '用于获取管理员权限的密码',
            'example': 'newpassword123'
        }
    }
    
    info = setting_info.get(setting_key, {})
    
    message = f"⚙️ **修改{info.get('name', setting_key)}**\n\n"
    message += f"当前值: `{current_value}`\n\n"
    message += f"说明: {info.get('description', '')}\n\n"
    message += f"请发送新的值（示例: `{info.get('example', '')}`）：\n\n"
    message += "发送 /cancel 取消操作"
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_system")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置等待用户输入
    context.user_data['next_action'] = {
        'action': 'set_setting',
        'setting_key': setting_key
    }

async def remove_from_leaderboard_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """批量移除排行榜用户提示"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    message = "❌ **批量移除排行榜用户**\n\n"
    message += "请发送要移除的用户信息，支持以下格式：\n"
    message += "• 用户ID：`123456789`\n"
    message += "• 用户名：`username`（不含@符号）\n"
    message += "• 多个用户（每行一个）：\n"
    message += "  ```\n  123456789\n  username1\n  username2\n  ```\n\n"
    message += "⚠️ 这将清除用户的所有声誉数据\n\n"
    message += "发送 /cancel 取消操作"
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_leaderboard_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    
    # 设置等待用户输入
    context.user_data['next_action'] = {
        'action': 'remove_from_leaderboard',
    }

async def show_all_commands(update: Update, context: ContextTypes.DEFAULT_TYPE, from_command: bool = False):
    """显示所有管理员命令"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        if from_command:
            await update.message.reply_text("❌ 此功能仅限管理员使用")
        else:
            await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    if not from_command:
        await update.callback_query.answer()
    
    message = "📋 **管理员命令大全**\n\n"
    
    message += "**🔧 基础命令**\n"
    message += "• `/godmode 密码` - 获取管理员权限\n"
    message += "• `/commands` - 查看此命令列表\n"
    message += "• `/cancel` - 取消当前操作\n\n"
    
    message += "**👥 用户管理**\n"
    message += "• 在管理面板中添加/移除管理员\n"
    message += "• 选择性清除排行榜用户数据\n"
    message += "• 批量移除问题用户\n\n"
    
    message += "**🏷️ 内容管理**\n"
    message += "• 添加推荐/警告标签\n"
    message += "• 批量添加箴言便签\n"
    message += "• 删除不当标签或便签\n\n"
    
    message += "**⚙️ 系统管理**\n"
    message += "• 修改开始消息\n"
    message += "• 调整排行榜参数\n"
    message += "• 修改管理员密码\n"
    message += "• 清除各种缓存\n\n"
    
    message += "**📊 数据管理**\n"
    message += "• 查看系统统计\n"
    message += "• 导出用户数据\n"
    message += "• 清理历史记录\n\n"
    
    message += "💡 所有操作都通过菜单界面完成，支持撤销和确认。"
    
    keyboard = []
    if not from_command:
        keyboard.append([InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    if from_command:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

# === 输入处理函数 ===

async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员输入"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        return
    
    # 检查是否有等待处理的操作
    next_action = context.user_data.get('next_action')
    if not next_action:
        return
    
    action = next_action.get('action')
    user_input = update.message.text.strip()
    
    try:
        if action == 'add_tags':
            await process_add_tags(update, context, user_input, next_action.get('tag_type'))
        elif action == 'add_mottos':
            await process_add_mottos(update, context, user_input)
        elif action == 'add_admin':
            await process_add_admin(update, context, user_input)
        elif action == 'set_start_message':
            await process_set_start_message(update, context, user_input)
        elif action == 'set_setting':
            await process_set_setting(update, context, user_input, next_action.get('setting_key'))
        elif action == 'remove_from_leaderboard':
            await process_remove_from_leaderboard(update, context, user_input)
    except Exception as e:
        logger.error(f"处理管理员输入失败: {e}", exc_info=True)
        await update.message.reply_text("❌ 处理输入时出错，请重试。")
    finally:
        # 清除等待状态
        if 'next_action' in context.user_data:
            del context.user_data['next_action']

async def process_add_tags(update: Update, context: ContextTypes.DEFAULT_TYPE, user_input: str, tag_type: str):
    """处理添加标签"""
    # 解析输入
    tags = []
    if '\n' in user_input:
        tags = [tag.strip() for tag in user_input.split('\n') if tag.strip()]
    elif ',' in user_input:
        tags = [tag.strip() for tag in user_input.split(',') if tag.strip()]
    else:
        tags = [user_input.strip()]
    
    if not tags:
        await update.message.reply_text("❌ 未检测到有效的标签名称。")
        return
    
    # 添加标签
    added_count = 0
    duplicate_count = 0
    
    for tag_name in tags:
        if len(tag_name) > 20:
            continue
        
        try:
            await db_execute(
                "INSERT INTO tags (name, type, created_by) VALUES ($1, $2, $3)",
                tag_name, tag_type, update.effective_user.id
            )
            added_count += 1
        except:
            duplicate_count += 1
    
    type_name = "推荐" if tag_type == "recommend" else "警告"
    message = f"✅ **{type_name}标签添加完成**\n\n"
    message += f"成功添加: {added_count} 个\n"
    if duplicate_count > 0:
        message += f"重复跳过: {duplicate_count} 个\n"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def process_add_mottos(update: Update, context: ContextTypes.DEFAULT_TYPE, user_input: str):
    """处理添加箴言便签"""
    # 解析输入
    mottos = [motto.strip() for motto in user_input.split('\n') if motto.strip()]
    
    if not mottos:
        await update.message.reply_text("❌ 未检测到有效的便签内容。")
        return
    
    # 添加便签
    added_count = await add_mottos_batch(mottos, update.effective_user.id)
    
    message = f"✅ **箴言便签添加完成**\n\n"
    message += f"成功添加: {added_count} 条便签\n"
    if added_count < len(mottos):
        message += f"跳过重复: {len(mottos) - added_count} 条\n"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def process_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_input: str):
    """处理添加管理员"""
    # 解析用户输入
    target_user = None
    
    if user_input.isdigit():
        # 用户ID
        user_id = int(user_input)
        target_user = await db_fetch_one("SELECT id, username, first_name FROM users WHERE id = $1", user_id)
    else:
        # 用户名
        username = user_input.lstrip('@')
        target_user = await db_fetch_one("SELECT id, username, first_name FROM users WHERE username = $1", username)
    
    if not target_user:
        await update.message.reply_text("❌ 未找到该用户，请确保用户已使用过机器人。")
        return
    
    # 检查是否已是管理员
    if await is_admin(target_user['id']):
        display_name = target_user['first_name'] or f"@{target_user['username']}" or f"用户{target_user['id']}"
        await update.message.reply_text(f"ℹ️ {display_name} 已经是管理员。")
        return
    
    # 授予管理员权限
    await db_execute("UPDATE users SET is_admin = TRUE WHERE id = $1", target_user['id'])
    
    display_name = target_user['first_name'] or f"@{target_user['username']}" or f"用户{target_user['id']}"
    message = f"✅ **管理员权限授予成功**\n\n{display_name} 已被授予管理员权限。"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def process_set_start_message(update: Update, context: ContextTypes.DEFAULT_TYPE, user_input: str):
    """处理设置开始消息"""
    if len(user_input) > 1000:
        await update.message.reply_text("❌ 消息内容过长，请控制在1000字符以内。")
        return
    
    success = await set_setting('start_message', user_input, update.effective_user.id)
    
    if success:
        message = "✅ **开始消息更新成功**\n\n新的开始消息已生效。"
    else:
        message = "❌ **更新失败**\n\n请稍后重试。"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def process_set_setting(update: Update, context: ContextTypes.DEFAULT_TYPE, user_input: str, setting_key: str):
    """处理设置系统设置"""
    # 验证输入
    if setting_key in ['min_votes_for_leaderboard', 'leaderboard_size']:
        if not user_input.isdigit():
            await update.message.reply_text("❌ 请输入有效的数字。")
            return
        
        value = int(user_input)
        if setting_key == 'min_votes_for_leaderboard' and (value < 1 or value > 50):
            await update.message.reply_text("❌ 排行榜最低票数应在1-50之间。")
            return
        elif setting_key == 'leaderboard_size' and (value < 5 or value > 50):
            await update.message.reply_text("❌ 排行榜显示数量应在5-50之间。")
            return
    
    success = await set_setting(setting_key, user_input, update.effective_user.id)
    
    if success:
        # 如果是排行榜相关设置，清除缓存
        if 'leaderboard' in setting_key:
            from handlers.leaderboard import clear_leaderboard_cache
            clear_leaderboard_cache()
        
        message = "✅ **设置更新成功**\n\n新设置已生效。"
    else:
        message = "❌ **更新失败**\n\n请稍后重试。"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def process_remove_from_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, user_input: str):
    """处理批量移除排行榜用户"""
    # 解析用户列表
    user_identifiers = []
    if '\n' in user_input:
        user_identifiers = [uid.strip() for uid in user_input.split('\n') if uid.strip()]
    else:
        user_identifiers = [user_input.strip()]
    
    removed_count = 0
    not_found_count = 0
    
    for uid in user_identifiers:
        target_user = None
        
        if uid.isdigit():
            # 用户ID
            user_id = int(uid)
            target_user = await db_fetch_one("SELECT id FROM users WHERE id = $1", user_id)
        else:
            # 用户名
            username = uid.lstrip('@')
            target_user = await db_fetch_one("SELECT id FROM users WHERE username = $1", username)
        
        if target_user:
            try:
                async with db_transaction() as conn:
                    await conn.execute("DELETE FROM reputations WHERE target_id = $1", target_user['id'])
                    await conn.execute("DELETE FROM favorites WHERE target_id = $1", target_user['id'])
                removed_count += 1
            except Exception as e:
                logger.error(f"移除用户 {target_user['id']} 失败: {e}")
        else:
            not_found_count += 1
    
    # 清除缓存
    from handlers.leaderboard import clear_leaderboard_cache
    clear_leaderboard_cache()
    
    message = f"✅ **批量移除完成**\n\n"
    message += f"成功移除: {removed_count} 人\n"
    if not_found_count > 0:
        message += f"未找到: {not_found_count} 人\n"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
