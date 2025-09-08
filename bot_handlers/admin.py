import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
)
from database import (
    list_tags,
    toggle_tag,
    delete_tag,
    add_tag,
    set_user_hidden_by_username,
    get_bot_statistics,
)

logger = logging.getLogger(__name__)
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

# Conversation states
TYPING_TAG_NAME = 1001
SELECTING_TAG_TYPE = 1002
TYPING_USERNAME_HIDE = 1003
TYPING_USERNAME_UNHIDE = 1004

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        if update.message:
            await update.message.reply_text("❌ 无权限")
        elif update.callback_query:
            await update.callback_query.answer("❌ 无权限", show_alert=True)
        return

    stats = await get_bot_statistics()
    text = (
        "🔧 *管理面板*\n\n"
        f"用户总数: {stats['total_users']}    评价总数: {stats['total_ratings']}\n"
        f"24h 活跃: {stats['active_users_24h']}\n\n"
        "请选择功能："
    )
    kb = [
        [InlineKeyboardButton("🏷️ 标签管理", callback_data="admin_tags")],
        [
            InlineKeyboardButton("🙈 隐藏用户", callback_data="admin_hide_user"),
            InlineKeyboardButton("👀 取消隐藏", callback_data="admin_unhide_user"),
        ],
        [InlineKeyboardButton("🔄 刷新", callback_data="admin_panel")],
    ]
    markup = InlineKeyboardMarkup(kb)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=markup
        )
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)

async def admin_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "admin_panel":
        await admin_panel(update, context)
    elif data == "admin_tags":
        await show_tag_management(q)
    elif data.startswith("admin_tag_toggle_"):
        tid = int(data.split("_")[-1])
        await toggle_tag(tid)
        await show_tag_management(q)
    elif data.startswith("admin_tag_delete_"):
        tid = int(data.split("_")[-1])
        await delete_tag(tid)
        await show_tag_management(q)
    elif data == "admin_add_tag":
        await q.message.reply_text("请输入新标签名称：")
        return TYPING_TAG_NAME
    elif data == "admin_hide_user":
        await q.message.reply_text("请输入要隐藏的用户名（不含@）：")
        return TYPING_USERNAME_HIDE
    elif data == "admin_unhide_user":
        await q.message.reply_text("请输入要取消隐藏的用户名（不含@）：")
        return TYPING_USERNAME_UNHIDE

async def show_tag_management(q):
    tags = await list_tags()
    text = "🏷️ 标签管理：\n"
    for t in tags:
        status = "✅" if t["is_active"] else "❌"
        text += f"{t['id']}. {t['name']} ({t['type']}) {status}\n"

    kb = [[InlineKeyboardButton("➕ 添加", callback_data="admin_add_tag")]]
    for t in tags[:10]:
        kb.append(
            [
                InlineKeyboardButton(
                    f"切换:{t['id']}", callback_data=f"admin_tag_toggle_{t['id']}"
                ),
                InlineKeyboardButton(
                    f"删除:{t['id']}", callback_data=f"admin_tag_delete_{t['id']}"
                ),
            ]
        )
    kb.append([InlineKeyboardButton("↩️ 返回", callback_data="admin_panel")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def add_tag_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_tag_name"] = update.message.text.strip()
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("正向", callback_data="tag_type_positive"),
                InlineKeyboardButton("负向", callback_data="tag_type_negative"),
            ]
        ]
    )
    await update.message.reply_text("请选择标签类型：", reply_markup=kb)
    return SELECTING_TAG_TYPE

async def add_tag_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tag_type = q.data.split("_")[-1]
    name = context.user_data.get("new_tag_name")
    if not name:
        await q.message.reply_text("名称缺失，请重试。")
        return ConversationHandler.END

    ok = await add_tag(name, tag_type)
    await q.message.reply_text("添加成功" if ok else "添加失败")
    return ConversationHandler.END

async def hide_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.message.text.strip()
    ok = await set_user_hidden_by_username(uname, True)
    await update.message.reply_text("已隐藏" if ok else "操作失败或用户不存在")
    return ConversationHandler.END

async def unhide_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = update.message.text.strip()
    ok = await set_user_hidden_by_username(uname, False)
    await update.message.reply_text("已取消隐藏" if ok else "操作失败或用户不存在")
    return ConversationHandler.END

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("已取消")
    return ConversationHandler.END

def build_admin_conversations():
    # 使用默认 per_message=False，避免 FAQ 警告。该设置可正常处理 MessageHandler 与 CallbackQueryHandler。
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_callback_router, pattern="^admin_")],
        states={
            TYPING_TAG_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_tag_name)
            ],
            SELECTING_TAG_TYPE: [
                CallbackQueryHandler(add_tag_type, pattern="^tag_type_")
            ],
            TYPING_USERNAME_HIDE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, hide_user_input)
            ],
            TYPING_USERNAME_UNHIDE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, unhide_user_input)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        map_to_parent={}
    )
