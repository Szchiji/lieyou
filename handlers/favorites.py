import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction, update_user_activity
from html import escape

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户的收藏列表"""
    user_id = update.effective_user.id
    
    # 更新用户活动记录
    await update_user_activity(user_id, update.effective_user.username)
    
    async with db_transaction() as conn:
        favorites = await conn.fetch("""
            SELECT f.favorite_username, 
                   p.recommend_count, p.block_count,
                   f.created_at
            FROM favorites f
            LEFT JOIN reputation_profiles p ON f.favorite_username = p.username
            WHERE f.user_id = $1
            ORDER BY f.created_at DESC
        """, user_id)
    
    if not favorites:
        text = (
            "┏━━━━「 🌟 <b>我的星盘</b> 」━━━━┓\n"
            "┃                          ┃\n"
            "┃  你的星盘中尚未收录任何存在。  ┃\n"
            "┃                          ┃\n"
            "┃  当你查询某人的神谕卷时，    ┃\n"
            "┃  可将其添加至星盘以便追踪。  ┃\n"
            "┃                          ┃\n"
            "┗━━━━━━━━━━━━━━━━━━┛"
        )
    else:
        # 更美观的星盘显示
        text_parts = [
            "┏━━━━「 🌟 <b>我的星盘</b> 」━━━━┓",
            "┃                          ┃",
            "┃  <b>已收录存在:</b>             ┃"
        ]
        
        for i, fav in enumerate(favorites):
            username = fav['favorite_username']
            recommend = fav['recommend_count'] or 0
            block = fav['block_count'] or 0
            
            # 计算总分
            if recommend + block == 0:
                score = 0
            else:
                score = round((recommend - block) / (recommend + block) * 10, 1)
            
            # 确定等级
            if score >= 7:
                level_icon = "🌟"
            elif score >= 3:
                level_icon = "✨"
            elif score >= -3:
                level_icon = "⚖️"
            elif score >= -7:
                level_icon = "⚠️"
            else:
                level_icon = "☠️"
                
            # 用更美观的格式显示用户名
            if i < 10:  # 显示前10个
                text_parts.append(f"┃  • <b>@{escape(username)}</b> {level_icon} ({score})   ┃")
        
        if len(favorites) > 10:
            text_parts.append(f"┃  • <i>及其他 {len(favorites)-10} 个存在...</i>  ┃")
            
        text_parts.extend([
            "┃                          ┃",
            "┗━━━━━━━━━━━━━━━━━━┛"
        ])
        
        text = "\n".join(text_parts)
    
    # 创建按钮
    keyboard = [[InlineKeyboardButton("🌍 返回凡界", callback_data="back_to_help")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='HTML')
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

async def handle_favorite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    # 更新用户活动
    await update_user_activity(user_id, query.from_user.username)
    
    # 更精确的解析方法，确保完整保留用户名
    if data.startswith('query_fav_add_'):
        action = 'add'
        username = data[len('query_fav_add_'):]  # 保留完整用户名（包括下划线）
    elif data.startswith('query_fav_remove_'):
        action = 'remove'
        username = data[len('query_fav_remove_'):]  # 保留完整用户名（包括下划线）
    else:
        await query.answer("❌ 无效的操作", show_alert=True)
        return
    
    try:
        async with db_transaction() as conn:
            if action == 'add':
                await conn.execute("""
                    INSERT INTO favorites (user_id, favorite_username) 
                    VALUES ($1, $2) 
                    ON CONFLICT (user_id, favorite_username) DO NOTHING
                """, user_id, username)
                await query.answer(f"✅ @{username} 已加入你的星盘！", show_alert=True)
            else:  # remove
                await conn.execute("""
                    DELETE FROM favorites 
                    WHERE user_id = $1 AND favorite_username = $2
                """, user_id, username)
                await query.answer(f"✅ @{username} 已从你的星盘移除！", show_alert=True)
        
        # 刷新声誉摘要显示
        from handlers.reputation import get_reputation_summary, build_summary_view
        summary = await get_reputation_summary(username, user_id)
        message_content = await build_summary_view(username, summary)
        await query.edit_message_text(**message_content)
        
    except Exception as e:
        logger.error(f"处理收藏操作时出错: {e}", exc_info=True)
        await query.answer("❌ 操作失败，请稍后再试", show_alert=True)
