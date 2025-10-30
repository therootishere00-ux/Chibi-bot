import logging
from telegram.ext import Application, CommandHandler
from config import BOT_TOKEN
from handlers import start_handler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def setup_handlers(application: Application) -> None:
    """Настройка обработчиков команд"""
    application.add_handler(CommandHandler("start", start_handler))

def main() -> None:
    """Основная функция запуска бота"""
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN не установлен в переменных окружения")
    
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Настраиваем обработчики
    setup_handlers(application)
    
    # Запускаем бота
    logger.info("Бот запущен")
    application.run_polling()

if __name__ == "__main__":
    main()
