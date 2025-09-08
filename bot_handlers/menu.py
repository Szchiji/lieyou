import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database

logger = logging.getLogger(__name__)

async def private_menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles callbacks from the private main menu."""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    if action == 'menu_my_report':
        from .reports import generate_my_report
        await generate_my_report(update, context)
    elif action == 'menu_leaderboard':
        await show_leaderboard_callback_handler(update, context)
    elif action == 'show_private_main_menu':
        from .start import show_private_main_menu
        await show_private_main_menu(update, context)
    else:
        await query.edit_message_text(f"功能 '{action}' 正在开发中。")

async def show_leaderboard_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the leaderboard type selection menu."""
    query = update.callback_query
    if query:
        await query.answer()

    keyboard = [
        [InlineKeyboardButton("信誉分排行榜", callback_data='leaderboard_rep')],
        [InlineKeyboardButton("返回主菜单", callback_data='show_private_main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = "🏆 *排行榜*\n\n请选择您想查看的榜单类型："
    
    if query:
        await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

async def leaderboard_type_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetches and displays the selected leaderboard."""
    query = update.callback_query
    await query.answer()
    
    board_type = query.data.split('_')[1]
    
    if board_type == 'rep':
        try:
            leaderboard_data = await database.db_fetch_all("""
                SELECT u.username, SUM(re.change) as total_score
                FROM reputation_events re
                JOIN users u ON re.target_user_id = u.id
                WHERE u.is_hidden = FALSE AND u.username IS NOT NULL
                GROUP BY u.username
                HAVING SUM(re.change) IS NOT NULL
                ORDER BY total_score DESC
                LIMIT 10;
            """)
            
            title = "信誉分排行榜"
            if not leaderboard_data:
                leaderboard_text = "目前还没有人获得信誉分。"
            else:
                leaderboard_text = "\n".join(
                    [f"{i+1}. @{row['username']} - {int(row['total_score'])}分" for i, row in enumerate(leaderboard_data)]
                )
        except Exception as e:
            logger.error(f"Error fetching reputation leaderboard: {e}", exc_info=True)
            leaderboard_text = "获取排行榜数据时出错。"
            title = "错误"
    else:
        await query.edit_message_text("此排行榜类型暂不可用。")
        return

    full_text = f"🏆 *{title}*\n\n{leaderboard_text}"
    
    keyboard = [[InlineKeyboardButton("返回", callback_data='menu_leaderboard')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(full_text, reply_markup=reply_markup, parse_mode='Markdown')
