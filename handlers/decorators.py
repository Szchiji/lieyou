import os
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

def restricted_to_group(func):
    """
    一个装饰器，用于将命令的执行限制在指定的群组中。
    """
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        # 私聊中的 /list, /leaderboard, /profile 应该被允许
        if update.effective_chat.type == 'private':
             # /hunt 和 /trap 必须在群里回复，所以它们天然不会在私聊中误触发
            if func.__name__ in ['list_prey', 'leaderboard', 'profile']:
                 return await func(update, context, *args, **kwargs)

        try:
            allowed_group_ids_str = os.environ.get("ALLOWED_GROUP_IDS", "")
            if not allowed_group_ids_str:
                print("警告: ALLOWED_GROUP_IDS 环境变量未设置，机器人将在任何群组响应。")
                return await func(update, context, *args, **kwargs)

            allowed_group_ids = [int(gid.strip()) for gid in allowed_group_ids_str.split(',')]
            
            if update.effective_chat.id in allowed_group_ids:
                return await func(update, context, *args, **kwargs)
            else:
                print(f"命令在不允许的群组 {update.effective_chat.id} 中被忽略。")
                return
        except ValueError:
            print("错误: ALLOWED_GROUP_IDS 环境变量格式不正确，应为逗号分隔的数字ID。")
            return
            
    return wrapped

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
