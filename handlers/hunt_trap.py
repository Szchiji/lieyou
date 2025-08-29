from telegram import Update
from telegram.ext import ContextTypes

from constants import REP_HUNT_SUCCESS, REP_TRAP_SUCCESS, REP_BEING_HUNTED, REP_BEING_TRAPPED, TYPE_HUNT, TYPE_TRAP
from database import get_conn, put_conn

async def handle_mark(update: Update, context: ContextTypes.DEFAULT_TYPE, mark_type: str):
    """统一处理 /hunt 和 /trap 命令的逻辑。"""
    message = update.effective_message
    marker = update.effective_user
    
    # 检查是否是回复消息
    if not message.reply_to_message:
        await message.reply_text("请回复一条消息来使用此命令。")
        return

    replied_message = message.reply_to_message
    sharer = replied_message.from_user
    
    # 不能标记自己或机器人
    if sharer.id == marker.id:
        await message.reply_text("你不能标记自己的分享。")
        return
    if sharer.is_bot:
        await message.reply_text("你不能标记机器人。")
        return

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 确保分享者和标记人都存在于users表中
            cur.execute("INSERT INTO users (id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING", (sharer.id, sharer.username, sharer.first_name))
            cur.execute("INSERT INTO users (id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING", (marker.id, marker.username, marker.first_name))

            # 找到或创建资源记录
            cur.execute(
                "INSERT INTO resources (chat_id, message_id, sharer_id, sharer_username, content) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (chat_id, message_id) DO UPDATE SET content = EXCLUDED.content RETURNING id",
                (replied_message.chat_id, replied_message.message_id, sharer.id, sharer.username, replied_message.text or replied_message.caption)
            )
            resource_id = cur.fetchone()[0]

            # 尝试插入反馈记录，利用UNIQUE约束防止重复标记
            cur.execute(
                "INSERT INTO feedback (resource_id, marker_id, type) VALUES (%s, %s, %s) ON CONFLICT (resource_id, marker_id) DO NOTHING RETURNING id",
                (resource_id, marker.id, mark_type)
            )
            feedback_id = cur.fetchone()

            if not feedback_id:
                await message.reply_text("你已经标记过这条分享了。", quote=True)
                return

            # 根据类型更新声望
            if mark_type == TYPE_HUNT:
                marker_rep_change = REP_HUNT_SUCCESS
                sharer_rep_change = REP_BEING_HUNTED
                response_text = f"🎯 @{marker.username} 的狩猎标记已收到！@{sharer.username} 的猎物得到了狼群的认可！"
            else: # TYPE_TRAP
                marker_rep_change = REP_TRAP_SUCCESS
                sharer_rep_change = REP_BEING_TRAPPED
                response_text = f"⚠️ @{marker.username} 发出了警告！狼群已注意到 @{sharer.username} 分享的陷阱。"

            # 更新声望
            cur.execute("UPDATE users SET reputation = reputation + %s WHERE id = %s", (marker_rep_change, marker.id))
            cur.execute("UPDATE users SET reputation = reputation + %s WHERE id = %s", (sharer_rep_change, sharer.id))
            
            conn.commit()
            await message.reply_text(response_text, quote=True)

    except Exception as e:
        conn.rollback()
        print(f"Error in handle_mark: {e}")
        await message.reply_text("处理时发生错误，请稍后再试。")
    finally:
        put_conn(conn)

async def hunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_mark(update, context, TYPE_HUNT)

async def trap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_mark(update, context, TYPE_TRAP)
