import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
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
    
    # Создаем инлайн-кнопку для канала
    keyboard = [
        [InlineKeyboardButton("Наш тгк", url="https://t.me/chibeki_official")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения: {e}")

async def mart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mart_text = """🛍️ *Рынок нижних уровней* 
_Здесь нет четких цен, игроки сами в праве задавать их_"""
    
    # Создаем клавиатуру для команды /mart
    keyboard = [
        [InlineKeyboardButton("Квикшоп 👽", callback_data="quickshop")],
        [
            InlineKeyboardButton("◀️", callback_data="page_prev"),
            InlineKeyboardButton("Создать лавку", callback_data="create_shop"),
            InlineKeyboardButton("▶️", callback_data="page_next")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        mart_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data == "quickshop":
        await query.edit_message_text(text="👽 Квикшоп пока в разработке...")
    elif callback_data == "create_shop":
        await query.edit_message_text(text="🛒 Функция создания лавки пока в разработке...")
    elif callback_data == "page_prev":
        await query.answer(text="⬅️ Предыдущая страница", show_alert=False)
    elif callback_data == "page_next":
        await query.answer(text="➡️ Следующая страница", show_alert=False)

def main() -> None:
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise ValueError("BOT_TOKEN не установлен")
    
    application = Application.builder().token(token).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mart", mart))
    
    # Добавляем обработчик инлайн-кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
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
