import os
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from flask import Flask

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Flask app для веб-сервера
app = Flask(__name__)

# Временное хранилище лавок (в реальном проекте используй БД)
user_shops = {}
shop_creation_data = {}

# Список эмодзи для лавок
SHOP_EMOJIS = ["💀", "🤖", "🤡", "🥵", "🔥", "✨", "⚡️", "⭐️", "🎭", "🏵️", "🐸", "🐾", "🦅", "🐙", "🐳", "👀", "👙", "🌵", "🐲", "🐉", "⛄️", "☃️", "🐊"]

@app.route('/')
def home():
    return "Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    
    sticker_file_id = "CAACAgIAAxkBAAE9JsNpAzQZv6b4b-KZ3ftL2Sld0kUjDQAC400AAkuWEEosjitzZk8fzDYE"
    
    try:
        await update.message.reply_sticker(sticker=sticker_file_id)
    except Exception as e:
        logging.error(f"Ошибка отправки стикера: {e}")
        await update.message.reply_text("👋")
    
    welcome_text = f"""⚡️*Хей, {user.first_name}!*
Вижу, ты новичок у нас? Что ж, вероятно ты здесь, потому что любишь коллекционировать ЧИБИКОВ, да?
Будем считать, _что я угадал_. В любом случае, раз ты тут впервые, я тебя задобрю, и это ни в коем случае не чтобы ты тут подольше остался, даже не думай! Я очень щедр, и начислю тебе целый 🧧 *ЧИБИ-ПАК!* Ты можешь найти и открыть его в меню, и получить своего первого ЧИБИКА. Также советую ознакомиться с остальными _командами бота_, ты тут надолго и они тебе точно пригодятся! Удачного пути, и хороших *ЧИБИКОВ!*"""
    
    keyboard = [
        [InlineKeyboardButton("Наш тгк", url="https://t.me/chibeki_official")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await update.message.reply_text(
            welcome_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    except Exception as e:
        logging.error(f"Ошибка отправки сообщения: {e}")

async def mart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    mart_text = """🛍️ *Рынок нижних уровней* 
_Здесь нет четких цен, игроки сами в праве задавать их_"""
    
    # Получаем лавки пользователя
    user_shop = user_shops.get(user_id)
    
    keyboard = []
    
    # Добавляем лавку пользователя сверху если есть
    if user_shop:
        keyboard.append([InlineKeyboardButton(f"{user_shop['emoji']} {user_shop['name']}", callback_data="my_shop")])
    
    keyboard.append([InlineKeyboardButton("Квикшоп 👽", callback_data="quickshop")])
    keyboard.append([
        InlineKeyboardButton("◀️", callback_data="page_prev"),
        InlineKeyboardButton("Создать лавку", callback_data="create_shop"),
        InlineKeyboardButton("▶️", callback_data="page_next")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        mart_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def create_shop_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    
    # Генерируем случайный эмодзи для начала
    random_emoji = random.choice(SHOP_EMOJIS)
    shop_creation_data[user_id] = {"emoji": random_emoji}
    
    shop_creation_text = """*🛍️ Создание лавки* 
_Укажи название, ответом на это сообщение. Без пробелов и лишних символов_"""
    
    keyboard = [
        [
            InlineKeyboardButton(random_emoji, callback_data="change_emoji"),
            InlineKeyboardButton("Создать", callback_data="confirm_create_shop")
        ],
        [InlineKeyboardButton("Назад", callback_data="back_to_mart")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        shop_creation_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def change_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    
    # Меняем эмодзи на случайный
    if user_id in shop_creation_data:
        new_emoji = random.choice(SHOP_EMOJIS)
        shop_creation_data[user_id]["emoji"] = new_emoji
        
        shop_creation_text = """*🛍️ Создание лавки* 
_Укажи название, ответом на это сообщение. Без пробелов и лишних символов_"""
        
        keyboard = [
            [
                InlineKeyboardButton(new_emoji, callback_data="change_emoji"),
                InlineKeyboardButton("Создать", callback_data="confirm_create_shop")
            ],
            [InlineKeyboardButton("Назад", callback_data="back_to_mart")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            shop_creation_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    await query.answer()

async def confirm_create_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    
    if user_id not in shop_creation_data or "name" not in shop_creation_data[user_id]:
        await query.answer("❌ Сначала укажи название лавки!", show_alert=True)
        return
    
    await query.answer()
    await finish_shop_creation(query, user_id)

async def handle_shop_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    shop_name = update.message.text.strip()
    
    # Проверяем название
    if not shop_name or " " in shop_name or len(shop_name) > 20:
        await update.message.reply_text("❌ *Название невалидно!*\n_Без пробелов, максимум 20 символов_", parse_mode='Markdown')
        return
    
    if user_id in shop_creation_data:
        shop_creation_data[user_id]["name"] = shop_name
        
        # Отправляем подтверждение создания
        emoji = shop_creation_data[user_id]["emoji"]
        confirmation_text = f"""*🛍️ Создание лавки* 
_Название: {shop_name}_
_Эмодзи: {emoji}_

✅ *Готово! Нажми \"Создать\" для завершения*"""
        
        keyboard = [
            [
                InlineKeyboardButton(emoji, callback_data="change_emoji"),
                InlineKeyboardButton("Создать", callback_data="confirm_create_shop")
            ],
            [InlineKeyboardButton("Назад", callback_data="back_to_mart")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            confirmation_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

async def finish_shop_creation(query, user_id):
    if user_id in shop_creation_data and "name" in shop_creation_data[user_id]:
        shop_data = shop_creation_data[user_id]
        
        # Сохраняем лавку
        user_shops[user_id] = {
            "name": shop_data["name"],
            "emoji": shop_data["emoji"]
        }
        
        # Удаляем сообщение создания
        await query.delete_message()
        
        # Отправляем стикер
        sticker_file_id = "CAACAgIAAxkBAAE9Js9pAzTWs9gLLtl9Gqz_9V_4sbwXqgAC7EYAAjNREEqhVSL_nxyHZTYE"
        await query.bot.send_sticker(chat_id=query.message.chat_id, sticker=sticker_file_id)
        
        # Отправляем сообщение об успехе
        success_text = """🎉 *Ура! Ты создал лавку!*
_Открой ее в */mart* и настрой товары, если есть что продавать!_"""
        
        keyboard = [[InlineKeyboardButton("Перейти к лавке", callback_data="back_to_mart")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.bot.send_message(
            chat_id=query.message.chat_id,
            text=success_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
        
        # Очищаем временные данные
        if user_id in shop_creation_data:
            del shop_creation_data[user_id]

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data == "quickshop":
        await query.edit_message_text(text="👽 Квикшоп пока в разработке...")
    elif callback_data == "create_shop":
        await create_shop_start(update, context)
    elif callback_data == "change_emoji":
        await change_emoji(update, context)
    elif callback_data == "confirm_create_shop":
        await confirm_create_shop(update, context)
    elif callback_data == "back_to_mart":
        await mart_callback(update, context)
    elif callback_data == "my_shop":
        await query.edit_message_text(text="🏪 Твоя лавка пока пуста...")
    elif callback_data in ["page_prev", "page_next"]:
        await query.answer(text="📄 Навигация пока не работает", show_alert=False)

async def mart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    
    mart_text = """🛍️ *Рынок нижних уровней* 
_Здесь нет четких цен, игроки сами в праве задавать их_"""
    
    # Получаем лавки пользователя
    user_shop = user_shops.get(user_id)
    
    keyboard = []
    
    # Добавляем лавку пользователя сверху если есть
    if user_shop:
        keyboard.append([InlineKeyboardButton(f"{user_shop['emoji']} {user_shop['name']}", callback_data="my_shop")])
    
    keyboard.append([InlineKeyboardButton("Квикшоп 👽", callback_data="quickshop")])
    keyboard.append([
        InlineKeyboardButton("◀️", callback_data="page_prev"),
        InlineKeyboardButton("Создать лавку", callback_data="create_shop"),
        InlineKeyboardButton("▶️", callback_data="page_next")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        mart_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

def main() -> None:
    token = os.getenv('BOT_TOKEN')
    if not token:
        raise ValueError("BOT_TOKEN не установлен")
    
    application = Application.builder().token(token).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("mart", mart))
    
    # Добавляем обработчик инлайн-кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Добавляем обработчик текстовых сообщений (для названия лавки)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_shop_name))
    
    # Добавляем обработчик ошибок
    async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        logging.error(f"Exception while handling an update: {context.error}")
    
    application.add_error_handler(error_handler)
    
    # Запускаем Flask в отдельном потоке
    from threading import Thread
    Thread(target=lambda: app.run(host='0.0.0.0', port=8080, debug=False)).start()
    
    # Запускаем бота с очисткой обновлений
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False
    )

if __name__ == '__main__':
    main()
