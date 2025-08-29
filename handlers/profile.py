from telegram import Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from database import db_cursor
import logging

logger = logging.getLogger(__name__)

async def handle_favorite_button(query: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理收藏按钮的点击。"""
    user_id = query.from_user.id
    parts = query.data.split('_')
    action = parts[1]
    target_id = int(parts[2])

    with db_cursor() as cur:
        if action == "add":
            try:
                cur.execute(
                    "INSERT INTO favorites (user_id, target_id) VALUES (%s, %s)",
                    (user_id, target_id)
                )
                await query.answer("✅ 已成功加入收藏夹！", show_alert=True)
            except Exception: # 可能是因为重复收藏
                await query.answer("🤔 你已经收藏过此用户了。", show_alert=True)
        # 将来可以扩展移除收藏的功能
        # elif action == "remove":
        #     cur.execute("DELETE FROM favorites WHERE user_id = %s AND target_id = %s", (user_id, target_id))
        #     await query.answer("已从收藏夹移除。")

async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """私聊发送用户的收藏列表。"""
    user = update.effective_user
    with db_cursor() as cur:
        cur.execute("""
            SELECT t.username, t.first_name, t.upvotes, t.downvotes
            FROM favorites f
            JOIN targets t ON f.target_id = t.id
            WHERE f.user_id = %s
            ORDER BY t.username
        """, (user.id,))
        favs = cur.fetchall()

    if not favs:
        text = "你的收藏夹是空的。"
    else:
        text = "⭐ **你的私人收藏夹:**\n\n"
        for fav in favs:
            safe_username = escape_markdown(fav['username'], version=2) if fav['username'] else 'N/A'
            safe_name = escape_markdown(fav['first_name'], version=2)
            text += f"👤 {safe_name} (@{safe_username}) \- \[👍{fav['upvotes']} / 👎{fav['downvotes']}\]\n"

    try:
        await user.send_message(text, parse_mode='MarkdownV2')
        if update.message.chat.type != 'private':
            await update.message.reply_text("我已将你的收藏夹私聊发给你了。")
    except Exception as e:
        logger.error(f"发送收藏夹失败: {e}")
        await update.message.reply_text("抱歉，发送私信失败。请确保你已私聊过我并且没有屏蔽我。")


async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户自己的声望统计。"""
    user = update.effective_user
    with db_cursor() as cur:
        # 获取收到的赞和踩
        cur.execute("SELECT upvotes, downvotes FROM targets WHERE id = %s", (user.id,))
        votes = cur.fetchone()
        
        # 获取收到的标签
        cur.execute("""
            SELECT t.tag_text, COUNT(at.tag_id) as tag_count
            FROM applied_tags at
            JOIN tags t ON at.tag_id = t.id
            WHERE at.vote_target_id = %s
            GROUP BY t.tag_text
            ORDER BY tag_count DESC
        """, (user.id,))
        tags = cur.fetchall()

    if not votes:
        text = "你还没有收到任何评价。"
    else:
        safe_name = escape_markdown(user.first_name, version=2)
        text = f"📊 *{safe_name}的个人档案*\n\n"
        text += f"*收到的评价:*\n👍 推荐: {votes['upvotes']} 次\n👎 拉黑: {votes['downvotes']} 次\n\n"
        if tags:
            text += "*收到的标签:*\n"
            text += "\n".join([f"`{tag['tag_text']}` \({tag['tag_count']} 次\)" for tag in tags])
        else:
            text += "*收到的标签:*\n无"
            
    await update.message.reply_text(text, parse_mode='MarkdownV2')
