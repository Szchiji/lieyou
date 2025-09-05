import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from database import get_or_create_user, get_user_by_username, db_fetch_all, db_fetch_one, db_execute

logger = logging.getLogger(__name__)

# =============================================================================
# 核心入口：处理所有文本消息
# =============================================================================
async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理可能包含@username和关键词的文本消息。"""
    message = update.effective_message
    text = message.text
    
    # 查找@username
    match = re.search(r'@(\w+)', text)
    if not match:
        return # 没有@username，不处理

    username = match.group(1)
    target_user = await get_user_by_username(username)

    if not target_user:
        # 如果数据库没有，也可能是新用户，暂时不处理
        logger.info(f"在数据库中未找到用户 @{username}，暂不处理。")
        return

    # 检查消息中是否包含推荐或警告的关键词
    has_recommend_keyword = any(kw in text.lower() for kw in ['推荐', '好评', '靠谱', '赞'])
    has_block_keyword = any(kw in text.lower() for kw in ['警告', '差评', '避雷', '拉黑'])

    # 如果同时包含或都不包含，则只发送声誉卡片
    if not (has_recommend_keyword ^ has_block_keyword):
        await send_reputation_card(update, context, target_user['pkid'])
        return

    # 确定操作类型
    vote_type = 'recommend' if has_recommend_keyword else 'block'
    
    # 直接跳转到投票菜单
    await vote_menu(update, context, target_user['pkid'], vote_type, origin='query')

# =============================================================================
# UI界面：发送声誉卡片
# =============================================================================
async def send_reputation_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str = 'query'):
    """发送一个用户的声誉卡片，包含统计数据和操作按钮。"""
    message = update.effective_message or update.callback_query.message
    from_user = await get_or_create_user(update.effective_user.id)
    
    target_user = await db_fetch_one("SELECT * FROM users WHERE pkid = $1", target_user_pkid)
    if not target_user:
        await message.reply_text("❌ 错误：找不到目标用户。")
        return

    # 获取统计数据
    stats = await db_fetch_one("""
        SELECT
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'recommend') as recommends,
            (SELECT COUNT(*) FROM evaluations WHERE target_user_pkid = $1 AND type = 'block') as blocks,
            (SELECT COUNT(*) FROM favorites WHERE target_user_pkid = $1) as favorites_count,
            (SELECT COUNT(*) FROM favorites WHERE user_pkid = $2 AND target_user_pkid = $1) as is_favorite
    """, target_user_pkid, from_user['pkid'])

    display_name = f"@{target_user['username']}" if target_user['username'] else target_user['first_name']
    score = stats['recommends'] - stats['blocks']
    
    text = (
        f"**声誉卡片: {display_name}**\n\n"
        f"👍 **推荐**: {stats['recommends']}\n"
        f"👎 **警告**: {stats['blocks']}\n"
        f"✨ **声望**: {score}\n"
        f"❤️ **人气**: {stats['favorites_count']}"
    )
    
    # 构建按钮
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

    # 如果是从收藏列表过来，返回按钮应该回到收藏列表
    if origin and origin.startswith("fav_"):
        page = int(origin.split('_')[1])
        keyboard.append([InlineKeyboardButton("🔙 返回我的收藏", callback_data=f"my_favorites_{page}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # 如果是按钮回调，编辑消息；如果是新消息，回复消息
    if update.callback_query:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN_V2)

# =============================================================================
# 投票流程
# =============================================================================
async def vote_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, vote_type: str, origin: str):
    """显示评价标签供用户选择。"""
    message = update.effective_message or update.callback_query.message
    
    tags = await db_fetch_all("SELECT pkid, name FROM tags WHERE type = $1", vote_type)
    if not tags:
        await message.reply_text(f"❌ 系统当前没有设置任何'{vote_type}'类型的标签，无法评价。")
        return
        
    keyboard = []
    for tag in tags:
        keyboard.append([InlineKeyboardButton(tag['name'], callback_data=f"process_vote_{target_user_pkid}_{tag['pkid']}_{origin}")])
    
    keyboard.append([InlineKeyboardButton("🔙 返回声誉卡片", callback_data=f"back_to_rep_card_{target_user_pkid}_{origin}")])
    
    text = f"请为您的“{'👍 推荐' if vote_type == 'recommend' else '👎 警告'}”选择一个标签："
    
    if update.callback_query:
        await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def process_vote(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, tag_pkid: int, origin: str):
    """处理用户的投票并存入数据库。"""
    query = update.callback_query
    from_user = await get_or_create_user(query.from_user.id)

    if from_user['pkid'] == target_user_pkid:
        await query.answer("🤔 你不能评价自己哦。", show_alert=True)
        return

    try:
        # 使用UPSERT语句，如果用户已经用同一个标签评价过，则更新时间；否则插入新纪录
        await db_execute("""
            INSERT INTO evaluations (user_pkid, target_user_pkid, tag_pkid, type)
            VALUES ($1, $2, $3, (SELECT type FROM tags WHERE pkid = $3))
            ON CONFLICT (user_pkid, target_user_pkid, tag_pkid) DO UPDATE SET created_at = NOW();
        """, from_user['pkid'], target_user_pkid, tag_pkid)
        
        await query.answer("✅ 感谢您的评价！", show_alert=True)
    except Exception as e:
        logger.error(f"评价处理失败: {e}", exc_info=True)
        await query.answer("❌ 评价失败，发生内部错误。", show_alert=True)

    # 评价后，刷新声誉卡片
    await send_reputation_card(update, context, target_user_pkid, origin)

# =============================================================================
# 返回操作
# =============================================================================
async def back_to_rep_card(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_pkid: int, origin: str):
    """从其他菜单返回到声誉卡片。"""
    await send_reputation_card(update, context, target_user_pkid, origin)
