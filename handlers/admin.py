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

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """管理员面板处理器"""
    query = update.callback_query
    user_id = update.effective_user.id
    
    if not await is_admin(user_id):
        await query.answer("❌ 权限不足", show_alert=True)
        return
    
    await query.answer()
    
    if query.data == "admin_panel_tags":
        await tag_management_menu(update, context)
    elif query.data == "admin_panel_mottos":
        await motto_management_menu(update, context)
    elif query.data == "admin_panel_permissions":
        await permission_management_menu(update, context)
    elif query.data == "admin_panel_system":
        await system_settings_menu(update, context)
    elif query.data == "admin_leaderboard_panel":
        await leaderboard_management_menu(update, context)
    elif query.data == "admin_show_commands":
        await show_admin_commands(update, context)

async def tag_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """标签管理菜单"""
    message = "🏷️ **标签管理中心**\n\n选择操作："
    
    keyboard = [
        [InlineKeyboardButton("📊 查看所有标签", callback_data="admin_view_all_tags")],
        [InlineKeyboardButton("➕ 添加新标签", callback_data="admin_add_tag")],
        [InlineKeyboardButton("✏️ 编辑标签", callback_data="admin_edit_tag")],
        [InlineKeyboardButton("🗑️ 删除标签", callback_data="admin_delete_tag")],
        [InlineKeyboardButton("📈 标签统计", callback_data="admin_tag_stats")],
        [InlineKeyboardButton("🔙 返回管理中心", callback_data="back_to_admin_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def motto_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """便签管理菜单"""
    message = "📝 **便签管理中心**\n\n选择操作："
    
    keyboard = [
        [InlineKeyboardButton("📊 查看便签统计", callback_data="admin_motto_stats")],
        [InlineKeyboardButton("🗑️ 删除便签", callback_data="admin_delete_motto")],
        [InlineKeyboardButton("📋 批量导入", callback_data="admin_batch_import")],
        [InlineKeyboardButton("📤 批量导出", callback_data="admin_batch_export")],
        [InlineKeyboardButton("🔍 搜索便签", callback_data="admin_search_mottos")],
        [InlineKeyboardButton("🔙 返回管理中心", callback_data="back_to_admin_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def permission_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """权限管理菜单"""
    message = "👑 **权限管理中心**\n\n选择操作："
    
    keyboard = [
        [InlineKeyboardButton("👥 查看管理员列表", callback_data="admin_view_admins")],
        [InlineKeyboardButton("➕ 添加管理员", callback_data="admin_add_admin")],
        [InlineKeyboardButton("➖ 移除管理员", callback_data="admin_remove_admin")],
        [InlineKeyboardButton("🔐 修改神谕密钥", callback_data="admin_change_password")],
        [InlineKeyboardButton("👤 用户信息查询", callback_data="admin_user_info")],
        [InlineKeyboardButton("🔙 返回管理中心", callback_data="back_to_admin_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def system_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """系统设置菜单"""
    message = "⚙️ **系统设置中心**\n\n选择操作："
    
    keyboard = [
        [InlineKeyboardButton("📊 系统状态", callback_data="admin_system_status")],
        [InlineKeyboardButton("🗄️ 数据库管理", callback_data="admin_database_menu")],
        [InlineKeyboardButton("📝 查看日志", callback_data="admin_view_logs")],
        [InlineKeyboardButton("🔧 系统维护", callback_data="admin_maintenance")],
        [InlineKeyboardButton("📤 备份数据", callback_data="admin_backup_data")],
        [InlineKeyboardButton("🔙 返回管理中心", callback_data="back_to_admin_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def leaderboard_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """排行榜管理菜单"""
    message = "🏆 **排行榜管理中心**\n\n选择操作："
    
    keyboard = [
        [InlineKeyboardButton("📊 查看排行榜", callback_data="admin_view_leaderboard")],
        [InlineKeyboardButton("🔄 重置排行榜", callback_data="admin_reset_leaderboard")],
        [InlineKeyboardButton("⚙️ 排行榜设置", callback_data="admin_leaderboard_settings")],
        [InlineKeyboardButton("📈 详细统计", callback_data="admin_detailed_stats")],
        [InlineKeyboardButton("🔙 返回管理中心", callback_data="back_to_admin_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

async def show_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示所有管理员命令"""
    commands_text = """📋 **管理员命令大全**

🔐 **权限管理**
• `/godmode <密码>` - 获取管理员权限
• `/admin` - 打开管理面板

🏷️ **标签管理**
• `/addtag <标签名>` - 添加新标签
• `/deltag <标签ID>` - 删除标签
• `/listtags` - 查看所有标签

📝 **便签管理**  
• `/delmotto <ID>` - 删除指定便签
• `/searchmotto <关键词>` - 搜索便签
• `/exportmottos` - 导出所有便签

👥 **用户管理**
• `/userinfo <用户ID>` - 查看用户信息
• `/addadmin <用户ID>` - 添加管理员
• `/removeadmin <用户ID>` - 移除管理员

⚙️ **系统管理**
• `/systemstats` - 系统状态
• `/backup` - 备份数据
• `/maintenance` - 维护模式

🏆 **排行榜管理**
• `/resetleaderboard` - 重置排行榜
• `/leaderboardstats` - 排行榜统计
"""
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回管理中心", callback_data="back_to_admin_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        commands_text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# 标签管理功能实现
async def view_all_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看所有标签"""
    query = update.callback_query
    await query.answer()
    
    try:
        tags = await db_fetch_all(
            "SELECT id, name, created_at, (SELECT COUNT(*) FROM motto_tags mt WHERE mt.tag_id = tags.id) as usage_count FROM tags ORDER BY usage_count DESC"
        )
        
        if not tags:
            message = "📊 **标签统计**\n\n暂无标签数据。"
        else:
            message = "📊 **所有标签列表**\n\n"
            for tag in tags:
                message += f"🏷️ **{tag['name']}** (ID: {tag['id']})\n"
                message += f"   使用次数: {tag['usage_count']}\n"
                message += f"   创建时间: {tag['created_at'].strftime('%Y-%m-%d')}\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回标签管理", callback_data="admin_panel_tags")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"查看标签失败: {e}")
        await query.edit_message_text(
            "❌ 获取标签信息失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_tags")]])
        )

async def add_new_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加新标签"""
    query = update.callback_query
    await query.answer()
    
    message = "➕ **添加新标签**\n\n请发送标签名称："
    
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
    context.user_data['waiting_for'] = 'new_tag_name'

async def process_new_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理新标签输入"""
    if context.user_data.get('waiting_for') != 'new_tag_name':
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
        tag_id = await db_fetchval(
            "INSERT INTO tags (name, created_by) VALUES ($1, $2) RETURNING id",
            tag_name, user_id
        )
        
        await update.message.reply_text(f"✅ 标签 '{tag_name}' 添加成功！\n标签ID: {tag_id}")
        
        # 清除等待状态
        context.user_data.pop('waiting_for', None)
        
    except Exception as e:
        logger.error(f"添加标签失败: {e}")
        await update.message.reply_text("❌ 添加标签失败，请稍后重试。")

# 便签管理功能实现
async def motto_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示便签统计"""
    query = update.callback_query
    await query.answer()
    
    try:
        # 获取便签统计数据
        total_mottos = await db_fetchval("SELECT COUNT(*) FROM mottos")
        total_users = await db_fetchval("SELECT COUNT(DISTINCT user_id) FROM mottos")
        today_mottos = await db_fetchval(
            "SELECT COUNT(*) FROM mottos WHERE DATE(created_at) = CURRENT_DATE"
        )
        
        # 获取最活跃用户
        top_users = await db_fetch_all("""
            SELECT u.username, u.first_name, COUNT(m.id) as motto_count
            FROM users u
            JOIN mottos m ON u.id = m.user_id
            GROUP BY u.id, u.username, u.first_name
            ORDER BY motto_count DESC
            LIMIT 5
        """)
        
        # 获取最受欢迎的标签
        top_tags = await db_fetch_all("""
            SELECT t.name, COUNT(mt.motto_id) as usage_count
            FROM tags t
            JOIN motto_tags mt ON t.id = mt.tag_id
            GROUP BY t.id, t.name
            ORDER BY usage_count DESC
            LIMIT 5
        """)
        
        message = f"""📊 **便签统计报告**

📝 **基础数据**
• 总便签数: {total_mottos}
• 参与用户: {total_users}
• 今日新增: {today_mottos}

👑 **最活跃用户**
"""
        
        for i, user in enumerate(top_users, 1):
            name = user['username'] or user['first_name'] or '未知用户'
            message += f"{i}. {name}: {user['motto_count']}条\n"
        
        if top_tags:
            message += "\n🏷️ **热门标签**\n"
            for i, tag in enumerate(top_tags, 1):
                message += f"{i}. {tag['name']}: {tag['usage_count']}次\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回便签管理", callback_data="admin_panel_mottos")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"获取便签统计失败: {e}")
        await query.edit_message_text(
            "❌ 获取统计数据失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_mottos")]])
        )

