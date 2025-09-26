from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from utils import get_db, admin_required, today_str

# 添加会员
@admin_required
async def add_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        user_id = int(args[0])
        name = args[1]
        expire = args[2]  # YYYY-MM-DD
        db = await get_db()
        await db.execute(
            "INSERT INTO members(user_id, name, expire) VALUES($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET name=$2, expire=$3",
            user_id, name, expire
        )
        await update.message.reply_text(f"添加会员成功：{name} (ID:{user_id}) 到期:{expire}")
    except Exception:
        await update.message.reply_text("用法: /addmember user_id name expire(YYYY-MM-DD)")

# 删除会员
@admin_required
async def del_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(context.args[0])
        db = await get_db()
        await db.execute("DELETE FROM members WHERE user_id=$1", user_id)
        await update.message.reply_text(f"已删除会员ID:{user_id}")
    except Exception:
        await update.message.reply_text("用法: /delmember user_id")

# 续费
@admin_required
async def renew_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = int(context.args[0])
        expire = context.args[1]
        db = await get_db()
        await db.execute("UPDATE members SET expire=$1 WHERE user_id=$2", expire, user_id)
        await update.message.reply_text(f"会员ID:{user_id} 已续费到 {expire}")
    except Exception:
        await update.message.reply_text("用法: /renewmember user_id expire(YYYY-MM-DD)")

# 查询所有会员
@admin_required
async def list_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = await get_db()
    rows = await db.fetch("SELECT user_id, name, expire FROM members ORDER BY expire")
    if not rows:
        await update.message.reply_text("无会员。")
        return
    lines = [f"{i+1}. {r['name']} (ID:{r['user_id']}) 到期:{r['expire']}" for i, r in enumerate(rows)]
    await update.message.reply_text("\n".join(lines))

def register(application):
    application.add_handler(CommandHandler("addmember", add_member))
    application.add_handler(CommandHandler("delmember", del_member))
    application.add_handler(CommandHandler("renewmember", renew_member))
    application.add_handler(CommandHandler("listmembers", list_members))
