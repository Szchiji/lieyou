import logging
import asyncio
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database import db_fetch_all, db_fetch_one

logger = logging.getLogger(__name__)

async def show_system_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统统计信息"""
    callback_query = update.callback_query
    
    # 如果是从按钮调用的，先回答回调查询
    if callback_query:
        await callback_query.answer()
        message = callback_query.message
    else:
        message = update.message
    
    try:
        # 开始查询统计数据前显示加载消息
        loading_message = await message.reply_text("🔄 正在收集神谕数据，请稍候...")
        
        # 异步查询所有统计数据
        stats = await asyncio.gather(
            get_user_stats(),
            get_reputation_stats(),
            get_tag_stats(),
            get_vote_time_stats(),
            get_top_tags()
        )
        
        user_stats, rep_stats, tag_stats, time_stats, top_tags = stats
        
        # 构建统计信息文本
        text = (
            f"📊 **神谕数据概览**\n\n"
            f"👥 **用户数据**\n"
            f"总用户数: {user_stats['total_users']}\n"
            f"管理员数: {user_stats['admin_count']}\n\n"
            
            f"⭐ **评价数据**\n"
            f"总评价数: {rep_stats['total_votes']}\n"
            f"正面评价: {rep_stats['positive_votes']} ({rep_stats['positive_percentage']}%)\n"
            f"负面评价: {rep_stats['negative_votes']} ({rep_stats['negative_percentage']}%)\n\n"
            
            f"🏷️ **标签数据**\n"
            f"推荐标签数: {tag_stats['recommend_tags']}\n"
            f"警告标签数: {tag_stats['block_tags']}\n"
            f"箴言数量: {tag_stats['quote_tags']}\n\n"
            
            f"⏱️ **时间分析**\n"
            f"过去24小时新增评价: {time_stats['last_24h']}\n"
            f"过去7天新增评价: {time_stats['last_7d']}\n"
            f"过去30天新增评价: {time_stats['last_30d']}\n\n"
            
            f"🔝 **热门标签** (使用次数)\n"
        )
        
        # 添加热门标签
        for i, (tag_type, content, count) in enumerate(top_tags, 1):
            type_emoji = "👍" if tag_type == "recommend" else "👎"
            text += f"{i}. {type_emoji} {content}: {count}次\n"
        
        # 返回按钮
        keyboard = [[InlineKeyboardButton("« 返回", callback_data="back_to_help")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 编辑或发送统计信息
        if callback_query:
            await callback_query.edit_message_text(
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            await message.reply_text(
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        
        # 删除加载消息
        await loading_message.delete()
        
    except Exception as e:
        logger.error(f"获取统计数据失败: {e}", exc_info=True)
        error_text = "❌ 收集神谕数据时遇到问题，请稍后再试。"
        if callback_query:
            await callback_query.edit_message_text(text=error_text)
        else:
            await message.reply_text(text=error_text)

async def get_user_stats():
    """获取用户统计数据"""
    try:
        # 获取总用户数
        total_users_query = "SELECT COUNT(*) FROM users"
        total_users = await db_fetch_one(total_users_query)
        
        # 获取管理员数量
        admin_count_query = "SELECT COUNT(*) FROM users WHERE is_admin = TRUE"
        admin_count = await db_fetch_one(admin_count_query)
        
        return {
            "total_users": total_users[0],
            "admin_count": admin_count[0]
        }
    except Exception as e:
        logger.error(f"获取用户统计数据失败: {e}")
        return {
            "total_users": 0,
            "admin_count": 0
        }

async def get_reputation_stats():
    """获取声誉评价统计数据"""
    try:
        # 获取总评价数
        total_votes_query = "SELECT COUNT(*) FROM reputation"
        total_votes = await db_fetch_one(total_votes_query)
        total_votes = total_votes[0] if total_votes else 0
        
        # 获取正面评价数
        positive_votes_query = "SELECT COUNT(*) FROM reputation WHERE is_positive = TRUE"
        positive_votes = await db_fetch_one(positive_votes_query)
        positive_votes = positive_votes[0] if positive_votes else 0
        
        # 获取负面评价数
        negative_votes_query = "SELECT COUNT(*) FROM reputation WHERE is_positive = FALSE"
        negative_votes = await db_fetch_one(negative_votes_query)
        negative_votes = negative_votes[0] if negative_votes else 0
        
        # 计算百分比
        positive_percentage = round((positive_votes / total_votes) * 100) if total_votes > 0 else 0
        negative_percentage = round((negative_votes / total_votes) * 100) if total_votes > 0 else 0
        
        return {
            "total_votes": total_votes,
            "positive_votes": positive_votes,
            "negative_votes": negative_votes,
            "positive_percentage": positive_percentage,
            "negative_percentage": negative_percentage
        }
    except Exception as e:
        logger.error(f"获取评价统计数据失败: {e}")
        return {
            "total_votes": 0,
            "positive_votes": 0,
            "negative_votes": 0,
            "positive_percentage": 0,
            "negative_percentage": 0
        }

async def get_tag_stats():
    """获取标签统计数据"""
    try:
        # 获取推荐标签数量
        recommend_query = "SELECT COUNT(*) FROM tags WHERE tag_type = 'recommend'"
        recommend_count = await db_fetch_one(recommend_query)
        
        # 获取警告标签数量
        block_query = "SELECT COUNT(*) FROM tags WHERE tag_type = 'block'"
        block_count = await db_fetch_one(block_query)
        
        # 获取箴言数量
        quote_query = "SELECT COUNT(*) FROM tags WHERE tag_type = 'quote'"
        quote_count = await db_fetch_one(quote_query)
        
        return {
            "recommend_tags": recommend_count[0] if recommend_count else 0,
            "block_tags": block_count[0] if block_count else 0,
            "quote_tags": quote_count[0] if quote_count else 0
        }
    except Exception as e:
        logger.error(f"获取标签统计数据失败: {e}")
        return {
            "recommend_tags": 0,
            "block_tags": 0,
            "quote_tags": 0
        }

async def get_vote_time_stats():
    """获取不同时间段的评价统计"""
    try:
        now = datetime.now()
        
        # 过去24小时
        last_24h_query = """
        SELECT COUNT(*) FROM reputation 
        WHERE created_at > $1
        """
        last_24h = await db_fetch_one(last_24h_query, now - timedelta(days=1))
        
        # 过去7天
        last_7d_query = """
        SELECT COUNT(*) FROM reputation 
        WHERE created_at > $1
        """
        last_7d = await db_fetch_one(last_7d_query, now - timedelta(days=7))
        
        # 过去30天
        last_30d_query = """
        SELECT COUNT(*) FROM reputation 
        WHERE created_at > $1
        """
        last_30d = await db_fetch_one(last_30d_query, now - timedelta(days=30))
        
        return {
            "last_24h": last_24h[0] if last_24h else 0,
            "last_7d": last_7d[0] if last_7d else 0,
            "last_30d": last_30d[0] if last_30d else 0
        }
    except Exception as e:
        logger.error(f"获取时间段统计数据失败: {e}")
        return {
            "last_24h": 0,
            "last_7d": 0,
            "last_30d": 0
        }

async def get_top_tags():
    """获取使用最多的标签"""
    try:
        query = """
        SELECT t.tag_type, t.content, COUNT(*) as usage_count
        FROM reputation r
        JOIN tags t ON r.tag_id = t.id
        GROUP BY t.tag_type, t.content
        ORDER BY usage_count DESC
        LIMIT 5
        """
        result = await db_fetch_all(query)
        
        # 将结果转换为列表格式
        return [(row['tag_type'], row['content'], row['usage_count']) for row in result]
    except Exception as e:
        logger.error(f"获取热门标签数据失败: {e}")
        return []
