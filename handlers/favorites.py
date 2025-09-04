import logging
from typing import List, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import db_fetch_all, db_fetchval, update_user_activity

logger = logging.getLogger(__name__)

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示我的收藏"""
    user_id = update.effective_user.id
    
    # 更新用户活动
    await update_user_activity(user_id, update.effective_user.username, update.effective_user.first_name)
    
    # 获取收藏列表
    favorites = await db_fetch_all("""
        SELECT 
            u.id, u.username, u.first_name,
            COUNT(r.*) as total_votes,
            COUNT(r.*) FILTER (WHERE r.is_positive = TRUE) as positive_votes,
            f.created_at
        FROM favorites f
        JOIN users u ON f.target_id = u.id
        LEFT JOIN reputations r ON u.id = r.target_id
        WHERE f.user_id = $1
        GROUP BY u.id, u.username, u.first_name, f.created_at
        ORDER BY f.created_at DESC
    """, user_id)
    
    message = "🌟 **我的星盘** - 收藏的用户\n\n"
    
    if not favorites:
        message += "暂无收藏的用户。\n\n💡 在查看用户声誉时点击收藏按钮即可添加到星盘。"
        keyboard = [[InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")]]
    else:
        message += f"共收藏了 **{len(favorites)}** 个用户:\n\n"
        
        for i, fav in enumerate(favorites, 1):
            display_name = fav['first_name'] or f"@{fav['username']}" if fav['username'] else f"用户{fav['id']}"
            total_votes = fav['total_votes'] or 0
            positive_votes = fav['positive_votes'] or 0
            
            if total_votes > 0:
                score = round((positive_votes / total_votes) * 100)
                score_text = f"{score}% ({total_votes}票)"
                if score >= 80:
                    icon = "✨"
                elif score >= 60:
                    icon = "⭐"
                else:
                    icon = "📊"
            else:
                icon = "🆕"
                score_text = "暂无评价"
            
            message += f"{i}. {icon} {display_name} - {score_text}\n"
        
        # 构建按钮 - 每行显示用户查询按钮
        keyboard = []
        
        # 用户查询按钮（每行2个）
        for i in range(0, min(len(favorites), 10), 2):  # 最多显示前10个
            row = []
            for j in range(2):
                if i + j < len(favorites) and i + j < 10:
                    fav = favorites[i + j]
                    display_name = fav['first_name'] or f"@{fav['username']}" if fav['username'] else f"用户{fav['id']}"
                    # 限制按钮文字长度
                    button_text = display_name[:15] + "..." if len(display_name) > 15 else display_name
                    row.append(InlineKeyboardButton(
                        button_text,
                        callback_data=f"query_fav_{fav['id']}"
                    ))
            if row:
                keyboard.append(row)
        
        if len(favorites) > 10:
            keyboard.append([InlineKeyboardButton(f"... 还有 {len(favorites) - 10} 个收藏", callback_data="noop")])
        
        keyboard.append([InlineKeyboardButton("🔙 返回主菜单", callback_data="back_to_help")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # 判断是否从按钮或命令触发
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def handle_favorite_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理收藏用户查询按钮"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    target_id = int(data.split("_")[2])
    
    # 导入声誉模块以显示用户信息
    from handlers.reputation import show_reputation_summary
    await show_reputation_summary(update, context, target_id)
