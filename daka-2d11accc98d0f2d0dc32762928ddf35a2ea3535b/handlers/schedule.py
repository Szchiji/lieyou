from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
    InputMediaPhoto, InputMediaVideo, InputMediaDocument
)
from telegram.ext import (
    CallbackQueryHandler, MessageHandler, filters, ConversationHandler, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, time
from utils import get_db, is_admin

scheduler = AsyncIOScheduler()

def get_schedule_list_markup(schedules):
    keyboard = []
    for s in schedules:
        status = "✅" if s["enabled"] else "❌"
        short_text = (s['text'] or '')[:10].replace('\n', ' ')
        txt = f"{status} {short_text}..."
        keyboard.append([InlineKeyboardButton(txt, callback_data=f"schedule_detail_{s['id']}")])
    keyboard.append([InlineKeyboardButton("➕ 新建定时消息", callback_data="schedule_create")])
    keyboard.append([InlineKeyboardButton("⬅️ 返回", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)

async def show_schedule_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_admin(user_id):
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("只有管理员才能操作。")
        return
    db = await get_db()
    async with db.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM scheduled_message WHERE chat_id=$1 ORDER BY id", chat_id)
    schedules = [dict(r) for r in rows]
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "所有定时消息：", reply_markup=get_schedule_list_markup(schedules)
    )

def get_schedule_status_text(s):
    detail = (
        f"🕰️ <b>定时消息</b> [ID:{s['id']}]\n\n"
        f"状态: {'✅开启' if s['enabled'] else '❌关闭'}\n"
        f"重复: 每{s['interval']}分钟\n"
        f"删除上一条: {'✅' if s['del_prev'] else '❌'}\n"
        f"置顶: {'✅' if s['pin'] else '❌'}\n"
        f"媒体: {'✅' if s['media'] else '❌'}（{s['media_type'] or '--'}）\n"
        f"按钮: {'✅' if s['button'] else '❌'}\n"
        f"时段: {s['period'] or '全天'}\n"
        f"有效期: {s['start_date'] or '--'} ~ {s['end_date'] or '--'}\n"
        f"文本内容:\n{(s['text'] or '(无内容)')}"
    )
    return detail

def schedule_detail_markup(s):
    keyboard = [
        [InlineKeyboardButton("启用", callback_data=f"schedule_enable_{s['id']}"),
         InlineKeyboardButton("关闭", callback_data=f"schedule_disable_{s['id']}")],
        [InlineKeyboardButton("删除上一条: 是", callback_data=f"schedule_delprev_yes_{s['id']}"),
         InlineKeyboardButton("否", callback_data=f"schedule_delprev_no_{s['id']}")],
        [InlineKeyboardButton("置顶: 是", callback_data=f"schedule_pin_yes_{s['id']}"),
         InlineKeyboardButton("否", callback_data=f"schedule_pin_no_{s['id']}")],
        [InlineKeyboardButton("📝 修改文本", callback_data=f"schedule_edit_text_{s['id']}")],
        [InlineKeyboardButton("🖼 修改媒体", callback_data=f"schedule_edit_media_{s['id']}")],
        [InlineKeyboardButton("🔘 修改按钮", callback_data=f"schedule_edit_button_{s['id']}")],
        [InlineKeyboardButton("🔁 重复时间", callback_data=f"schedule_edit_interval_{s['id']}"),
         InlineKeyboardButton("⏰ 设置时段", callback_data=f"schedule_edit_period_{s['id']}")],
        [InlineKeyboardButton("📅 开始日期", callback_data=f"schedule_edit_start_{s['id']}"),
         InlineKeyboardButton("📅 终止日期", callback_data=f"schedule_edit_end_{s['id']}")],
        [InlineKeyboardButton("🗑 删除此定时", callback_data=f"schedule_delete_{s['id']}")],
        [InlineKeyboardButton("⬅️ 返回列表", callback_data="menu_schedule")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def get_schedule(chat_id, sid):
    db = await get_db()
    async with db.acquire() as conn:
        s = await conn.fetchrow("SELECT * FROM scheduled_message WHERE chat_id=$1 AND id=$2", chat_id, sid)
    return dict(s) if s else None

async def show_schedule_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    sid = int(update.callback_query.data.split('_')[-1])
    if not is_admin(user_id):
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("只有管理员才能操作。")
        return
    s = await get_schedule(chat_id, sid)
    await update.callback_query.answer()
    if s['media']:
        if s['media_type'] == "photo":
            await update.callback_query.edit_message_media(
                media=InputMediaPhoto(s['media'], caption=get_schedule_status_text(s), parse_mode="HTML"),
                reply_markup=schedule_detail_markup(s)
            )
        elif s['media_type'] == "video":
            await update.callback_query.edit_message_media(
                media=InputMediaVideo(s['media'], caption=get_schedule_status_text(s), parse_mode="HTML"),
                reply_markup=schedule_detail_markup(s)
            )
        elif s['media_type'] == "document":
            await update.callback_query.edit_message_media(
                media=InputMediaDocument(s['media'], caption=get_schedule_status_text(s), parse_mode="HTML"),
                reply_markup=schedule_detail_markup(s)
            )
        else:
            await update.callback_query.edit_message_text(
                get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
            )
    else:
        await update.callback_query.edit_message_text(
            get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
        )

async def create_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    db = await get_db()
    async with db.acquire() as conn:
        await conn.fetchrow(
            "INSERT INTO scheduled_message (chat_id, text, interval, enabled) VALUES ($1, $2, $3, FALSE) RETURNING id",
            chat_id, "新定时消息", 60
        )
    await show_schedule_list(update, context)

async def delete_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sid = int(update.callback_query.data.split('_')[-1])
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute("DELETE FROM scheduled_message WHERE chat_id=$1 AND id=$2", chat_id, sid)
    await show_schedule_list(update, context)
    await reload_cron_jobs(context)

async def toggle_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    parts = update.callback_query.data.split('_')
    action, sid = '_'.join(parts[:-1]), int(parts[-1])
    db = await get_db()
    async with db.acquire() as conn:
        if action == "schedule_enable":
            await conn.execute("UPDATE scheduled_message SET enabled=TRUE WHERE chat_id=$1 AND id=$2", chat_id, sid)
        elif action == "schedule_disable":
            await conn.execute("UPDATE scheduled_message SET enabled=FALSE WHERE chat_id=$1 AND id=$2", chat_id, sid)
        elif action == "schedule_delprev_yes":
            await conn.execute("UPDATE scheduled_message SET del_prev=TRUE WHERE chat_id=$1 AND id=$2", chat_id, sid)
        elif action == "schedule_delprev_no":
            await conn.execute("UPDATE scheduled_message SET del_prev=FALSE WHERE chat_id=$1 AND id=$2", chat_id, sid)
        elif action == "schedule_pin_yes":
            await conn.execute("UPDATE scheduled_message SET pin=TRUE WHERE chat_id=$1 AND id=$2", chat_id, sid)
        elif action == "schedule_pin_no":
            await conn.execute("UPDATE scheduled_message SET pin=FALSE WHERE chat_id=$1 AND id=$2", chat_id, sid)
    s = await get_schedule(chat_id, sid)
    if s['media']:
        if s['media_type'] == "photo":
            await update.callback_query.edit_message_media(
                media=InputMediaPhoto(s['media'], caption=get_schedule_status_text(s), parse_mode="HTML"),
                reply_markup=schedule_detail_markup(s)
            )
        elif s['media_type'] == "video":
            await update.callback_query.edit_message_media(
                media=InputMediaVideo(s['media'], caption=get_schedule_status_text(s), parse_mode="HTML"),
                reply_markup=schedule_detail_markup(s)
            )
        elif s['media_type'] == "document":
            await update.callback_query.edit_message_media(
                media=InputMediaDocument(s['media'], caption=get_schedule_status_text(s), parse_mode="HTML"),
                reply_markup=schedule_detail_markup(s)
            )
        else:
            await update.callback_query.edit_message_text(
                get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
            )
    else:
        await update.callback_query.edit_message_text(
            get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
        )
    await reload_cron_jobs(context)

(EDIT_TEXT, EDIT_MEDIA, EDIT_BUTTON, EDIT_INTERVAL, EDIT_PERIOD, EDIT_START, EDIT_END) = range(200, 207)

async def edit_text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data["sid"] = sid
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("请发送新的文本内容（支持多行）。")
    return EDIT_TEXT

async def edit_text_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sid = context.user_data["sid"]
    text = update.message.text
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute("UPDATE scheduled_message SET text=$1 WHERE chat_id=$2 AND id=$3", text, chat_id, sid)
    await update.message.reply_text("文本已更新。")
    s = await get_schedule(chat_id, sid)
    await update.message.reply_text(
        get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
    )
    await reload_cron_jobs(update)
    return ConversationHandler.END

async def edit_media_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data["sid"] = sid
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("请发送图片、视频或文件（支持jpg/png/gif/mp4/pdf/doc/xls/zip等）或回复要用的多媒体消息。")
    return EDIT_MEDIA

async def edit_media_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sid = context.user_data["sid"]
    db = await get_db()
    media_type = None
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        media_type = "photo"
    elif update.message.video:
        file_id = update.message.video.file_id
        media_type = "video"
    elif update.message.document:
        file_id = update.message.document.file_id
        mime = update.message.document.mime_type or ""
        if mime.startswith("image/"):
            media_type = "photo"
        elif mime.startswith("video/"):
            media_type = "video"
        else:
            media_type = "document"
    else:
        await update.message.reply_text("请发送图片、视频或文件。")
        return EDIT_MEDIA

    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE scheduled_message SET media=$1, media_type=$2 WHERE chat_id=$3 AND id=$4",
            file_id, media_type, chat_id, sid
        )

    await update.message.reply_text("多媒体内容已更新。")
    s = await get_schedule(chat_id, sid)
    if media_type == "photo":
        await update.message.reply_photo(file_id, caption=get_schedule_status_text(s), parse_mode="HTML",
                                        reply_markup=schedule_detail_markup(s))
    elif media_type == "video":
        await update.message.reply_video(file_id, caption=get_schedule_status_text(s), parse_mode="HTML",
                                        reply_markup=schedule_detail_markup(s))
    elif media_type == "document":
        await update.message.reply_document(file_id, caption=get_schedule_status_text(s), parse_mode="HTML",
                                           reply_markup=schedule_detail_markup(s))
    await reload_cron_jobs(update)
    return ConversationHandler.END

async def edit_button_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data["sid"] = sid
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "请发送按钮文本和链接（如：按钮名|https://xxx.com），多行可多个。")
    return EDIT_BUTTON

async def edit_button_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sid = context.user_data["sid"]
    lines = update.message.text.strip().splitlines()
    buttons = []
    for l in lines:
        if "|" in l: btn, url = l.split("|",1); buttons.append({"text":btn.strip(),"url":url.strip()})
    import json
    btn_json = json.dumps(buttons, ensure_ascii=False)
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute("UPDATE scheduled_message SET button=$1 WHERE chat_id=$2 AND id=$3", btn_json, chat_id, sid)
    await update.message.reply_text("按钮已更新。")
    s = await get_schedule(chat_id, sid)
    await update.message.reply_text(
        get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
    )
    await reload_cron_jobs(update)
    return ConversationHandler.END

async def edit_interval_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data["sid"] = sid
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("请输入重复间隔，单位分钟（如60）。")
    return EDIT_INTERVAL

async def edit_interval_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sid = context.user_data["sid"]
    try:
        interval = int(update.message.text.strip())
        assert interval > 0
    except:
        await update.message.reply_text("格式错误，请输入正整数。")
        return EDIT_INTERVAL
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute("UPDATE scheduled_message SET interval=$1 WHERE chat_id=$2 AND id=$3", interval, chat_id, sid)
    await update.message.reply_text("重复间隔已更新。")
    s = await get_schedule(chat_id, sid)
    await update.message.reply_text(
        get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
    )
    await reload_cron_jobs(update)
    return ConversationHandler.END

async def edit_period_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data["sid"] = sid
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "请输入时段（如08:00-20:00），多段用逗号隔开，如08:00-12:00,14:00-18:00。")
    return EDIT_PERIOD

async def edit_period_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sid = context.user_data["sid"]
    period = update.message.text.strip()
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute("UPDATE scheduled_message SET period=$1 WHERE chat_id=$2 AND id=$3", period, chat_id, sid)
    await update.message.reply_text("时段已更新。")
    s = await get_schedule(chat_id, sid)
    await update.message.reply_text(
        get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
    )
    await reload_cron_jobs(update)
    return ConversationHandler.END

async def edit_start_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data["sid"] = sid
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("请输入开始日期（YYYY-MM-DD）。")
    return EDIT_START

async def edit_start_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sid = context.user_data["sid"]
    try:
        val = update.message.text.strip()
        datetime.strptime(val, "%Y-%m-%d")
    except:
        await update.message.reply_text("格式错误，请输入YYYY-MM-DD格式。")
        return EDIT_START
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute("UPDATE scheduled_message SET start_date=$1 WHERE chat_id=$2 AND id=$3", val, chat_id, sid)
    await update.message.reply_text("开始日期已更新。")
    s = await get_schedule(chat_id, sid)
    await update.message.reply_text(
        get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
    )
    await reload_cron_jobs(update)
    return ConversationHandler.END

async def edit_end_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sid = int(update.callback_query.data.split('_')[-1])
    context.user_data["sid"] = sid
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("请输入终止日期（YYYY-MM-DD）。")
    return EDIT_END

async def edit_end_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    sid = context.user_data["sid"]
    try:
        val = update.message.text.strip()
        datetime.strptime(val, "%Y-%m-%d")
    except:
        await update.message.reply_text("格式错误，请输入YYYY-MM-DD格式。")
        return EDIT_END
    db = await get_db()
    async with db.acquire() as conn:
        await conn.execute("UPDATE scheduled_message SET end_date=$1 WHERE chat_id=$2 AND id=$3", val, chat_id, sid)
    await update.message.reply_text("终止日期已更新。")
    s = await get_schedule(chat_id, sid)
    await update.message.reply_text(
        get_schedule_status_text(s), reply_markup=schedule_detail_markup(s), parse_mode="HTML"
    )
    await reload_cron_jobs(update)
    return ConversationHandler.END

def in_period(period_str, now=None):
    if not period_str:
        return True
    if now is None:
        now = datetime.now().time()
    for p in period_str.split(','):
        p = p.strip()
        if not p: continue
        try:
            start, end = p.split('-')
            start = time.fromisoformat(start.strip())
            end = time.fromisoformat(end.strip())
            if start <= now <= end:
                return True
        except Exception:
            continue
    return False

async def reload_cron_jobs(context):
    scheduler.remove_all_jobs()
    db = await get_db()
    async with db.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM scheduled_message WHERE enabled=TRUE")
    for row in rows:
        try:
            interval = row["interval"]
            if not interval: continue
            chat_id = row["chat_id"]
            sid = row["id"]
            scheduler.add_job(
                send_cron_message,
                'interval',
                minutes=interval,
                args=[chat_id, sid, context.bot],
                id=f"cronmsg_{row['id']}",
                replace_existing=True,
            )
        except Exception as e:
            print(f"定时消息ID{row['id']}调度失败：{e}")

async def send_cron_message(chat_id, sid, bot):
    db = await get_db()
    async with db.acquire() as conn:
        s = await conn.fetchrow("SELECT * FROM scheduled_message WHERE chat_id=$1 AND id=$2", chat_id, sid)
        if not s or not s['enabled']:
            return
        now = datetime.now()
        if s['start_date'] and now.date() < s['start_date']:
            return
        if s['end_date'] and now.date() > s['end_date']:
            return
        if not in_period(s['period'], now.time()):
            return
        if s['del_prev'] and s.get('last_msg_id'):
            try:
                await bot.delete_message(chat_id, s['last_msg_id'])
            except: pass
        reply_markup = None
        if s['button']:
            import json
            try:
                blist = json.loads(s['button'])
                buttons = []
                for b in blist:
                    buttons.append([InlineKeyboardButton(b['text'], url=b['url'])])
                reply_markup = InlineKeyboardMarkup(buttons)
            except:
                pass
        msg = None
        if s['media'] and s['media_type']:
            if s['media_type'] == "photo":
                msg = await bot.send_photo(chat_id, s['media'], caption=s['text'], reply_markup=reply_markup)
            elif s['media_type'] == "video":
                msg = await bot.send_video(chat_id, s['media'], caption=s['text'], reply_markup=reply_markup)
            elif s['media_type'] == "document":
                msg = await bot.send_document(chat_id, s['media'], caption=s['text'], reply_markup=reply_markup)
        else:
            msg = await bot.send_message(chat_id, s['text'], reply_markup=reply_markup)
        if s['pin'] and msg:
            try:
                await bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
            except: pass
        if msg:
            await conn.execute("UPDATE scheduled_message SET last_msg_id=$1 WHERE chat_id=$2 AND id=$3", msg.message_id, chat_id, sid)

def register(application):
    application.add_handler(CallbackQueryHandler(show_schedule_list, pattern="^menu_schedule$"))
    application.add_handler(CallbackQueryHandler(show_schedule_detail, pattern="^schedule_detail_\\d+$"))
    application.add_handler(CallbackQueryHandler(create_schedule, pattern="^schedule_create$"))
    application.add_handler(CallbackQueryHandler(delete_schedule, pattern="^schedule_delete_\\d+$"))
    application.add_handler(CallbackQueryHandler(toggle_switch,
        pattern="^schedule_(enable|disable|delprev_yes|delprev_no|pin_yes|pin_no)_\\d+$"))
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_text_entry, pattern="^schedule_edit_text_\\d+$")],
        states={EDIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_text_save)]},
        fallbacks=[],
        per_chat=True
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_media_entry, pattern="^schedule_edit_media_\\d+$")],
        states={EDIT_MEDIA: [MessageHandler(
            filters.PHOTO | filters.VIDEO | filters.Document.ALL, edit_media_save)]},
        fallbacks=[],
        per_chat=True
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_button_entry, pattern="^schedule_edit_button_\\d+$")],
        states={EDIT_BUTTON: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_button_save)]},
        fallbacks=[],
        per_chat=True
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_interval_entry, pattern="^schedule_edit_interval_\\d+$")],
        states={EDIT_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_interval_save)]},
        fallbacks=[],
        per_chat=True
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_period_entry, pattern="^schedule_edit_period_\\d+$")],
        states={EDIT_PERIOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_period_save)]},
        fallbacks=[],
        per_chat=True
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start_entry, pattern="^schedule_edit_start_\\d+$")],
        states={EDIT_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_start_save)]},
        fallbacks=[],
        per_chat=True
    ))
    application.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_end_entry, pattern="^schedule_edit_end_\\d+$")],
        states={EDIT_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_end_save)]},
        fallbacks=[],
        per_chat=True
    ))
    # 不要在这里 scheduler.start()，只在主程序入口调用一次
