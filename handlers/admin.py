import logging
import re
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction

logger = logging.getLogger(__name__)

# 定义管理员操作类型
class AdminAction(Enum):
    ADD_TAG_RECOMMEND = "add_tag_recommend"
    ADD_TAG_BLOCK = "add_tag_block"
    ADD_ADMIN = "add_admin"
    SET_SETTING = "set_setting"
    REMOVE_LEADERBOARD = "remove_leaderboard"
    ADD_MOTTO = "add_motto"

async def is_admin(user_id):
    """检查用户是否是管理员"""
    async with db_transaction() as conn:
        result = await conn.fetchval("SELECT is_admin FROM users WHERE id = $1", user_id)
        return bool(result)

async def god_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /godmode 命令 - 管理员入口"""
    user_id = update.effective_user.id
    
    # 检查用户是否是管理员
    if not await is_admin(user_id):
        await update.message.reply_text("你不是守护者，无法使用此命令。")
        return
    
    await settings_menu(update, context)

async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示管理员设置菜单"""
    # 确认是通过命令还是回调查询访问的
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        edit_message = query.edit_message_text
    else:
        edit_message = update.message.reply_text
    
    # 创建管理员菜单按钮
    keyboard = [
        [
            InlineKeyboardButton("🏷️ 标签管理", callback_data="admin_panel_tags"),
            InlineKeyboardButton("👥 权限管理", callback_data="admin_panel_permissions")
        ],
        [
            InlineKeyboardButton("⚙️ 系统设置", callback_data="admin_panel_system"),
            InlineKeyboardButton("🏆 排行榜管理", callback_data="admin_leaderboard_panel")
        ],
        [
            InlineKeyboardButton("📝 添加箴言", callback_data="admin_add_motto_prompt")
        ],
        [
            InlineKeyboardButton("返回主菜单", callback_data="back_to_help")
        ]
    ]
    
    await edit_message(
        "🌌 **时空枢纽** - 管理员控制面板\n\n请选择要管理的功能区域：",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ===== 标签管理 =====

async def tags_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示标签管理面板"""
    query = update.callback_query
    
    keyboard = [
        [
            InlineKeyboardButton("➕ 添加推荐标签", callback_data="admin_tags_add_recommend_prompt"),
            InlineKeyboardButton("➕ 添加警告标签", callback_data="admin_tags_add_block_prompt")
        ],
        [
            InlineKeyboardButton("➖ 删除标签", callback_data="admin_tags_remove_menu_1"),
            InlineKeyboardButton("📋 查看所有标签", callback_data="admin_tags_list")
        ],
        [
            InlineKeyboardButton("返回设置菜单", callback_data="admin_settings_menu")
        ]
    ]
    
    await query.edit_message_text(
        "🏷️ **标签管理**\n\n管理可用于评价用户的标签。",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def add_tag_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_type):
    """提示添加新标签"""
    query = update.callback_query
    
    # 保存下一步要执行的操作
    context.user_data['next_action'] = AdminAction.ADD_TAG_RECOMMEND.value if tag_type == 'recommend' else AdminAction.ADD_TAG_BLOCK.value
    
    tag_type_text = "推荐标签" if tag_type == 'recommend' else "警告标签"
    
    # 创建取消按钮
    keyboard = [[InlineKeyboardButton("取消", callback_data="admin_settings_menu")]]
    
    await query.edit_message_text(
        f"请输入要添加的{tag_type_text}名称（不要包含#号）：\n"
        f"您可以一次添加多个标签，每行一个标签。\n\n"
        f"完成后，会自动返回标签管理面板。",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def remove_tag_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, page=1):
    """显示可删除的标签列表"""
    query = update.callback_query
    
    # 获取标签列表
    async with db_transaction() as conn:
        all_tags = await conn.fetch("SELECT id, name, tag_type FROM tags ORDER BY tag_type, name")
    
    if not all_tags:
        keyboard = [[InlineKeyboardButton("返回标签管理", callback_data="admin_panel_tags")]]
        await query.edit_message_text(
            "当前没有任何标签可删除。",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # 分页处理
    page_size = 8
    total_pages = (len(all_tags) + page_size - 1) // page_size
    page = max(1, min(page, total_pages))
    
    start_idx = (page - 1) * page_size
    end_idx = min(start_idx + page_size, len(all_tags))
    
    # 创建标签按钮
    keyboard = []
    for i in range(start_idx, end_idx):
        tag = all_tags[i]
        tag_type_emoji = "✅" if tag['tag_type'] == 'recommend' else "❌"
        keyboard.append([
            InlineKeyboardButton(
                f"{tag_type_emoji} {tag['name']}",
                callback_data=f"admin_tags_remove_confirm_{tag['id']}_{page}"
            )
        ])
    
    # 添加翻页按钮
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton("◀️ 上一页", callback_data=f"admin_tags_remove_menu_{page-1}")
        )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton("▶️ 下一页", callback_data=f"admin_tags_remove_menu_{page+1}")
        )
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    # 添加返回按钮
    keyboard.append([InlineKeyboardButton("返回标签管理", callback_data="admin_panel_tags")])
    
    await query.edit_message_text(
        f"选择要删除的标签 (第 {page}/{total_pages} 页)：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def remove_tag_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, tag_id, page):
    """确认删除标签"""
    query = update.callback_query
    
    # 获取标签信息
    async with db_transaction() as conn:
        tag_info = await conn.fetchrow("SELECT name, tag_type FROM tags WHERE id = $1", tag_id)
        if not tag_info:
            await query.answer("该标签不存在或已被删除", show_alert=True)
            await remove_tag_menu(update, context, page)
            return
        
        # 检查标签是否有关联的评价
        usage_count = await conn.fetchval("""
            SELECT COUNT(*) FROM reputation_tags WHERE tag_id = $1
        """, tag_id)
    
    tag_name = tag_info['name']
    tag_type_text = "推荐标签" if tag_info['tag_type'] == 'recommend' else "警告标签"
    
    # 创建确认按钮
    keyboard = [
        [
            InlineKeyboardButton("✅ 确认删除", callback_data=f"admin_tags_delete_{tag_id}_{page}"),
            InlineKeyboardButton("❌ 取消", callback_data=f"admin_tags_remove_menu_{page}")
        ]
    ]
    
    warning_text = f"确认要删除{tag_type_text} **{tag_name}**？\n\n"
    if usage_count > 0:
        warning_text += f"⚠️ 该标签已被使用了 {usage_count} 次。删除后，相关评价将失去此标签。"
    
    await query.edit_message_text(
        warning_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def list_all_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有标签"""
    query = update.callback_query
    
    # 获取所有标签
    async with db_transaction() as conn:
        recommend_tags = await conn.fetch(
            "SELECT name, COUNT(rt.tag_id) as usage FROM tags t "
            "LEFT JOIN reputation_tags rt ON t.id = rt.tag_id "
            "WHERE tag_type = 'recommend' "
            "GROUP BY t.id, t.name "
            "ORDER BY name"
        )
        
        block_tags = await conn.fetch(
            "SELECT name, COUNT(rt.tag_id) as usage FROM tags t "
            "LEFT JOIN reputation_tags rt ON t.id = rt.tag_id "
            "WHERE tag_type = 'block' "
            "GROUP BY t.id, t.name "
            "ORDER BY name"
        )
    
    # 创建标签列表文本
    text = "📋 **系统中的所有标签**\n\n"
    
    # 推荐标签
    text += "**✅ 推荐标签：**\n"
    if recommend_tags:
        for i, tag in enumerate(recommend_tags, 1):
            text += f"{i}. #{tag['name']} (使用次数: {tag['usage']})\n"
    else:
        text += "暂无推荐标签\n"
    
    text += "\n**❌ 警告标签：**\n"
    if block_tags:
        for i, tag in enumerate(block_tags, 1):
            text += f"{i}. #{tag['name']} (使用次数: {tag['usage']})\n"
    else:
        text += "暂无警告标签\n"
    
    # 创建返回按钮
    keyboard = [[InlineKeyboardButton("返回标签管理", callback_data="admin_panel_tags")]]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ===== 权限管理 =====

async def permissions_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示权限管理面板"""
    query = update.callback_query
    
    keyboard = [
        [
            InlineKeyboardButton("➕ 添加管理员", callback_data="admin_perms_add_prompt"),
            InlineKeyboardButton("➖ 删除管理员", callback_data="admin_perms_remove_menu")
        ],
        [
            InlineKeyboardButton("📋 查看管理员列表", callback_data="admin_perms_list")
        ],
        [
            InlineKeyboardButton("返回设置菜单", callback_data="admin_settings_menu")
        ]
    ]
    
    await query.edit_message_text(
        "👥 **权限管理**\n\n管理可访问管理面板的用户。",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示添加新管理员"""
    query = update.callback_query
    
    # 保存下一步要执行的操作
    context.user_data['next_action'] = AdminAction.ADD_ADMIN.value
    
    # 创建取消按钮
    keyboard = [[InlineKeyboardButton("取消", callback_data="admin_panel_permissions")]]
    
    await query.edit_message_text(
        "请输入要添加为管理员的用户ID：\n"
        "(用户ID必须是一个数字，可以通过 @userinfobot 获取)",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有管理员"""
    query = update.callback_query
    
    # 获取所有管理员
    async with db_transaction() as conn:
        admins = await conn.fetch(
            "SELECT id, username, created_at FROM users WHERE is_admin = TRUE ORDER BY created_at"
        )
    
    # 创建管理员列表文本
    text = "👥 **系统管理员列表**\n\n"
    
    if admins:
        for i, admin in enumerate(admins, 1):
            username = admin['username'] or "未知用户名"
            join_date = admin['created_at'].strftime("%Y-%m-%d")
            text += f"{i}. @{username} (ID: {admin['id']}, 加入时间: {join_date})\n"
    else:
        text += "系统中没有管理员记录。"
    
    # 创建返回按钮
    keyboard = [[InlineKeyboardButton("返回权限管理", callback_data="admin_panel_permissions")]]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def remove_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示可删除的管理员列表"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # 获取除了当前用户之外的所有管理员
    async with db_transaction() as conn:
        admins = await conn.fetch(
            "SELECT id, username FROM users WHERE is_admin = TRUE AND id != $1 ORDER BY username",
            user_id
        )
    
    if not admins:
        keyboard = [[InlineKeyboardButton("返回权限管理", callback_data="admin_panel_permissions")]]
        await query.edit_message_text(
            "没有其他管理员可以删除。",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # 创建管理员按钮
    keyboard = []
    for admin in admins:
        username = admin['username'] or f"用户 {admin['id']}"
        keyboard.append([
            InlineKeyboardButton(
                f"@{username}",
                callback_data=f"admin_perms_remove_confirm_{admin['id']}"
            )
        ])
    
    # 添加返回按钮
    keyboard.append([InlineKeyboardButton("返回权限管理", callback_data="admin_panel_permissions")])
    
    await query.edit_message_text(
        "选择要移除管理员权限的用户：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def remove_admin_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, admin_id):
    """确认删除管理员"""
    query = update.callback_query
    
    # 获取管理员信息
    async with db_transaction() as conn:
        admin_info = await conn.fetchrow(
            "SELECT username FROM users WHERE id = $1 AND is_admin = TRUE",
            admin_id
        )
        
        if not admin_info:
            await query.answer("该用户不是管理员或不存在", show_alert=True)
            await remove_admin_menu(update, context)
            return
        
        # 执行权限移除
        await conn.execute(
            "UPDATE users SET is_admin = FALSE WHERE id = $1",
            admin_id
        )
    
    username = admin_info['username'] or f"用户 {admin_id}"
    
    await query.answer(f"已移除 @{username} 的管理员权限", show_alert=True)
    
    # 返回管理员列表
    await remove_admin_menu(update, context)

# ===== 系统设置 =====

async def system_settings_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统设置面板"""
    query = update.callback_query
    
    # 获取当前设置
    async with db_transaction() as conn:
        settings = await conn.fetch("SELECT key, value FROM settings")
    
    settings_dict = {row['key']: row['value'] for row in settings}
    
    # 创建设置列表文本
    text = "⚙️ **系统设置**\n\n"
    
    # 显示设置项
    settings_map = {
        "min_reputation_votes": "最低评价阈值",
        "max_daily_votes": "每日最大投票数",
        "leaderboard_min_votes": "排行榜最低阈值",
        "leaderboard_size": "排行榜显示数量"
    }
    
    for key, name in settings_map.items():
        value = settings_dict.get(key, "未设置")
        text += f"• **{name}**: {value}\n"
    
    # 创建设置按钮
    keyboard = []
    for key, name in settings_map.items():
        keyboard.append([
            InlineKeyboardButton(f"设置 {name}", callback_data=f"admin_system_set_prompt_{key}")
        ])
    
    # 添加箴言管理按钮
    keyboard.append([
        InlineKeyboardButton("📝 添加箴言", callback_data="admin_add_motto_prompt")
    ])
    
    # 添加返回按钮
    keyboard.append([InlineKeyboardButton("返回设置菜单", callback_data="admin_settings_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def set_setting_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, setting_key):
    """提示设置系统设置值"""
    query = update.callback_query
    
    # 保存下一步要执行的操作和设置键
    context.user_data['next_action'] = AdminAction.SET_SETTING.value
    context.user_data['setting_key'] = setting_key
    
    # 获取设置的名称
    settings_map = {
        "min_reputation_votes": "最低评价阈值",
        "max_daily_votes": "每日最大投票数",
        "leaderboard_min_votes": "排行榜最低阈值",
        "leaderboard_size": "排行榜显示数量"
    }
    
    setting_name = settings_map.get(setting_key, setting_key)
    
    # 获取当前设置值
    async with db_transaction() as conn:
        setting_value = await conn.fetchval(
            "SELECT value FROM settings WHERE key = $1",
            setting_key
        )
    
    # 创建取消按钮
    keyboard = [[InlineKeyboardButton("取消", callback_data="admin_panel_system")]]
    
    await query.edit_message_text(
        f"请输入 **{setting_name}** 的新值：\n"
        f"(当前值: {setting_value or '未设置'})\n\n"
        f"此项设置应该为一个整数值。",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ===== 排行榜管理 =====

async def leaderboard_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示排行榜管理面板"""
    query = update.callback_query
    
    keyboard = [
        [
            InlineKeyboardButton("移除用户从排行榜", callback_data="admin_leaderboard_remove_prompt"),
            InlineKeyboardButton("清除排行榜缓存", callback_data="admin_leaderboard_clear_cache")
        ],
        [
            InlineKeyboardButton("返回设置菜单", callback_data="admin_settings_menu")
        ]
    ]
    
    await query.edit_message_text(
        "🏆 **排行榜管理**\n\n"
        "在这里您可以管理系统排行榜功能。",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def remove_from_leaderboard_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示输入要从排行榜中移除的用户"""
    query = update.callback_query
    
    # 保存下一步要执行的操作
    context.user_data['next_action'] = AdminAction.REMOVE_LEADERBOARD.value
    
    # 创建取消按钮
    keyboard = [[InlineKeyboardButton("取消", callback_data="admin_leaderboard_panel")]]
    
    await query.edit_message_text(
        "请输入要从排行榜中移除的用户ID或用户名：\n"
        "(用户ID必须是一个数字，用户名需要包含@符号)",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ===== 箴言管理 =====

async def add_motto_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提示添加新箴言"""
    query = update.callback_query
    
    # 保存下一步要执行的操作
    context.user_data['next_action'] = AdminAction.ADD_MOTTO.value
    
    # 创建取消按钮
    keyboard = [[InlineKeyboardButton("取消", callback_data="admin_settings_menu")]]
    
    await query.edit_message_text(
        "请输入要添加的箴言内容：\n"
        "您可以一次添加多条箴言，每行一条。\n\n"
        "完成后，会自动返回到设置菜单。",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

# ===== 处理管理员输入 =====

async def process_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员在私聊中的输入"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # 检查用户是否是管理员
    if not await is_admin(user_id):
        await update.message.reply_text("你不是守护者，无法执行管理操作。")
        return
    
    # 检查是否有待处理的操作
    if 'next_action' not in context.user_data:
