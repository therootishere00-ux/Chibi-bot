from telegram import Update
from telegram.ext import ContextTypes
from config import START_STICKER_ID
from texts import get_start_message

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user = update.effective_user
    
    # Отправляем стикер
    await update.message.reply_sticker(sticker=START_STICKER_ID)
    
    # Отправляем текстовое сообщение
    welcome_text = get_start_message(user.first_name)
    await update.message.reply_text(welcome_text, parse_mode='Markdown')
