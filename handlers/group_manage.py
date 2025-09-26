from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, CommandHandler, ChatMemberHandler
)
from utils import get_db, is_admin

# 1. 机器人被拉入新群时自动记录群信息
async def on_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_status = update.my_chat_member.new_chat_member.status
    old_status = update.my_chat_member.old_chat_member.status
    chat = update.effective_chat
    # 只记录机器人被拉入新群的情况
    if chat.type in ("group", "supergroup") and old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        chat_id = chat.id
        chat_title = chat.title
        db = await get_db()
        async with db.acquire() as conn:
            await conn.execute(
                "INSERT INTO bot_groups (chat_id, title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET title=$2",
                chat_id, chat_title
            )
        print(f"机器人已加入新群: {chat_id} - {chat_title}")

# 2. 私聊命令，展示所有管理的群，让管理员选择
async def show_group_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("只有管理员才能操作。")
        return
    db = await get_db()
    async with db.acquire() as conn:
        rows = await conn.fetch("SELECT chat_id, title FROM bot_groups ORDER BY chat_id")
    if not rows:
        await update.message.reply_text("机器人还没有被拉进任何群组。")
        return
    keyboard = [
        [InlineKeyboardButton(f"{r['title'] or r['chat_id']}", callback_data=f"select_group_{r['chat_id']}")]
        for r in rows
    ]
    await update.message.reply_text("请选择要管理的群：", reply_markup=InlineKeyboardMarkup(keyboard))

# 3. 处理群选择，记录到用户上下文
async def on_select_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = int(update.callback_query.data.split('_')[-1])
    context.user_data['selected_group'] = chat_id
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(f"已选择群：{chat_id}\n你可以使用相关命令进行管理。")

# 4. 注册到 application
def register(application):
    application.add_handler(ChatMemberHandler(on_my_chat_member, chat_member_types=["my_chat_member"]))
    application.add_handler(CommandHandler("groups", show_group_list))
    application.add_handler(CallbackQueryHandler(on_select_group, pattern="^select_group_\\-?\\d+$"))
