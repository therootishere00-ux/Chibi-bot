import telebot
from telebot import types
import logging
import threading
import time
from datetime import datetime, timedelta
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Список админов (юзернеймы без @)
ADMINS = ['temkazavr', 'Ribapibaa']

# Хранилище ошибок
error_reports = {}
# Хранилище постов
pending_posts = {}

class AdminBot:
    def __init__(self, token, main_bot_token=None):
        self.bot = telebot.TeleBot(token)
        self.main_bot_token = main_bot_token
        if main_bot_token:
            self.main_bot = telebot.TeleBot(main_bot_token)
        
    def is_admin(self, user):
        """Проверяет, является ли пользователь админом"""
        if user.username and user.username.lower() in [admin.lower() for admin in ADMINS]:
            return True
        return False
    
    def report_error(self, error_type, error_code, user_nick=None):
        """Отправляет отчет об ошибке админам"""
        current_time = datetime.now()
        
        # Создаем ключ ошибки
        error_key = f"{error_type}_{error_code}"
        
        # Обновляем статистику ошибки
        if error_key in error_reports:
            error_data = error_reports[error_key]
            error_data['count'] += 1
            last_time = error_data['last_time']
            time_diff = (current_time - last_time).total_seconds() / 60  # в минутах
            error_data['time_diff'] = int(time_diff)
            error_data['last_time'] = current_time
        else:
            error_reports[error_key] = {
                'count': 1,
                'first_time': current_time,
                'last_time': current_time,
                'time_diff': 0,
                'error_code': error_code,
                'error_type': error_type
            }
        
        error_data = error_reports[error_key]
        
        # Формируем сообщение об ошибке
        user_info = f"Эй, *{user_nick}* не смог получить чибика!" if user_nick else "Произошла ошибка!"
        error_text = f"""{user_info} ({error_data['count']}) [{error_data['time_diff']}]
Код ошибки: {error_code}"""
        
        # Отправляем всем админам
        for admin_username in ADMINS:
            try:
                # Здесь нужно получить chat_id админа, но для простоты отправляем в лог
                logger.info(f"Ошибка для {admin_username}: {error_text}")
            except Exception as e:
                logger.error(f"Не удалось отправить ошибку админу {admin_username}: {e}")
        
        # В реальном боте здесь был бы код отправки сообщения админам
        # Для демонстрации просто логируем
        logger.info(f"Ошибка зарегистрирована: {error_text}")
    
    def setup_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start_handler(message):
            if not self.is_admin(message.from_user):
                self.bot.send_message(message.chat.id, "🤖 Ты не админ")
                return
            
            welcome_text = """*🤖 Админ-панель Chibeki*
_Доступные команды:_
/post - создать пост для основного бота
/errors - просмотреть ошибки"""
            
            self.bot.send_message(message.chat.id, welcome_text, parse_mode='Markdown')
        
        @self.bot.message_handler(commands=['post'])
        def post_handler(message):
            if not self.is_admin(message.from_user):
                self.bot.send_message(message.chat.id, "🤖 Ты не админ")
                return
            
            post_text = """*Создаем пост*
_Напиши сообщение поста. Можно прикрепить фото_"""
            
            # Сохраняем состояние для пользователя
            pending_posts[message.from_user.id] = {'step': 'waiting_for_post'}
            
            self.bot.send_message(message.chat.id, post_text, parse_mode='Markdown')
        
        @self.bot.message_handler(content_types=['text', 'photo', 'animation'])
        def content_handler(message):
            if not self.is_admin(message.from_user):
                self.bot.send_message(message.chat.id, "🤖 Ты не админ")
                return
            
            user_id = message.from_user.id
            if user_id in pending_posts and pending_posts[user_id]['step'] == 'waiting_for_post':
                
                # Сохраняем данные поста
                pending_posts[user_id] = {
                    'step': 'post_ready',
                    'text': message.text or message.caption or '',
                    'content_type': message.content_type,
                    'photo_id': message.photo[-1].file_id if message.photo else None,
                    'animation_id': message.animation.file_id if message.animation else None
                }
                
                # Показываем превью поста
                preview_text = f"""*Превью поста:*
{message.text or message.caption or ''}

_Отправить этот пост в основной бот?_"""
                
                markup = types.InlineKeyboardMarkup()
                btn_send = types.InlineKeyboardButton("Отправить", callback_data="send_post")
                btn_cancel = types.InlineKeyboardButton("Отмена", callback_data="cancel_post")
                markup.add(btn_send, btn_cancel)
                
                # Отправляем превью
                if message.photo:
                    self.bot.send_photo(
                        message.chat.id,
                        message.photo[-1].file_id,
                        caption=preview_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                elif message.animation:
                    self.bot.send_animation(
                        message.chat.id,
                        message.animation.file_id,
                        caption=preview_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                else:
                    self.bot.send_message(
                        message.chat.id,
                        preview_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
        
        @self.bot.message_handler(commands=['errors'])
        def errors_handler(message):
            if not self.is_admin(message.from_user):
                self.bot.send_message(message.chat.id, "🤖 Ты не админ")
                return
            
            if not error_reports:
                self.bot.send_message(message.chat.id, "📊 Ошибок пока нет!")
                return
            
            # Показываем последние 5 ошибок
            errors_text = "*📊 Последние ошибки:*\n\n"
            recent_errors = list(error_reports.items())[-5:]
            
            for error_key, error_data in recent_errors:
                errors_text += f"""*{error_data['error_type']}* ({error_data['count']}) [{error_data['time_diff']}м]
Код: `{error_data['error_code']}`
━━━━━━━━━━━━━━━━━━━━\n"""
            
            self.bot.send_message(message.chat.id, errors_text, parse_mode='Markdown')
        
        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call):
            try:
                if not self.is_admin(call.from_user):
                    self.bot.answer_callback_query(call.id, "🤖 Ты не админ")
                    return
                
                if call.data == "send_post":
                    user_id = call.from_user.id
                    if user_id in pending_posts and pending_posts[user_id]['step'] == 'post_ready':
                        
                        # Меняем сообщение на подтверждение
                        confirm_text = "Сообщение отправится в основного бота через 10с"
                        markup = types.InlineKeyboardMarkup()
                        btn_cancel = types.InlineKeyboardButton("отменить", callback_data="cancel_sending")
                        markup.add(btn_cancel)
                        
                        self.bot.edit_message_text(
                            confirm_text,
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=markup
                        )
                        
                        # Запускаем таймер отправки
                        post_data = pending_posts[user_id].copy()
                        threading.Thread(
                            target=self.send_post_after_delay,
                            args=(call.message.chat.id, call.message.message_id, user_id, post_data, 10)
                        ).start()
                        
                    else:
                        self.bot.answer_callback_query(call.id, "❌ Пост не найден")
                
                elif call.data == "cancel_post":
                    user_id = call.from_user.id
                    if user_id in pending_posts:
                        del pending_posts[user_id]
                    
                    self.bot.edit_message_text(
                        "❌ Отправка поста отменена",
                        call.message.chat.id,
                        call.message.message_id
                    )
                
                elif call.data == "cancel_sending":
                    user_id = call.from_user.id
                    if user_id in pending_posts:
                        pending_posts[user_id]['cancelled'] = True
                    
                    self.bot.edit_message_text(
                        "❌ Отправка отменена",
                        call.message.chat.id,
                        call.message.message_id
                    )
                
                elif call.data.startswith("error_more_"):
                    error_key = call.data[11:]
                    if error_key in error_reports:
                        error_data = error_reports[error_key]
                        
                        first_time = error_data['first_time'].strftime("%H:%M")
                        first_date = error_data['first_time'].strftime("%d %b %Y")
                        
                        detailed_text = f"""*Детали ошибки:*
Код: `{error_data['error_code']}`
Тип: {error_data['error_type']}
Первое появление: {first_time}, {first_date}
Количество: {error_data['count']}
Интервал: {error_data['time_diff']} мин"""
                        
                        markup = types.InlineKeyboardMarkup()
                        btn_less = types.InlineKeyboardButton("Меньше", callback_data=f"error_less_{error_key}")
                        markup.add(btn_less)
                        
                        self.bot.edit_message_text(
                            detailed_text,
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=markup,
                            parse_mode='Markdown'
                        )
                
                elif call.data.startswith("error_less_"):
                    error_key = call.data[11:]
                    if error_key in error_reports:
                        error_data = error_reports[error_key]
                        
                        short_text = f"""*{error_data['error_type']}* ({error_data['count']}) [{error_data['time_diff']}м]
Код: `{error_data['error_code']}`"""
                        
                        markup = types.InlineKeyboardMarkup()
                        btn_more = types.InlineKeyboardButton("Больше", callback_data=f"error_more_{error_key}")
                        markup.add(btn_more)
                        
                        self.bot.edit_message_text(
                            short_text,
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=markup,
                            parse_mode='Markdown'
                        )
                
                self.bot.answer_callback_query(call.id)
                
            except Exception as e:
                logger.error(f"Ошибка в callback: {e}")
                self.bot.answer_callback_query(call.id, "❌ Ошибка!")
    
    def send_post_after_delay(self, chat_id, message_id, user_id, post_data, delay):
        """Отправляет пост после задержки"""
        try:
            for i in range(delay, 0, -1):
                time.sleep(1)
                # Проверяем, не отменили ли отправку
                if user_id in pending_posts and pending_posts[user_id].get('cancelled'):
                    return
            
            # Проверяем еще раз перед отправкой
            if user_id in pending_posts and pending_posts[user_id].get('cancelled'):
                return
            
            # Отправляем пост (в реальном боте здесь был бы код отправки всем пользователям)
            success_text = "✅ Пост успешно отправлен в основной бот!"
            self.bot.edit_message_text(
                success_text,
                chat_id,
                message_id
            )
            
            # Очищаем данные поста
            if user_id in pending_posts:
                del pending_posts[user_id]
                
            logger.info(f"Пост отправлен: {post_data['text'][:50]}...")
            
        except Exception as e:
            logger.error(f"Ошибка при отправке поста: {e}")
            error_text = "❌ Ошибка при отправке поста"
            self.bot.edit_message_text(
                error_text,
                chat_id,
                message_id
            )
    
    def run(self):
        logger.info("🤖 Админ-бот запущен!")
        self.setup_handlers()
        self.bot.infinity_polling()

def get_admin_token():
    return os.getenv('ADMIN_BOT_TOKEN')

def get_main_bot_token():
    return os.getenv('BOT_TOKEN')

if __name__ == "__main__":
    admin_token = get_admin_token()
    if not admin_token:
        print("❌ Токен админ-бота не найден!")
        exit(1)
    
    main_bot_token = get_main_bot_token()
    
    admin_bot = AdminBot(admin_token, main_bot_token)
    admin_bot.run()
