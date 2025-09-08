import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import get_user_favorites, remove_favorite
from bot_handlers.reputation import show_user_reputation

logger = logging.getLogger(__name__)

async def show_my_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    favs = await get_user_favorites(user_id)
    if not favs:
        await update.message.reply_text("⭐ 还没有收藏。查询用户后点 ❤️ 收藏。")
        return
    text = "⭐ *我的收藏*\n\n"
    for i, f in enumerate(favs[:50], 1):
        uname = f"@{f['username']}" if f.get('username') else (f['first_name'] or '用户')
        text += f"{i}. {uname}  信誉:{f['reputation_score']}\n"
    kb = []
    for f in favs[:8]:
        uname = f"@{f['username']}" if f.get('username') else (f['first_name'] or '用户')
        kb.append([
            InlineKeyboardButton(uname, callback_data=f"favview_{f['favorite_user_id']}"),
            InlineKeyboardButton("❌", callback_data=f"favdel_{f['favorite_user_id']}")
        ])
    markup = InlineKeyboardMarkup(kb) if kb else None
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)

async def favorites_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith("favview_"):
        uid = int(data.split('_')[1])
        await show_user_reputation(q.message, uid, q.from_user.id, edit=False)
    elif data.startswith("favdel_"):
        uid = int(data.split('_')[1])
        ok = await remove_favorite(q.from_user.id, uid)
        await q.answer("已移除" if ok else "失败", show_alert=True)
        # 重新显示列表
        fake_update = Update(update.update_id, message=q.message)
        await show_my_favorites(fake_update, context)
