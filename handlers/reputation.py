import re
import logging
from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# 示例数据库函数，需要替换为你的实现
async def db_transaction():
    # 你的数据库上下文管理器
    pass

async def get_reputation_summary(nominee_username, nominator_id):
    # 查询并返回赞誉/警示统计和星盘状态
    # 示例返回结构
    return {
        'recommend_count': 0,
        'block_count': 0,
        'is_favorite': False
    }

async def get_voter_usernames(nominee_username, vote_type):
    # 查询数据库返回所有赞誉者或警示者用户名列表
    # 示例返回
    return []

async def handle_nomination(update, context):
    message = update.message
    nominee_username = None

    # 更宽容的正则，支持 @miss_maomi、@user_name 等
    match = re.search(r'@([A-Za-z0-9_]{5,})|查询\s*@([A-Za-z0-9_]{5,})', message.text)
    if match:
        nominee_username = match.group(1) or match.group(2)

    if not nominee_username:
        logger.warning("未找到有效用户名")
        return

    nominator_id = update.effective_user.id
    async with db_transaction() as conn:
        await conn.execute(
            "INSERT INTO users (id, username) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET username = $2",
            nominator_id,
            update.effective_user.username
        )

    summary = await get_reputation_summary(nominee_username, nominator_id)
    message_content = await build_summary_view(nominee_username, summary)
    await update.message.reply_text(**message_content)

async def build_summary_view(nominee_username: str, summary: dict):
    text = (
        f"╭───「 📜 <b>神谕之卷</b> 」───╮\n"
        f"│\n"
        f"│  👤 <b>求问对象:</b> @{escape(nominee_username)}\n"
        f"│\n"
        f"│  👍 <b>赞誉:</b> {summary['recommend_count']} 次\n"
        f"│  👎 <b>警示:</b> {summary['block_count']} 次\n"
        f"│\n"
        f"╰──────────────╯"
    )
    fav_icon = "🌟" if summary['is_favorite'] else "➕"
    fav_text = "加入星盘" if not summary['is_favorite'] else "移出星盘"
    fav_callback = "query_fav_remove" if summary['is_favorite'] else "query_fav_add"
    keyboard = [
        [
            InlineKeyboardButton("👍 献上赞誉", callback_data=f"vote_recommend_{nominee_username}"),
            InlineKeyboardButton("👎 降下警示", callback_data=f"vote_block_{nominee_username}"),
        ],
        [
            InlineKeyboardButton("📜 查看箴言", callback_data=f"rep_detail_{nominee_username}"),
            InlineKeyboardButton(f"{fav_icon} {fav_text}", callback_data=f"{fav_callback}_{nominee_username}")
        ],
        [
            InlineKeyboardButton("👍 查看赞誉者", callback_data=f"rep_voters_recommend_{nominee_username}"),
            InlineKeyboardButton("👎 查看警示者", callback_data=f"rep_voters_block_{nominee_username}")
        ],
        [
            InlineKeyboardButton("⬅️ 返回卷宗", callback_data=f"rep_summary_{nominee_username}")
        ]
    ]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}

async def show_reputation_voters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info(f"rep_voters callback data: {query.data}")
    try:
        parts = query.data.split('_')
        if len(parts) < 4:
            logger.error(f"回调参数错误: {query.data}")
            await query.answer("参数有误", show_alert=True)
            return
        _, _, vote_type, nominee_username = parts
        logger.info(f"vote_type: {vote_type}, nominee_username: {nominee_username}")
        message_content = await build_voters_view(nominee_username, vote_type)
        logger.info(f"build_voters_view content: {message_content}")
        await query.edit_message_text(**message_content)
    except Exception as e:
        logger.error(f"处理rep_voters出错: {e}", exc_info=True)
        await query.answer("❌ 无法展示名单，请联系管理员。", show_alert=True)

async def build_voters_view(nominee_username: str, vote_type: str):
    logger.info(f"构建献祭者名单: {nominee_username}, 类型: {vote_type}")
    voters = await get_voter_usernames(nominee_username, vote_type)  # 需替换为你的数据库查询
    logger.info(f"voters: {voters}")
    if not voters:
        text = f"没有任何{'赞誉' if vote_type == 'recommend' else '警示'}者。"
    else:
        text = f"{'赞誉' if vote_type == 'recommend' else '警示'}者名单：\n"
        text += '\n'.join([f"@{escape(username)}" for username in voters])
    keyboard = [[InlineKeyboardButton("⬅️ 返回卷宗", callback_data=f"rep_summary_{nominee_username}")]]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}