# 权限管理功能实现
async def view_admin_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看管理员列表"""
    query = update.callback_query
    await query.answer()
    
    try:
        admins = await db_fetch_all(
            "SELECT id, username, first_name, created_at FROM users WHERE is_admin = TRUE ORDER BY created_at"
        )
        
        if not admins:
            message = "👑 **管理员列表**\n\n暂无管理员。"
        else:
            message = "👑 **管理员列表**\n\n"
            for admin in admins:
                name = admin['username'] or admin['first_name'] or '未知用户'
                message += f"👤 **{name}** (ID: {admin['id']})\n"
                message += f"   注册时间: {admin['created_at'].strftime('%Y-%m-%d')}\n\n"
        
        keyboard = [
            [InlineKeyboardButton("➕ 添加管理员", callback_data="admin_add_admin")],
            [InlineKeyboardButton("➖ 移除管理员", callback_data="admin_remove_admin")],
            [InlineKeyboardButton("🔙 返回权限管理", callback_data="admin_panel_permissions")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"查看管理员列表失败: {e}")
        await query.edit_message_text(
            "❌ 获取管理员信息失败。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data="admin_panel_permissions")]])
        )

# 系统设置功能实现
async def system_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统状态"""
    query = update.callback_query
    await query.answer()
    
    try:
        import psutil
        import datetime
        
        # 获取系统信息
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # 获取数据库统计
        db_stats = await db_fetch_all("""
            SELECT 
                'mottos' as table_name,
                COUNT(*) as count
            FROM mottos
            UNION ALL
            SELECT 
                'users' as table_name,
                COUNT(*) as count
            FROM users
            UNION ALL
            SELECT 
                'tags' as table_name,
                COUNT(*) as count
            FROM tags
        """)
        
        message = f"""📊 **系统状态报告**

🖥️ **系统资源**
• CPU使用率: {cpu_percent}%
• 内存使用: {memory.percent}% ({memory.used // 1024 // 1024}MB / {memory.total // 1024 // 1024}MB)
• 磁盘使用: {disk.percent}% ({disk.used // 1024 // 1024 // 1024}GB / {disk.total // 1024 // 1024 // 1024}GB)

🗄️ **数据库统计**
"""
        
        for stat in db_stats:
            message += f"• {stat['table_name']}: {stat['count']}条记录\n"
        
        message += f"\n⏰ **系统时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        keyboard = [
            [InlineKeyboardButton("🔄 刷新", callback_data="admin_system_status")],
            [InlineKeyboardButton("🔙 返回系统设置", callback_data="admin_panel_system")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"获取系统状态失败: {e}")
        message = "❌ 获取系统状态失败。\n\n可能原因：\n• psutil模块未安装\n• 权限不足\n• 系统错误"
        
        keyboard = [
            [InlineKeyboardButton("🔙 返回系统设置", callback_data="admin_panel_system")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

# 处理各种回调
async def handle_admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员回调"""
    query = update.callback_query
    data = query.data
    
    # 权限检查
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await query.answer("❌ 权限不足", show_alert=True)
        return
    
    # 根据callback_data分发处理
    if data == "back_to_admin_menu":
        await settings_menu(update, context)
    elif data == "admin_view_all_tags":
        await view_all_tags(update, context)
    elif data == "admin_add_tag":
        await add_new_tag(update, context)
    elif data == "admin_motto_stats":
        await motto_statistics(update, context)
    elif data == "admin_view_admins":
        await view_admin_list(update, context)
    elif data == "admin_system_status":
        await system_status(update, context)
    elif data.startswith("admin_"):
        # 处理其他admin相关的callback
        await handle_other_admin_actions(update, context)

async def handle_other_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理其他管理员操作"""
    query = update.callback_query
    data = query.data
    await query.answer()
    
    # 这里可以添加更多的管理员操作处理逻辑
    if data == "admin_edit_tag":
        message = "✏️ **编辑标签**\n\n该功能正在开发中..."
    elif data == "admin_delete_tag":
        message = "🗑️ **删除标签**\n\n该功能正在开发中..."
    elif data == "admin_tag_stats":
        message = "📈 **标签统计**\n\n该功能正在开发中..."
    elif data == "admin_delete_motto":
        message = "🗑️ **删除便签**\n\n该功能正在开发中..."
    elif data == "admin_batch_import":
        message = "📋 **批量导入**\n\n该功能正在开发中..."
    elif data == "admin_batch_export":
        message = "📤 **批量导出**\n\n该功能正在开发中..."
    elif data == "admin_search_mottos":
        message = "🔍 **搜索便签**\n\n该功能正在开发中..."
    elif data == "admin_add_admin":
        message = "➕ **添加管理员**\n\n该功能正在开发中..."
    elif data == "admin_remove_admin":
        message = "➖ **移除管理员**\n\n该功能正在开发中..."
    elif data == "admin_change_password":
        message = "🔐 **修改神谕密钥**\n\n该功能正在开发中..."
    elif data == "admin_user_info":
        message = "👤 **用户信息查询**\n\n该功能正在开发中..."
    elif data == "admin_database_menu":
        message = "🗄️ **数据库管理**\n\n该功能正在开发中..."
    elif data == "admin_view_logs":
        message = "📝 **查看日志**\n\n该功能正在开发中..."
    elif data == "admin_maintenance":
        message = "🔧 **系统维护**\n\n该功能正在开发中..."
    elif data == "admin_backup_data":
        message = "📤 **备份数据**\n\n该功能正在开发中..."
    elif data == "admin_view_leaderboard":
        message = "📊 **查看排行榜**\n\n该功能正在开发中..."
    elif data == "admin_reset_leaderboard":
        message = "🔄 **重置排行榜**\n\n该功能正在开发中..."
    elif data == "admin_leaderboard_settings":
        message = "⚙️ **排行榜设置**\n\n该功能正在开发中..."
    elif data == "admin_detailed_stats":
        message = "📈 **详细统计**\n\n该功能正在开发中..."
    else:
        message = "❓ 未知操作"
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回管理中心", callback_data="back_to_admin_menu")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )

# 分页功能支持
async def create_pagination_keyboard(items: List[Dict], page: int, per_page: int, callback_prefix: str):
    """创建分页键盘"""
    total_pages = (len(items) + per_page - 1) // per_page
    
    # 计算当前页显示的项目
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(items))
    current_items = items[start_idx:end_idx]
    
    keyboard = []
    
    # 添加项目按钮
    for item in current_items:
        keyboard.append([InlineKeyboardButton(
            f"{item['display_text']}", 
            callback_data=f"{callback_prefix}_{item['id']}"
        )])
    
    # 添加翻页按钮
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"{callback_prefix}_page_{page-1}"))
        
        nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="ignore"))
        
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("➡️ 下一页", callback_data=f"{callback_prefix}_page_{page+1}"))
        
        # 修复第1018行的缩进问题 - 确保这里有正确的缩进
        if nav_buttons:
            keyboard.append(nav_buttons)
    
    return InlineKeyboardMarkup(keyboard)

