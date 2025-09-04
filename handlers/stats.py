import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_system_stats, update_user_activity, db_transaction
from datetime import datetime

logger = logging.getLogger(__name__)

async def show_system_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示系统统计数据"""
    user_id = update.effective_user.id
    
    # 更新用户活动记录
    await update_user_activity(user_id, update.effective_user.username)
    
    # 检查votes表结构，确保有必要的列
    async with db_transaction() as conn:
        try:
            columns = await conn.fetch("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'votes' AND column_name IN ('vote_type', 'created_at')
            """)
            column_names = [col['column_name'] for col in columns]
            
            # 如果缺少必要的列，添加它们
            if 'vote_type' not in column_names:
                await conn.execute("ALTER TABLE votes ADD COLUMN vote_type TEXT NOT NULL DEFAULT 'recommend';")
                logger.info("✅ 添加了'vote_type'列到votes表")
                
            if 'created_at' not in column_names:
                await conn.execute("ALTER TABLE votes ADD COLUMN created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
                logger.info("✅ 添加了'created_at'列到votes表")
        except Exception as e:
            logger.error(f"检查votes表结构失败: {e}", exc_info=True)
    
    try:
        # 获取基本统计数据
        async with db_transaction() as conn:
            stats = {}
            
            # 总用户数
            stats['total_users'] = await conn.fetchval("SELECT COUNT(*) FROM users")
            
            # 总档案数
            stats['total_profiles'] = await conn.fetchval("SELECT COUNT(*) FROM reputation_profiles")
            
            # 总投票数
            stats['total_votes'] = await conn.fetchval("SELECT COUNT(*) FROM votes")
            
            # 标签数量
            stats['recommend_tags'] = await conn.fetchval("SELECT COUNT(*) FROM tags WHERE type = 'recommend'")
            stats['block_tags'] = await conn.fetchval("SELECT COUNT(*) FROM tags WHERE type = 'block'")
            
            # 今日活跃统计
            today = datetime.now().date()
            has_created_at = 'created_at' in [col['column_name'] for col in columns] if 'columns' in locals() else False
            
            if has_created_at:
                stats['today_votes'] = await conn.fetchval(
                    "SELECT COUNT(*) FROM votes WHERE DATE(created_at) = $1", 
                    today
                )
            else:
                stats['today_votes'] = 0
            
            # 最活跃用户
            most_active = await conn.fetch("""
                SELECT nominee_username, COUNT(*) as vote_count 
                FROM votes 
                GROUP BY nominee_username 
                ORDER BY vote_count DESC 
                LIMIT 1
            """)
            stats['most_active_user'] = most_active[0]['nominee_username'] if most_active else None
        
        # 当前时间
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 构建统计信息文本
        text_parts = [
            "┏━━━━「 📊 <b>神谕数据</b> 」━━━━┓",
            "┃                          ┃",
            f"┃  ⏰ <b>时间印记:</b> {current_time[:10]}  ┃",
            "┃                          ┃",
            f"┃  👥 <b>用户数据:</b>            ┃",
            f"┃  - 总用户数: {stats['total_users']} 位求道者    ┃",
            f"┃  - 总档案数: {stats['total_profiles']} 份神谕之卷   ┃",
            "┃                          ┃",
            f"┃  ⚖️ <b>审判数据:</b>            ┃",
            f"┃  - 累计审判: {stats['total_votes']} 次        ┃",
            f"┃  - 今日审判: {stats.get('today_votes', 0)} 次        ┃",
            "┃                          ┃",
            f"┃  📜 <b>箴言数据:</b>            ┃",
            f"┃  - 赞誉箴言: {stats['recommend_tags']} 种        ┃",
            f"┃  - 警示箴言: {stats['block_tags']} 种        ┃",
        ]
        
        # 如果有最活跃用户，添加到统计中
        if stats.get('most_active_user'):
            text_parts.extend([
                "┃                          ┃",
                f"┃  🌟 <b>最活跃存在:</b> @{stats['most_active_user']}  ┃",
            ])
        
        text_parts.append("┗━━━━━━━━━━━━━━━━━━┛")
        text = "\n".join(text_parts)
        
    except Exception as e:
        logger.error(f"获取统计数据失败: {e}",
