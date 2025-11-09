import telebot
from telebot import types
import random
import string
import os
import logging
import threading
import time
from flask import Flask
from datetime import datetime, timedelta
from pymongo import MongoClient
from bson import ObjectId

from config import BOT_CONFIG, BOT_TEXTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChibiBot:
    def __init__(self, token):
        self.bot = telebot.TeleBot(token)
        
        # Подключение к MongoDB
        self.mongo_uri = os.getenv('MONGODB_URI')
        if not self.mongo_uri:
            logger.error("MONGODB_URI не найден в переменных окружения!")
            raise ValueError("MONGODB_URI не найден")
        
        try:
            self.client = MongoClient(self.mongo_uri)
            self.db = self.client.chibibot
            self.users_collection = self.db.users
            self.orders_collection = self.db.orders
            logger.info("✅ Успешное подключение к MongoDB")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к MongoDB: {e}")
            raise
        
        # Инициализация коллекций
        self._init_collections()
        
        # In-memory кэш для быстрого доступа
        self.used_ids = set()
        self.gift_selections = {}
        self.user_states = {}
        self.message_owners = {}
        self.user_order_creation = {}
        self.order_accepted_by = {}
        
        # Счетчик заказов
        self.next_order_id = 1
        
        # Тестовые аккаунты
        self.test_users = ['tmkazavr', 'ya_admin7']
        
    def _init_collections(self):
        """Инициализация коллекций и индексов"""
        # Создаем индексы для пользователей
        self.users_collection.create_index("telegram_id", unique=True)
        self.users_collection.create_index("user_id", unique=True)
        
        # Создаем индексы для заказов
        self.orders_collection.create_index("order_id", unique=True)
        self.orders_collection.create_index("status")
        self.orders_collection.create_index("creator_id")
        
    def is_test_user(self, username):
        return username in self.test_users if username else False
        
    def is_banned(self, user_id):
        user_data = self.users_collection.find_one({"telegram_id": str(user_id)})
        if user_data and user_data.get('banned_until'):
            if datetime.now() < user_data['banned_until']:
                return True
            else:
                # Бан истек, очищаем
                self.users_collection.update_one(
                    {"telegram_id": str(user_id)},
                    {"$unset": {"banned_until": ""}}
                )
        return False
        
    def clear_user_data(self, telegram_id_str):
        """Полная очистка данных пользователя"""
        self.users_collection.update_one(
            {"telegram_id": telegram_id_str},
            {"$set": {
                "chibis": [],
                "items": {"🧧 Чиби-пак": 1},
                "coins": 0,
                "level": 1,
                "exp": 0,
                "chibi_timestamps": {},
                "last_chibi_time": None,
                "last_task_time": None,
                "last_task_type": None,
                "last_bonus_time": None,
                "active_hunt": None,
                "hunt_start_times": {},
                "current_task": None
            }}
        )
            
    def ban_user(self, user_id, duration_days=7):
        telegram_id_str = str(user_id)
        ban_until = datetime.now() + timedelta(days=duration_days)
        
        self.users_collection.update_one(
            {"telegram_id": telegram_id_str},
            {"$set": {"banned_until": ban_until}}
        )
        
    def unban_user(self, user_id):
        telegram_id_str = str(user_id)
        self.users_collection.update_one(
            {"telegram_id": telegram_id_str},
            {"$unset": {"banned_until": ""}}
        )
            
    def get_ban_time_left(self, user_id):
        user_data = self.users_collection.find_one({"telegram_id": str(user_id)})
        if user_data and user_data.get('banned_until'):
            time_left = user_data['banned_until'] - datetime.now()
            return max(1, time_left.days)
        return 0
        
    def format_time(self, seconds):
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}ч {minutes:02d}м"
        
    def check_chibi_cooldown(self, user_id):
        user_data = self.users_collection.find_one({"telegram_id": str(user_id)})
        if not user_data:
            return None
            
        if self.is_test_user(user_data.get('username')):
            return None
            
        if user_data.get('last_chibi_time'):
            last_time = user_data['last_chibi_time']
            time_passed = (datetime.now() - last_time).total_seconds()
            if time_passed < 3 * 3600:  # 3 часа
                return 3 * 3600 - time_passed
        return None
        
    def check_task_cooldown(self, user_id):
        user_data = self.users_collection.find_one({"telegram_id": str(user_id)})
        if not user_data:
            return None
            
        if self.is_test_user(user_data.get('username')):
            return None
            
        if user_data.get('last_task_time'):
            last_time = user_data['last_task_time']
            task_type = user_data.get('last_task_type', 'completed')
            
            time_passed = (datetime.now() - last_time).total_seconds()
            
            if task_type == 'completed':
                cooldown = 4 * 3600  # 4 часа
            else:  # skipped
                cooldown = 5.5 * 3600  # 5.5 часов
                
            if time_passed < cooldown:
                return cooldown - time_passed
        return None
        
    def check_bonus_cooldown(self, user_id):
        user_data = self.users_collection.find_one({"telegram_id": str(user_id)})
        if not user_data:
            return None
            
        if self.is_test_user(user_data.get('username')):
            return None
            
        if user_data.get('last_bonus_time'):
            now = datetime.now()
            last_bonus = user_data['last_bonus_time']
            
            # Проверяем, наступила ли полночь по Москве
            moscow_time = now + timedelta(hours=3)  # UTC+3
            last_bonus_moscow = last_bonus + timedelta(hours=3)
            
            # Если сегодня уже брали бонус
            if last_bonus_moscow.date() == moscow_time.date():
                # Считаем время до следующей полночи
                next_midnight = datetime(moscow_time.year, moscow_time.month, moscow_time.day) + timedelta(days=1)
                time_left = next_midnight - moscow_time
                return time_left.total_seconds()
        return None
        
    def generate_unique_user_id(self):
        attempts = 0
        while attempts < 100:
            letter = random.choice(string.ascii_uppercase)
            numbers = ''.join(random.choices(string.digits, k=4))
            position = random.randint(0, 1)
            user_id = letter + numbers if position == 0 else numbers + letter
            
            # Проверяем в базе данных
            existing = self.users_collection.find_one({"user_id": user_id})
            if not existing and user_id not in self.used_ids:
                self.used_ids.add(user_id)
                return user_id
            attempts += 1
        return f"U{random.randint(1000, 9999)}"
    
    def get_or_create_user(self, telegram_id, first_name=None, username=None):
        telegram_id_str = str(telegram_id)
        
        if self.is_banned(telegram_id):
            return None, False
            
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        
        if user_data:
            # Обновляем последнюю активность
            self.users_collection.update_one(
                {"telegram_id": telegram_id_str},
                {"$set": {"last_active": datetime.now()}}
            )
            return user_data, False
        else:
            user_id = self.generate_unique_user_id()
            user_data = {
                "telegram_id": telegram_id_str,
                "user_id": user_id,
                "first_name": first_name,
                "username": username,
                "registration_date": datetime.now(),
                "last_active": datetime.now(),
                "chibis": [],
                "items": {"🧧 Чиби-пак": 1},
                "coins": 0,
                "level": 1,
                "exp": 0,
                "chibi_timestamps": {},
                "last_chibi_time": None,
                "last_task_time": None,
                "last_task_type": None,
                "last_bonus_time": None,
                "active_hunt": None,
                "hunt_start_times": {},
                "current_task": None
            }
            
            # Для тестовых пользователей даем особые условия
            if self.is_test_user(username):
                user_data["coins"] = 1000  # Стартовый бонус
                user_data["level"] = 10    # Средний уровень
                user_data["items"]["🧧 Чиби-пак"] = 5  # Несколько паков
            
            self.users_collection.insert_one(user_data)
            logger.info(f"Новый пользователь: {user_id}")
            return user_data, True

    def check_user_started(self, user_id):
        user_data = self.users_collection.find_one({"telegram_id": str(user_id)})
        return user_data is not None

    def send_start_suggestion(self, chat_id, message_id=None):
        text = "⭐️ *Советую сначала запустить бота*"
        markup = types.InlineKeyboardMarkup()
        btn_start = types.InlineKeyboardButton("Запуск", url=f"https://t.me/{self.bot.get_me().username}?start=start")
        markup.add(btn_start)
        
        if message_id:
            try:
                self.bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode='Markdown')
            except:
                self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
        else:
            self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

    def get_required_exp(self, level):
        # Сбалансированная система опыта для умеренного прогресса
        if level < 5:
            return level * 80  # Быстрый старт
        elif level < 10:
            return 400 + (level - 4) * 120  # Умеренный рост
        elif level < 20:
            return 1120 + (level - 9) * 180  # Медленный рост
        elif level < 30:
            return 2920 + (level - 19) * 250  # Замедление
        else:
            return 5420 + (level - 29) * 350  # Медленный прогресс

    def add_exp(self, telegram_id, exp_amount):
        telegram_id_str = str(telegram_id)
        
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        if not user_data:
            return 0, 1
            
        current_level = user_data.get('level', 1)
        current_exp = user_data.get('exp', 0)
        new_exp = current_exp + exp_amount
        
        required_exp = self.get_required_exp(current_level)
        level_ups = 0
        
        while new_exp >= required_exp:
            new_exp -= required_exp
            current_level += 1
            level_ups += 1
            required_exp = self.get_required_exp(current_level)
        
        # Обновляем в базе
        self.users_collection.update_one(
            {"telegram_id": telegram_id_str},
            {"$set": {
                "level": current_level,
                "exp": new_exp
            }}
        )
        
        return level_ups, current_level

    def get_level_progress(self, telegram_id):
        telegram_id_str = str(telegram_id)
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        if not user_data:
            return 1, 0, self.get_required_exp(1), 0
            
        level = user_data.get('level', 1)
        current_exp = user_data.get('exp', 0)
        required_exp = self.get_required_exp(level)
        percentage = int((current_exp / required_exp) * 100) if required_exp > 0 else 0
        return level, current_exp, required_exp, percentage

    def get_unlocked_feature(self, level):
        if level == 3:
            return "Охота за чибиками"
        elif level == 7:
            return "Заказы в кантине"
        return None

    def send_level_up_message(self, telegram_id, old_level, new_level):
        time.sleep(1)
        
        telegram_id_str = str(telegram_id)
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        if not user_data:
            return
            
        user_name = user_data.get('first_name', 'путешественник')
        
        # Добавляем чиби-пак
        current_items = user_data.get('items', {})
        if "🧧 Чиби-пак" not in current_items:
            current_items["🧧 Чиби-пак"] = 0
        current_items["🧧 Чиби-пак"] += 1
        
        self.users_collection.update_one(
            {"telegram_id": telegram_id_str},
            {"$set": {"items": current_items}}
        )
        
        unlocked_feature = self.get_unlocked_feature(new_level)
        
        try:
            sticker_id = "CAACAgIAAxkBAAE9VHtpCGLDUXiyHkIeGqv7M2eqFbN3eQAC1kgAAuSPEUq4MV_FOLGn0zYE"
            self.bot.send_sticker(telegram_id, sticker_id)
        except:
            pass
        
        if unlocked_feature:
            level_text = f"""*Эй, {user_name}!*
Ты только что апнул новый уровень! Поздравляю!
•••••••••••••••••••
*Уровень {old_level} --> Уровень {new_level}*
•••••••••••••••••••
Теперь доступно: 
  - *{unlocked_feature}*
•••••••••••••••••••
И чтобы ты не расслаблялся, держи небольшой подгон:
+ *🧧 1* Чиби-пак"""
        else:
            level_text = f"""*Эй, {user_name}!*
Ты только что апнул новый уровень! Поздравляю!
•••••••••••••••••••
*Уровень {old_level} --> Уровень {new_level}*
•••••••••••••••••••
И чтобы ты не расслаблялся, держи небольшой подгон:
+ *🧧 1* Чиби-пак"""
        
        try:
            sent_message = self.bot.send_message(telegram_id, level_text, parse_mode='Markdown')
            self.message_owners[(telegram_id, sent_message.message_id)] = telegram_id_str
        except:
            pass

    def format_exp(self, exp):
        if exp < 1000:
            return str(exp)
        elif exp < 1000000:
            return f"{exp/1000:.1f}K".replace('.0K', 'K')
        else:
            return f"{exp/1000000:.1f}M".replace('.0M', 'M')

    def add_chibi_to_user(self, telegram_id, chibi_name):
        telegram_id_str = str(telegram_id)
        
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        if not user_data:
            return
            
        current_chibis = user_data.get('chibis', [])
        current_timestamps = user_data.get('chibi_timestamps', {})
        
        current_chibis.append(chibi_name)
        current_timestamps[chibi_name] = datetime.now()
        
        self.users_collection.update_one(
            {"telegram_id": telegram_id_str},
            {"$set": {
                "chibis": current_chibis,
                "chibi_timestamps": current_timestamps
            }}
        )

    def get_fresh_chibi_count(self, telegram_id, chibi_name, hunt_start_time):
        telegram_id_str = str(telegram_id)
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        if not user_data:
            return 0
            
        chibis = user_data.get('chibis', [])
        timestamps = user_data.get('chibi_timestamps', {})
        
        count = 0
        for chibi in chibis:
            if chibi == chibi_name:
                chibi_time = timestamps.get(chibi_name)
                if chibi_time and chibi_time > hunt_start_time:
                    count += 1
        return count

    def get_random_chibi(self, from_pack=False):
        if from_pack and random.random() <= 0.05:
            chibi_folder = "chibis/secret"
        else:
            chibi_folder = "chibis/common"
        
        if not os.path.exists(chibi_folder):
            logger.error(f"Папка {chibi_folder} не найдена!")
            return None, None, "Common"
        
        chibi_files = [f for f in os.listdir(chibi_folder) if f.lower().endswith('.png')]
        
        if not chibi_files:
            logger.error(f"В папке {chibi_folder} нет PNG файлов!")
            return None, None, "Common"
        
        random_file = random.choice(chibi_files)
        file_path = os.path.join(chibi_folder, random_file)
        file_name = os.path.splitext(random_file)[0]
        formatted_name = file_name.replace('_', ' ')
        
        rarity = "Secret" if from_pack and chibi_folder == "chibis/secret" else "Common"
        
        return file_path, formatted_name, rarity

    def get_all_common_chibis(self):
        chibi_folder = "chibis/common"
        
        if not os.path.exists(chibi_folder):
            logger.error(f"Папка {chibi_folder} не найдена!")
            return []
        
        chibi_files = [f for f in os.listdir(chibi_folder) if f.lower().endswith('.png')]
        chibi_names = [os.path.splitext(f)[0].replace('_', ' ') for f in chibi_files]
        
        return sorted(chibi_names)

    def get_chibi_count(self, telegram_id, chibi_name):
        telegram_id_str = str(telegram_id)
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        if not user_data:
            return 0
            
        chibis = user_data.get('chibis', [])
        return chibis.count(chibi_name)

    def generate_task(self, telegram_id):
        telegram_id_str = str(telegram_id)
        
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        if not user_data:
            return None
            
        if user_data.get('current_task') is not None:
            return user_data['current_task']
        
        emojis = ['🐊', '🐸', '🤖', '⛄️', '🐲', '👽']
        names = ['Грирт', 'Таррек', 'Грит', 'Тарр', 'Крилл', 'Гето', 'Дин', 'Боксо', 'Мерин', 'Хрило', 'Гомадо', 'Грож']
        phrases = [
            "Эй, ты! Принеси-ка мне {chibi}, я щедро тебя награжу!",
            "Приветствую… Очень хочу заполучить {chibi}, если принесешь мне его, в долгу не останусь",
            "Бурабура, лакуш'н, принеси мне {chibi}, я готов платить"
        ]
        
        _, chibi_name, _ = self.get_random_chibi()
        if chibi_name is None:
            chibi_name = "редкого чибика"
        
        reward = random.randint(32, 49)
        emoji = random.choice(emojis)
        name = random.choice(names)
        phrase = random.choice(phrases).format(chibi=chibi_name)
        
        task_data = {
            "chibi": chibi_name,
            "reward": reward,
            "emoji": emoji,
            "name": name,
            "phrase": phrase
        }
        
        self.users_collection.update_one(
            {"telegram_id": telegram_id_str},
            {"$set": {"current_task": task_data}}
        )
        
        return task_data

    def get_task_text(self, task_data, telegram_id):
        telegram_id_str = str(telegram_id)
        has_chibi = self.get_chibi_count(telegram_id, task_data["chibi"]) > 0
        button_text = "✅ Сдать задание (1/1)" if has_chibi else "Сдать задание (0/1)"
        
        task_text = f"""*{task_data['emoji']} {task_data['name']}*
{task_data['phrase']}
•••••••••••••••••••
Дам *💰 {task_data['reward']}* за {task_data['chibi']}"""
        
        return task_text, button_text, has_chibi

    def get_user_chibis_paginated(self, telegram_id, page=1, per_page=8):
        telegram_id_str = str(telegram_id)
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        if not user_data:
            return [], 1, 1
        
        chibis = user_data.get('chibis', [])
        chibi_counts = {}
        for chibi in chibis:
            chibi_counts[chibi] = chibi_counts.get(chibi, 0) + 1
        
        sorted_chibis = sorted(
            [(name, count) for name, count in chibi_counts.items()],
            key=lambda x: (-x[1], x[0])
        )
        
        total_pages = max(1, (len(sorted_chibis) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_chibis = sorted_chibis[start_idx:end_idx]
        
        return page_chibis, page, total_pages

    def get_user_items_paginated(self, telegram_id, page=1, per_page=8):
        telegram_id_str = str(telegram_id)
        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
        if not user_data:
            return [], 1, 1
        
        items = user_data.get('items', {})
        active_items = {name: count for name, count in items.items() if count > 0}
        
        sorted_items = sorted(
            [(name, count) for name, count in active_items.items()],
            key=lambda x: (-x[1], x[0])
        )
        
        total_pages = max(1, (len(sorted_items) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_items = sorted_items[start_idx:end_idx]
        
        return page_items, page, total_pages

    def get_user_chibis_for_gift(self, telegram_id, page=1, per_page=6):
        return self.get_user_chibis_paginated(telegram_id, page, per_page)

    def get_all_chibis_paginated(self, page=1, per_page=6):
        all_chibis = self.get_all_common_chibis()
        
        total_pages = max(1, (len(all_chibis) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_chibis = all_chibis[start_idx:end_idx]
        
        return page_chibis, page, total_pages

    def get_user_active_order(self, telegram_id):
        telegram_id_str = str(telegram_id)
        order_data = self.orders_collection.find_one({
            "creator_id": telegram_id_str,
            "status": "active"
        })
        
        if order_data:
            return order_data.get('order_id'), order_data
        return None, None

    def get_other_orders_paginated(self, telegram_id, page=1, per_page=7):
        telegram_id_str = str(telegram_id)
        
        other_orders = list(self.orders_collection.find({
            "creator_id": {"$ne": telegram_id_str},
            "status": "active"
        }).sort("reward", -1))
        
        orders_with_status = []
        for order_data in other_orders:
            is_accepted = telegram_id_str in self.order_accepted_by.get(order_data.get('order_id'), [])
            orders_with_status.append((order_data.get('order_id'), order_data, is_accepted))
        
        total_pages = max(1, (len(orders_with_status) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_orders = orders_with_status[start_idx:end_idx]
        
        return page_orders, page, total_pages

    def format_date(self, date):
        months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 
                 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
        return f"{date.day}{months[date.month-1]} {date.year}"

    def check_message_ownership(self, call):
        if call.message.chat.type == 'private':
            return True
            
        telegram_id_str = str(call.from_user.id)
        message_key = (call.message.chat.id, call.message.message_id)
        
        if message_key in self.message_owners:
            if self.message_owners[message_key] != telegram_id_str:
                self.bot.answer_callback_query(call.id, "🙈 *Не твое!*", parse_mode='Markdown')
                return False
        return True

    def setup_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start_handler(message):
            if message.chat.type != 'private':
                return
                
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    return
                    
                user_data, is_new_user = self.get_or_create_user(
                    message.from_user.id,
                    message.from_user.first_name,
                    message.from_user.username
                )
                
                if user_data is None:
                    return
                    
                user_name = message.from_user.first_name or "путешественник"
                
                if is_new_user:
                    sticker_id = "CAACAgIAAxkBAAE9JsNpAzQZv6b4b-KZ3ftL2Sld0kUjDQAC400AAkuWEEosjitzZk8fzDYE"
                else:
                    sticker_id = "CAACAgIAAxkBAAE9JstpAzTQNnpt9KcoUte9P7K3CiHpswACmEQAAk-mEEqVynQKXagSVjYE"
                
                self.bot.send_sticker(message.chat.id, sticker_id)
                
                if is_new_user:
                    welcome_text = BOT_TEXTS['welcome'].format(name=user_name)
                    markup = types.InlineKeyboardMarkup()
                    btn_channel = types.InlineKeyboardButton(
                        '📢 Наш тгк', 
                        url=BOT_CONFIG['telegram_channel']
                    )
                    markup.add(btn_channel)
                    sent_message = self.bot.send_message(message.chat.id, welcome_text, reply_markup=markup, parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    sent_message = self.bot.send_message(message.chat.id, BOT_TEXTS['already_started'], parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    
            except Exception as e:
                logger.error(f"Ошибка в start: {e}")
                sent_message = self.bot.send_message(
                    message.chat.id,
                    "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                    parse_mode='Markdown'
                )
                self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)

        @self.bot.message_handler(commands=['ban'])
        def ban_handler(message):
            try:
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                telegram_id_str = str(message.from_user.id)
                user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                
                if not self.is_test_user(user_data.get('username')):
                    self.bot.reply_to(message, "❌ *Недостаточно прав!*", parse_mode='Markdown')
                    return
                    
                if len(message.text.split()) < 2:
                    self.bot.reply_to(message, "🤷‍♂️ *Использование:* `/ban @username`", parse_mode='Markdown')
                    return
                    
                target = message.text.split()[1].strip()
                
                # Ищем пользователя по username или ID
                target_user = self.users_collection.find_one({
                    "$or": [
                        {"username": target.replace('@', '')},
                        {"user_id": target}
                    ]
                })
                
                if not target_user:
                    self.bot.reply_to(message, "👻 *Пользователь не найден!*", parse_mode='Markdown')
                    return
                    
                self.ban_user(target_user['telegram_id'])
                self.bot.reply_to(message, f"✅ *Пользователь забанен на 7 дней!*", parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка бана: {e}")
                self.bot.reply_to(message, "⛓️‍💥* Потеряно соединение!* Попробуй снова!", parse_mode='Markdown')

        @self.bot.message_handler(commands=['unban'])
        def unban_handler(message):
            try:
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                telegram_id_str = str(message.from_user.id)
                user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                
                if not self.is_test_user(user_data.get('username')):
                    self.bot.reply_to(message, "❌ *Недостаточно прав!*", parse_mode='Markdown')
                    return
                    
                if len(message.text.split()) < 2:
                    self.bot.reply_to(message, "🤷‍♂️ *Использование:* `/unban @username`", parse_mode='Markdown')
                    return
                    
                target = message.text.split()[1].strip()
                
                target_user = self.users_collection.find_one({
                    "$or": [
                        {"username": target.replace('@', '')},
                        {"user_id": target}
                    ]
                })
                        
                if not target_user:
                    self.bot.reply_to(message, "👻 *Пользователь не найден!*", parse_mode='Markdown')
                    return
                    
                self.unban_user(target_user['telegram_id'])
                self.bot.reply_to(message, f"✅ *Пользователь разбанен!*", parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка разбана: {e}")
                self.bot.reply_to(message, "⛓️‍💥* Потеряно соединение!* Попробуй снова!", parse_mode='Markdown')

        @self.bot.message_handler(commands=['myid'])
        def myid_handler(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(
                            message.chat.id,
                            f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.", parse_mode='Markdown')
                    return
                    
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                user_data, _ = self.get_or_create_user(message.from_user.id)
                user_id = user_data['user_id']
                
                response_text = f"⭐️ Твой айди — `{user_id}`"
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, response_text, parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, response_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Потеряно соединение!* Попробуй снова!", parse_mode='Markdown')

        @self.bot.message_handler(commands=['balance'])
        def balance_handler(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(
                            message.chat.id,
                            f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.", parse_mode='Markdown')
                    return
                    
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                telegram_id_str = str(message.from_user.id)
                user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                coins = user_data.get('coins', 0) if user_data else 0
                
                balance_text = f"💰 У тебя — *{coins}* коинов!"
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, balance_text, parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, balance_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Потеряно соединение!* Попробуй снова!", parse_mode='Markdown')

        @self.bot.message_handler(commands=['level'])
        def level_handler(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(
                            message.chat.id,
                            f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.", parse_mode='Markdown')
                    return
                    
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                level, current_exp, required_exp, percentage = self.get_level_progress(message.from_user.id)
                
                level_text = f"""💫 *Твой уровень* — *{level}* ({percentage}%)"""
                
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, level_text, parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, level_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Потеряно соединение!* Попробуй снова!", parse_mode='Markdown')

        @self.bot.message_handler(commands=['mart'])
        def mart_handler(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(
                            message.chat.id,
                            f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.", parse_mode='Markdown')
                    return
                    
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                mart_text = """🎏 *Лавка джавы*
Джавы, может, и не отличаются умом, но зато точно знают толк в ценах!"""
                
                markup = types.InlineKeyboardMarkup()
                btn_pack = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_chibi_pack")
                markup.add(btn_pack)
                
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        mart_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    reply_msg = self.bot.reply_to(message, mart_text, reply_markup=markup, parse_mode='Markdown')
                    self.message_owners[(message.chat.id, reply_msg.message_id)] = str(message.from_user.id)
                
            except Exception as e:
                logger.error(f"Ошибка при открытии лавки: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Потеряно соединение!* Попробуй снова!", parse_mode='Markdown')

        @self.bot.message_handler(commands=['chibi'])
        def chibi_handler(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(
                            message.chat.id,
                            f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.", parse_mode='Markdown')
                    return
                    
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                # Проверяем КД
                cooldown = self.check_chibi_cooldown(message.from_user.id)
                if cooldown:
                    time_left = self.format_time(int(cooldown))
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(
                            message.chat.id,
                            f"⚡️ *Ты уже залутал чибика в последнее время!* Возвращайся за новеньким-готовеньким через *{time_left}*!",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, f"⚡️ *Ты уже залутал чибика в последнее время!* Возвращайся за новеньким-готовеньким через *{time_left}*!", parse_mode='Markdown')
                    return
                    
                telegram_id_str = str(message.from_user.id)
                file_path, chibi_name, rarity = self.get_random_chibi(from_pack=False)
                
                if file_path is None:
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(message.chat.id, "🌀 *Чибики сейчас отдыхают!* Загляни позже", parse_mode='Markdown')
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, "🌀 *Чибики сейчас отдыхают!* Загляни позже", parse_mode='Markdown')
                    return
                
                self.add_chibi_to_user(message.from_user.id, chibi_name)
                chibi_count = self.get_chibi_count(message.from_user.id, chibi_name)
                
                # Начисляем опыт за чибика (сбалансированно)
                exp_gained = random.randint(15, 25)
                level_ups, new_level = self.add_exp(message.from_user.id, exp_gained)
                
                # Обновляем время получения чибика
                self.users_collection.update_one(
                    {"telegram_id": telegram_id_str},
                    {"$set": {"last_chibi_time": datetime.now()}}
                )
                
                rarity_emoji = "🔷" if rarity == "Common" else "🔶"
                
                chibi_text = f"""*Тебе выпал — {chibi_name}!*
Надеюсь, он тебе понравился! 
Приходи еще через *2ч 59м*
•••••••••••••••••••
Редкость: {rarity_emoji} {rarity}
У тебя: {chibi_count}
•••••••••••••••••••
+ ⭐️ *{exp_gained}* опыта"""
                
                with open(file_path, 'rb') as photo:
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_photo(
                            message.chat.id,
                            photo,
                            caption=chibi_text,
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        sent_message = self.bot.send_photo(
                            message.chat.id,
                            photo,
                            caption=chibi_text,
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    
                logger.info(f"Отправлен чиби: {chibi_name} (Редкость: {rarity})")
                
                if level_ups > 0:
                    threading.Thread(target=self.send_level_up_message, 
                                   args=(message.from_user.id, new_level - level_ups, new_level)).start()
                    
            except Exception as e:
                logger.error(f"Ошибка при отправке чиби: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Потеряно соединение!* Попробуй снова!", parse_mode='Markdown')

        @self.bot.message_handler(commands=['task'])
        def task_handler(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(
                            message.chat.id,
                            f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.", parse_mode='Markdown')
                    return
                    
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                # Проверяем КД задания
                cooldown = self.check_task_cooldown(message.from_user.id)
                if cooldown:
                    time_left = self.format_time(int(cooldown))
                    user_data = self.users_collection.find_one({"telegram_id": str(message.from_user.id)})
                    task_type = user_data.get('last_task_type', 'completed') if user_data else 'completed'
                    
                    if task_type == 'completed':
                        text = f"🎯 *Ты выполнил свой таск недавно. Думаю, стоит взять перерыв! Осталось подождать* *{time_left}*"
                    else:
                        text = f"🎯 *Ты пропустил свой таск, поэтому придется ждать дольше*. Приходи через *{time_left}*"
                    
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(message.chat.id, text, parse_mode='Markdown')
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, text, parse_mode='Markdown')
                    return
                    
                task_data = self.generate_task(message.from_user.id)
                task_text, button_text, has_chibi = self.get_task_text(task_data, message.from_user.id)
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn_complete = types.InlineKeyboardButton(
                    button_text, 
                    callback_data="task_complete" if has_chibi else "task_cannot_complete"
                )
                btn_skip = types.InlineKeyboardButton(
                    "Пропустить", 
                    callback_data="task_skip_confirm"
                )
                markup.add(btn_complete, btn_skip)
                
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        task_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    reply_msg = self.bot.reply_to(message, task_text, reply_markup=markup, parse_mode='Markdown')
                    self.message_owners[(message.chat.id, reply_msg.message_id)] = str(message.from_user.id)
                
            except Exception as e:
                logger.error(f"Ошибка при генерации задания: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Потеряно соединение!* Попробуй снова!", parse_mode='Markdown')

        @self.bot.message_handler(commands=['menu'])
        def menu_handler(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(
                            message.chat.id,
                            f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.", parse_mode='Markdown')
                    return
                    
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                menu_text = """*✨ Меню* 
Здесь ты найдешь все, что нужно, но не имеет команды. Мы постарались"""
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn_warehouse = types.InlineKeyboardButton("📦 Склад", callback_data="menu_warehouse")
                btn_channel = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
                
                # Проверяем КД бонуса
                bonus_cooldown = self.check_bonus_cooldown(message.from_user.id)
                if bonus_cooldown:
                    time_left = self.format_time(int(bonus_cooldown))
                    btn_bonus = types.InlineKeyboardButton(f"🔒 Приходи через {time_left}", callback_data="bonus_cooldown")
                else:
                    btn_bonus = types.InlineKeyboardButton("🎁 Ежедневный бонус", callback_data="menu_bonus")
                
                markup.add(btn_warehouse, btn_channel)
                markup.add(btn_bonus)
                
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        menu_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    reply_msg = self.bot.reply_to(message, menu_text, reply_markup=markup, parse_mode='Markdown')
                    self.message_owners[(message.chat.id, reply_msg.message_id)] = str(message.from_user.id)
                
            except Exception as e:
                logger.error(f"Ошибка при открытии меню: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Потеряно соединение!* Попробуй снова!", parse_mode='Markdown')

        @self.bot.message_handler(commands=['gift'])
        def gift_handler(message):
            if message.chat.type != 'private':
                self.bot.reply_to(message, "🙅‍♂️ *Не-не, дружок!* Эта команда доступна только в *личке с ботом*", parse_mode='Markdown')
                return
                
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    return
                    
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                if len(message.text.split()) < 2:
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "🤷‍♂️ *Ты что-то не так ввел, друг!* Попробуй: `/gift 1234Е`",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    return
                
                target_user_id = message.text.split()[1].strip()
                
                target_user = self.users_collection.find_one({"user_id": target_user_id})
                
                if not target_user:
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "👻 *Такого друга еще нет!* Проверь ID и попробуй снова",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    return
                
                if str(message.from_user.id) in self.users_collection.find_one({"user_id": target_user_id}).get('telegram_id', ''):
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "🐲 *Не-не, самому себе подарки не дарим!* Попробуй найти друзей",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    return
                
                telegram_id_str = str(message.from_user.id)
                self.gift_selections[telegram_id_str] = {
                    "target_user_id": target_user_id,
                    "target_telegram_id": target_user.get('telegram_id'),
                    "target_name": target_user.get('first_name', 'пользователь')
                }
                
                chibis, current_page, total_pages = self.get_user_chibis_for_gift(message.from_user.id, 1)
                
                if not chibis:
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "🎁 *А дарить-то нечего!* Сначала собери коллекцию чибиков",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    return
                
                gift_text = f"""✨ *О, да ты у нас щедрый!*
Выбери, какого чибика подаришь"""
                
                markup = types.InlineKeyboardMarkup()
                
                for chibi_name, count in chibis:
                    if count > 1:
                        btn_text = f"{chibi_name} ({count})"
                    else:
                        btn_text = chibi_name
                    markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"gift_select_{chibi_name}"))
                
                nav_buttons = []
                if total_pages > 1:
                    nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"gift_page_{((current_page-2) % total_pages) + 1}"))
                
                nav_buttons.append(types.InlineKeyboardButton("Отменить", callback_data="gift_cancel"))
                
                if total_pages > 1:
                    nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"gift_page_{(current_page % total_pages) + 1}"))
                
                markup.row(*nav_buttons)
                
                sent_message = self.bot.send_message(
                    message.chat.id,
                    gift_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                
            except Exception as e:
                logger.error(f"Ошибка при отправке подарка: {e}")
                sent_message = self.bot.send_message(
                    message.chat.id,
                    "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                    parse_mode='Markdown'
                )
                self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)

        @self.bot.message_handler(commands=['cantina'])
        def cantina_handler(message):
            if message.chat.type != 'private':
                self.bot.reply_to(message, "🙅‍♂️ *Не-не, дружок!* Эта команда доступна только в *личке с ботом*", parse_mode='Markdown')
                return
                
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time_left(message.from_user.id)
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        f"🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    return
                    
                if not self.check_user_started(message.from_user.id):
                    self.send_start_suggestion(message.chat.id)
                    return
                    
                telegram_id_str = str(message.from_user.id)
                
                user_order_id, user_order_data = self.get_user_active_order(message.from_user.id)
                
                cantina_text = """*🕍 Кантина*
Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…"""
                
                markup = types.InlineKeyboardMarkup()
                
                if user_order_id is not None:
                    btn_my_order = types.InlineKeyboardButton(
                        f"🔹 {user_order_data['chibi_name']} - 💰{user_order_data['reward']}",
                        callback_data="cantina_view_my_order"
                    )
                    markup.add(btn_my_order)
                else:
                    btn_create = types.InlineKeyboardButton("Создать заказ", callback_data="cantina_create_order")
                    markup.add(btn_create)
                
                other_orders, current_page, total_pages = self.get_other_orders_paginated(message.from_user.id, 1)
                
                for order_id, order_data, is_accepted in other_orders:
                    creator_name = self.users_collection.find_one({"telegram_id": order_data["creator_id"]}).get('first_name', 'Неизвестный')
                    if not creator_name or creator_name == 'Неизвестный':
                        creator_username = self.users_collection.find_one({"telegram_id": order_data["creator_id"]}).get('username')
                        if creator_username:
                            creator_name = f"@{creator_username}"
                        else:
                            creator_name = "Неизвестный"
                    
                    prefix = "🔸" if is_accepted else ""
                    btn_order = types.InlineKeyboardButton(
                        f"{prefix} {order_data['chibi_name']} - 💰{order_data['reward']} ({creator_name})",
                        callback_data=f"cantina_view_order_{order_id}"
                    )
                    markup.add(btn_order)
                
                if total_pages > 1:
                    nav_buttons = []
                    if current_page > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"cantina_orders_page_{current_page-1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="cantina_orders_info"))
                    
                    if current_page < total_pages:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"cantina_orders_page_{current_page+1}"))
                    
                    markup.row(*nav_buttons)
                
                sent_message = self.bot.send_message(
                    message.chat.id,
                    cantina_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                
            except Exception as e:
                logger.error(f"Ошибка при открытии кантины: {e}")
                sent_message = self.bot.send_message(
                    message.chat.id,
                    "⛓️‍💥* Потеряно соединение!* Попробуй снова!",
                    parse_mode='Markdown'
                )
                self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)

        @self.bot.message_handler(func=lambda message: True)
        def text_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                
                if self.user_states.get(telegram_id_str) == "waiting_for_reward":
                    try:
                        reward = int(message.text)
                        recommended_price = random.randint(32, 45)
                        
                        if reward < 25:
                            if message.chat.type == 'private':
                                sent_message = self.bot.send_message(
                                    message.chat.id,
                                    "💸 *Слишком мало!* Минимум — 25 коинов",
                                    parse_mode='Markdown'
                                )
                                self.message_owners[(message.chat.id, sent_message.message_id)] = telegram_id_str
                            else:
                                self.bot.reply_to(message, "💸 *Слишком мало!* Минимум — 25 коинов", parse_mode='Markdown')
                            return
                        elif reward > 440:
                            if message.chat.type == 'private':
                                sent_message = self.bot.send_message(
                                    message.chat.id,
                                    "💰 *Слишком много!* Максимум — 440 коинов",
                                    parse_mode='Markdown'
                                )
                                self.message_owners[(message.chat.id, sent_message.message_id)] = telegram_id_str
                            else:
                                self.bot.reply_to(message, "💰 *Слишком много!* Максимум — 440 коинов", parse_mode='Markdown')
                            return
                        
                        if telegram_id_str in self.user_order_creation:
                            self.user_order_creation[telegram_id_str]["reward"] = reward
                        
                        self.user_states[telegram_id_str] = None
                        
                        create_text = """🕍 *Создаем заказ*
Укажи, какого чибика охотники будут искать, и цену, которую ты готов заплатить. Помни, цена влияет на твою репутацию"""
                        
                        markup = types.InlineKeyboardMarkup()
                        
                        if self.user_order_creation[telegram_id_str]["chibi_name"]:
                            btn_chibi = types.InlineKeyboardButton(
                                self.user_order_creation[telegram_id_str]["chibi_name"],
                                callback_data="cantina_select_chibi"
                            )
                        else:
                            btn_chibi = types.InlineKeyboardButton("Выбрать чибика", callback_data="cantina_select_chibi")
                        
                        btn_reward = types.InlineKeyboardButton(
                            f"Твоя цена: {self.user_order_creation[telegram_id_str]['reward']}",
                            callback_data="cantina_set_reward"
                        )
                        
                        markup.add(btn_chibi)
                        markup.add(btn_reward)
                        
                        if (self.user_order_creation[telegram_id_str]["chibi_name"] and 
                            self.user_order_creation[telegram_id_str]["reward"]):
                            btn_confirm = types.InlineKeyboardButton("Подтвердить", callback_data="cantina_confirm_order")
                            markup.add(btn_confirm)
                        else:
                            btn_back = types.InlineKeyboardButton("Назад", callback_data="cantina_back")
                            markup.add(btn_back)
                        
                        self.bot.edit_message_text(
                            create_text,
                            message.chat.id,
                            message.message_id - 1,
                            reply_markup=markup,
                            parse_mode='Markdown'
                        )
                        
                        self.bot.delete_message(message.chat.id, message.message_id)
                        
                    except ValueError:
                        if message.chat.type == 'private':
                            sent_message = self.bot.send_message(
                                message.chat.id,
                                "🔢 *Цифрами, пожалуйста!* Введи число",
                                parse_mode='Markdown'
                            )
                            self.message_owners[(message.chat.id, sent_message.message_id)] = telegram_id_str
                        else:
                            self.bot.reply_to(message, "🔢 *Цифрами, пожалуйста!* Введи число", parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка в текстовом обработчике: {e}")

        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call):
            try:
                if not self.check_message_ownership(call):
                    return

                if call.data == "task_complete":
                    telegram_id_str = str(call.from_user.id)
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    if not user_data or not user_data.get('current_task'):
                        self.bot.answer_callback_query(call.id, "🎯 Задание уже выполнено!")
                        return
                    
                    task_data = user_data['current_task']
                    
                    if task_data["chibi"] in user_data.get('chibis', []):
                        # Удаляем чибика
                        new_chibis = [chibi for chibi in user_data.get('chibis', []) if chibi != task_data["chibi"]]
                        self.users_collection.update_one(
                            {"telegram_id": telegram_id_str},
                            {"$set": {"chibis": new_chibis}}
                        )
                    else:
                        self.bot.answer_callback_query(call.id, "🤷‍♂️ И что ты собрался сдавать?")
                        return
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sticker_id = "CAACAgIAAxkBAAE9Js9pAzTWs9gLLtl9Gqz_9V_4sbwXqgAC7EYAAjNREEqhVSL_nxyHZTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id)
                    
                    reward = task_data["reward"]
                    new_coins = user_data.get('coins', 0) + reward
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {
                            "coins": new_coins,
                            "current_task": None,
                            "last_task_time": datetime.now(),
                            "last_task_type": 'completed'
                        }}
                    )
                    
                    # Начисляем опыт за задание
                    exp_gained = random.randint(20, 30)
                    level_ups, new_level = self.add_exp(call.from_user.id, exp_gained)
                    
                    user_nick = call.from_user.first_name or "путешественник"
                    complete_text = f"""*Ес! {user_nick}, ты выполнил таск!*
За это ты получаешь обещанную награду. Даже не буду гадать, сколько ты выбивал нужного чибика
•••••••••••••••••••
+ 💰*{reward}* коинов
+ ⭐️ *{exp_gained}* опыта"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        complete_text,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                    if level_ups > 0:
                        threading.Thread(target=self.send_level_up_message, 
                                       args=(call.from_user.id, new_level - level_ups, new_level)).start()
                    
                elif call.data == "task_cannot_complete":
                    self.bot.answer_callback_query(call.id, "🤷‍♂️ И что ты собрался сдавать?")
                    
                elif call.data == "task_skip":
                    telegram_id_str = str(call.from_user.id)
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {
                            "current_task": None,
                            "last_task_time": datetime.now(),
                            "last_task_type": 'skipped'
                        }}
                    )
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    skip_text = """✨*Ты пропустил таск. Жди новый!*
Осталось 5ч 29м"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        skip_text,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                elif call.data == "task_skip_confirm":
                    telegram_id_str = str(call.from_user.id)
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    if not user_data or not user_data.get('current_task'):
                        self.bot.answer_callback_query(call.id, "🎯 Нет активного задания!")
                        return
                    
                    task_data = user_data['current_task']
                    
                    skip_text = f"""{task_data['emoji']}* Ты точно хочешь пропустить задание?*
Придется долго ждать следующее, но пропуск бесплатный"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_skip = types.InlineKeyboardButton("Пропустить", callback_data="task_skip")
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="task_back")
                    markup.add(btn_skip, btn_back)
                    
                    self.bot.edit_message_text(
                        skip_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "task_back":
                    telegram_id_str = str(call.from_user.id)
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    if not user_data or not user_data.get('current_task'):
                        self.bot.answer_callback_query(call.id, "🎯 Нет активного задания!")
                        return
                    
                    task_data = user_data['current_task']
                    task_text, button_text, has_chibi = self.get_task_text(task_data, call.from_user.id)
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn_complete = types.InlineKeyboardButton(
                        button_text, 
                        callback_data="task_complete" if has_chibi else "task_cannot_complete"
                    )
                    btn_skip = types.InlineKeyboardButton(
                        "Пропустить", 
                        callback_data="task_skip_confirm"
                    )
                    markup.add(btn_complete, btn_skip)
                    
                    self.bot.edit_message_text(
                        task_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "menu_warehouse":
                    warehouse_text = """*📦 Перепутье*
Выбери, на какой раздел склада хочешь глянуть"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn_chibis = types.InlineKeyboardButton("Чибики", callback_data="warehouse_chibis_1")
                    btn_items = types.InlineKeyboardButton("Предметы", callback_data="warehouse_items_1")
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="menu_back")
                    
                    markup.add(btn_chibis, btn_items)
                    markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        warehouse_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("warehouse_chibis_"):
                    page = int(call.data.split("_")[2])
                    chibis, current_page, total_pages = self.get_user_chibis_paginated(call.from_user.id, page)
                    
                    chibis_text = f"""📦 *Твои чибики*
Великолепные и неповторимые. Ну, почти…
Страница {current_page}/{total_pages}"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if chibis:
                        for chibi_name, count in chibis:
                            if count > 1:
                                btn_text = f"{chibi_name} ({count})"
                            else:
                                btn_text = chibi_name
                            markup.add(types.InlineKeyboardButton(btn_text, callback_data="chibi_click"))
                    else:
                        markup.add(types.InlineKeyboardButton("Пусто", callback_data="empty"))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"warehouse_chibis_{((current_page-2) % total_pages) + 1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Назад", callback_data="menu_warehouse"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"warehouse_chibis_{(current_page % total_pages) + 1}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        chibis_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("warehouse_items_"):
                    page = int(call.data.split("_")[2])
                    items, current_page, total_pages = self.get_user_items_paginated(call.from_user.id, page)
                    
                    items_text = f"""*📦 Твои предметы* 
Тут хранятся твои боксы. Других предметов в боте пока и нет…
Страница {current_page}/{total_pages}"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if items:
                        for item_name, count in items:
                            if count > 1:
                                btn_text = f"{item_name} ({count})"
                            else:
                                btn_text = item_name
                            if item_name == "🧧 Чиби-пак":
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="open_chibi_pack"))
                            else:
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="item_click"))
                    else:
                        markup.add(types.InlineKeyboardButton("Пусто", callback_data="empty"))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"warehouse_items_{((current_page-2) % total_pages) + 1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Назад", callback_data="menu_warehouse"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"warehouse_items_{(current_page % total_pages) + 1}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        items_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "open_chibi_pack":
                    telegram_id_str = str(call.from_user.id)
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    if not user_data:
                        return
                        
                    pack_count = user_data.get('items', {}).get("🧧 Чиби-пак", 0)
                    
                    confirm_text = f"""*Ты точно хочешь открыть 🧧 Чиби-пак?*
Хотя что тебе еще делать с ним? Разве что повесить на стену и любоваться"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    
                    if pack_count == 1:
                        btn_open1 = types.InlineKeyboardButton("Открыть х1", callback_data="open_pack_1")
                        markup.add(btn_open1)
                    else:
                        btn_open1 = types.InlineKeyboardButton("Открыть х1", callback_data="open_pack_1")
                        btn_open_all = types.InlineKeyboardButton(f"Открыть х{pack_count}", callback_data=f"open_pack_{pack_count}")
                        markup.add(btn_open1, btn_open_all)
                    
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="warehouse_items_1")
                    markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        confirm_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("open_pack_"):
                    count = int(call.data.split("_")[2])
                    telegram_id_str = str(call.from_user.id)
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    if not user_data:
                        return
                    
                    current_packs = user_data.get('items', {}).get("🧧 Чиби-пак", 0)
                    if current_packs < count:
                        self.bot.answer_callback_query(call.id, "🎒 *Недостаточно Чиби-паков!*")
                        return
                    
                    # Уменьшаем количество паков
                    new_packs = current_packs - count
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"items.🧧 Чиби-пак": new_packs}}
                    )
                    
                    for i in range(count):
                        file_path, chibi_name, rarity = self.get_random_chibi(from_pack=True)
                        
                        if file_path is not None:
                            self.add_chibi_to_user(call.from_user.id, chibi_name)
                            chibi_count = self.get_chibi_count(call.from_user.id, chibi_name)
                            
                            rarity_emoji = "🔷" if rarity == "Common" else "🔶"
                            
                            chibi_text = f"""*Тебе выпал — {chibi_name}!*
Надеюсь, он тебе понравился!
•••••••••••••••••••
Редкость: {rarity_emoji} {rarity}
У тебя: {chibi_count}"""
                            
                            with open(file_path, 'rb') as photo:
                                sent_message = self.bot.send_photo(
                                    call.message.chat.id,
                                    photo,
                                    caption=chibi_text,
                                    parse_mode='Markdown'
                                )
                                self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                    self.bot.answer_callback_query(call.id, f"🎉 Открыто {count} Чиби-пак(ов)!")
                    
                    items, current_page, total_pages = self.get_user_items_paginated(call.from_user.id, 1)
                    
                    items_text = f"""*📦 Твои предметы* 
Тут хранятся твои боксы. Других предметов в боте пока и нет…
Страница {current_page}/{total_pages}"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if items:
                        for item_name, count in items:
                            if count > 1:
                                btn_text = f"{item_name} ({count})"
                            else:
                                btn_text = item_name
                            if item_name == "🧧 Чиби-пак":
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="open_chibi_pack"))
                            else:
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="item_click"))
                    else:
                        markup.add(types.InlineKeyboardButton("Пусто", callback_data="empty"))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"warehouse_items_{((current_page-2) % total_pages) + 1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Назад", callback_data="menu_warehouse"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"warehouse_items_{(current_page % total_pages) + 1}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        items_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "mart_chibi_pack":
                    pack_text = """🎏 *Хочешь купить этот прекрасный Чиби-пак?*
Да брось, знаю что так руки и чешутся!"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_buy = types.InlineKeyboardButton("Купить (120)", callback_data="buy_chibi_pack")
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="mart_back")
                    markup.add(btn_buy)
                    markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        pack_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "buy_chibi_pack":
                    telegram_id_str = str(call.from_user.id)
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    if not user_data:
                        return
                    
                    coins = user_data.get('coins', 0)
                    
                    if coins < 120:
                        missing = 120 - coins
                        self.bot.answer_callback_query(call.id, f"✨ Бро, сначала подкопи! Тебе не хватает {missing} коинов")
                        return
                    
                    # Списание коинов и добавление пака
                    new_coins = coins - 120
                    current_items = user_data.get('items', {})
                    if "🧧 Чиби-пак" not in current_items:
                        current_items["🧧 Чиби-пак"] = 0
                    current_items["🧧 Чиби-пак"] += 1
                    
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {
                            "coins": new_coins,
                            "items": current_items
                        }}
                    )
                    
                    self.bot.answer_callback_query(call.id, "🎉 Чиби-пак куплен!")
                    
                    mart_text = """🎏 *Лавка джавы*
Джавы, может, и не отличаются умом, но зато точно знают толк в ценах!"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_pack = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_chibi_pack")
                    markup.add(btn_pack)
                    
                    self.bot.edit_message_text(
                        mart_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "mart_back":
                    mart_text = """🎏 *Лавка джавы*
Джавы, может, и не отличаются умом, но зато точно знают толк в ценах!"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_pack = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_chibi_pack")
                    markup.add(btn_pack)
                    
                    self.bot.edit_message_text(
                        mart_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "menu_bonus":
                    telegram_id_str = str(call.from_user.id)
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    if not user_data:
                        return
                    
                    # Проверяем КД бонуса
                    bonus_cooldown = self.check_bonus_cooldown(call.from_user.id)
                    if bonus_cooldown and not self.is_test_user(user_data.get('username')):
                        time_left = self.format_time(int(bonus_cooldown))
                        self.bot.answer_callback_query(call.id, f"🔒 Бонус будет доступен через {time_left}")
                        return
                    
                    bonus = random.randint(7, 19)
                    
                    # Начисляем бонус
                    new_coins = user_data.get('coins', 0) + bonus
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {
                            "coins": new_coins,
                            "last_bonus_time": datetime.now()
                        }}
                    )
                    
                    user_name = user_data.get('first_name', 'путешественник')
                    bonus_text = f"""🎁 *Эй, {user_name}!*
Ты только что получил ежедневный бонус! 
•••••••••••••••••
+ 💰*{bonus}* коинов"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        bonus_text,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                elif call.data == "bonus_cooldown":
                    telegram_id_str = str(call.from_user.id)
                    bonus_cooldown = self.check_bonus_cooldown(call.from_user.id)
                    if bonus_cooldown:
                        time_left = self.format_time(int(bonus_cooldown))
                        self.bot.answer_callback_query(call.id, f"🔒 Бонус будет доступен через {time_left}")
                    
                elif call.data == "menu_back":
                    menu_text = """*✨ Меню* 
Здесь ты найдешь все, что нужно, но не имеет команды. Мы постарались"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn_warehouse = types.InlineKeyboardButton("📦 Склад", callback_data="menu_warehouse")
                    btn_channel = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
                    
                    # Обновляем кнопку бонуса
                    bonus_cooldown = self.check_bonus_cooldown(call.from_user.id)
                    user_data = self.users_collection.find_one({"telegram_id": str(call.from_user.id)})
                    if bonus_cooldown and not self.is_test_user(user_data.get('username') if user_data else None):
                        time_left = self.format_time(int(bonus_cooldown))
                        btn_bonus = types.InlineKeyboardButton(f"🔒 Приходи через {time_left}", callback_data="bonus_cooldown")
                    else:
                        btn_bonus = types.InlineKeyboardButton("🎁 Ежедневный бонус", callback_data="menu_bonus")
                    
                    markup.add(btn_warehouse, btn_channel)
                    markup.add(btn_bonus)
                    
                    self.bot.edit_message_text(
                        menu_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("gift_page_"):
                    page = int(call.data.split("_")[2])
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str not in self.gift_selections:
                        self.bot.answer_callback_query(call.id, "⏰ *Сессия подарка истекла!*")
                        return
                    
                    chibis, current_page, total_pages = self.get_user_chibis_for_gift(call.from_user.id, page)
                    
                    gift_text = f"""✨ *О, да ты у нас щедрый!*
Выбери, какого чибика подаришь"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    for chibi_name, count in chibis:
                        if count > 1:
                            btn_text = f"{chibi_name} ({count})"
                        else:
                            btn_text = chibi_name
                        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"gift_select_{chibi_name}"))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"gift_page_{((current_page-2) % total_pages) + 1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Отменить", callback_data="gift_cancel"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"gift_page_{(current_page % total_pages) + 1}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        gift_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("gift_select_"):
                    chibi_name = call.data.replace("gift_select_", "")
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str not in self.gift_selections:
                        self.bot.answer_callback_query(call.id, "⏰ *Сессия подарка истекла!*")
                        return
                    
                    self.gift_selections[telegram_id_str]["chibi_name"] = chibi_name
                    
                    target_name = self.gift_selections[telegram_id_str]["target_name"]
                    
                    confirm_text = f"""✨ *Дарим чибика?*
Ты уверен, что хочешь этого? Назад вернуть уже не получится
•••••••••••••••
Кому: *{target_name}*
Кого: *{chibi_name}*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_confirm = types.InlineKeyboardButton("✅ Подтвердить", callback_data="gift_confirm")
                    btn_cancel = types.InlineKeyboardButton("🙅‍♂️ Отмена", callback_data="gift_cancel")
                    markup.add(btn_confirm, btn_cancel)
                    
                    self.bot.edit_message_text(
                        confirm_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "gift_confirm":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str not in self.gift_selections:
                        self.bot.answer_callback_query(call.id, "⏰ *Сессия подарка истекла!*")
                        return
                    
                    gift_data = self.gift_selections[telegram_id_str]
                    chibi_name = gift_data["chibi_name"]
                    target_telegram_id = gift_data["target_telegram_id"]
                    target_name = gift_data["target_name"]
                    
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    if not user_data or chibi_name not in user_data.get('chibis', []):
                        self.bot.answer_callback_query(call.id, "🎒 *У тебя больше нет этого чибика!*")
                        return
                    
                    # Удаляем чибика у отправителя
                    new_chibis = [chibi for chibi in user_data.get('chibis', []) if chibi != chibi_name]
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"chibis": new_chibis}}
                    )
                    
                    # Добавляем чибика получателю
                    target_user = self.users_collection.find_one({"telegram_id": target_telegram_id})
                    if target_user:
                        target_chibis = target_user.get('chibis', [])
                        target_chibis.append(chibi_name)
                        target_timestamps = target_user.get('chibi_timestamps', {})
                        target_timestamps[chibi_name] = datetime.now()
                        
                        self.users_collection.update_one(
                            {"telegram_id": target_telegram_id},
                            {"$set": {
                                "chibis": target_chibis,
                                "chibi_timestamps": target_timestamps
                            }}
                        )
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    

                    sticker_id_sender = "CAACAgIAAxkBAAE9JtFpAzTjbRJ884hA4YNjTqPc7Z05lAACQEgAAlZVEUqWc8vDGvLqWTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id_sender)
                    
                    sender_name = call.from_user.first_name or "Отправитель"
                    sender_text = f"""*✨ Чибик отправлен! 
Надеюсь, {target_name} он понравится!*"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        sender_text,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                    sticker_id_receiver = "CAACAgIAAxkBAAE9OxxpBRLZ5OANTuRD-97sRPdCONwv0AACU0YAAkVlEErI0vjxKMrHnTYE"
                    self.bot.send_sticker(target_telegram_id, sticker_id_receiver)
                    
                    receiver_text = f"""*💌 Тебе подарок!*
{sender_name} подарил тебе {chibi_name}!"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_view = types.InlineKeyboardButton("Посмотреть", callback_data="warehouse_chibis_1")
                    markup.add(btn_view)
                    
                    sent_message = self.bot.send_message(
                        target_telegram_id,
                        receiver_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(target_telegram_id, sent_message.message_id)] = target_telegram_id
                    
                    del self.gift_selections[telegram_id_str]
                    
                elif call.data == "gift_cancel":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str in self.gift_selections:
                        del self.gift_selections[telegram_id_str]
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                elif call.data == "cantina_create_order":
                    telegram_id_str = str(call.from_user.id)
                    
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    user_level = user_data.get('level', 1) if user_data else 1
                    
                    if user_level < 7:
                        self.bot.answer_callback_query(call.id, "🐸 Ты еще мелкий для таких дел! Возвращайся на 7-м уровне!")
                        return
                    
                    existing_order_id, existing_order_data = self.get_user_active_order(call.from_user.id)
                    if existing_order_id is not None:
                        self.bot.answer_callback_query(call.id, "🔄 *У тебя уже есть активный заказ!*")
                        return
                    
                    self.user_order_creation[telegram_id_str] = {
                        "chibi_name": None,
                        "reward": None
                    }
                    
                    create_text = """🕍 *Создаем заказ*
Укажи, какого чибика охотники будут искать, и цену, которую ты готов заплатить. Помни, цена влияет на твою репутацию"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    btn_chibi = types.InlineKeyboardButton("Выбрать чибика", callback_data="cantina_select_chibi")
                    btn_reward = types.InlineKeyboardButton("Установить награду", callback_data="cantina_set_reward")
                    
                    markup.add(btn_chibi)
                    markup.add(btn_reward)
                    markup.add(types.InlineKeyboardButton("Назад", callback_data="cantina_back"))
                    
                    self.bot.edit_message_text(
                        create_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "cantina_select_chibi":
                    chibis, current_page, total_pages = self.get_all_chibis_paginated(1)
                    
                    select_text = """🕍 *Выбираем жертву*
Выбери чибика, которого *хочешь получить*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    for chibi_name in chibis:
                        markup.add(types.InlineKeyboardButton(chibi_name, callback_data=f"cantina_chibi_{chibi_name}"))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"cantina_chibis_page_{((current_page-2) % total_pages) + 1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Назад", callback_data="cantina_back_to_create"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"cantina_chibis_page_{(current_page % total_pages) + 1}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        select_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("cantina_chibis_page_"):
                    page = int(call.data.split("_")[3])
                    chibis, current_page, total_pages = self.get_all_chibis_paginated(page)
                    
                    select_text = """🕍 *Выбираем жертву*
Выбери чибика, которого *хочешь получить*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    for chibi_name in chibis:
                        markup.add(types.InlineKeyboardButton(chibi_name, callback_data=f"cantina_chibi_{chibi_name}"))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"cantina_chibis_page_{((current_page-2) % total_pages) + 1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Назад", callback_data="cantina_back_to_create"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"cantina_chibis_page_{(current_page % total_pages) + 1}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        select_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("cantina_chibi_"):
                    chibi_name = call.data.replace("cantina_chibi_", "")
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str not in self.user_order_creation:
                        self.bot.answer_callback_query(call.id, "⏰ *Сессия создания заказа истекла!*")
                        return
                    
                    self.user_order_creation[telegram_id_str]["chibi_name"] = chibi_name
                    
                    create_text = """🕍 *Создаем заказ*
Укажи, какого чибика охотники будут искать, и цену, которую ты готов заплатить. Помни, цена влияет на твою репутацию"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    btn_chibi = types.InlineKeyboardButton(
                        chibi_name,
                        callback_data="cantina_select_chibi"
                    )
                    
                    if self.user_order_creation[telegram_id_str]["reward"]:
                        btn_reward = types.InlineKeyboardButton(
                            f"Твоя цена: {self.user_order_creation[telegram_id_str]['reward']}",
                            callback_data="cantina_set_reward"
                        )
                    else:
                        btn_reward = types.InlineKeyboardButton("Установить награду", callback_data="cantina_set_reward")
                    
                    markup.add(btn_chibi)
                    markup.add(btn_reward)
                    
                    if self.user_order_creation[telegram_id_str]["reward"]:
                        btn_confirm = types.InlineKeyboardButton("Подтвердить", callback_data="cantina_confirm_order")
                        markup.add(btn_confirm)
                    else:
                        btn_back = types.InlineKeyboardButton("Назад", callback_data="cantina_back")
                        markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        create_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "cantina_set_reward":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str not in self.user_order_creation:
                        self.bot.answer_callback_query(call.id, "⏰ *Сессия создания заказа истекла!*")
                        return
                    
                    recommended_price = random.randint(32, 45)
                    reward_text = f"""🕍 *Устанавливаем плату*
Установи награду, которую *ты* заплатишь за выбранного чибика, если охотник доставит его тебе. Помни, что зарплата влияет на репутацию
•••••••••••••••••
Введи цену и отправь мне. Рекомендованная цена : *{recommended_price}*"""
                    
                    self.user_states[telegram_id_str] = "waiting_for_reward"
                    
                    self.bot.edit_message_text(
                        reward_text,
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "cantina_confirm_order":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str not in self.user_order_creation:
                        self.bot.answer_callback_query(call.id, "⏰ *Сессия создания заказа истекла!*")
                        return
                    
                    order_data = self.user_order_creation[telegram_id_str]
                    
                    if not order_data["chibi_name"] or order_data["reward"] is None:
                        self.bot.answer_callback_query(call.id, "📝 *Заполни все поля!*")
                        return
                    
                    confirm_text = f"""🕍 *Создаем заказ* 
Финальный шаг. Проверь все, чтобы не было неприятностей. Имей в виду, что твоя награда *охотнику* за заказ будет заложена, и вернуть ее можно будет только отменив свой заказ
•••••••••••••••••
Ты заказываешь: *{order_data['chibi_name']}* 
Ты платишь: *{order_data['reward']}*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_create = types.InlineKeyboardButton("Создать", callback_data="cantina_final_create")
                    btn_cancel = types.InlineKeyboardButton("Отменить", callback_data="cantina_final_cancel")
                    markup.add(btn_create, btn_cancel)
                    
                    self.bot.edit_message_text(
                        confirm_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "cantina_final_create":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str not in self.user_order_creation:
                        self.bot.answer_callback_query(call.id, "⏰ *Сессия создания заказа истекла!*")
                        return
                    
                    order_data = self.user_order_creation[telegram_id_str]
                    
                    existing_order_id, existing_order_data = self.get_user_active_order(call.from_user.id)
                    if existing_order_id is not None:
                        self.bot.answer_callback_query(call.id, "🔄 *У тебя уже есть активный заказ!*")
                        return
                    
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    coins = user_data.get('coins', 0) if user_data else 0
                    
                    if coins < order_data["reward"]:
                        self.bot.answer_callback_query(call.id, f"💸 *Недостаточно коинов!* Нужно {order_data['reward']}")
                        return
                    
                    # Списание коинов
                    new_coins = coins - order_data["reward"]
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"coins": new_coins}}
                    )
                    
                    # Создание заказа в базе данных
                    order_id = self.next_order_id
                    order_doc = {
                        "order_id": order_id,
                        "creator_id": telegram_id_str,
                        "chibi_name": order_data["chibi_name"],
                        "reward": order_data["reward"],
                        "status": "active",
                        "date_created": datetime.now()
                    }
                    self.orders_collection.insert_one(order_doc)
                    self.next_order_id += 1
                    
                    self.order_accepted_by[order_id] = []
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    del self.user_order_creation[telegram_id_str]
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        "✅ *Заказ создан!*",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                    # Обновляем список заказов
                    cantina_text = """*🕍 Кантина*
Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    user_order_id, user_order_data = self.get_user_active_order(call.from_user.id)
                    if user_order_id is not None:
                        btn_my_order = types.InlineKeyboardButton(
                            f"🔹 {user_order_data['chibi_name']} - 💰{user_order_data['reward']}",
                            callback_data="cantina_view_my_order"
                        )
                        markup.add(btn_my_order)
                    else:
                        btn_create = types.InlineKeyboardButton("Создать заказ", callback_data="cantina_create_order")
                        markup.add(btn_create)
                    
                    other_orders, current_page, total_pages = self.get_other_orders_paginated(call.from_user.id, 1)
                    
                    for order_id, order_data, is_accepted in other_orders:
                        creator_data = self.users_collection.find_one({"telegram_id": order_data["creator_id"]})
                        creator_name = creator_data.get('first_name', 'Неизвестный') if creator_data else 'Неизвестный'
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = creator_data.get('username') if creator_data else None
                            if creator_username:
                                creator_name = f"@{creator_username}"
                            else:
                                creator_name = "Неизвестный"
                        
                        prefix = "🔸" if is_accepted else ""
                        btn_order = types.InlineKeyboardButton(
                            f"{prefix} {order_data['chibi_name']} - 💰{order_data['reward']} ({creator_name})",
                            callback_data=f"cantina_view_order_{order_id}"
                        )
                        markup.add(btn_order)
                    
                    if total_pages > 1:
                        nav_buttons = []
                        if current_page > 1:
                            nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"cantina_orders_page_{current_page-1}"))
                        
                        nav_buttons.append(types.InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="cantina_orders_info"))
                        
                        if current_page < total_pages:
                            nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"cantina_orders_page_{current_page+1}"))
                        
                        markup.row(*nav_buttons)
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        cantina_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                elif call.data == "cantina_final_cancel":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str in self.user_order_creation:
                        del self.user_order_creation[telegram_id_str]
                    
                    self.bot.edit_message_text(
                        "🕍 *Заказ отменен*",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "cantina_back_to_create":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str not in self.user_order_creation:
                        self.bot.answer_callback_query(call.id, "⏰ *Сессия создания заказа истекла!*")
                        return
                    
                    create_text = """🕍 *Создаем заказ*
Укажи, какого чибика охотники будут искать, и цену, которую ты готов заплатить. Помни, цена влияет на твою репутацию"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if self.user_order_creation[telegram_id_str]["chibi_name"]:
                        btn_chibi = types.InlineKeyboardButton(
                            self.user_order_creation[telegram_id_str]["chibi_name"],
                            callback_data="cantina_select_chibi"
                        )
                    else:
                        btn_chibi = types.InlineKeyboardButton("Выбрать чибика", callback_data="cantina_select_chibi")
                    
                    if self.user_order_creation[telegram_id_str]["reward"]:
                        btn_reward = types.InlineKeyboardButton(
                            f"Твоя цена: {self.user_order_creation[telegram_id_str]['reward']}",
                            callback_data="cantina_set_reward"
                        )
                    else:
                        btn_reward = types.InlineKeyboardButton("Установить награду", callback_data="cantina_set_reward")
                    
                    markup.add(btn_chibi)
                    markup.add(btn_reward)
                    
                    if (self.user_order_creation[telegram_id_str]["chibi_name"] and 
                        self.user_order_creation[telegram_id_str]["reward"]):
                        btn_confirm = types.InlineKeyboardButton("Подтвердить", callback_data="cantina_confirm_order")
                        markup.add(btn_confirm)
                    else:
                        btn_back = types.InlineKeyboardButton("Назад", callback_data="cantina_back")
                        markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        create_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "cantina_back":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str in self.user_order_creation:
                        del self.user_order_creation[telegram_id_str]
                    
                    user_order_id, user_order_data = self.get_user_active_order(call.from_user.id)
                    
                    cantina_text = """*🕍 Кантина*
Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if user_order_id is not None:
                        btn_my_order = types.InlineKeyboardButton(
                            f"🔹 {user_order_data['chibi_name']} - 💰{user_order_data['reward']}",
                            callback_data="cantina_view_my_order"
                        )
                        markup.add(btn_my_order)
                    else:
                        btn_create = types.InlineKeyboardButton("Создать заказ", callback_data="cantina_create_order")
                        markup.add(btn_create)
                    
                    other_orders, current_page, total_pages = self.get_other_orders_paginated(call.from_user.id, 1)
                    
                    for order_id, order_data, is_accepted in other_orders:
                        creator_data = self.users_collection.find_one({"telegram_id": order_data["creator_id"]})
                        creator_name = creator_data.get('first_name', 'Неизвестный') if creator_data else 'Неизвестный'
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = creator_data.get('username') if creator_data else None
                            if creator_username:
                                creator_name = f"@{creator_username}"
                            else:
                                creator_name = "Неизвестный"
                        
                        prefix = "🔸" if is_accepted else ""
                        btn_order = types.InlineKeyboardButton(
                            f"{prefix} {order_data['chibi_name']} - 💰{order_data['reward']} ({creator_name})",
                            callback_data=f"cantina_view_order_{order_id}"
                        )
                        markup.add(btn_order)
                    
                    if total_pages > 1:
                        nav_buttons = []
                        if current_page > 1:
                            nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"cantina_orders_page_{current_page-1}"))
                        
                        nav_buttons.append(types.InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="cantina_orders_info"))
                        
                        if current_page < total_pages:
                            nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"cantina_orders_page_{current_page+1}"))
                        
                        markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        cantina_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("cantina_orders_page_"):
                    page = int(call.data.split("_")[3])
                    
                    user_order_id, user_order_data = self.get_user_active_order(call.from_user.id)
                    
                    cantina_text = """*🕍 Кантина*
Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if user_order_id is not None:
                        btn_my_order = types.InlineKeyboardButton(
                            f"🔹 {user_order_data['chibi_name']} - 💰{user_order_data['reward']}",
                            callback_data="cantina_view_my_order"
                        )
                        markup.add(btn_my_order)
                    else:
                        btn_create = types.InlineKeyboardButton("Создать заказ", callback_data="cantina_create_order")
                        markup.add(btn_create)
                    
                    other_orders, current_page, total_pages = self.get_other_orders_paginated(call.from_user.id, page)
                    
                    for order_id, order_data, is_accepted in other_orders:
                        creator_data = self.users_collection.find_one({"telegram_id": order_data["creator_id"]})
                        creator_name = creator_data.get('first_name', 'Неизвестный') if creator_data else 'Неизвестный'
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = creator_data.get('username') if creator_data else None
                            if creator_username:
                                creator_name = f"@{creator_username}"
                            else:
                                creator_name = "Неизвестный"
                        
                        prefix = "🔸" if is_accepted else ""
                        btn_order = types.InlineKeyboardButton(
                            f"{prefix} {order_data['chibi_name']} - 💰{order_data['reward']} ({creator_name})",
                            callback_data=f"cantina_view_order_{order_id}"
                        )
                        markup.add(btn_order)
                    
                    if total_pages > 1:
                        nav_buttons = []
                        if current_page > 1:
                            nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"cantina_orders_page_{current_page-1}"))
                        
                        nav_buttons.append(types.InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="cantina_orders_info"))
                        
                        if current_page < total_pages:
                            nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"cantina_orders_page_{current_page+1}"))
                        
                        markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        cantina_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "cantina_view_my_order":
                    telegram_id_str = str(call.from_user.id)
                    order_id, order_data = self.get_user_active_order(call.from_user.id)
                    
                    if order_id is None:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    accepted_count = len(self.order_accepted_by.get(order_id, []))
                    date_str = self.format_date(order_data["date_created"])
                    
                    order_text = f"""*🕍 Твой заказ* 
Выбери, что хочешь сделать
•••••••••••••••••
Взялись: *{accepted_count}*
Выложен: *{date_str}*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_cancel = types.InlineKeyboardButton("🙅‍♂️ Отозвать", callback_data="cantina_cancel_my_order")
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="cantina_back")
                    markup.add(btn_cancel)
                    markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        order_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "cantina_cancel_my_order":
                    telegram_id_str = str(call.from_user.id)
                    order_id, order_data = self.get_user_active_order(call.from_user.id)
                    
                    if order_id is None:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    reward = order_data["reward"]
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    if user_data:
                        new_coins = user_data.get('coins', 0) + reward
                        self.users_collection.update_one(
                            {"telegram_id": telegram_id_str},
                            {"$set": {"coins": new_coins}}
                        )
                    
                    # Обновляем статус заказа в базе
                    self.orders_collection.update_one(
                        {"order_id": order_id},
                        {"$set": {"status": "cancelled"}}
                    )
                    
                    accepted_users = self.order_accepted_by.get(order_id, [])
                    for user_id in accepted_users:
                        # Обновляем активные охоты пользователей
                        self.users_collection.update_one(
                            {"telegram_id": user_id},
                            {"$set": {"active_hunt": None}}
                        )
                        
                        user_name = self.users_collection.find_one({"telegram_id": user_id}).get('first_name', 'Игрок') if self.users_collection.find_one({"telegram_id": user_id}) else 'Игрок'
                        sent_message = self.bot.send_message(
                            user_id,
                            f"*Хей, {user_name}!*\nЗаказ, который ты принял, был отозван! Соболезную",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(user_id, sent_message.message_id)] = user_id
                    
                    if order_id in self.order_accepted_by:
                        del self.order_accepted_by[order_id]
                    
                    self.bot.edit_message_text(
                        "🕍 *Заказ отменен*",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("cantina_view_order_"):
                    order_id = int(call.data.split("_")[3])
                    telegram_id_str = str(call.from_user.id)
                    
                    order_data = self.orders_collection.find_one({"order_id": order_id})
                    if not order_data:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    if order_data["status"] != "active":
                        self.bot.answer_callback_query(call.id, "✅ *Заказ уже завершен или отменен!*")
                        self.bot.edit_message_text(
                            "🕍 *Заказ завершен*",
                            call.message.chat.id,
                            call.message.message_id,
                            parse_mode='Markdown'
                        )
                        return
                    
                    is_accepted = telegram_id_str in self.order_accepted_by.get(order_id, [])
                    
                    if is_accepted:
                        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                        hunt_start_time = user_data.get('hunt_start_times', {}).get(str(order_id)) if user_data else None
                        
                        if not hunt_start_time:
                            hunt_start_time = datetime.now()
                            if user_data:
                                hunt_start_times = user_data.get('hunt_start_times', {})
                                hunt_start_times[str(order_id)] = hunt_start_time
                                self.users_collection.update_one(
                                    {"telegram_id": telegram_id_str},
                                    {"$set": {"hunt_start_times": hunt_start_times}}
                                )
                        
                        has_fresh_chibi = self.get_fresh_chibi_count(call.from_user.id, order_data["chibi_name"], hunt_start_time) > 0
                        button_text = "✅ Сдать заказ (1/1)" if has_fresh_chibi else "Сдать заказ (0/1)"
                        
                        order_text = f"""🕍*Твой текущий заказ*