# 数据导入导出功能
async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE, data_type: str):
    """数据导出功能"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        if data_type == "mottos":
            data = await db_fetch_all("""
                SELECT m.id, m.content, m.created_at, u.username, u.first_name,
                       array_agg(t.name) as tags
                FROM mottos m
                JOIN users u ON m.user_id = u.id
                LEFT JOIN motto_tags mt ON m.id = mt.motto_id
                LEFT JOIN tags t ON mt.tag_id = t.id
                GROUP BY m.id, m.content, m.created_at, u.username, u.first_name
                ORDER BY m.created_at DESC
            """)
        elif data_type == "users":
            data = await db_fetch_all("""
                SELECT id, username, first_name, is_admin, created_at,
                       (SELECT COUNT(*) FROM mottos WHERE user_id = users.id) as motto_count
                FROM users
                ORDER BY created_at DESC
            """)
        elif data_type == "tags":
            data = await db_fetch_all("""
                SELECT t.id, t.name, t.created_at,
                       COUNT(mt.motto_id) as usage_count
                FROM tags t
                LEFT JOIN motto_tags mt ON t.id = mt.tag_id
                GROUP BY t.id, t.name, t.created_at
                ORDER BY usage_count DESC
            """)
        else:
            await update.message.reply_text("❌ 不支持的数据类型")
            return
        
        # 转换为CSV格式
        import io
        import csv
        
        output = io.StringIO()
        if data:
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            for row in data:
                # 处理特殊字段
                processed_row = {}
                for key, value in row.items():
                    if key == 'created_at' and value:
                        processed_row[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                    elif isinstance(value, list):
                        processed_row[key] = ', '.join(filter(None, value))
                    else:
                        processed_row[key] = value
                writer.writerow(processed_row)
        
        csv_content = output.getvalue()
        output.close()
        
        # 发送文件
        from io import BytesIO
        file_buffer = BytesIO(csv_content.encode('utf-8'))
        file_buffer.name = f"{data_type}_export_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        await update.message.reply_document(
            document=file_buffer,
            filename=file_buffer.name,
            caption=f"📤 {data_type} 数据导出完成\n\n共 {len(data)} 条记录"
        )
        
    except Exception as e:
        logger.error(f"数据导出失败: {e}")
        await update.message.reply_text("❌ 数据导出失败，请稍后重试。")

# 批量操作功能
async def batch_delete_mottos(update: Update, context: ContextTypes.DEFAULT_TYPE, motto_ids: List[int]):
    """批量删除便签"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        async with db_transaction() as tx:
            # 删除标签关联
            await tx.execute(
                "DELETE FROM motto_tags WHERE motto_id = ANY($1)",
                motto_ids
            )
            
            # 删除便签
            deleted_count = await tx.fetchval(
                "DELETE FROM mottos WHERE id = ANY($1) RETURNING COUNT(*)",
                motto_ids
            )
            
            if deleted_count:
                await update.message.reply_text(f"✅ 成功删除 {deleted_count} 条便签")
                logger.info(f"管理员 {user_id} 批量删除了 {deleted_count} 条便签")
            else:
                await update.message.reply_text("❌ 没有找到要删除的便签")
    
    except Exception as e:
        logger.error(f"批量删除便签失败: {e}")
        await update.message.reply_text("❌ 批量删除失败，请稍后重试。")

