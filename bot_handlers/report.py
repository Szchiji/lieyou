import logging
from telegram import Update
from telegram.ext import ContextTypes
import database
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

async def generate_my_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates a personal reputation report for the user."""
    user = update.effective_user
    user_record = await database.get_user(user.id)
    if not user_record:
        await update.message.reply_text("请先使用 /start 与机器人互动，以创建您的档案。")
        return

    user_pkid = user_record['pkid']

    # 1. Overall Stats
    overall_stats_query = """
        SELECT
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'recommend') as recommends,
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'warn') as warns,
            (SELECT COUNT(*) FROM favorites WHERE target_user_pkid = $1) as favorites
        FROM users WHERE pkid = $1;
    """
    overall_stats = await database.db_fetch_one(overall_stats_query, user_pkid)

    # 2. Activity in the last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    last_30_days_query = """
        SELECT
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'recommend' AND created_at >= $2) as recommends,
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'warn' AND created_at >= $2) as warns
    """
    last_30_days_stats = await database.db_fetch_one(last_30_days_query, user_pkid, thirty_days_ago)

    # 3. Top 5 users who recommended you
    top_recommenders_query = """
        SELECT u.username, COUNT(e.pkid) as count
        FROM evaluations e
        JOIN users u ON e.evaluator_user_pkid = u.pkid
        WHERE e.target_user_pkid = $1 AND e.type = 'recommend' AND u.is_hidden = FALSE
        GROUP BY u.username
        ORDER BY count DESC
        LIMIT 5;
    """
    top_recommenders = await database.db_fetch_all(top_recommenders_query, user_pkid)

    # Assemble the report
    text = f"📊 **您的个人声誉报告, @{user.username}**\n\n"
    
    if overall_stats:
        text += "--- **生涯总览** ---\n"
        text += f"👍 总推荐: {overall_stats.get('recommends', 0)}\n"
        text += f"👎 总警告: {overall_stats.get('warns', 0)}\n"
        text += f"❤️ 总收藏: {overall_stats.get('favorites', 0)}\n\n"
    
    if last_30_days_stats:
        text += "--- **最近30天动态** ---\n"
        text += f"👍 收到推荐: {last_30_days_stats.get('recommends', 0)}\n"
        text += f"👎 收到警告: {last_30_days_stats.get('warns', 0)}\n\n"

    if top_recommenders:
        text += "--- **您的贵人榜 (Top 5)** ---\n"
        for i, recommender in enumerate(top_recommenders):
            text += f"{i+1}. @{recommender['username']} ({recommender['count']}次)\n"
    else:
        text += "--- **您的贵人榜 (Top 5)** ---\n"
        text += "暂时还没有人推荐您哦，多在社区里帮助他人吧！\n"

    await update.message.reply_text(text)
