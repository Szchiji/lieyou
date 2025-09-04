import logging
import asyncio
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db_transaction

logger = logging.getLogger(__name__)

async def show_system_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统统计数据"""
    try:
        query = update.callback_query
        
        # 使用异步上下文管理器获取数据库连接
        async with db_transaction() as conn:
            # 获取基本统计数据
            basic_stats = await conn.fetchrow("""
                SELECT 
                    (SELECT COUNT(*) FROM users) AS total_users,
                    (SELECT COUNT(*) FROM reputations) AS total_ratings,
                    (SELECT COUNT(DISTINCT target_id) FROM reputations) AS rated_users,
                    (SELECT COUNT(DISTINCT user_id) FROM reputations) AS rating_users,
                    (SELECT COUNT(*) FROM tags) AS total_tags
            """)
            
            # 获取过去7天的数据趋势
            now = datetime.now()
            seven_days_ago = now - timedelta(days=7)
            
            daily_stats = await conn.fetch("""
                SELECT 
                    DATE_TRUNC('day', created_at) AS date,
                    COUNT(*) as count
                FROM reputations
                WHERE created_at > $1
                GROUP BY DATE_TRUNC('day', created_at)
                ORDER BY date DESC
            """, seven_days_ago)
            
            # 获取最活跃的标签
            active_tags = await conn.fetch("""
                SELECT 
                    t.id,
                    t.name,
                    t.tag_type,
                    COUNT(*) as usage_count
                FROM 
                    reputation_tags rt
                JOIN 
                    tags t ON rt.tag_id = t.id
                GROUP BY 
                    t.id, t.name, t.tag_type
                ORDER BY 
                    usage_count DESC
                LIMIT 5
            """)
            
            # 获取系统设置
            settings = await conn.fetch("SELECT key, value FROM settings")
            settings_dict = {row['key']: row['value'] for row in settings}
            
        # 格式化统计信息
        stats_text = (
            "📊 **系统统计数据**\n\n"
            f"👥 总用户数: {basic_stats['total_users']}\n"
            f"⭐ 总评价数: {basic_stats['total_ratings']}\n"
            f"🎯 被评价用户: {basic_stats['rated_users']}\n"
            f"✍️ 评价过他人的用户: {basic_stats['rating_users']}\n"
            f"🏷️ 系统标签数: {basic_stats['total_tags']}\n\n"
        )
        
        # 添加过去7天趋势
        if daily_stats:
            stats_text += "**近7日评价趋势**\n"
            for day in daily_stats:
                date_str = day['date'].strftime("%m-%d")
                stats_text += f"{date_str}: {day['count']}条评价\n"
            stats_text += "\n"
        
        # 添加热门标签
        if active_tags:
            stats_text += "**热门标签**\n"
            for tag in active_tags:
                tag_type = "✅" if tag['tag_type'] == 'recommend' else "❌"
                stats_text += f"{tag_type} {tag['name']}: {tag['usage_count']}次使用\n"
        
        # 添加返回按钮
        keyboard = [[InlineKeyboardButton("返回", callback_data="back_to_help")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=stats_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"获取统计数据失败: {e}")  # 修复这里的括号问题
        if update.callback_query:
            await update.callback_query.answer("获取统计数据时出错，请稍后再试。", show_alert=True)
