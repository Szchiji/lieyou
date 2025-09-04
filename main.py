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
        await update.message.reply_text("🔐 请提供神谕密钥。")
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
        await update.message.reply_text("✨ 恭喜！你已被授予守护者权限。")
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
        [InlineKeyboardButton("📜 箴言管理", callback_data="admin_panel_mottos")],
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
    
    message = "🏷️ **标签管理**\n\n选择操作："
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加推荐标签", callback_data="admin_tags_add_recommend_prompt")],
        [InlineKeyboardButton("➕ 添加警告标签", callback_data="admin_tags_add_block_prompt")],
        [InlineKeyboardButton("❌ 删除标签", callback_data="admin_tags_remove_menu_1")],
        [InlineKeyboardButton("📋 查看所有标签", callback_data="admin_tags_list")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

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
    usage_count = await db_fetchval("SELECT COUNT(*) FROM reputations WHERE tag_id = $1", tag_id)
    
    if not tag_info:
        await update.callback_query.edit_message_text(
            "❌ 标签不存在或已被删除。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data=f"admin_tags_remove_menu_{page}")
            ]])
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

# === 箴言管理相关函数 ===

async def mottos_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """箴言管理面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    message = "📜 **箴言管理**\n\n选择操作："
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加箴言", callback_data="admin_add_motto_prompt")],
        [InlineKeyboardButton("📋 查看所有箴言", callback_data="admin_list_mottos")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def add_motto_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示添加箴言"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    message = "➕ **添加箴言**\n\n"
    message += "请发送要添加的箴言内容。支持以下格式：\n"
    message += "• 单个箴言：`智者仁心，常怀谨慎之思。`\n"
    message += "• 多个箴言（每行一个）：\n"
    message += "  ```\n  智者仁心，常怀谨慎之思。\n  信誉如金，一言九鼎。\n  德行天下，人心自明。\n  ```\n\n"
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
    """列出所有箴言"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    mottos = await get_all_mottos()
    
    message = "📜 **所有箴言列表**\n\n"
    
    if not mottos:
        message += "暂无箴言。"
    else:
        for i, motto in enumerate(mottos[:20], 1):  # 只显示前20个
            message += f"{i}. {motto['content']}\n"
        
        if len(mottos) > 20:
            message += f"\n... 还有 {len(mottos) - 20} 条箴言"
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# === 权限管理相关函数 ===

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """权限管理面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    message = "👑 **权限管理**\n\n选择操作："
    
    keyboard = [
        [InlineKeyboardButton("➕ 添加管理员", callback_data="admin_perms_add_prompt")],
        [InlineKeyboardButton("📋 查看管理员", callback_data="admin_perms_list")],
        [InlineKeyboardButton("❌ 移除管理员", callback_data="admin_perms_remove_menu")],
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
    message += "请发送要添加为管理员的用户ID。\n"
    message += "例如：`123456789`\n\n"
    message += "💡 提示：可以通过转发该用户的消息给 @userinfobot 获取用户ID\n\n"
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
        'action': 'add_admin'
    }

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有管理员"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 获取所有管理员
    admins = await db_fetch_all("""
        SELECT id, username, first_name, created_at 
        FROM users 
        WHERE is_admin = TRUE 
        ORDER BY created_at
    """)
    
    message = "👑 **管理员列表**\n\n"
    
    if not admins:
        message += "暂无管理员。"
    else:
        for i, admin in enumerate(admins, 1):
            name = admin['first_name'] or admin['username'] or f"用户{admin['id']}"
            username_part = f" (@{admin['username']})" if admin['username'] else ""
            message += f"{i}. {name}{username_part}\n"
            message += f"   ID: `{admin['id']}`\n"
    
    keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]]
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
    
    # 获取其他管理员（不包括自己）
    admins = await db_fetch_all("""
        SELECT id, username, first_name 
        FROM users 
        WHERE is_admin = TRUE AND id != $1
        ORDER BY id
    """, user_id)
    
    message = "❌ **移除管理员**\n\n选择要移除管理员权限的用户："
    
    keyboard = []
    
    if not admins:
        message += "\n没有其他管理员可以移除。"
    else:
        for admin in admins:
            name = admin['first_name'] or admin['username'] or f"用户{admin['id']}"
            keyboard.append([InlineKeyboardButton(
                name,
                callback_data=f"admin_perms_remove_confirm_{admin['id']}"
            )])
    
    # 返回按钮
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
    
    # 获取要移除的管理员信息
    admin_info = await db_fetch_one(
        "SELECT username, first_name FROM users WHERE id = $1 AND is_admin = TRUE",
        admin_id
    )
    
    if not admin_info:
        await update.callback_query.edit_message_text(
            "❌ 用户不存在或不是管理员。",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 返回", callback_data="admin_perms_remove_menu")
            ]])
        )
        return
    
    name = admin_info['first_name'] or admin_info['username'] or f"用户{admin_id}"
    
    message = f"⚠️ **确认移除管理员权限**\n\n"
    message += f"用户: **{name}**\n"
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
    
    message = "⚙️ **系统设置**\n\n选择要修改的设置："
    
    keyboard = [
        [InlineKeyboardButton("💬 修改欢迎消息", callback_data="admin_system_set_start_message")],
        [InlineKeyboardButton("🔐 修改管理员密码", callback_data="admin_system_set_prompt_admin_password")],
        [InlineKeyboardButton("📊 排行榜最小投票数", callback_data="admin_system_set_prompt_min_votes_for_leaderboard")],
        [InlineKeyboardButton("🏆 排行榜显示数量", callback_data="admin_system_set_prompt_leaderboard_size")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def set_start_message_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示设置开始消息"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    current_message = await get_setting('start_message') or "未设置"
    
    message = "💬 **修改欢迎消息**\n\n"
    message += f"当前消息:\n```\n{current_message[:200]}{'...' if len(current_message) > 200 else ''}\n```\n\n"
    message += "请发送新的欢迎消息内容：\n\n"
    message += "💡 支持Markdown格式\n"
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
        'action': 'set_start_message'
    }

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_key: str):
    """提示设置系统配置"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    # 设置信息映射
    setting_info = {
        'admin_password': {
            'name': '管理员密码',
            'description': '用于/godmode命令获取管理员权限的密码',
            'example': 'mypassword123'
        },
        'min_votes_for_leaderboard': {
            'name': '排行榜最小投票数',
            'description': '用户需要获得多少票才能进入排行榜',
            'example': '3'
        },
        'leaderboard_size': {
            'name': '排行榜显示数量',
            'description': '每页排行榜显示多少个用户',
            'example': '10'
        }
    }
    
    if setting_key not in setting_info:
        await update.callback_query.edit_message_text("❌ 未知的设置项")
        return
    
    info = setting_info[setting_key]
    current_value = await get_setting(setting_key) or "未设置"
    
    message = f"⚙️ **修改{info['name']}**\n\n"
    message += f"说明: {info['description']}\n"
    message += f"当前值: `{current_value}`\n"
    message += f"示例: `{info['example']}`\n\n"
    message += "请发送新的设置值：\n\n"
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

