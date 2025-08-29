import os
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

# ... (restricted_to_group 装饰器保持不变) ...

def admin_only(func):
    """
    一个装饰器，用于将命令的执行限制为机器人管理员。
    """
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        try:
            admin_ids_str = os.environ.get("ADMIN_IDS", "")
            if not admin_ids_str:
                await update.message.reply_text("机器人未配置管理员。")
                return

            admin_ids = [int(aid.strip()) for aid in admin_ids_str.split(',')]
            
            if user_id in admin_ids:
                return await func(update, context, *args, **kwargs)
            else:
                await update.message.reply_text("你没有权限使用此命令。")
                return
        except ValueError:
            await update.message.reply_text("管理员ID配置格式错误。")
            return
            
    return wrapped
