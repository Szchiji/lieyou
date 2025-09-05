import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_fetch_all, db_fetch_one, db_fetchval, update_user_activity, get_setting

logger = logging.getLogger(__name__)

async def show_system_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统统计信息"""
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    await update_user_activity(user_id, update.effective_user.username, update.effective_user.first_name)
    
    try:
        total_users = await db_fetchval("SELECT COUNT(*) FROM users") or 0
        total_reputations = await db_fetchval("SELECT COUNT(*) FROM reputations") or 0
        total_tags = await db_fetchval("SELECT COUNT(*) FROM tags") or 0
        
        positive_votes = await db_fetchval("SELECT COUNT(*) FROM reputations WHERE is_positive = TRUE") or 0
        negative_votes = total_reputations - positive_votes
        
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        active_users = await db_fetchval("SELECT COUNT(*) FROM users WHERE last_activity >= $1", seven_days_ago) or 0
        
        total_favorites = await db_fetchval("SELECT COUNT(*) FROM favorites") or 0
        
        min_votes_str = await get_setting('min_votes_for_leaderboard')
        min_votes = int(min_votes_str) if min_votes_str and min_votes_str.isdigit() else 3
        
        leaderboard_users = await db_fetchval("""
            SELECT COUNT(*) FROM (
                SELECT 1 FROM reputations GROUP BY target_id HAVING COUNT(*) >= $1
            ) as leaderboard_qualifiers
        """, min_votes) or 0
        
        # **最终修复**: 增加类型检查，确保只对数组类型的列使用 UNNEST
        tag_usage = await db_fetch_all("""
            SELECT t.name, t.type, COUNT(r.id) as usage_count
            FROM reputations r, UNNEST(r.tag_id) as current_tag_id
            JOIN tags t ON t.id = current_tag_id
            WHERE pg_typeof(r.tag_id) = 'integer[]' AND r.tag_id IS NOT NULL
            GROUP BY t.id, t.name, t.type
            ORDER BY usage_count DESC
            LIMIT 5
        """)
        
        positive_ratio = round((positive_votes / total_reputations) * 100) if total_reputations > 0 else 0
        
        message = "📊 **神谕数据中心**\n\n"
        message += "**📈 基础统计**\n"
        message += f"• 注册用户: {total_users} 人\n"
        message += f"• 活跃用户: {active_users} 人 (7日内)\n"
        message += f"• 评价总数: {total_reputations} 条\n"
        message += f"• 收藏总数: {total_favorites} 条\n"
        message += f"• 系统标签: {total_tags} 个\n\n"
        
        message += "**⚖️ 评价统计**\n"
        message += f"• 好评: {positive_votes} 条 (👍{positive_ratio}%)\n"
        message += f"• 差评: {negative_votes} 条 (👎{100-positive_ratio if total_reputations > 0 else 0}%)\n"
        message += f"• 排行榜用户: {leaderboard_users} 人\n\n"
        
        if tag_usage:
            message += "**🏷️ 热门标签**\n"
            for tag in tag_usage:
                emoji = "🏅" if tag['type'] == 'recommend' else "⚠️"
                message += f"• {emoji} {tag['name']}: {tag['usage_count']} 次\n"
        else:
            message += "**🏷️ 热门标签**\n暂无使用数据\n"
        
        if total_users > 0:
            message += "\n**💚 系统健康度**\n"
            health_status = "🟢 良好" if positive_ratio >= 70 else "🟡 一般" if positive_ratio >= 50 else "🔴 需关注"
            active_ratio = active_users / total_users
            participation_status = '🟢 高' if active_ratio > 0.3 else '🟡 中等' if active_ratio > 0.1 else '🔴 低'
            message += f"• 整体氛围: {health_status}\n"
            message += f"• 用户参与度: {participation_status}\n"
            
    except Exception as e:
        logger.error(f"获取系统统计失败: {e}", exc_info=True)
        message = "📊 **神谕数据中心**\n\n❌ 获取统计数据失败，请稍后再试。"
    
    keyboard = [
        [InlineKeyboardButton("🔄 刷新数据", callback_data="show_system_stats")],
        [InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def get_user_personal_stats(user_id: int) -> Optional[Dict]:
    """获取用户个人统计"""
    try:
        given_stats = await db_fetch_one("SELECT COUNT(*) as total_given, COUNT(*) FILTER (WHERE is_positive = TRUE) as positive_given, COUNT(*) FILTER (WHERE is_positive = FALSE) as negative_given FROM reputations WHERE voter_id = $1", user_id)
        received_stats = await db_fetch_one("SELECT COUNT(*) as total_received, COUNT(*) FILTER (WHERE is_positive = TRUE) as positive_received, COUNT(*) FILTER (WHERE is_positive = FALSE) as negative_received, COUNT(DISTINCT voter_id) as unique_voters FROM reputations WHERE target_id = $1", user_id)
        favorites_given = await db_fetchval("SELECT COUNT(*) FROM favorites WHERE user_id = $1", user_id)
        favorites_received = await db_fetchval("SELECT COUNT(*) FROM favorites WHERE target_id = $1", user_id)
        
        return {
            'given': given_stats, 'received': received_stats,
            'favorites_given': favorites_given or 0, 'favorites_received': favorites_received or 0
        }
    except Exception as e:
        logger.error(f"获取用户统计失败 {user_id}: {e}")
        return None

async def show_personal_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示个人统计"""
    user_id = update.effective_user.id
    stats = await get_user_personal_stats(user_id)
    
    if not stats:
        await update.message.reply_text("❌ 获取个人统计失败")
        return
    
    message = f"📊 **{update.effective_user.first_name or '您'}的个人统计**\n\n"
    
    given = stats.get('given', {})
    message += f"**📤 您给出的评价**\n• 总评价: {given.get('total_given', 0)} 条\n"
    if given.get('total_given', 0) > 0:
        message += f"• 好评: {given.get('positive_given', 0)} 条\n• 差评: {given.get('negative_given', 0)} 条\n"
    message += "\n"
    
    received = stats.get('received', {})
    message += f"**📥 您收到的评价**\n• 总评价: {received.get('total_received', 0)} 条\n"
    if received.get('total_received', 0) > 0:
        positive_received = received.get('positive_received', 0)
        total_received = received.get('total_received', 1)
        message += f"• 好评: {positive_received} 条\n"
        message += f"• 差评: {received.get('negative_given', 0)} 条\n"
        message += f"• 评价人数: {received.get('unique_voters', 0)} 人\n"
        reputation_score = round((positive_received / total_received) * 100) if total_received > 0 else 0
        message += f"• 声誉分数: {reputation_score}%\n"
    message += "\n"
    
    message += f"**💖 收藏统计**\n• 您收藏的用户: {stats.get('favorites_given', 0)} 个\n• 收藏您的用户: {stats.get('favorites_received', 0)} 个\n"
    
    keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    target_message = update.callback_query.message if update.callback_query else update.message
    await target_message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
