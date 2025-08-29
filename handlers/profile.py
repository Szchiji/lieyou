from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor
import logging

logger = logging.getLogger(__name__)

async def handle_favorite_button(query, user):
    """处理收藏按钮点击。"""
    parts = query.data.split('_')
    action = parts[1]
    target_id = int(parts[2])

    with db_cursor() as cur:
        if action == "add":
            try:
                cur.execute(
                    "INSERT INTO favorites (user_id, target_id) VALUES (%s, %s)",
                    (user.id, target_id)
                )
                await query.answer("已成功加入收藏！", show_alert=True)
            except Exception:
                await query.answer("已在你的收藏夹中。", show_alert=True)
        elif action == "remove":
            cur.execute(
                "DELETE FROM favorites WHERE user_id = %s AND target_id = %s",
                (user.id, target_id)
            )
            await query.answer("已从收藏夹移除。")
            # 刷新收藏列表
            await my_favorites(query, user_id=user.id, is_callback=True)


async def my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None, is_callback=False):
    """显示用户的收藏列表。"""
    if not is_callback:
        user_id = update.effective_user.id
    
    with db_cursor() as cur:
        cur.execute("""
            SELECT t.id, t.username, t.upvotes, t.downvotes
            FROM favorites f
            JOIN targets t ON f.target_id = t.id
            WHERE f.user_id = %s
            ORDER BY f.created_at DESC
        """, (user_id,))
        favs = cur.fetchall()

    if not favs:
        text = "你的收藏夹是空的。"
        keyboard = None
    else:
        text = "⭐ **我的收藏夹** ⭐\n\n"
        buttons = []
        for fav in favs:
            text += f"👤 @{fav['username']} - [👍{fav['upvotes']} / 👎{fav['downvotes']}]\n"
            buttons.append([
                InlineKeyboardButton(f"移除 @{fav['username']}", callback_data=f"fav_remove_{fav['id']}")
            ])
        keyboard = InlineKeyboardMarkup(buttons)
    
    try:
        if is_callback:
            await update.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        else:
            # 私聊发送
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard, parse_mode='Markdown')
            if update.effective_chat.type != 'private':
                await update.message.reply_text("我已将你的收藏夹私聊发给你了。")
    except Exception as e:
        logger.error(f"发送收藏夹失败: {e}")
        if not is_callback:
            await update.message.reply_text("发送失败，请先私聊我一次，让我认识你。")

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户自己的声望和标签。"""
    user_id = update.effective_user.id
    with db_cursor() as cur:
        cur.execute("SELECT * FROM targets WHERE id = %s", (user_id,))
        profile = cur.fetchone()
        
        if not profile:
            text = "你还没有被任何人提名或评价过。"
        else:
            text = (
                f"👤 **你的个人档案** 👤\n\n"
                f"**声望**: [推荐: {profile['upvotes']}] [拉黑: {profile['downvotes']}]\n\n"
                "**收到的标签**:\n"
            )
            cur.execute("""
                SELECT t.tag_text, COUNT(*) as count
                FROM applied_tags at
                JOIN tags t ON at.tag_id = t.id
                WHERE at.vote_target_id = %s
                GROUP BY t.tag_text
                ORDER BY count DESC
            """, (user_id,))
            tags = cur.fetchall()
            
            if not tags:
                text += "还没有收到任何标签。"
            else:
                for tag in tags:
                    text += f"- {tag['tag_text']}: {tag['count']} 次\n"

    await update.message.reply_text(text, parse_mode='Markdown')
