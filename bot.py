import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Токен бота (будет браться из переменных окружения)
BOT_TOKEN = os.getenv('BOT_TOKEN')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    first_name = user.first_name or 'друг'
    
    # Отправляем стикер
    sticker_id = "CAACAgIAAxkBAAE9JsNpAzQZv6b4b-KZ3ftL2Sld0kUjDQAC400AAkuWEEosjitzZk8fzDYE"
    await update.message.reply_sticker(sticker=sticker_id)
    
    # Отправляем текстовое сообщение
    welcome_text = f"""⚡️*Хей, {first_name}!*
Вижу, ты новичок у нас? Что ж, вероятно ты здесь, потому что любишь коллекционировать ЧИБИКОВ, да?
Будем считать, _что я угадал_. В любом случае, раз ты тут впервые, я тебя задобрю, и это ни в коем случае не чтобы ты тут подольше остался, даже не думай! Я очень щедр, и начислю тебе целый 🧧 *ЧИБИ-ПАК!* Ты можешь найти и открыть его в меню, и получить своего первого ЧИБИКА. Также советую ознакомиться с остальными _командами бота_, ты тут надолго и они тебе точно пригодятся! Удачного пути, и хороших *ЧИБИКОВ!*"""
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

def main():
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN не установлен!")
        return
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Добавляем обработчик команды /start
    application.add_handler(CommandHandler("start", start))
    
    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