Это заказ от игрока {self.users_collection.find_one({"telegram_id": order_data["creator_id"]}).get('first_name', 'Неизвестный') if self.users_collection.find_one({"telegram_id": order_data["creator_id"]}) else 'Неизвестный'}, который ты принял в кантине, и вся о нем инфа 
•••••••••••••••••
Требуется: *{order_data['chibi_name']}* 
Плата: *{order_data['reward']}*"""
                        
                        markup = types.InlineKeyboardMarkup(row_width=2)
                        btn_complete = types.InlineKeyboardButton(
                            button_text, 
                            callback_data=f"cantina_complete_order_{order_id}" if has_fresh_chibi else "cantina_cannot_complete"
                        )
                        btn_refuse = types.InlineKeyboardButton("Отказаться", callback_data=f"cantina_refuse_order_{order_id}")
                        btn_back = types.InlineKeyboardButton("Назад", callback_data="cantina_back")
                        markup.add(btn_complete, btn_refuse)
                        markup.add(btn_back)
                        
                        self.bot.edit_message_text(
                            order_text,
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=markup,
                            parse_mode='Markdown'
                        )
                    else:
                        creator_data = self.users_collection.find_one({"telegram_id": order_data["creator_id"]})
                        creator_name = creator_data.get('first_name', 'Неизвестный') if creator_data else 'Неизвестный'
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = creator_data.get('username') if creator_data else None
                            if creator_username:
                                creator_name = f"@{creator_username}"
                            else:
                                creator_name = "Неизвестный"
                        
                        user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                        user_level = user_data.get('level', 1) if user_data else 1
                        
                        if user_level < 3:
                            self.bot.answer_callback_query(call.id, "🐸 Ты еще мелкий для гильдии! Возвращайся на 3-м уровне")
                            return
                        
                        order_text = f"""*🕍 Заказ игрока {creator_name}*