# === 排行榜管理相关函数 ===

async def leaderboard_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """排行榜管理面板"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    message = "🏆 **排行榜管理**\n\n选择操作："
    
    keyboard = [
        [InlineKeyboardButton("❌ 从排行榜移除用户", callback_data="admin_leaderboard_remove_prompt")],
        [InlineKeyboardButton("🔄 清除排行榜缓存", callback_data="admin_leaderboard_clear_cache")],
        [InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def remove_from_leaderboard_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示从排行榜移除用户"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.callback_query.answer("❌ 权限不足", show_alert=True)
        return
    
    await update.callback_query.answer()
    
    message = "❌ **从排行榜移除用户**\n\n"
    message += "请发送要移除的用户ID或用户名。\n"
    message += "例如：`123456789` 或 `username`\n\n"
    message += "⚠️ 此操作将删除该用户的所有评价记录！\n\n"
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
        'action': 'remove_from_leaderboard'
    }

# === 命令帮助相关函数 ===

async def show_all_commands(update: Update, context: ContextTypes.DEFAULT_TYPE, from_command: bool = False):
    """显示所有命令"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        if update.callback_query:
            await update.callback_query.answer("❌ 权限不足", show_alert=True)
        else:
            await update.message.reply_text("❌ 此命令仅管理员可用")
        return
    
    if update.callback_query:
        await update.callback_query.answer()
    
    message = "📋 **所有可用命令**\n\n"
    message += "**用户命令:**\n"
    message += "• `/start` 或 `/help` - 显示主菜单\n"
    message += "• `/myfavorites` - 查看我的收藏\n"
    message += "• `/cancel` - 取消当前操作\n"
    message += "• `查询 @用户名` - 查询用户声誉\n\n"
    
    message += "**管理员命令:**\n"
    message += "• `/godmode 密码` - 获取管理员权限\n"
    message += "• `/commands` - 显示所有命令\n\n"
    
    message += "**群聊功能:**\n"
    message += "• `@用户名` - 查询用户声誉\n"
    message += "• `查询 @用户名` - 查询用户声誉\n\n"
    
    message += "**按钮功能:**\n"
    message += "• 🏆 英灵殿 - 查看好评排行榜\n"
    message += "• ☠️ 放逐深渊 - 查看差评排行榜\n"
    message += "• 🌟 我的星盘 - 查看收藏的用户\n"
    message += "• 📊 神谕数据 - 查看系统统计\n"
    message += "• 🔥 抹除室 - 数据清理功能\n"
    
    if from_command:
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    else:
        keyboard = [[InlineKeyboardButton("🔙 返回", callback_data="admin_settings_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

# === 文本输入处理函数 ===

async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员的文本输入"""
    user_id = update.effective_user.id
    
    # 检查管理员权限
    if not await is_admin(user_id):
        return
    
    # 检查是否有等待处理的操作
    if 'next_action' not in context.user_data:
        return
    
    action_info = context.user_data['next_action']
    action = action_info['action']
    text = update.message.text.strip()
    
    try:
        if action == 'add_tags':
            await handle_add_tags(update, context, action_info['tag_type'], text)
        elif action == 'add_mottos':
            await handle_add_mottos(update, context, text)
        elif action == 'add_admin':
            await handle_add_admin(update, context, text)
        elif action == 'set_start_message':
            await handle_set_start_message(update, context, text)
        elif action == 'set_setting':
            await handle_set_setting(update, context, action_info['setting_key'], text)
        elif action == 'remove_from_leaderboard':
            await handle_remove_from_leaderboard(update, context, text)
        
        # 清除等待状态
        del context.user_data['next_action']
        
    except Exception as e:
        logger.error(f"处理管理员输入时出错: {e}", exc_info=True)
        await update.message.reply_text("❌ 处理输入时出错，请重试。")

async def handle_add_tags(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type: str, text: str):
    """处理添加标签"""
    # 解析标签（支持换行和逗号分隔）
    tags = []
    
    # 先按换行分割，再按逗号分割
    lines = text.split('\n')
    for line in lines:
        if ',' in line:
            tags.extend([tag.strip() for tag in line.split(',') if tag.strip()])
        else:
            if line.strip():
                tags.append(line.strip())
    
    # 去重并过滤空值
    tags = list(set([tag for tag in tags if tag and len(tag) <= 20]))
    
    if not tags:
        await update.message.reply_text("❌ 没有找到有效的标签内容。")
        return
    
    # 添加标签到数据库
    added_count = 0
    failed_tags = []
    
    async with db_transaction() as conn:
        for tag in tags:
            try:
                await conn.execute(
                    "INSERT INTO tags (name, type, created_by) VALUES ($1, $2, $3)",
                    tag, tag_type, update.effective_user.id
                )
                added_count += 1
            except Exception as e:
                failed_tags.append(tag)
                logger.error(f"添加标签失败 {tag}: {e}")
    
    # 构建结果消息
    type_name = "推荐" if tag_type == "recommend" else "警告"
    message = f"✅ **{type_name}标签添加完成**\n\n"
    message += f"成功添加: **{added_count}** 个标签\n"
    
    if failed_tags:
        message += f"失败: **{len(failed_tags)}** 个标签\n"
        message += f"失败标签: {', '.join(failed_tags[:5])}"
        if len(failed_tags) > 5:
            message += f" 等{len(failed_tags)}个"
    
    # 显示成功添加的标签
    if added_count > 0:
        success_tags = [tag for tag in tags if tag not in failed_tags]
        message += f"\n\n新增标签: {', '.join(success_tags[:10])}"
        if len(success_tags) > 10:
            message += f" 等{len(success_tags)}个"
    
    keyboard = [[InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_add_mottos(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """处理添加箴言"""
    # 解析箴言（按行分割）
    mottos = [line.strip() for line in text.split('\n') if line.strip()]
    
    if not mottos:
        await update.message.reply_text("❌ 没有找到有效的箴言内容。")
        return
    
    # 添加箴言到数据库
    added_count = await add_mottos_batch(mottos, update.effective_user.id)
    
    message = f"✅ **箴言添加完成**\n\n"
    message += f"成功添加: **{added_count}** 条箴言\n"
    
    if added_count < len(mottos):
        message += f"失败: **{len(mottos) - added_count}** 条箴言\n"
    
    # 显示添加的箴言
    if added_count > 0:
        message += "\n新增箴言:\n"
        for i, motto in enumerate(mottos[:3], 1):
            message += f"{i}. {motto}\n"
        if len(mottos) > 3:
            message += f"... 等{len(mottos)}条"
    
    keyboard = [[InlineKeyboardButton("🔙 返回箴言管理", callback_data="admin_panel_mottos")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """处理添加管理员"""
    # 验证输入是否为有效的用户ID
    try:
        admin_id = int(text)
    except ValueError:
        await update.message.reply_text("❌ 请输入有效的用户ID（纯数字）。")
        return
    
    # 检查用户是否已经是管理员
    if await is_admin(admin_id):
        await update.message.reply_text("ℹ️ 该用户已经是管理员。")
        return
    
    # 添加管理员权限
    try:
        await db_execute(
            "INSERT INTO users (id, is_admin) VALUES ($1, TRUE) ON CONFLICT (id) DO UPDATE SET is_admin = TRUE",
            admin_id
        )
        
        message = f"✅ **管理员添加成功**\n\n"
        message += f"用户ID: `{admin_id}` 已被授予管理员权限。"
        
        keyboard = [[InlineKeyboardButton("🔙 返回权限管理", callback_data="admin_panel_permissions")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"用户 {admin_id} 被 {update.effective_user.id} 添加为管理员")
        
    except Exception as e:
        logger.error(f"添加管理员失败: {e}")
        await update.message.reply_text("❌ 添加管理员失败，请重试。")

async def handle_set_start_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """处理设置开始消息"""
    if len(text) > 2000:
        await update.message.reply_text("❌ 消息内容过长，请控制在2000字符以内。")
        return
    
    # 设置开始消息
    success = await set_setting('start_message', text, update.effective_user.id)
    
    if success:
        message = "✅ **欢迎消息更新成功**\n\n"
        message += f"新消息预览:\n```\n{text[:200]}{'...' if len(text) > 200 else ''}\n```"
        
        keyboard = [[InlineKeyboardButton("🔙 返回系统设置", callback_data="admin_panel_system")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("❌ 更新欢迎消息失败，请重试。")

async def handle_set_setting(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_key: str, text: str):
    """处理设置系统配置"""
    # 验证设置值
    if setting_key in ['min_votes_for_leaderboard', 'leaderboard_size']:
        try:
            value = int(text)
            if value < 1:
                await update.message.reply_text("❌ 数值必须大于0。")
                return
            text = str(value)
        except ValueError:
            await update.message.reply_text("❌ 请输入有效的数字。")
            return
    
    # 设置配置
    success = await set_setting(setting_key, text, update.effective_user.id)
    
    if success:
        setting_names = {
            'admin_password': '管理员密码',
            'min_votes_for_leaderboard': '排行榜最小投票数',
            'leaderboard_size': '排行榜显示数量'
        }
        
        setting_name = setting_names.get(setting_key, setting_key)
        
        message = f"✅ **{setting_name}更新成功**\n\n"
        
        if setting_key == 'admin_password':
            message += f"新密码: `{text[:20]}{'...' if len(text) > 20 else ''}`"
        else:
            message += f"新值: `{text}`"
        
        keyboard = [[InlineKeyboardButton("🔙 返回系统设置", callback_data="admin_panel_system")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("❌ 更新设置失败，请重试。")

async def handle_remove_from_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """处理从排行榜移除用户"""
    user_identifier = text.strip()
    
    # 尝试解析为用户ID或用户名
    target_user = None
    
    if user_identifier.isdigit():
        # 按用户ID查找
        target_user = await db_fetch_one("SELECT id, username, first_name FROM users WHERE id = $1", int(user_identifier))
    else:
        # 按用户名查找
        target_user = await db_fetch_one("SELECT id, username, first_name FROM users WHERE username = $1", user_identifier)
    
    if not target_user:
        await update.message.reply_text("❌ 未找到该用户。")
        return
    
    # 获取用户评价统计
    reputation_count = await db_fetchval("SELECT COUNT(*) FROM reputations WHERE target_id = $1", target_user['id'])
    
    if reputation_count == 0:
        await update.message.reply_text("ℹ️ 该用户没有评价记录。")
        return
    
    # 删除用户的所有评价记录
    try:
        async with db_transaction() as conn:
            await conn.execute("DELETE FROM reputations WHERE target_id = $1", target_user['id'])
            await conn.execute("DELETE FROM favorites WHERE target_id = $1", target_user['id'])
        
        # 清除排行榜缓存
        from handlers.leaderboard import clear_leaderboard_cache
        clear_leaderboard_cache()
        
        user_name = target_user['first_name'] or target_user['username'] or f"用户{target_user['id']}"
        
        message = f"✅ **用户已从排行榜移除**\n\n"
        message += f"用户: **{user_name}**\n"
        message += f"删除了 **{reputation_count}** 条评价记录"
        
        keyboard = [[InlineKeyboardButton("🔙 返回排行榜管理", callback_data="admin_leaderboard_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
        logger.info(f"管理员 {update.effective_user.id} 从排行榜移除用户 {target_user['id']}")
        
    except Exception as e:
        logger.error(f"从排行榜移除用户失败: {e}")
        await update.message.reply_text("❌ 移除用户失败，请重试。")
