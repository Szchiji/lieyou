import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction, update_user_activity
from html import escape

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户收藏的用户列表"""
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    # 更新用户活动记录
    await update_user_activity(user_id, username)
    
    # 获取收藏列表，包括声誉信息
    async with db_transaction() as conn:
        favorites = await conn.fetch("""
            SELECT f.favorite_username, 
                   p.recommend_count, 
                   p.block_count, 
                   f.created_at
            FROM favorites f
            LEFT JOIN reputation_profiles p ON f.favorite_username = p.username
            WHERE f.user_id = $1
            ORDER BY f.created_at DESC
        """, user_id)
    
    if not favorites:
        text = "🌟 <b>我的星盘</b>\n\n您的星盘尚未收录任何存在。\n\n当您遇到值得关注的存在时，可通过神谕之卷界面将其加入星盘。"
        keyboard = [[InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")]]
    else:
        text_parts = ["🌟 <b>我的星盘</b>\n" + ("-"*20)]
        for fav in favorites:
            # 计算声誉评分
            recommend_count = fav['recommend_count'] or 0
            block_count = fav['block_count'] or 0
            total_votes = recommend_count + block_count
            
            if total_votes > 0:
                score = round((recommend_count - block_count) / total_votes * 10, 1)
                
                # 确定声誉级别和对应图标
                if score >= 7: 
                    rep_icon = "🌟"
                elif score >= 3:
                    rep_icon = "✨"
                elif score >= -3:
                    rep_icon = "⚖️"
                elif score >= -7:
                    rep_icon = "⚠️"
                else:
                    rep_icon = "☠️"
            else:
                score = 0
                rep_icon = "⚖️"
                
            # 格式化时间
            added_date = fav['created_at'].strftime("%Y-%m-%d") if fav['created_at'] else "未知"
            
            # 构建用户条目
            username_text = escape(fav['favorite_username'])
            text_parts.append(f"<b>{rep_icon} <code>@{username_text}</code></b> [{score}]")
            text_parts.append(f"  👍 {recommend_count} | 👎 {block_count} | 📅 {added_date}")
            text_parts.append("")
            
        text = "\n".join(text_parts)
        keyboard = [
            [InlineKeyboardButton("🔄 刷新", callback_data="show_my_favorites")],
            [InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_favorite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理收藏/取消收藏的按钮点击"""
    query = update.callback_query
    data_parts = query.data.split('_')
    action, username = data_parts[2], data_parts[3]
    user_id = query.from_user.id
    
    # 更新用户活动记录
    await update_user_activity(user_id, query.from_user.username)
    
    try:
        async with db_transaction() as conn:
            if action == "add":
                # 添加到收藏
                await conn.execute("""
                    INSERT INTO favorites (user_id, favorite_username) 
                    VALUES ($1, $2)
                    ON CONFLICT (user_id, favorite_username) DO NOTHING
                """, user_id, username)
                await query.answer(f"✅ @{username} 已加入您的星盘！", show_alert=True)
            elif action == "remove":
                # 从收藏中移除
                await conn.execute("""
                    DELETE FROM favorites 
                    WHERE user_id = $1 AND favorite_username = $2
                """, user_id, username)
                await query.answer(f"✅ @{username} 已从您的星盘移除！", show_alert=True)
        
        # 刷新声誉摘要显示
        from handlers.reputation import get_reputation_summary, build_summary_view
        summary = await get_reputation_summary(username, user_id)
        message_content = await build_summary_view(username, summary)
        await query.edit_message_text(**message_content)
    except Exception as e:
        logger.error(f"处理收藏按钮时出错: {e}", exc_info=True)
        await query.answer("❌ 操作失败，请稍后重试。", show_alert=True)
