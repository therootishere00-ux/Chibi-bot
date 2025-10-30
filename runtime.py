from telegram.ext import Application, CommandHandler
from config import Config
from handlers import start_command

def setup_handlers(application: Application) -> None:
    """Настройка обработчиков команд"""
    application.add_handler(CommandHandler("start", start_command))

def create_application() -> Application:
    """Создание и настройка приложения"""
    application = Application.builder().token(Config.BOT_TOKEN).build()
    setup_handlers(application)
    return application

def run_polling() -> None:
    """Запуск бота в режиме polling"""
    application = create_application()
    print("Бот запущен в режиме polling...")
    application.run_polling()