# 高级搜索功能
async def advanced_search_mottos(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                               keyword: str = None, user_id: int = None, 
                               tag_name: str = None, date_from: str = None, 
                               date_to: str = None):
    """高级便签搜索"""
    if not await is_admin(update.effective_user.id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        conditions = []
        params = []
        param_count = 0
        
        query = """
            SELECT DISTINCT m.id, m.content, m.created_at, 
                   u.username, u.first_name,
                   array_agg(t.name) as tags
            FROM mottos m
            JOIN users u ON m.user_id = u.id
            LEFT JOIN motto_tags mt ON m.id = mt.motto_id
            LEFT JOIN tags t ON mt.tag_id = t.id
        """
        
        if keyword:
            param_count += 1
            conditions.append(f"m.content ILIKE ${param_count}")
            params.append(f"%{keyword}%")
        
        if user_id:
            param_count += 1
            conditions.append(f"m.user_id = ${param_count}")
            params.append(user_id)
        
        if tag_name:
            param_count += 1
            conditions.append(f"t.name = ${param_count}")
            params.append(tag_name)
        
        if date_from:
            param_count += 1
            conditions.append(f"m.created_at >= ${param_count}")
            params.append(date_from)
        
        if date_to:
            param_count += 1
            conditions.append(f"m.created_at <= ${param_count}")
            params.append(date_to)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += """
            GROUP BY m.id, m.content, m.created_at, u.username, u.first_name
            ORDER BY m.created_at DESC
            LIMIT 50
        """
        
        results = await db_fetch_all(query, *params)
        
        if not results:
            await update.message.reply_text("🔍 没有找到符合条件的便签。")
            return
        
        message = f"🔍 **搜索结果** (共 {len(results)} 条)\n\n"
        
        for i, motto in enumerate(results[:10], 1):  # 只显示前10条
            user_name = motto['username'] or motto['first_name'] or '未知用户'
            tags = ', '.join(filter(None, motto['tags'] or []))
            
            message += f"**{i}.** {motto['content'][:50]}{'...' if len(motto['content']) > 50 else ''}\n"
            message += f"   👤 {user_name} | 🏷️ {tags or '无'} | 📅 {motto['created_at'].strftime('%Y-%m-%d')}\n\n"
        
        if len(results) > 10:
            message += f"... 还有 {len(results) - 10} 条结果"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"高级搜索失败: {e}")
        await update.message.reply_text("❌ 搜索失败，请稍后重试。")

