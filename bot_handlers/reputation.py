import logging
from telegram import Update, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import (
    get_or_create_virtual_user, get_user_info, get_user_reputation,
    get_tags_by_type, get_or_create_pair_rating, attach_tags_to_rating,
    clear_tags_if_sentiment_changed, get_detailed_user_stats,
    is_user_favorite, add_favorite, remove_favorite, log_user_query
)

logger = logging.getLogger(__name__)
MULTI_KEY = "multi_rating"

def _multi(context: ContextTypes.DEFAULT_TYPE):
    if MULTI_KEY not in context.user_data:
        context.user_data[MULTI_KEY] = {}
    return context.user_data[MULTI_KEY]

async def handle_any_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not msg.entities:
        return
    text = msg.text or msg.caption or ""
    used = set()
    for ent in msg.entities:
        if ent.type == MessageEntity.MENTION:
            raw = text[ent.offset: ent.offset + ent.length]
            uname = raw.lstrip('@')
            if uname in used:
                continue
            used.add(uname)
            row = await get_or_create_virtual_user(uname)
            if not row:
                await msg.reply_text(f"❌ 用户名 {raw} 不合法")
                continue
            try:
                await log_user_query(msg.from_user.id, row["user_id"], msg.chat.id if msg.chat else None)
            except Exception:
                pass
            await show_user_reputation(msg, row["user_id"], msg.from_user.id, edit=False)

async def reputation_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split('_')
    if len(parts) < 3 or parts[0] != 'rep':
        return
    action = parts[1]
    target_id = int(parts[2])
    requester = q.from_user.id

    if action in ("recommend","warn"):
        sentiment = "positive" if action == "recommend" else "negative"
        await show_multi_tag_selector(q, context, target_id, requester, sentiment)
    elif action == "favorite":
        fav = await is_user_favorite(requester, target_id)
        if fav:
            ok = await remove_favorite(requester, target_id)
            await q.answer("已取消收藏" if ok else "失败", show_alert=True)
        else:
            ok = await add_favorite(requester, target_id)
            await q.answer("已收藏" if ok else "失败", show_alert=True)
        await show_user_reputation(q.message, target_id, requester, edit=True)
    elif action == "stats":
        await show_detailed_stats(q, target_id)

async def show_multi_tag_selector(query, context, target_user_id, requester_id, sentiment):
    tags = await get_tags_by_type(sentiment)
    store = _multi(context)
    key = (target_user_id, sentiment)
    if key not in store:
        store[key] = set()
    selected = store[key]

    kb = []
    for i in range(0, len(tags), 2):
        row = []
        for j in range(i, min(i+2, len(tags))):
            t = tags[j]
            mark = "✅" if t["id"] in selected else ""
            row.append(
                InlineKeyboardButton(
                    f"{mark}{t['name']}",
                    callback_data=f"tagtoggle_{t['id']}_{target_user_id}_{sentiment}"
                )
            )
        kb.append(row)

    kb.append([
        InlineKeyboardButton("✅ 完成", callback_data=f"tagconfirm_{target_user_id}_{sentiment}"),
        InlineKeyboardButton("🧹 清除", callback_data=f"tagclear_{target_user_id}_{sentiment}")
    ])
    kb.append([InlineKeyboardButton("↩️ 返回", callback_data=f"back_to_user_{target_user_id}")])

    title = "选择推荐标签(多选)" if sentiment == "positive" else "选择警告标签(多选)"
    await query.edit_message_text(title, reply_markup=InlineKeyboardMarkup(kb))

