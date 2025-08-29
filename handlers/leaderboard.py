import logging
import math
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import db_transaction
from html import escape

logger = logging.getLogger(__name__)
PAGE_SIZE = 10
leaderboard_cache = {}

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE, board_type: str, page: int = 1):
    """
    Displays the leaderboard using a robust HTML format to ensure stability.
    The pagination is always preserved.
    """
    is_callback = update.callback_query is not None
    
    try:
        # --- 获取缓存设置 ---
        async with db_transaction() as conn:
            ttl_row = await conn.fetchrow("SELECT value FROM settings WHERE key = 'leaderboard_cache_ttl'")
        cache_ttl = int(ttl_row['value']) if ttl_row else 300
        
        cache_key = f"{board_type}_{page}"
        current_time = time.time()

        if cache_key in leaderboard_cache and current_time - leaderboard_cache[cache_key]['timestamp'] < cache_ttl:
            cached_data = leaderboard_cache[cache_key]['data']
            logger.info(f"命中排行榜缓存: {cache_key}")
            if is_callback:
                await update.callback_query.edit_message_text(**cached_data)
            else:
                await update.message.reply_text(**cached_data)
            return
        
        logger.info(f"未命中排行榜缓存，正在从数据库生成: {cache_key}")
        async with db_transaction() as conn:
            # --- 法则修订 III: 命名变更 ---
            title_text = "红榜" if board_type == 'top' else "黑榜"
            title_icon = "🏆" if board_type == 'top' else "☠️"
            order_col = "recommend_count" if board_type == 'top' else "block_count"
            count_col_name = "推荐" if board_type == 'top' else "拉黑"
            
            total_record = await conn.fetchrow(f"SELECT COUNT(*) FROM reputation_profiles WHERE {order_col} > 0")
            profiles = await conn.fetch(f"SELECT username, {order_col} FROM reputation_profiles WHERE {order_col} > 0 ORDER BY {order_col} DESC, username ASC LIMIT {PAGE_SIZE} OFFSET {(page - 1) * PAGE_SIZE}")

        total_profiles = total_record['count']
        total_pages = math.ceil(total_profiles / PAGE_SIZE) if total_profiles > 0 else 1
        
        # --- 使用稳定可靠的 HTML 格式 ---
        text_lines = [f"<b>{title_icon} {escape(title_text)} {title_icon}</b>"]
        
        if not profiles:
            text_lines.append("\n这个排行榜是空的。")
        else:
            # 使用 <code> 标签来模拟等宽字体，并手动添加空格进行对齐
            text_lines.append("\n<pre>排名  | 用户             | 次数</pre>")
            text_lines.append("<pre>------+------------------+------</pre>")
            start_num = (page - 1) * PAGE_SIZE
            for i, p in enumerate(profiles):
                rank = i + start_num + 1
                # 使用 escape() 来确保用户名的绝对安全
                username = escape(f"@{p['username']}")
                count = p[order_col]
                
                # 手动进行左对齐填充
                rank_str = str(rank).ljust(5)
                username_str = username.ljust(16)
                count_str = str(count).ljust(4)
                
                line = f"<pre>{rank_str} | {username_str} | {count_str}</pre>"
                text_lines.append(line)

        text = "\n".join(text_lines)
        
        # --- 翻页按钮将永远存在 ---
        keyboard = []
        page_row = []
        if page > 1: page_row.append(InlineKeyboardButton("⬅️ 上页", callback_data=f"leaderboard_{board_type}_{page - 1}"))
        page_row.append(InlineKeyboardButton(f" {page}/{total_pages} ", callback_data="leaderboard_noop"))
        if page < total_pages: page_row.append(InlineKeyboardButton("下页 ➡️", callback_data=f"leaderboard_{board_type}_{page + 1}"))
        if page_row: keyboard.append(page_row)
        
        keyboard.append([InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_help")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 明确指定使用 HTML 解析模式
        message_data = {'text': text, 'reply_markup': reply_markup, 'parse_mode': 'HTML'}
        leaderboard_cache[cache_key] = {'timestamp': current_time, 'data': message_data}
        
        if is_callback:
            try:
                await update.callback_query.edit_message_text(**message_data)
            except Exception as e:
                # 如果因为消息未改变而报错，则忽略
                if "Message is not modified" not in str(e):
                    raise e
        else:
            await update.message.reply_text(**message_data)

    except Exception as e:
        logger.error(f"生成排行榜时出错: {e}", exc_info=True)
        error_message = "生成排行榜时发生错误，请稍后再试。"
        try:
            if is_callback:
                await update.callback_query.answer(error_message, show_alert=True)
            else:
                await update.message.reply_text(error_message)
        except:
            pass
