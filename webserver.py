from flask import Flask
import threading
import time
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/')
def home():
    """Главная страница для health checks"""
    return "🤖 Bot is alive and running!"

@app.route('/health')
def health():
    """Эндпоинт для проверки здоровья"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "service": "chibi-telegram-bot"
    }

@app.route('/ping')
def ping():
    """Эндпоинт для пинга"""
    return "pong"

def run_web_server():
    """Запуск веб-сервера"""
    try:
        port = int(os.environ.get('PORT', 8080))
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Web server error: {e}")

if __name__ == "__main__":
    run_web_server()