async def tag_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    await q.answer()
    if data.startswith("tagtoggle_"):
        _, tag_id, uid, sent = data.split('_')
        tag_id = int(tag_id); uid = int(uid)
        store = _multi(context)
        key = (uid, sent)
        store.setdefault(key, set())
        if tag_id in store[key]:
            store[key].remove(tag_id)
        else:
            store[key].add(tag_id)
        await show_multi_tag_selector(q, context, uid, q.from_user.id, sent)
    elif data.startswith("tagclear_"):
        _, uid, sent = data.split('_')
        uid = int(uid)
        store = _multi(context)
        store[(uid, sent)] = set()
        await show_multi_tag_selector(q, context, uid, q.from_user.id, sent)
    elif data.startswith("tagconfirm_"):
        _, uid, sent = data.split('_')
        uid = int(uid)
        store = _multi(context)
        key = (uid, sent)
        chosen = list(store.get(key, []))
        rating_id, is_new, final_s, changed = await get_or_create_pair_rating(
            rater_id=q.from_user.id,
            user_id=uid,
            sentiment=sent
        )
        # 可选：若情感改变时清空旧标签，取消下一行的注释
        # if changed and not is_new: await clear_tags_if_sentiment_changed(rating_id)
        if chosen:
            await attach_tags_to_rating(rating_id, chosen)
        store.pop(key, None)
        await q.answer("已创建评价" if is_new else "已更新评价", show_alert=True)
        await show_user_reputation(q.message, uid, q.from_user.id, edit=True)
    elif data.startswith("back_to_user_"):
        uid = int(data.split('_')[-1])
        await show_user_reputation(q.message, uid, q.from_user.id, edit=True)

async def show_user_reputation(msg, target_user_id: int, requester_id: int, edit=False):
    info = await get_user_info(target_user_id)
    if not info:
        text = "❌ 未找到用户"
        if edit:
            await msg.edit_text(text)
        else:
            await msg.reply_text(text)
        return
    rep = await get_user_reputation(target_user_id)
    fav = await is_user_favorite(requester_id, target_user_id)
    disp = f"@{info['username']}" if info.get("username") else "匿名用户"
    text = (
        f"📋 *用户声誉档案*\n\n"
        f"👤 用户：{disp}\n"
        f"📊 信誉分：{rep['score']}\n"
        f"👍 推荐：{rep['recommendations']}    👎 警告：{rep['warnings']}\n\n"
        f"🏷️ 常见标签：\n"
    )
    if rep['tags']:
        for t in rep['tags'][:5]:
            text += f"• {t['name']} ({t['count']}次)\n"
    else:
        text += "暂无标签\n"
    kb = [
        [
            InlineKeyboardButton("👍 推荐", callback_data=f"rep_recommend_{target_user_id}"),
            InlineKeyboardButton("👎 警告", callback_data=f"rep_warn_{target_user_id}")
        ],
        [
            InlineKeyboardButton("💔 取消收藏" if fav else "❤️ 收藏", callback_data=f"rep_favorite_{target_user_id}"),
            InlineKeyboardButton("📊 详细统计", callback_data=f"rep_stats_{target_user_id}")
        ]
    ]
    if edit:
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def show_detailed_stats(q, user_id: int):
    stats = await get_detailed_user_stats(user_id)
    info = await get_user_info(user_id)
    disp = f"@{info['username']}" if info.get("username") else "匿名用户"
    text = f"📊 *{disp}* 详细统计\n\n*推荐标签排行:*\n"
    if stats['positive_tags']:
        for r in stats['positive_tags']:
            text += f"• {r['name']}:{r['count']}次\n"
    else:
        text += "暂无\n"
    text += "\n*警告标签排行:*\n"
    if stats['negative_tags']:
        for r in stats['negative_tags']:
            text += f"• {r['name']}:{r['count']}次\n"
    else:
        text += "暂无\n"
    text += "\n*最近评价:*\n"
    if stats['recent_ratings']:
        for rr in stats['recent_ratings']:
            emo = "👍" if rr['sentiment']=='positive' else "👎"
            tagn = rr['tag_name'] or "无标签"
            text += f"{emo} {tagn} - {rr['created_at'].strftime('%m-%d')}\n"
    else:
        text += "暂无记录\n"
    back = InlineKeyboardMarkup([[InlineKeyboardButton("↩️ 返回", callback_data=f"back_to_user_{user_id}")]])
    await q.message.edit_text(text, parse_mode="Markdown", reply_markup=back)