# 统计报告生成
async def generate_weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """生成周报告"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        # 获取本周数据
        week_stats = await db_fetch_one("""
            SELECT 
                COUNT(*) as total_mottos,
                COUNT(DISTINCT user_id) as active_users,
                AVG(LENGTH(content)) as avg_length
            FROM mottos 
            WHERE created_at >= date_trunc('week', CURRENT_DATE)
        """)
        
        # 获取上周数据对比
        last_week_stats = await db_fetch_one("""
            SELECT 
                COUNT(*) as total_mottos,
                COUNT(DISTINCT user_id) as active_users
            FROM mottos 
            WHERE created_at >= date_trunc('week', CURRENT_DATE) - interval '1 week'
              AND created_at < date_trunc('week', CURRENT_DATE)
        """)
        
        # 获取本周热门标签
        popular_tags = await db_fetch_all("""
            SELECT t.name, COUNT(*) as usage_count
            FROM tags t
            JOIN motto_tags mt ON t.id = mt.tag_id
            JOIN mottos m ON mt.motto_id = m.id
            WHERE m.created_at >= date_trunc('week', CURRENT_DATE)
            GROUP BY t.name
            ORDER BY usage_count DESC
            LIMIT 5
        """)
        
        # 生成报告
        motto_change = week_stats['total_mottos'] - last_week_stats['total_mottos']
        user_change = week_stats['active_users'] - last_week_stats['active_users']
        
        report = f"""📊 **本周数据报告**

