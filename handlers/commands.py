from telegram import Update
from telegram.ext import ContextTypes
from data.texts import START_STICKER, START_MESSAGE

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    user = update.effective_user
    
    # Отправляем стикер
    await update.message.reply_sticker(sticker=START_STICKER)
    
    # Отправляем текстовое сообщение
    welcome_text = START_MESSAGE.format(name=user.first_name)
    await update.message.reply_text(welcome_text, parse_mode='Markdown')