Подумай, насколько тебе это выгодно, и прими решение 
•••••••••••••••••
Требуется: {order_data['chibi_name']}
Плата: *💰 {order_data['reward']}*"""
                        
                        markup = types.InlineKeyboardMarkup(row_width=2)
                        btn_accept = types.InlineKeyboardButton("Принять", callback_data=f"cantina_accept_order_{order_id}")
                        btn_howto = types.InlineKeyboardButton("Как охотиться?", url="https://telegra.ph/KANTINA--CHIBIKI-11-01")
                        btn_back = types.InlineKeyboardButton("Назад", callback_data="cantina_back")
                        markup.add(btn_accept, btn_howto)
                        markup.add(btn_back)
                        
                        self.bot.edit_message_text(
                            order_text,
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=markup,
                            parse_mode='Markdown'
                        )
                    
                elif call.data.startswith("cantina_accept_order_"):
                    order_id = int(call.data.split("_")[3])
                    telegram_id_str = str(call.from_user.id)
                    
                    order_data = self.orders_collection.find_one({"order_id": order_id})
                    if not order_data:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    if order_data["status"] != "active":
                        self.bot.answer_callback_query(call.id, "✅ *Заказ уже завершен или отменен!*")
                        return
                    
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    user_level = user_data.get('level', 1) if user_data else 1
                    
                    if user_level < 3:
                        self.bot.answer_callback_query(call.id, "🐸 Ты еще мелкий для гильдии! Возвращайся на 3-м уровне")
                        return
                    
                    if user_data and user_data.get('active_hunt'):
                        self.bot.answer_callback_query(call.id, "🔄 *У тебя уже есть активный заказ!*")
                        return
                    
                    if order_id not in self.order_accepted_by:
                        self.order_accepted_by[order_id] = []
                    
                    if telegram_id_str not in self.order_accepted_by[order_id]:
                        self.order_accepted_by[order_id].append(telegram_id_str)
                    
                    # Обновляем активную охоту пользователя
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"active_hunt": order_id}}
                    )
                    
                    # Обновляем время начала охоты
                    hunt_start_times = user_data.get('hunt_start_times', {}) if user_data else {}
                    hunt_start_times[str(order_id)] = datetime.now()
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"hunt_start_times": hunt_start_times}}
                    )
                    
                    self.bot.answer_callback_query(call.id, "✅ *Заказ принят!*")
                    
                    hunt_start_time = hunt_start_times.get(str(order_id))
                    has_fresh_chibi = self.get_fresh_chibi_count(call.from_user.id, order_data["chibi_name"], hunt_start_time) > 0
                    button_text = "✅ Сдать заказ (1/1)" if has_fresh_chibi else "Сдать заказ (0/1)"
                    
                    order_text = f"""🕍*Твой текущий заказ*
Это заказ от игрока {self.users_collection.find_one({"telegram_id": order_data["creator_id"]}).get('first_name', 'Неизвестный') if self.users_collection.find_one({"telegram_id": order_data["creator_id"]}) else 'Неизвестный'}, который ты принял в кантине, и вся о нем инфа 
•••••••••••••••••
Требуется: *{order_data['chibi_name']}* 
Плата: *{order_data['reward']}*"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn_complete = types.InlineKeyboardButton(
                        button_text, 
                        callback_data=f"cantina_complete_order_{order_id}" if has_fresh_chibi else "cantina_cannot_complete"
                    )
                    btn_refuse = types.InlineKeyboardButton("Отказаться", callback_data=f"cantina_refuse_order_{order_id}")
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="cantina_back")
                    markup.add(btn_complete, btn_refuse)
                    markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        order_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("cantina_refuse_order_"):
                    order_id = int(call.data.split("_")[3])
                    telegram_id_str = str(call.from_user.id)
                    
                    order_data = self.orders_collection.find_one({"order_id": order_id})
                    if not order_data:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    if order_id in self.order_accepted_by and telegram_id_str in self.order_accepted_by[order_id]:
                        self.order_accepted_by[order_id].remove(telegram_id_str)
                    
                    # Обновляем активную охоту пользователя
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"active_hunt": None}}
                    )
                    
                    self.bot.answer_callback_query(call.id, "✅ *Отказ от заказа принят!*")
                    
                    cantina_text = """*🕍 Кантина*
Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    user_order_id, user_order_data = self.get_user_active_order(call.from_user.id)
                    if user_order_id is not None:
                        btn_my_order = types.InlineKeyboardButton(
                            f"🔹 {user_order_data['chibi_name']} - 💰{user_order_data['reward']}",
                            callback_data="cantina_view_my_order"
                        )
                        markup.add(btn_my_order)
                    else:
                        btn_create = types.InlineKeyboardButton("Создать заказ", callback_data="cantina_create_order")
                        markup.add(btn_create)
                    
                    other_orders, current_page, total_pages = self.get_other_orders_paginated(call.from_user.id, 1)
                    
                    for order_id, order_data, is_accepted in other_orders:
                        creator_data = self.users_collection.find_one({"telegram_id": order_data["creator_id"]})
                        creator_name = creator_data.get('first_name', 'Неизвестный') if creator_data else 'Неизвестный'
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = creator_data.get('username') if creator_data else None
                            if creator_username:
                                creator_name = f"@{creator_username}"
                            else:
                                creator_name = "Неизвестный"
                        
                        prefix = "🔸" if is_accepted else ""
                        btn_order = types.InlineKeyboardButton(
                            f"{prefix} {order_data['chibi_name']} - 💰{order_data['reward']} ({creator_name})",
                            callback_data=f"cantina_view_order_{order_id}"
                        )
                        markup.add(btn_order)
                    
                    if total_pages > 1:
                        nav_buttons = []
                        if current_page > 1:
                            nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"cantina_orders_page_{current_page-1}"))
                        
                        nav_buttons.append(types.InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="cantina_orders_info"))
                        
                        if current_page < total_pages:
                            nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"cantina_orders_page_{current_page+1}"))
                        
                        markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        cantina_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("cantina_complete_order_"):
                    order_id = int(call.data.split("_")[3])
                    telegram_id_str = str(call.from_user.id)
                    
                    order_data = self.orders_collection.find_one({"order_id": order_id})
                    if not order_data:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    if order_data["status"] != "active":
                        self.bot.answer_callback_query(call.id, "✅ *Заказ уже завершен или отменен!*")
                        return
                    
                    user_data = self.users_collection.find_one({"telegram_id": telegram_id_str})
                    hunt_start_time = user_data.get('hunt_start_times', {}).get(str(order_id)) if user_data else None
                    
                    if not hunt_start_time:
                        self.bot.answer_callback_query(call.id, "⏰ *Ошибка времени охоты!*")
                        return
                    
                    if self.get_fresh_chibi_count(call.from_user.id, order_data["chibi_name"], hunt_start_time) == 0:
                        self.bot.answer_callback_query(call.id, "🎒 *У тебя нет свежего чибика для этого заказа!*")
                        return
                    
                    # Удаляем чибика у охотника
                    chibis = user_data.get('chibis', [])
                    for i, chibi in enumerate(chibis):
                        if chibi == order_data["chibi_name"]:
                            chibi_time = user_data.get('chibi_timestamps', {}).get(order_data["chibi_name"])
                            if chibi_time and chibi_time > hunt_start_time:
                                del chibis[i]
                                chibi_timestamps = user_data.get('chibi_timestamps', {})
                                if order_data["chibi_name"] in chibi_timestamps and chibi_timestamps[order_data["chibi_name"]] == chibi_time:
                                    del chibi_timestamps[order_data["chibi_name"]]
                                break
                    
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {
                            "chibis": chibis,
                            "chibi_timestamps": user_data.get('chibi_timestamps', {})
                        }}
                    )
                    
                    # Начисляем награду охотнику
                    reward = order_data["reward"]
                    hunter_coins = user_data.get('coins', 0) + reward
                    self.users_collection.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"coins": hunter_coins}}
                    )
                    
                    # Начисляем опыт за выполнение заказа
                    exp_gained = random.randint(25, 35)
                    level_ups, new_level = self.add_exp(call.from_user.id, exp_gained)
                    
                    # Добавляем чибика создателю заказа
                    creator_id = order_data["creator_id"]
                    creator_data = self.users_collection.find_one({"telegram_id": creator_id})
                    if creator_data:
                        creator_chibis = creator_data.get('chibis', [])
                        creator_chibis.append(order_data["chibi_name"])
                        creator_timestamps = creator_data.get('chibi_timestamps', {})
                        creator_timestamps[order_data["chibi_name"]] = datetime.now()
                        
                        self.users_collection.update_one(
                            {"telegram_id": creator_id},
                            {"$set": {
                                "chibis": creator_chibis,
                                "chibi_timestamps": creator_timestamps
                            }}
                        )
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sticker_id = "CAACAgIAAxkBAAE9Js1pAzTTQ9xRej9YYWAs_M_2sMGFnQAC2kkAAkZFCUqenx6Y9nShgTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id)
                    
                    user_name = call.from_user.first_name or "путешественник"
                    complete_text = f"""*{user_name}, ты выполнил заказ!*
