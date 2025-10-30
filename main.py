import os
import threading
import time
import logging
from webserver import run_web_server
from bot import start_bot

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def run_bot():
    """Запуск бота с перезапуском при ошибках"""
    while True:
        try:
            logger.info("Starting Telegram bot...")
            application = start_bot()
            
            if application:
                application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
            else:
                logger.error("Failed to create bot application, retrying in 10 seconds...")
                time.sleep(10)
                
        except Exception as e:
            logger.error(f"Bot crashed with error: {e}")
            logger.info("Restarting bot in 10 seconds...")
            time.sleep(10)

if __name__ == "__main__":
    # Запускаем веб-сервер в отдельном потоке
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    logger.info("Web server started")
    
    # Запускаем бота в основном потоке
    run_bot()
