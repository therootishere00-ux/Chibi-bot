import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get('BOT_TOKEN')
STICKER_FILE_ID = "CAACAgIAAxkBAAE9JsNpAzQZv6b4b-KZ3ftL2Sld0kUjDQAC400AAkuWEEosjitzZk8fzDYE"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    try:
        user = update.effective_user
        user_name = user.first_name if user.first_name else "путешественник"
        
        # Отправляем стикер
        await update.message.reply_sticker(sticker=STICKER_FILE_ID)
        
        # Отправляем текстовое сообщение
        welcome_text = f"""⚡️*Хей, {user_name}!*

Вижу, ты новичок у нас? Что ж, вероятно ты здесь, потому что любишь коллекционировать ЧИБИКОВ, да?
Будем считать, _что я угадал_. В любом случае, раз ты тут впервые, я тебя задобрю, и это ни в коем случае не чтобы ты тут подольше остался, даже не думай! Я очень щедр, и начислю тебе целый 🧧 *ЧИБИ-ПАК!* Ты можешь найти и открыть его в меню, и получить своего первого ЧИБИКА. Также советую ознакомиться с остальными _командами бота_, ты тут надолго и они тебе точно пригодятся! Удачного пути, и хороших *ЧИБИКОВ!*"""
        
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown'
        )
        
        logger.info(f"New user started: {user.id} - {user_name}")
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка. Попробуйте позже.")

def start_bot():
    """Функция запуска бота"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is not set!")
        return None
    
    try:
        # Создаем приложение
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Регистрируем обработчики
        application.add_handler(CommandHandler("start", start))
        
        return application
    except Exception as e:
        logger.error(f"Failed to create bot application: {e}")
        return None
