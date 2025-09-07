import logging
import math
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)
DECAY_LAMBDA = 0.0038  # Half-life of ~6 months

async def get_reputation_stats(target_user_pkid: int):
    """Fetches reputation stats for a user with time decay."""
    query = f"""
        WITH weighted_evals AS (
            SELECT
                type,
                exp(-{DECAY_LAMBDA} * EXTRACT(EPOCH FROM (NOW() - created_at)) / 86400.0) as weight
            FROM evaluations
            WHERE target_user_pkid = $1
        )
        SELECT
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'recommend') as total_recommends,
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'warn') as total_warns,
            COALESCE(SUM(CASE WHEN type = 'recommend' THEN weight ELSE 0 END), 0) as weighted_recommends,
            COALESCE(SUM(CASE WHEN type = 'warn' THEN weight ELSE 0 END), 0) as weighted_warns
        FROM weighted_evals
    """
    
    stats = await database.db_fetch_one(query, target_user_pkid)
    
    if not stats or stats['total_recommends'] is None:
        return {"recommend_count": 0, "warn_count": 0, "reputation_score": 0, "favorites_count": 0}

    reputation_score = stats['weighted_recommends'] - stats['weighted_warns']
    
    favorites_count = await database.db_fetch_val(
        "SELECT COUNT(*) FROM favorites WHERE target_user_pkid = $1", target_user_pkid
    )

    return {
        "recommend_count": stats['total_recommends'],
        "warn_count": stats['total_warns'],
        "reputation_score": math.ceil(reputation_score * 10),
        "favorites_count": favorites_count or 0
    }

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles @username queries."""
    message_text = update.message.text
    # Find all @mentions
    entities = [e for e in update.message.entities if e.type == 'mention']
    if not entities:
        return

    # Process only the first mention
    entity = entities[0]
    target_username = message_text[entity.offset + 1 : entity.offset + entity.length]
    
    evaluator_user = update.effective_user
    evaluator_pkid = await database.save_user(evaluator_user)

    target_user_record = await database.db_fetch_one(
        "SELECT pkid, is_hidden FROM users WHERE username = $1", target_username
    )

    if not target_user_record or target_user_record['is_hidden']:
        await update.message.reply_text(f"找不到用户 @{target_username} 或该用户已被管理员隐藏。")
        return
        
    target_user_pkid = target_user_record['pkid']

    stats = await get_reputation_stats(target_user_pkid)
    
    is_favorited = await database.db_fetch_val(
        "SELECT 1 FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2",
        evaluator_pkid, target_user_pkid
    )

    text = (
        f"👤 **@{target_username} 的声誉档案**\n\n"
        f"👍 **推荐**: {stats['recommend_count']} 次\n"
        f"👎 **警告**: {stats['warn_count']} 次\n"
        f"❤️ **收藏人气**: {stats['favorites_count']}\n"
        f"🔥 **综合声望**: {stats['reputation_score']}"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("👍 推荐", callback_data=f"rep_rec_{target_user_pkid}"),
            InlineKeyboardButton("👎 警告", callback_data=f"rep_warn_{target_user_pkid}"),
        ],
        [
            InlineKeyboardButton("💔 取消收藏" if is_favorited else "❤️ 收藏", callback_data=f"rep_fav_{target_user_pkid}"),
            InlineKeyboardButton("📊 详细统计", callback_data=f"rep_stats_{target_user_pkid}"),
        ]
    ]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def reputation_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all callbacks starting with 'rep_'."""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split('_')
    action = parts[1]
    target_user_pkid = int(parts[2])

    evaluator_user = update.effective_user
    evaluator_pkid = await database.save_user(evaluator_user)

    if action in ['rec', 'warn']:
        tag_type = 'recommend' if action == 'rec' else 'warn'
        tags = await database.db_fetch_all("SELECT pkid, name FROM tags WHERE type = $1 AND is_active = TRUE", tag_type)
        if not tags:
            await query.edit_message_text(f"暂无可用标签，请联系管理员添加。")
            return
        
        keyboard = [
            [InlineKeyboardButton(tag['name'], callback_data=f"tag_{tag['pkid']}_{target_user_pkid}")]
            for tag in tags
        ]
        keyboard.append([InlineKeyboardButton("🔙 取消", callback_data=f"rep_cancel_{target_user_pkid}")])
        action_text = "推荐" if tag_type == 'recommend' else "警告"
        await query.edit_message_text(f"请为您的“{action_text}”选择一个标签：", reply_markup=InlineKeyboardMarkup(keyboard))

    elif action == 'fav':
        is_favorited = await database.db_fetch_val(
            "SELECT 1 FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2",
            evaluator_pkid, target_user_pkid
        )
        if is_favorited:
            await database.db_execute(
                "DELETE FROM favorites WHERE user_pkid = $1 AND target_user_pkid = $2",
                evaluator_pkid, target_user_pkid
            )
            await query.answer("💔 已取消收藏")
        else:
            await database.db_execute(
                "INSERT INTO favorites (user_pkid, target_user_pkid) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                evaluator_pkid, target_user_pkid
            )
            await query.answer("❤️ 已收藏！")
        # Note: We don't update the original message to avoid race conditions in groups.
        # The change will be reflected the next time the user is queried.

async def tag_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles tag selection for an evaluation."""
    query = update.callback_query
    
    parts = query.data.split('_')
    tag_pkid = int(parts[1])
    target_user_pkid = int(parts[2])
    
    evaluator_user = update.effective_user
    evaluator_pkid = await database.save_user(evaluator_user)

    tag_info = await database.db_fetch_one("SELECT type FROM tags WHERE pkid = $1", tag_pkid)
    if not tag_info:
        await query.answer("标签不存在或已失效。")
        return

    # Prevent self-evaluation
    if evaluator_pkid == target_user_pkid:
        await query.answer("您不能评价自己。", show_alert=True)
        # Restore original message if possible, or just send a text
        await query.edit_message_text("操作失败：您不能评价自己。")
        return
        
    await database.db_execute(
        """
        INSERT INTO evaluations (evaluator_user_pkid, target_user_pkid, tag_pkid, type)
        VALUES ($1, $2, $3, $4)
        """,
        evaluator_pkid, target_user_pkid, tag_pkid, tag_info['type']
    )
    
    target_username = await database.db_fetch_val("SELECT username FROM users WHERE pkid = $1", target_user_pkid)
    
    await query.edit_message_text(f"✅ 感谢您的评价！您已成功评价 @{target_username}。")
