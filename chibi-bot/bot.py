import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Flask app для веб-сервера
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Правильный File ID стикера 👋 из CrayonsEmojiPack
    sticker_file_id = "CAACAgIAAxkBAAE9JsNpAzQZv6b4b-KZ3ftL2Sld0kUjDQAC400AAkuWEEosjitzZk8fzDYE"
    
    try:
        await update.message.reply_sticker(sticker=sticker_file_id)
    except Exception as e:
        logging.error(f"Ошибка отправки стикера: {e}")
        # Fallback на эмодзи если стикер не работает
        await update.message.reply_text("👋")
    
    welcome_text = f"""⚡️*Хей, {user.first_name}!*
Вижу, ты новичок у нас? Что ж, вероятно ты здесь, потому что любишь коллекционировать ЧИБИКОВ, да?
Будем считать, _что я угадал_. В любом случае, раз ты тут впервые, я тебя задобрю, и это ни в коем случае не чтобы ты тут подольше остался, даже не думай! Я очень щедр, и начислю тебе целый 🧧 *ЧИБИ-ПАК!* Ты можешь найти и открыть его в меню, и получить своего первого ЧИБИКА. Также советую ознакомиться с остальными _командами бота_, ты тут надолго и они тебе точно пригодятся! Удачного пути, и хороших *ЧИБИКОВ!*"""
    
    try:
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения: {e}")

def main() -> None:
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise ValueError("BOT_TOKEN не установлен")
    
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    
    # Добавляем обработчик ошибок
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        logging.error(f"Exception while handling an update: {context.error}")
    
    application.add_error_handler(error_handler)
    
    # Запускаем Flask в отдельном потоке
    from threading import Thread
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080, debug=False)).start()
    
    # Запускаем бота с очисткой обновлений
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,  # Очищает очередь при старте
        close_loop=False
    )

if __name__ == '__main__':
    main()
