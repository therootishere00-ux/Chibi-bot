import os
import threading
import time
import logging
from webserver import run_web_server
from bot import main as run_bot

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def run_bot_wrapper():
    """Обертка для запуска бота с перезапуском при ошибках"""
    while True:
        try:
            logger.info("Starting Telegram bot...")
            run_bot()
        except Exception as e:
            logger.error(f"Bot crashed with error: {e}")
            logger.info("Restarting bot in 10 seconds...")
            time.sleep(10)

if __name__ == "__main__":
    # Запускаем веб-сервер в отдельном потоке
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    logger.info("Web server started on port 8080")
    
    # Запускаем бота в основном потоке
    run_bot_wrapper()
