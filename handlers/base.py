from telegram import Update
from telegram.ext import ContextTypes

from database import get_conn, put_conn

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """欢迎用户并创建用户记录。"""
    user = update.effective_user
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                (user.id, user.username, user.first_name)
            )
            conn.commit()
    finally:
        put_conn(conn)
        
    await update.message.reply_text(
        f"你好，{user.first_name}！\n\n"
        "欢迎来到狼群。在这里，你的每一次发现都至关重要。\n"
        "使用 /help 查看如何开始你的狩猎之旅。"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """发送帮助信息，解释机器人玩法。"""
    help_text = (
        "🐺 **狼群生存法则** 🐺\n\n"
        "我是这个狼群的记录者。我的任务是记录下每一个有价值的“猎物”和每一个危险的“陷阱”。\n\n"
        "--- **核心指令** ---\n\n"
        "🎯 **发现猎物 (`/hunt`)**\n"
        "当你看到一个优质的分享时，**回复那条消息**并输入 `/hunt`。\n"
        "这会为分享者增加声望，你自己也会获得奖励。这是对贡献者的最高致敬！\n\n"
        "⚠️ **发现陷阱 (`/trap`)**\n"
        "如果一个分享是无效的、错误的或危险的，**回复那条消息**并输入 `/trap`。\n"
        "这会警告其他同伴，并扣除分享者的声望。感谢你的警惕！\n\n"
        "--- **查询指令** ---\n\n"
        "📖 **查看猎物名录 (`/list`)**\n"
        "查看由整个狼群共同筛选出的优质资源列表。你可以按“最新”或“最热”排序。\n\n"
        "👤 **查看个人档案 (`/profile`)**\n"
        "查看你自己的声望、等级和狩猎记录。也可以回复某人消息并使用 `/profile` 查看他的档案。\n\n"
        "🏆 **查看头狼榜 (`/leaderboard`)**\n"
        "查看社区中声望最高的成员，以及本周的“猎王”和“首席哨兵”。\n\n"
        "--- \n"
        "你的每一次标记，都在塑造这个狼群的未来。祝狩猎愉快！"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')