📈 **核心指标**
• 新增便签: {week_stats['total_mottos']} ({'+' if motto_change >= 0 else ''}{motto_change})
• 活跃用户: {week_stats['active_users']} ({'+' if user_change >= 0 else ''}{user_change})
• 平均长度: {week_stats['avg_length']:.1f} 字符

🏷️ **热门标签**
"""
        
        for i, tag in enumerate(popular_tags, 1):
            report += f"{i}. {tag['name']}: {tag['usage_count']}次\n"
        
        report += f"\n📅 统计时间: {datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M')}"
        
        await update.message.reply_text(report, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"生成周报告失败: {e}")
        await update.message.reply_text("❌ 生成报告失败，请稍后重试。")

# 系统维护功能
async def cleanup_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """数据库清理"""
    user_id = update.effective_user.id
    if not await is_admin(user_id):
        await update.message.reply_text("❌ 权限不足")
        return
    
    try:
        async with db_transaction() as tx:
            # 清理孤立的标签关联
            orphaned_relations = await tx.fetchval("""
                DELETE FROM motto_tags 
                WHERE motto_id NOT IN (SELECT id FROM mottos) 
                   OR tag_id NOT IN (SELECT id FROM tags)
                RETURNING COUNT(*)
            """)
            
            # 清理未使用的标签
            unused_tags = await tx.fetchval("""
                DELETE FROM tags 
                WHERE id NOT IN (SELECT DISTINCT tag_id FROM motto_tags)
                RETURNING COUNT(*)
            """)
            
            # 更新统计信息
            await tx.execute("ANALYZE mottos")
            await tx.execute("ANALYZE users")
            await tx.execute("ANALYZE tags")
            await tx.execute("ANALYZE motto_tags")
            
            message = f"""🧹 **数据库清理完成**

