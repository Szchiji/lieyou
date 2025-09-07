import logging
import math
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)
DECAY_LAMBDA = 0.0038  # Must be consistent with reputation.py

async def get_leaderboard_text(leaderboard_type: str) -> (str, bool):
    """
    Fetches and formats leaderboard data with time-decay weighted scores.
    """
    if leaderboard_type not in ['reputation', 'avoid', 'popularity']:
        return "未知的排行榜类型。", False

    title_map = {
        'reputation': '🏆 声望榜 (动态权重)',
        'avoid': '☠️ 避雷榜 (动态权重)',
        'popularity': '❤️ 人气收藏榜'
    }
    title = title_map[leaderboard_type]
    
    query = ""
    if leaderboard_type in ['reputation', 'avoid']:
        # For reputation, score is sum of weighted recommends and warns
        # For avoid, it's the same score, but ordered ascendingly
        order = 'DESC' if leaderboard_type == 'reputation' else 'ASC'
        query = f"""
            WITH user_scores AS (
                SELECT
                    u.pkid,
                    u.username,
                    SUM(
                        CASE
                            WHEN e.type = 'recommend' THEN exp(-{DECAY_LAMBDA} * EXTRACT(EPOCH FROM (NOW() - e.created_at)) / 86400.0)
                            WHEN e.type = 'warn' THEN -exp(-{DECAY_LAMBDA} * EXTRACT(EPOCH FROM (NOW() - e.created_at)) / 86400.0)
                            ELSE 0
                        END
                    ) as score
                FROM users u
                JOIN evaluations e ON u.pkid = e.target_user_pkid
                WHERE u.is_hidden = FALSE
                GROUP BY u.pkid, u.username
            )
            SELECT username, score
            FROM user_scores
            WHERE score != 0
            ORDER BY score {order}
            LIMIT 20;
        """
    elif leaderboard_type == 'popularity':
        query = """
            SELECT u.username, COUNT(f.pkid) as count
            FROM favorites f
            JOIN users u ON f.target_user_pkid = u.pkid
            WHERE u.is_hidden = FALSE
            GROUP BY u.pkid, u.username
            ORDER BY count DESC
            LIMIT 20;
        """

    data = await database.db_fetch_all(query)

    if not data:
        return f"{title}\n\n榜单上暂时还没有人哦。", False

    leaderboard_text = f"{title}\n\n"
    for i, row in enumerate(data):
        score_display = ""
        if 'score' in row and row['score'] is not None:
            score_display = f"声望: {math.ceil(row['score'] * 10)}"
        elif 'count' in row and row['count'] is not None:
            score_display = f"收藏: {row['count']}"
        
        username = row['username'] if row['username'] else f"user_{i+1}"
        leaderboard_text += f"{i+1}. @{username} - {score_display}\n"
        
    return leaderboard_text, True

async def show_leaderboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the main leaderboard selection menu."""
    query = update.callback_query
    
    keyboard = [
        [
            InlineKeyboardButton("🏆 声望榜", callback_data="lb_reputation"),
            InlineKeyboardButton("☠️ 避雷榜", callback_data="lb_avoid"),
        ],
        [
            InlineKeyboardButton("❤️ 人气榜", callback_data="lb_popularity"),
        ],
        [
            InlineKeyboardButton("🔙 返回主菜单", callback_data="show_private_main_menu"),
        ]
    ]
    
    text = "📊 **排行榜中心**\n请选择您想查看的榜单："
    
    if query:
        await query.answer()
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else: # This case is unlikely with the new menu system but good for fallback
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def leaderboard_type_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a specific type of leaderboard."""
    query = update.callback_query
    await query.answer()
    
    leaderboard_type = query.data.split('_')[1]
    
    leaderboard_text, _ = await get_leaderboard_text(leaderboard_type)
    
    keyboard = [
        [InlineKeyboardButton("🔙 返回排行榜中心", callback_data="show_leaderboard_public")]
    ]
    
    await query.edit_message_text(leaderboard_text, reply_markup=InlineKeyboardMarkup(keyboard))
