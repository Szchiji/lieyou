from telegram import Update
from telegram.ext import ContextTypes

from database import get_conn, put_conn
from handlers.decorators import admin_only

@admin_only
async def set_rep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    管理员命令：手动设置用户的声望。
    用法: /setrep <声望值> (回复一个用户的消息)
    """
    if not update.message.reply_to_message:
        await update.message.reply_text("请回复一个用户的消息来使用此命令。")
        return
        
    try:
        args = context.args
        if len(args) != 1:
            await update.message.reply_text("用法: /setrep <声望值>")
            return
            
        new_rep = int(args[0])
        target_user = update.message.reply_to_message.from_user
        
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # 确保用户存在
                cur.execute("INSERT INTO users (id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING", (target_user.id, target_user.username, target_user.first_name))
                cur.execute("UPDATE users SET reputation = %s WHERE id = %s", (new_rep, target_user.id))
                conn.commit()
                await update.message.reply_text(f"已将 @{target_user.username} 的声望设置为 {new_rep}。")
        finally:
            put_conn(conn)
            
    except (IndexError, ValueError):
        await update.message.reply_text("请输入一个有效的声望数值。")
    except Exception as e:
        await update.message.reply_text(f"发生错误: {e}")