✅ 清理结果:
• 孤立关联: {orphaned_relations} 条
• 未用标签: {unused_tags} 个
• 统计信息已更新

数据库已优化完成！"""
            
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
            logger.info(f"管理员 {user_id} 执行了数据库清理")
    
    except Exception as e:
        logger.error(f"数据库清理失败: {e}")
        await update.message.reply_text("❌ 数据库清理失败，请稍后重试。")

# 消息处理器
async def handle_admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理管理员文本输入"""
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
    # 可以添加更多输入处理逻辑

async def process_password_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理密码修改"""
    new_password = update.message.text.strip()
    user_id = update.effective_user.id
    
    try:
        await set_setting('admin_password', new_password)
        await update.message.reply_text("✅ 神谕密钥已更新！")
        context.user_data.pop('waiting_for', None)
        logger.info(f"管理员 {user_id} 修改了系统密码")
    except Exception as e:
        logger.error(f"修改密码失败: {e}")
        await update.message.reply_text("❌ 修改失败，请稍后重试。")

async def process_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理用户搜索"""
    search_term = update.message.text.strip()
    
    try:
        # 尝试按用户ID搜索
        if search_term.isdigit():
            user = await db_fetch_one(
                "SELECT * FROM users WHERE id = $1",
                int(search_term)
            )
        else:
            # 按用户名搜索
            user = await db_fetch_one(
                "SELECT * FROM users WHERE username ILIKE $1 OR first_name ILIKE $1",
                f"%{search_term}%"
            )
        
        if user:
            motto_count = await db_fetchval(
                "SELECT COUNT(*) FROM mottos WHERE user_id = $1",
                user['id']
            )
            
            message = f"""👤 **用户信息**

🆔 ID: {user['id']}
👤 用户名: {user['username'] or '未设置'}
📝 姓名: {user['first_name'] or '未设置'}
👑 管理员: {'是' if user['is_admin'] else '否'}
📅 注册时间: {user['created_at'].strftime('%Y-%m-%d %H:%M')}
📝 便签数量: {motto_count}
⏰ 最后活动: {user['last_activity'].strftime('%Y-%m-%d %H:%M') if user['last_activity'] else '未知'}"""
            
            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ 未找到相关用户。")
        
        context.user_data.pop('waiting_for', None)
        
    except Exception as e:
        logger.error(f"用户搜索失败: {e}")
        await update.message.reply_text("❌ 搜索失败，请稍后重试。")

# 权限装饰器
def admin_required(func):
    """管理员权限装饰器"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not await is_admin(user_id):
            await update.message.reply_text("❌ 此功能需要管理员权限。")
            return
        return await func(update, context)
    return wrapper

# 导出所有处理函数
__all__ = [
    'god_mode_command',
    'settings_menu', 
    'admin_panel_handler',
    'handle_admin_callbacks',
    'handle_admin_text_input',
    'export_data',
    'batch_delete_mottos',
    'advanced_search_mottos',
    'generate_weekly_report',
    'cleanup_database',
    'admin_required'
]
