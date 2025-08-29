from telegram import Update
from telegram.ext import ContextTypes
from database import db_cursor

# (my_favorites 和 handle_favorite_button 函数保持不变)

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with db_cursor() as cur:
        user_data = await cur.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        tags = await cur.fetch("""
            SELECT t.tag_name, COUNT(v.id) as count FROM votes v
            JOIN tags t ON v.tag_id = t.id
            WHERE v.nominee_id = $1 GROUP BY t.tag_name
        """, user_id)
    
    tags_str = "\n".join([f"- {tag['tag_name']} ({tag['count']})" for tag in tags]) or "暂无"
    
    # 核心改造：显示推荐数和拉黑数
    text = (f"我的档案:\n"
            f"👍 收到推荐: {user_data['recommend_count']} 次\n"
            f"👎 收到拉黑: {user_data['block_count']} 次\n\n"
            f"收到的所有评价标签:\n{tags_str}")
            
    await update.message.reply_text(text)
