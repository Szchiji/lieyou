import re
from html import escape

async def handle_nomination(update, context):
    message = update.message
    nominee_username = None

    # 更宽容的正则，支持 @miss_maomi、@user_name 等
    match = re.search(r'@([A-Za-z0-9_]{5,})|查询\s*@([A-Za-z0-9_]{5,})', message.text)
    if match:
        nominee_username = match.group(1) or match.group(2)

    if not nominee_username:
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
            InlineKeyboardButton("⚖️ 追溯献祭者", callback_data=f"rep_voters_menu_{nominee_username}")
        ]
    ]
    return {'text': text, 'reply_markup': InlineKeyboardMarkup(keyboard), 'parse_mode': 'HTML'}