Мои поздравления! Думаю, это было достаточно непросто, но ты — первый из наемников, кто справился с ним 
••••••••••••••••••
+ *💰 {reward}* чибикоинов
+ ⭐️ *{exp_gained}* опыта"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        complete_text,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                    creator_name = self.users_collection.find_one({"telegram_id": creator_id}).get('first_name', 'Игрок') if self.users_collection.find_one({"telegram_id": creator_id}) else 'Игрок'
                    sent_message = self.bot.send_message(
                        creator_id,
                        f"*🎉 Твой заказ выполнен!*\nОхотник {user_name} доставил тебе {order_data['chibi_name']}!",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(creator_id, sent_message.message_id)] = creator_id
                    
                    accepted_users = self.order_accepted_by.get(order_id, [])
                    for user_id in accepted_users:
                        if user_id != telegram_id_str:
                            # Обновляем активные охоты других пользователей
                            self.users_collection.update_one(
                                {"telegram_id": user_id},
                                {"$set": {"active_hunt": None}}
                            )
                            
                            user_name = self.users_collection.find_one({"telegram_id": user_id}).get('first_name', 'Игрок') if self.users_collection.find_one({"telegram_id": user_id}) else 'Игрок'
                            sent_message = self.bot.send_message(
                                user_id,
                                f"*Хей, {user_name}!*\nЗаказ, который ты принял, был завершен! Соболезную",
                                parse_mode='Markdown'
                            )
                            self.message_owners[(user_id, sent_message.message_id)] = user_id
                    
                    # Обновляем статус заказа в базе
                    self.orders_collection.update_one(
                        {"order_id": order_id},
                        {"$set": {"status": "completed"}}
                    )
                    
                    if order_id in self.order_accepted_by:
                        del self.order_accepted_by[order_id]
                    
                    # Обновляем активные охоты всех пользователей
                    self.users_collection.update_many(
                        {"active_hunt": order_id},
                        {"$set": {"active_hunt": None}}
                    )
                    
                    if level_ups > 0:
                        threading.Thread(target=self.send_level_up_message, 
                                       args=(call.from_user.id, new_level - level_ups, new_level)).start()
                    
                elif call.data == "cantina_cannot_complete":
                    self.bot.answer_callback_query(call.id, "🤷‍♂️ И что ты собрался сдавать?")
                    
                elif call.data == "chibi_click":
                    self.bot.answer_callback_query(call.id)
                    
                elif call.data == "item_click":
                    self.bot.answer_callback_query(call.id, "🔒 *Этот предмет нельзя использовать!*")
                    
                elif call.data == "empty":
                    self.bot.answer_callback_query(call.id, "📭 *Здесь пусто!*")
                    
                elif call.data == "cantina_current_reward":
                    self.bot.answer_callback_query(call.id, "💰 Текущая цена")
                    
                elif call.data == "cantina_orders_info":
                    self.bot.answer_callback_query(call.id, "📄 Страница заказов")
                    
                else:
                    self.bot.answer_callback_query(call.id)
                    
            except Exception as e:
                logger.error(f"Ошибка в callback: {e}")
                self.bot.answer_callback_query(call.id, "🙈 *Не твое!*", parse_mode='Markdown')

    def run(self):
        logger.info("🤖 Чиби-бот запущен с MongoDB!")
        self.setup_handlers()
        self.bot.infinity_polling()

def get_token():
    return os.getenv('BOT_TOKEN')

PORT = int(os.environ.get('PORT', 5000))

if __name__ == "__main__":
    token = get_token()
    if not token:
        print("❌ Токен не найден!")
        exit(1)
    
    if "RENDER" in os.environ:
        app = Flask(__name__)
        @app.route('/')
        def home():
            return "🤖 Чиби-бот работает с MongoDB!"
        def run_flask():
            app.run(host='0.0.0.0', port=PORT)
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
    
    bot = ChibiBot(token)
    bot.run()
