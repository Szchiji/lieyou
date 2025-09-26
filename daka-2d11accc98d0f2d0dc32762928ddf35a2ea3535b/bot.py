import os
from telegram.ext import Application
from handlers import register as register_handlers

TOKEN = os.getenv("TELEGRAM_TOKEN") or "YOUR_BOT_TOKEN"

def main():
    application = Application.builder().token(TOKEN).build()
    register_handlers(application)
    print("Bot started!")
    application.run_polling()  # Render推荐写法

if __name__ == "__main__":
    main()
