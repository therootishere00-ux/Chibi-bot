import os
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

def get_random_chibi_image():
    """Получает случайную картинку из папок chibis"""
    base_path = "chibi-bot/chibis"
    folders = ["common", "secret"]
    
    all_images = []
    for folder in folders:
        folder_path = os.path.join(base_path, folder)
        if os.path.exists(folder_path):
            images = [f for f in os.listdir(folder_path) 
                     if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
            all_images.extend([(folder, img) for img in images])
    
    if not all_images:
        return None, None
    
    folder, image_name = random.choice(all_images)
    image_path = os.path.join(base_path, folder, image_name)
    return image_path, image_name

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    # Правильный File ID стикера 👋 из CrayonsEmojiPack
    sticker_file_id = "CAACAgIAAxkBAAE9JsNpAzQZv6b4b-KZ3ftL2Sld0kUjDQAC400AAkuWEEosjitzZk8fzDYE"
    
    try:
        await update.message.reply_sticker(sticker=sticker_file_id)
    except Exception as e:
        logging.error(f"Ошибка отправки стикера: {e}")
        await update.message.reply_text("👋")
    
    # Создаем инлайн-кнопку
    keyboard = [
        [InlineKeyboardButton("Наш тгк", url="https://t.me/chibeki_official")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = f"""⚡️*Хей, {user.first_name}!*
Вижу, ты новичок у нас? Что ж, вероятно ты здесь, потому что любишь коллекционировать ЧИБИКОВ, да?
Будем считать, _что я угадал_. В любом случае, раз ты тут впервые, я тебя задобрю, и это ни в коем случае не чтобы ты тут подольше остался, даже не думай! Я очень щедр, и начислю тебе целый 🧧 *ЧИБИ-ПАК!* Ты можешь найти и открыть его в меню, и получить своего первого ЧИБИКА. Также советую ознакомиться с остальными _командами бота_, ты тут надолго и они тебе точно пригодятся! Удачного пути, и хороших *ЧИБИКОВ!*"""
    
    try:
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения: {e}")

async def chibi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /chibi - возвращает случайную картинку чибика"""
    image_path, image_name = get_random_chibi_image()
    
    if not image_path or not os.path.exists(image_path):
        await update.message.reply_text("❌ Чибики временно спят... Попробуй позже!")
        return
    
    # Определяем действие по названию папки
    folder = os.path.basename(os.path.dirname(image_path))
    action = "залутал" if folder == "secret" else "выбил"
    
    # Убираем расширение файла для красивого названия
    name_without_ext = os.path.splitext(image_name)[0]
    
    caption = f"""⚡️*Ты {action} {name_without_ext}!*

_Надеюсь ты доволен. В любом случае, возвращайся через 3ч 59м_"""
    
    try:
        with open(image_path, 'rb') as photo:
            await update.message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode='Markdown'
            )
    except Exception as e:
        logging.error(f"Ошибка отправки картинки: {e}")
        await update.message.reply_text("❌ Ошибка загрузки чибика!")

def main() -> None:
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise ValueError("BOT_TOKEN не установлен")
    
    application = Application.builder().token(token).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("chibi", chibi))
    
    # Добавляем обработчик ошибок
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logging.error(f"Exception while handling an update: {context.error}")
    
    application.add_error_handler(error_handler)
    
    # Запускаем Flask в отдельном потоке
    from threading import Thread
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)).start()
    
    # Запускаем бота
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
