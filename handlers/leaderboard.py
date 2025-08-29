import logging
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_cursor

logger = logging.getLogger(__name__)

PAGE_SIZE = 10  # 定义每页显示10个用户

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    """
    一个统一的、支持分页的排行榜生成函数。
    :param update: Telegram 的 Update 对象。
    :param context: Telegram 的 Context 对象。
    :param board_type: 'top' (红榜) 或 'bottom' (黑榜)。
    :param page: 要显示的页码。
    """
    is_callback = update.callback_query is not None
    
    try:
        async with db_cursor() as cur:
            if board_type == 'top':
                title = "🏆 推荐榜 🏆"
                order_col = "recommend_count"
                count_col_name = "次推荐"
                # 查询总人数
                total_users_record = await cur.fetchrow(f"SELECT COUNT(*) FROM users WHERE {order_col} > 0")
                # 查询当页数据
                users = await cur.fetch(f"""
                    SELECT full_name, username, {order_col} FROM users 
                    WHERE {order_col} > 0 
                    ORDER BY {order_col} DESC, id ASC
                    LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}
                """)
            else: # 'bottom'
                title = "☠️ 拉黑榜 ☠️"
                order_col = "block_count"
                count_col_name = "次拉黑"
                # 查询总人数
                total_users_record = await cur.fetchrow(f"SELECT COUNT(*) FROM users WHERE {order_col} > 0")
                # 查询当页数据
                users = await cur.fetch(f"""
                    SELECT full_name, username, {order_col} FROM users 
                    WHERE {order_col} > 0 
                    ORDER BY {order_col} DESC, id ASC
                    LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}
                """)

            total_users = total_users_record['count']
            total_pages = math.ceil(total_users / PAGE_SIZE) if total_users > 0 else 1

            # --- 构建消息文本 ---
            text = f"{title}\n\n"
            if not users:
                text += "这个排行榜是空的。"
            else:
                start_num = (page - 1) * PAGE_SIZE + 1
                text += "\n".join([f"{i + start_num}. {u['full_name']} (@{u['username']}) - {u[order_col]} {count_col_name}" for i, u in enumerate(users)])

            # --- 构建分页按钮 ---
            keyboard = []
            row = []
            if page > 1:
                row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"leaderboard_{board_type}_{page - 1}"))
            
            row.append(InlineKeyboardButton(f"第 {page}/{total_pages} 页", callback_data="leaderboard_noop")) # noop = 无操作
            
            if page < total_pages:
                row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"leaderboard_{board_type}_{page + 1}"))
            
            if row:
                keyboard.append(row)

            reply_markup = InlineKeyboardMarkup(keyboard)

            # --- 发送或编辑消息 ---
            if is_callback:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"生成排行榜时出错: {e}", exc_info=True)
        if is_callback:
            await update.callback_query.answer("生成排行榜时出错，请稍后再试。", show_alert=True)
        else:
            await update.message.reply_text("生成排行榜时出错，请稍后再试。")


# --- 命令处理函数现在变得非常简单 ---
async def get_top_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """命令入口：/top 或 /红榜"""
    await show_leaderboard(update, context, board_type='top', page=1)

async def get_bottom_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """命令入口：/bottom 或 /黑榜"""
    await show_leaderboard(update, context, board_type='bottom', page=1)
