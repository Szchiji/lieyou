import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import get_or_create_user, get_or_create_target, db_fetch_all, db_fetch_one, db_execute
from handlers.utils import membership_required # <-- 导入我们的检查器

logger = logging.getLogger(__name__)

@membership_required # <-- 贴上标签
async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理包含@username和关键词的文本消息，处理任意字符串，不检查群成员。"""
    message = update.effective_message
    text = message.text
    
    match = re.search(r'@(\w+)', text)
    if not match:
        return

    username = match.group(1).lower()
    
    try:
        target_user = await get_or_create_target(username)
    except ValueError as e:
        logger.error(f"创建目标 @{username} 失败: {e}")
        return

    has_recommend_keyword = any(kw in text.lower() for kw in ['推荐', '好评', '靠谱', '赞'])
    has_block_keyword = any(kw in text.lower() for kw in ['警告', '差评', '避雷', '拉黑'])

    if not (has_recommend_keyword ^ has_block_keyword):
        await send_reputation_card(update, context, target_user['pkid'])
    else:
        vote_type = 'recommend' if has_recommend_keyword else 'block'
        await vote_menu(update, context, target_user['pkid'], vote_type, origin='query')

@membership_required # <-- 贴上标签 (保护所有通过按钮触发的后续操作)
async def send_reputation_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str = 'query'):
    """发送一个目标的声誉卡片。"""
    message = update.effective_message or update.callback_query.message
    
    try:
        from_user = await get_or_create_user(update.effective_user)
    except ValueError as e:
        await message.reply_text(f"❌ 操作失败: {e}\n你需要设置一个Telegram用户名才能进行评价。")
        return

    target_user = await db_fetch_one("SELECT * FROM users WHERE pkid = $1", target_user_pkid)
    if not target_user:
        await message.reply_text("❌ 错误：找不到目标。")
        return

    stats = await db_fetch_one("""
        SELECT
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'recommend') as recommends,
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'block') as blocks,
            (SELECT COUNT(*) FROM favorites WHERE target_user_pkid = $1) as favorites_count,
            (SELECT COUNT(*) FROM favorites WHERE user_pkid = $2 AND target_user_pkid = $1) as is_favorite
    """, target_user_pkid, from_user['pkid'])

    display_name = f"@{target_user['username']}"
    score = stats['recommends'] - stats['blocks']
    
    safe_display_name = display_name.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]')

    text = (
        f"**声誉卡片: {safe_display_name}**\n\n"
        f"👍 **推荐**: {stats['recommends']}\n"
        f"👎 **警告**: {stats['blocks']}\n"
        f"✨ **声望**: {score}\n"
        f"❤️ **人气**: {stats['favorites_count']}"
    )
    
    keyboard = []
    row1 = [
        InlineKeyboardButton(f"👍 推荐", callback_data=f"vote_recommend_{target_user_pkid}_{origin}"),
        InlineKeyboardButton(f"👎 警告", callback_data=f"vote_block_{target_user_pkid}_{origin}")
    ]
    keyboard.append(row1)

    fav_text = "💔 取消收藏" if stats['is_favorite'] else "❤️ 添加收藏"
    fav_callback = f"remove_favorite_{target_user_pkid}_{origin}" if stats['is_favorite'] else f"add_favorite_{target_user_pkid}_{origin}"
    
    row2 = [
        InlineKeyboardButton(fav_text, callback_data=fav_callback),
        InlineKeyboardButton("📊 查看统计", callback_data=f"stats_user_{target_user_pkid}_1_{origin}")
    ]
    keyboard.append(row2)

    if origin and origin.startswith("fav_"):
        page = int(origin.split('_')[1])
        keyboard.append([InlineKeyboardButton("🔙 返回我的收藏", callback_data=f"my_favorites_{page}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)

@membership_required # <-- 贴上标签
async def vote_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, vote_type: str, origin: str):
    message = update.effective_message or update.callback_query.message
    tags = await db_fetch_all("SELECT pkid, name FROM tags WHERE type = $1", vote_type)
    if not tags:
        await message.reply_text(f"❌ 系统当前没有设置任何'{'推荐' if vote_type == 'recommend' else '警告'}'类型的标签，无法评价。")
        return
    keyboard = [[InlineKeyboardButton(tag['name'], callback_data=f"process_vote_{target_user_pkid}_{tag['pkid']}_{origin}")] for tag in tags]
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_pkid}_{origin}")])
    text = f"请为您的“{'👍 推荐' if vote_type == 'recommend' else '👎 警告'}”选择一个标签："
    if update.callback_query: await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

@membership_required # <-- 贴上标签
async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, tag_pkid: int, origin: str):
    query = update.callback_query
    try:
        from_user = await get_or_create_user(query.from_user)
    except ValueError as e:
        await query.answer(f"❌ 操作失败: {e}", show_alert=True)
        return
    if from_user['pkid'] == target_user_pkid:
        await query.answer("🤔 你不能评价自己哦。", show_alert=True)
        return
    try:
        tag_type_record = await db_fetch_one("SELECT type FROM tags WHERE pkid = $1", tag_pkid)
        if not tag_type_record:
            await query.answer("❌ 标签不存在。", show_alert=True)
            return

        await db_execute("INSERT INTO evaluations (user_pkid, target_user_pkid, tag_pkid, type) VALUES ($1, $2, $3, $4) ON CONFLICT (user_pkid, target_user_pkid, tag_pkid) DO UPDATE SET created_at = NOW();", from_user['pkid'], target_user_pkid, tag_pkid, tag_type_record['type'])
        await query.answer("✅ 感谢您的评价！", show_alert=True)
    except Exception as e:
        logger.error(f"评价处理失败: {e}", exc_info=True)
        await query.answer("❌ 评价失败，发生内部错误。", show_alert=True)
    await send_reputation_card(update, context, target_user_pkid, origin)

@membership_required # <-- 贴上标签
async def back_to_rep_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str):
    await send_reputation_card(update, context, target_user_pkid, origin)
