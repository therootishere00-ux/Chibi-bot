import telebot
from telebot import types
import random
import string
import os
import logging
import threading
import time
from flask import Flask
from datetime import datetime

from config import BOT_CONFIG, BOT_TEXTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChibiBot:
    def __init__(self, token):
        self.bot = telebot.TeleBot(token)
        self.users = {}  # Храним в памяти
        self.used_ids = set()
        self.user_chibis = {}  # Храним чибиков пользователей: {user_id: [chibi_name1, chibi_name2, ...]}
        self.user_items = {}   # Храним предметы пользователей: {user_id: {"🧧 Чиби-пак": 1}}
        self.user_tasks = {}   # Храним текущие задания пользователей: {user_id: {"chibi": "имя", "reward": 35, "emoji": "🐊", "name": "Грирт"}}
        self.user_coins = {}   # Храним коины пользователей: {user_id: 0}
        self.user_levels = {}  # Храним уровни пользователей: {user_id: 1}
        self.user_exp = {}     # Храним опыт пользователей: {user_id: 0}
        self.gift_selections = {}  # Храним выбранных чибиков для подарка: {user_id: {"target_user_id": "123", "chibi_name": "имя"}}
        self.cantina_orders = {}   # Храним заказы кантины
        self.user_order_creation = {}  # Храним данные создания заказа
        self.user_active_hunts = {}    # Храним активные охоты пользователей: {user_id: order_id}
        self.order_accepted_by = {}    # Храним кто принял заказы: {order_id: [user_id1, user_id2]}
        self.user_states = {}          # Храним состояния пользователей для ввода текста
        self.user_chibi_timestamps = {} # Храним когда получены чибики: {user_id: {chibi_name: datetime}}
        self.hunt_start_times = {}     # Храним время начала охоты: {user_id: {order_id: datetime}}
        self.next_order_id = 1
        self.message_owners = {}       # Храним владельцев сообщений: {(chat_id, message_id): user_id}
        
    def generate_unique_user_id(self):
        attempts = 0
        while attempts < 100:
            letter = random.choice(string.ascii_uppercase)
            numbers = ''.join(random.choices(string.digits, k=4))
            position = random.randint(0, 1)
            user_id = letter + numbers if position == 0 else numbers + letter
            if user_id not in self.used_ids:
                self.used_ids.add(user_id)
                return user_id
            attempts += 1
        return f"U{random.randint(1000, 9999)}"
    
    def get_or_create_user(self, telegram_id, first_name=None, username=None):
        telegram_id_str = str(telegram_id)
        
        if telegram_id_str in self.users:
            # Существующий пользователь
            self.users[telegram_id_str]['last_active'] = datetime.now()
            return self.users[telegram_id_str], False
        else:
            # Новый пользователь
            user_id = self.generate_unique_user_id()
            user_data = {
                'user_id': user_id,
                'first_name': first_name,
                'username': username,
                'registration_date': datetime.now(),
                'last_active': datetime.now()
            }
            self.users[telegram_id_str] = user_data
            # Инициализируем коллекцию чибиков для нового пользователя
            self.user_chibis[telegram_id_str] = []
            # Инициализируем предметы и выдаем бесплатный Чиби-пак
            self.user_items[telegram_id_str] = {"🧧 Чиби-пак": 1}
            # Инициализируем коины
            self.user_coins[telegram_id_str] = 0
            # Инициализируем уровни и опыт
            self.user_levels[telegram_id_str] = 1
            self.user_exp[telegram_id_str] = 0
            # Инициализируем временные метки чибиков
            self.user_chibi_timestamps[telegram_id_str] = {}
            logger.info(f"Новый пользователь: {user_id}")
            return user_data, True

    def get_required_exp(self, level):
        """Вычисляет требуемый опыт для перехода на следующий уровень"""
        if level < 7:
            return level * 100
        elif level < 15:
            return 600 + (level - 6) * 150
        elif level < 30:
            return 1950 + (level - 14) * 200
        else:
            return 4950 + (level - 29) * 300

    def add_exp(self, telegram_id, exp_amount):
        """Добавляет опыт пользователю и проверяет повышение уровня"""
        telegram_id_str = str(telegram_id)
        
        if telegram_id_str not in self.user_levels:
            self.user_levels[telegram_id_str] = 1
        if telegram_id_str not in self.user_exp:
            self.user_exp[telegram_id_str] = 0
        
        current_level = self.user_levels[telegram_id_str]
        self.user_exp[telegram_id_str] += exp_amount
        
        # Проверяем повышение уровня
        required_exp = self.get_required_exp(current_level)
        level_ups = 0
        
        while self.user_exp[telegram_id_str] >= required_exp:
            self.user_exp[telegram_id_str] -= required_exp
            current_level += 1
            self.user_levels[telegram_id_str] = current_level
            level_ups += 1
            required_exp = self.get_required_exp(current_level)
        
        return level_ups, current_level

    def send_level_up_message(self, telegram_id, old_level, new_level):
        """Отправляет сообщение о повышении уровня с задержкой"""
        time.sleep(1)  # Задержка 1 секунда
        
        telegram_id_str = str(telegram_id)
        user_name = self.users.get(telegram_id_str, {}).get('first_name', 'путешественник')
        
        # Начисляем чиби-пак
        if telegram_id_str not in self.user_items:
            self.user_items[telegram_id_str] = {}
        if "🧧 Чиби-пак" not in self.user_items[telegram_id_str]:
            self.user_items[telegram_id_str]["🧧 Чиби-пак"] = 0
        self.user_items[telegram_id_str]["🧧 Чиби-пак"] += 1
        
        # Отправляем стикер
        try:
            sticker_id = "CAACAgIAAxkBAAE9VHtpCGLDUXiyHkIeGqv7M2eqFbN3eQAC1kgAAuSPEUq4MV_FOLGn0zYE"
            self.bot.send_sticker(telegram_id, sticker_id)
        except:
            pass
        
        # Отправляем сообщение
        level_text = f"""*Эй, {user_name}!*
_Ты только что апнул новый уровень! Поздравляю!_
`•••••••••••••••••••`
*Уровень {old_level} —> Уровень {new_level}*
`•••••••••••••••••••`
И чтобы ты не расслаблялся, держи небольшой подгон:
+ *🧧 1* Чиби-пак"""
        
        try:
            sent_message = self.bot.send_message(telegram_id, level_text, parse_mode='Markdown')
            self.message_owners[(telegram_id, sent_message.message_id)] = telegram_id_str
        except:
            pass

    def format_exp(self, exp):
        """Форматирует опыт для отображения"""
        if exp < 1000:
            return str(exp)
        elif exp < 1000000:
            return f"{exp/1000:.1f}K".replace('.0K', 'K')
        else:
            return f"{exp/1000000:.1f}M".replace('.0M', 'M')

    def add_chibi_to_user(self, telegram_id, chibi_name):
        """Добавляет чибика пользователю с временной меткой"""
        telegram_id_str = str(telegram_id)
        if telegram_id_str not in self.user_chibis:
            self.user_chibis[telegram_id_str] = []
        if telegram_id_str not in self.user_chibi_timestamps:
            self.user_chibi_timestamps[telegram_id_str] = {}
        
        self.user_chibis[telegram_id_str].append(chibi_name)
        # Сохраняем время получения чибика
        self.user_chibi_timestamps[telegram_id_str][chibi_name] = datetime.now()

    def get_fresh_chibi_count(self, telegram_id, chibi_name, hunt_start_time):
        """Получает количество свежих чибиков (полученных после начала охоты)"""
        telegram_id_str = str(telegram_id)
        if (telegram_id_str not in self.user_chibis or 
            telegram_id_str not in self.user_chibi_timestamps):
            return 0
        
        count = 0
        for chibi in self.user_chibis[telegram_id_str]:
            if chibi == chibi_name:
                chibi_time = self.user_chibi_timestamps[telegram_id_str].get(chibi_name)
                if chibi_time and chibi_time > hunt_start_time:
                    count += 1
        return count

    def get_random_chibi(self, from_pack=False):
        """Получает случайный чиби из папки common или secret"""
        if from_pack and random.random() <= 0.05:  # 5% шанс на секретного чибика из пака
            chibi_folder = "chibis/secret"
        else:
            chibi_folder = "chibis/common"
        
        # Проверяем существование папки
        if not os.path.exists(chibi_folder):
            logger.error(f"Папка {chibi_folder} не найдена!")
            return None, None, "Common"
        
        # Получаем список PNG файлов
        chibi_files = [f for f in os.listdir(chibi_folder) if f.lower().endswith('.png')]
        
        if not chibi_files:
            logger.error(f"В папке {chibi_folder} нет PNG файлов!")
            return None, None, "Common"
        
        # Выбираем случайный файл
        random_file = random.choice(chibi_files)
        file_path = os.path.join(chibi_folder, random_file)
        
        # Форматируем название файла
        file_name = os.path.splitext(random_file)[0]  # Убираем расширение
        formatted_name = file_name.replace('_', ' ')  # Заменяем _ на пробелы
        
        # Определяем редкость
        rarity = "Secret" if from_pack and chibi_folder == "chibis/secret" else "Common"
        
        return file_path, formatted_name, rarity

    def get_all_common_chibis(self):
        """Получает список всех common чибиков"""
        chibi_folder = "chibis/common"
        
        if not os.path.exists(chibi_folder):
            logger.error(f"Папка {chibi_folder} не найдена!")
            return []
        
        chibi_files = [f for f in os.listdir(chibi_folder) if f.lower().endswith('.png')]
        chibi_names = [os.path.splitext(f)[0].replace('_', ' ') for f in chibi_files]
        
        return sorted(chibi_names)  # Сортируем по алфавиту

    def get_chibi_count(self, telegram_id, chibi_name):
        """Получает количество конкретного чибика у пользователя"""
        telegram_id_str = str(telegram_id)
        if telegram_id_str not in self.user_chibis:
            return 0
        return self.user_chibis[telegram_id_str].count(chibi_name)

    def generate_task(self, telegram_id):
        """Генерирует случайное задание для пользователя"""
        telegram_id_str = str(telegram_id)
        
        # Если у пользователя уже есть активное задание, возвращаем его
        if telegram_id_str in self.user_tasks and self.user_tasks[telegram_id_str] is not None:
            return self.user_tasks[telegram_id_str]
        
        # Создаем новое задание
        # Случайные эмодзи
        emojis = ['🐊', '🐸', '🤖', '⛄️', '🐲', '👽']
        
        # Случайные имена
        names = ['Грирт', 'Таррек', 'Грит', 'Тарр', 'Крилл', 'Гето', 'Дин', 'Боксо', 'Мерин', 'Хрило', 'Гомадо', 'Грож']
        
        # Случайные реплики
        phrases = [
            "Эй, ты! Принеси-ка мне {chibi}, я щедро тебя награжу!",
            "Приветствую… Очень хочу заполучить {chibi}, если принесешь мне его, в долгу не останусь",
            "Бурабура, лакуш'н, принеси мне {chibi}, я готов платить"
        ]
        
        # Получаем случайный чибик для задания
        _, chibi_name, _ = self.get_random_chibi()
        if chibi_name is None:
            chibi_name = "редкого чибика"  # Запасной вариант
        
        # Случайная награда
        reward = random.randint(32, 49)
        
        # Выбираем случайные элементы
        emoji = random.choice(emojis)
        name = random.choice(names)
        phrase = random.choice(phrases).format(chibi=chibi_name)
        
        # Сохраняем задание для пользователя
        task_data = {
            "chibi": chibi_name,
            "reward": reward,
            "emoji": emoji,
            "name": name,
            "phrase": phrase
        }
        
        self.user_tasks[telegram_id_str] = task_data
        return task_data

    def get_task_text(self, task_data, telegram_id):
        """Формирует текст задания с проверкой выполнения"""
        telegram_id_str = str(telegram_id)
        
        # Проверяем, есть ли у пользователя нужный чибик
        has_chibi = self.get_chibi_count(telegram_id, task_data["chibi"]) > 0
        button_text = "✅ Сдать задание (1/1)" if has_chibi else "Сдать задание (0/1)"
        
        task_text = f"""*{task_data['emoji']} {task_data['name']}*
_{task_data['phrase']}_
`•••••••••••••••••••`
Дам *💰 {task_data['reward']}* за {task_data['chibi']}"""
        
        return task_text, button_text, has_chibi

    def get_user_chibis_paginated(self, telegram_id, page=1, per_page=8):
        """Получает чибиков пользователя с пагинацией"""
        telegram_id_str = str(telegram_id)
        if telegram_id_str not in self.user_chibis:
            self.user_chibis[telegram_id_str] = []
        
        chibis = self.user_chibis[telegram_id_str]
        
        # Подсчитываем количество каждого чибика
        chibi_counts = {}
        for chibi in chibis:
            chibi_counts[chibi] = chibi_counts.get(chibi, 0) + 1
        
        # Сортируем по количеству (от большего к меньшему), затем по алфавиту
        sorted_chibis = sorted(
            [(name, count) for name, count in chibi_counts.items()],
            key=lambda x: (-x[1], x[0])
        )
        
        # Пагинация
        total_pages = max(1, (len(sorted_chibis) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_chibis = sorted_chibis[start_idx:end_idx]
        
        return page_chibis, page, total_pages

    def get_user_items_paginated(self, telegram_id, page=1, per_page=8):
        """Получает предметы пользователя с пагинацией"""
        telegram_id_str = str(telegram_id)
        if telegram_id_str not in self.user_items:
            self.user_items[telegram_id_str] = {}
        
        items = self.user_items[telegram_id_str]
        
        # Фильтруем предметы с количеством > 0
        active_items = {name: count for name, count in items.items() if count > 0}
        
        # Сортируем по количеству (от большего к меньшему), затем по алфавиту
        sorted_items = sorted(
            [(name, count) for name, count in active_items.items()],
            key=lambda x: (-x[1], x[0])
        )
        
        # Пагинация
        total_pages = max(1, (len(sorted_items) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_items = sorted_items[start_idx:end_idx]
        
        return page_items, page, total_pages

    def get_user_chibis_for_gift(self, telegram_id, page=1, per_page=6):
        """Получает чибиков пользователя для выбора подарка"""
        telegram_id_str = str(telegram_id)
        if telegram_id_str not in self.user_chibis:
            self.user_chibis[telegram_id_str] = []
        
        chibis = self.user_chibis[telegram_id_str]
        
        # Подсчитываем количество каждого чибика
        chibi_counts = {}
        for chibi in chibis:
            chibi_counts[chibi] = chibi_counts.get(chibi, 0) + 1
        
        # Сортируем по количеству (от большего к меньшему), затем по алфавиту
        sorted_chibis = sorted(
            [(name, count) for name, count in chibi_counts.items()],
            key=lambda x: (-x[1], x[0])
        )
        
        # Пагинация
        total_pages = max(1, (len(sorted_chibis) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_chibis = sorted_chibis[start_idx:end_idx]
        
        return page_chibis, page, total_pages

    def get_all_chibis_paginated(self, page=1, per_page=6):
        """Получает все common чибики с пагинацией"""
        all_chibis = self.get_all_common_chibis()
        
        # Пагинация
        total_pages = max(1, (len(all_chibis) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_chibis = all_chibis[start_idx:end_idx]
        
        return page_chibis, page, total_pages

    def get_user_active_order(self, telegram_id):
        """Получает активный заказ пользователя"""
        telegram_id_str = str(telegram_id)
        for order_id, order_data in self.cantina_orders.items():
            if order_data["creator_id"] == telegram_id_str and order_data["status"] == "active":
                return order_id, order_data
        return None, None

    def get_other_orders_paginated(self, telegram_id, page=1, per_page=7):
        """Получает заказы других пользователей с пагинацией"""
        telegram_id_str = str(telegram_id)
        other_orders = []
        
        for order_id, order_data in self.cantina_orders.items():
            if (order_data["creator_id"] != telegram_id_str and 
                order_data["status"] == "active"):
                # Проверяем, принял ли пользователь этот заказ
                is_accepted = telegram_id_str in self.order_accepted_by.get(order_id, [])
                other_orders.append((order_id, order_data, is_accepted))
        
        # Сортируем по награде (от высокой к низкой)
        other_orders.sort(key=lambda x: x[1]["reward"], reverse=True)
        
        # Пагинация
        total_pages = max(1, (len(other_orders) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_orders = other_orders[start_idx:end_idx]
        
        return page_orders, page, total_pages

    def format_date(self, date):
        """Форматирует дату в формат '25авг 2025'"""
        months = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 
                 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
        return f"{date.day}{months[date.month-1]} {date.year}"

    def check_message_ownership(self, call):
        """Проверяет, принадлежит ли сообщение пользователю (только в группах)"""
        if call.message.chat.type == 'private':
            return True
            
        telegram_id_str = str(call.from_user.id)
        message_key = (call.message.chat.id, call.message.message_id)
        
        if message_key in self.message_owners:
            if self.message_owners[message_key] != telegram_id_str:
                self.bot.answer_callback_query(call.id, "🙈 *Не трогай чужое!*", parse_mode='Markdown')
                return False
        # Если сообщение не зарегистрировано, разрешаем нажатие (на всякий случай)
        return True

    def setup_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start_handler(message):
            # Игнорируем команду /start в группах
            if message.chat.type != 'private':
                return
                
            try:
                user_data, is_new_user = self.get_or_create_user(
                    message.from_user.id,
                    message.from_user.first_name,
                    message.from_user.username
                )
                
                user_name = message.from_user.first_name or "путешественник"
                
                # Отправляем разные стикеры для нового и существующего пользователя
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
                    # Сохраняем владельца сообщения
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    sent_message = self.bot.send_message(message.chat.id, BOT_TEXTS['already_started'], parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
                self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)

        @self.bot.message_handler(commands=['myid'])
        def myid_handler(message):
            try:
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
                    sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')

        @self.bot.message_handler(commands=['balance'])
        def balance_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                coins = self.user_coins.get(telegram_id_str, 0)
                
                balance_text = f"💰 У тебя — *{coins}* коинов!"
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, balance_text, parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, balance_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')

        @self.bot.message_handler(commands=['level'])
        def level_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                level = self.user_levels.get(telegram_id_str, 1)
                current_exp = self.user_exp.get(telegram_id_str, 0)
                required_exp = self.get_required_exp(level)
                
                level_text = f"""🎯 *Твой уровень: {level}*
`{self.format_exp(current_exp)}/{self.format_exp(required_exp)}`"""
                
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, level_text, parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, level_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')

        @self.bot.message_handler(commands=['mart'])
        def mart_handler(message):
            try:
                mart_text = """🎏 *Лавка джавы*
_Джавы, может, и не отличаются умом, но зато точно знают толк в ценах!_"""
                
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
                    sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')

        @self.bot.message_handler(commands=['chibi'])
        def chibi_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                file_path, chibi_name, rarity = self.get_random_chibi(from_pack=False)
                
                if file_path is None:
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(message.chat.id, "🌀 *Чибики сейчас отдыхают!* Загляни позже", parse_mode='Markdown')
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, "🌀 *Чибики сейчас отдыхают!* Загляни позже", parse_mode='Markdown')
                    return
                
                # Проверяем, есть ли активная охота у пользователя
                active_hunt_order_id = self.user_active_hunts.get(telegram_id_str)
                hunt_chibi_needed = None
                hunt_start_time = None
                if active_hunt_order_id and active_hunt_order_id in self.cantina_orders:
                    hunt_chibi_needed = self.cantina_orders[active_hunt_order_id]["chibi_name"]
                    hunt_start_time = self.hunt_start_times.get(telegram_id_str, {}).get(active_hunt_order_id)
                
                # Добавляем чибика в коллекцию пользователя
                self.add_chibi_to_user(message.from_user.id, chibi_name)
                
                # Получаем количество этого чибика у пользователя
                chibi_count = self.get_chibi_count(message.from_user.id, chibi_name)
                
                # Начисляем опыт за чибика
                exp_gained = random.randint(12, 19)
                level_ups, new_level = self.add_exp(message.from_user.id, exp_gained)
                
                # Формируем текст сообщения
                rarity_emoji = "🔷" if rarity == "Common" else "💠"
                
                if hunt_chibi_needed and chibi_name == hunt_chibi_needed:
                    chibi_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Этот чибик нужен тебе, чтобы выполнить заказ в кантине! Скорее сдай его, пока конкуренты тебя не опередили_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _{rarity}_
У тебя: *{chibi_count}*
`•••••••••••••••••••`
+ ⭐️ *{exp_gained}* опыта"""
                else:
                    chibi_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Надеюсь, он тебе понравился! Приходи еще через *3ч 59м*_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _{rarity}_
У тебя: {chibi_count}
`•••••••••••••••••••`
+ ⭐️ *{exp_gained}* опыта"""
                
                # Отправляем картинку с текстом
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
                        # В группах отправляем фото без реплая
                        sent_message = self.bot.send_photo(
                            message.chat.id,
                            photo,
                            caption=chibi_text,
                            parse_mode='Markdown'
                        )
                        self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    
                logger.info(f"Отправлен чиби: {chibi_name} (Редкость: {rarity})")
                
                # Отправляем сообщение о повышении уровня с задержкой
                if level_ups > 0:
                    threading.Thread(target=self.send_level_up_message, 
                                   args=(message.from_user.id, new_level - level_ups, new_level)).start()
                    
            except Exception as e:
                logger.error(f"Ошибка при отправке чиби: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')

        @self.bot.message_handler(commands=['task'])
        def task_handler(message):
            try:
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
                    sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')

        @self.bot.message_handler(commands=['menu'])
        def menu_handler(message):
            try:
                menu_text = """*✨ Меню* 
_Здесь ты найдешь все, что нужно, но не имеет команды. Мы постарались_"""
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn_warehouse = types.InlineKeyboardButton("📦 Склад", callback_data="menu_warehouse")
                btn_channel = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
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
                    sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')

        @self.bot.message_handler(commands=['gift'])
        def gift_handler(message):
            # Запрещаем команду в группах
            if message.chat.type != 'private':
                self.bot.reply_to(message, "🙅‍♂️ *Не-не, дружок!* Эта команда доступна только в *личке с ботом*", parse_mode='Markdown')
                return
                
            try:
                if len(message.text.split()) < 2:
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "🐲 *Не-не, самому себе подарки не дарим!* Попробуй найти друзей\n\n_Используй: `/gift [ID_пользователя]`_",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    return
                
                target_user_id = message.text.split()[1].strip()
                
                target_user_found = False
                target_user_data = None
                
                for telegram_id_str, user_data in self.users.items():
                    if user_data['user_id'] == target_user_id:
                        target_user_found = True
                        target_user_data = user_data
                        break
                
                if not target_user_found:
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "👻 *Такого друга еще нет!* Проверь ID и попробуй снова",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)
                    return
                
                if str(message.from_user.id) in self.users and self.users[str(message.from_user.id)]['user_id'] == target_user_id:
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
                    "target_telegram_id": None,
                    "target_name": target_user_data.get('first_name', 'пользователь')
                }
                
                for telegram_id, user_data in self.users.items():
                    if user_data['user_id'] == target_user_id:
                        self.gift_selections[telegram_id_str]["target_telegram_id"] = telegram_id
                        break
                
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
_Выбери, какого чибика подаришь_"""
                
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
                sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
                self.message_owners[(message.chat.id, sent_message.message_id)] = str(message.from_user.id)

        @self.bot.message_handler(commands=['cantina'])
        def cantina_handler(message):
            # Запрещаем команду в группах
            if message.chat.type != 'private':
                self.bot.reply_to(message, "🙅‍♂️ *Не-не, дружок!* Эта команда доступна только в *личке с ботом*", parse_mode='Markdown')
                return
                
            try:
                telegram_id_str = str(message.from_user.id)
                
                user_order_id, user_order_data = self.get_user_active_order(message.from_user.id)
                
                cantina_text = """*🕍 Кантина*
_Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…_"""
                
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
                    creator_name = self.users.get(order_data["creator_id"], {}).get('first_name', 'Неизвестный')
                    if not creator_name or creator_name == 'Неизвестный':
                        creator_username = self.users.get(order_data["creator_id"], {}).get('username')
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
                sent_message = self.bot.send_message(message.chat.id, "⛓️‍💥 *Друг, потеряно соединение!* Попробуй снова", parse_mode='Markdown')
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
                        
                        # Сохраняем цену
                        if telegram_id_str in self.user_order_creation:
                            self.user_order_creation[telegram_id_str]["reward"] = reward
                        
                        # Очищаем состояние
                        self.user_states[telegram_id_str] = None
                        
                        # Возвращаем к созданию заказа
                        create_text = """🕍 *Создаем заказ*
_Укажи, какого чибика охотники будут искать, и цену, которую ты готов заплатить. Помни, цена влияет на твою репутацию_"""
                        
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
                        
                        # Редактируем сообщение вместо отправки нового
                        self.bot.edit_message_text(
                            create_text,
                            message.chat.id,
                            message.message_id - 1,  # Предыдущее сообщение
                            reply_markup=markup,
                            parse_mode='Markdown'
                        )
                        
                        # Удаляем сообщение с вводом цены
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

        # Обработчик callback для кнопок
        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call):
            try:
                # Проверяем владельца сообщения (только в группах)
                if not self.check_message_ownership(call):
                    return

                if call.data == "task_complete":
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str not in self.user_tasks or self.user_tasks[telegram_id_str] is None:
                        self.bot.answer_callback_query(call.id, "🎯 Задание уже выполнено!")
                        return
                    
                    task_data = self.user_tasks[telegram_id_str]
                    
                    if telegram_id_str in self.user_chibis and task_data["chibi"] in self.user_chibis[telegram_id_str]:
                        self.user_chibis[telegram_id_str].remove(task_data["chibi"])
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sticker_id = "CAACAgIAAxkBAAE9Js9pAzTWs9gLLtl9Gqz_9V_4sbwXqgAC7EYAAjNREEqhVSL_nxyHZTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id)
                    
                    reward = task_data["reward"]
                    if telegram_id_str not in self.user_coins:
                        self.user_coins[telegram_id_str] = 0
                    self.user_coins[telegram_id_str] += reward
                    
                    # Начисляем опыт за задание
                    exp_gained = random.randint(19, 25)
                    level_ups, new_level = self.add_exp(call.from_user.id, exp_gained)
                    
                    user_nick = call.from_user.first_name or "путешественник"
                    complete_text = f"""*Ес! {user_nick}, ты выполнил таск!*
_За это ты получаешь обещанную награду. Даже не буду гадать, сколько ты выбивал нужного чибика_
`•••••••••••••••••••`
+ 💰*{reward}* коинов
+ ⭐️ *{exp_gained}* опыта"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        complete_text,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                    self.user_tasks[telegram_id_str] = None
                    
                    # Отправляем сообщение о повышении уровня с задержкой
                    if level_ups > 0:
                        threading.Thread(target=self.send_level_up_message, 
                                       args=(call.from_user.id, new_level - level_ups, new_level)).start()
                    
                elif call.data == "task_cannot_complete":
                    self.bot.answer_callback_query(call.id, "🎒 *Нужного чибика нет!* Сначала найди его")
                    
                elif call.data == "task_skip":
                    telegram_id_str = str(call.from_user.id)
                    self.user_tasks[telegram_id_str] = None
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    skip_text = """✨*Ты пропустил таск. Жди новый!*
_Осталось 8ч 59м_"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        skip_text,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                elif call.data == "task_skip_confirm":
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str not in self.user_tasks or self.user_tasks[telegram_id_str] is None:
                        self.bot.answer_callback_query(call.id, "🎯 Нет активного задания!")
                        return
                    
                    task_data = self.user_tasks[telegram_id_str]
                    
                    skip_text = f"""{task_data['emoji']}* Ты точно хочешь пропустить задание?*
_Придется долго ждать следующее, но пропуск бесплатный_"""
                    
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
                    if telegram_id_str not in self.user_tasks or self.user_tasks[telegram_id_str] is None:
                        self.bot.answer_callback_query(call.id, "🎯 Нет активного задания!")
                        return
                    
                    task_data = self.user_tasks[telegram_id_str]
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
_Выбери, на какой раздел склада хочешь глянуть_"""
                    
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
_Великолепные и неповторимые. Ну, почти…
Страница {current_page}/{total_pages}_"""
                    
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
_Тут хранятся твои боксы. Других предметов в боте пока и нет…
Страница {current_page}/{total_pages}_"""
                    
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
                    pack_count = self.user_items.get(telegram_id_str, {}).get("🧧 Чиби-пак", 0)
                    
                    confirm_text = f"""*Ты точно хочешь открыть 🧧 Чиби-пак?*
_Хотя что тебе еще делать с ним? Разве что повесить на стену и любоваться_"""
                    
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
                    
                    current_packs = self.user_items.get(telegram_id_str, {}).get("🧧 Чиби-пак", 0)
                    if current_packs < count:
                        self.bot.answer_callback_query(call.id, "🎒 *Недостаточно Чиби-паков!*")
                        return
                    
                    self.user_items[telegram_id_str]["🧧 Чиби-пак"] = current_packs - count
                    
                    for i in range(count):
                        file_path, chibi_name, rarity = self.get_random_chibi(from_pack=True)
                        
                        if file_path is not None:
                            telegram_id_str = str(call.from_user.id)
                            active_hunt_order_id = self.user_active_hunts.get(telegram_id_str)
                            hunt_chibi_needed = None
                            hunt_start_time = None
                            if active_hunt_order_id and active_hunt_order_id in self.cantina_orders:
                                hunt_chibi_needed = self.cantina_orders[active_hunt_order_id]["chibi_name"]
                                hunt_start_time = self.hunt_start_times.get(telegram_id_str, {}).get(active_hunt_order_id)
                            
                            self.add_chibi_to_user(call.from_user.id, chibi_name)
                            
                            chibi_count = self.get_chibi_count(call.from_user.id, chibi_name)
                            
                            rarity_emoji = "🔷" if rarity == "Common" else "💠"
                            
                            if hunt_chibi_needed and chibi_name == hunt_chibi_needed:
                                chibi_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Этот чибик нужен тебе, чтобы выполнить заказ в кантине! Скорее сдай его, пока конкуренты тебя не опередили_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _{rarity}_
У тебя: *{chibi_count}*"""
                            else:
                                chibi_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Надеюсь, он тебе понравился!_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _{rarity}_
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
_Тут хранятся твои боксы. Других предметов в боте пока и нет…
Страница {current_page}/{total_pages}_"""
                    
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
_Да брось, знаю что так руки и чешутся!_"""
                    
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
                    coins = self.user_coins.get(telegram_id_str, 0)
                    
                    if coins < 120:
                        self.bot.answer_callback_query(call.id, "💸 *Недостаточно коинов!* Нужно 120.")
                        return
                    
                    self.user_coins[telegram_id_str] = coins - 120
                    
                    if telegram_id_str not in self.user_items:
                        self.user_items[telegram_id_str] = {}
                    
                    if "🧧 Чиби-пак" not in self.user_items[telegram_id_str]:
                        self.user_items[telegram_id_str]["🧧 Чиби-пак"] = 0
                    
                    self.user_items[telegram_id_str]["🧧 Чиби-пак"] += 1
                    
                    self.bot.answer_callback_query(call.id, "🎉 Чиби-пак куплен!")
                    
                    mart_text = """🎏 *Лавка джавы*
_Джавы, может, и не отличаются умом, но зато точно знают толк в ценах!_"""
                    
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
_Джавы, может, и не отличаются умом, но зато точно знают толк в ценах!_"""
                    
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
                    bonus = random.randint(7, 19)
                    
                    if telegram_id_str not in self.user_coins:
                        self.user_coins[telegram_id_str] = 0
                    self.user_coins[telegram_id_str] += bonus
                    
                    user_name = call.from_user.first_name or "путешественник"
                    bonus_text = f"""🎁 *Эй, {user_name}!*
_Ты только что получил ежедневный бонус!_ 
`•••••••••••••••••`
+ 💰*{bonus}* коинов"""
                    
                    self.bot.edit_message_text(
                        bonus_text,
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "menu_back":
                    menu_text = """*✨ Меню* 
_Здесь ты найдешь все, что нужно, но не имеет команды. Мы постарались_"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn_warehouse = types.InlineKeyboardButton("📦 Склад", callback_data="menu_warehouse")
                    btn_channel = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
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
_Выбери, какого чибика подаришь_"""
                    
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
_Ты уверен, что хочешь этого? Назад вернуть уже не получится_
_•••••••••••••••_
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
                    
                    if telegram_id_str not in self.user_chibis or chibi_name not in self.user_chibis[telegram_id_str]:
                        self.bot.answer_callback_query(call.id, "🎒 *У тебя больше нет этого чибика!*")
                        return
                    
                    self.user_chibis[telegram_id_str].remove(chibi_name)
                    
                    if target_telegram_id not in self.user_chibis:
                        self.user_chibis[target_telegram_id] = []
                    self.user_chibis[target_telegram_id].append(chibi_name)
                    
                    # Обновляем временную метку для получателя (чтобы чибик считался свежим для заказов)
                    if target_telegram_id not in self.user_chibi_timestamps:
                        self.user_chibi_timestamps[target_telegram_id] = {}
                    self.user_chibi_timestamps[target_telegram_id][chibi_name] = datetime.now()
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sticker_id_sender = "CAACAgIAAxkBAAE9JtFpAzTjbRJ884hA4YNjTqPc7Z05lAACQEgAAlZVEUqWc8vDGvLqWTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id_sender)
                    
                    sender_name = call.from_user.first_name or "Отправитель"
                    sender_text = f"""*✨ Чибик отправлен! 
_Надеюсь, {target_name} он понравится!_*"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        sender_text,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                    sticker_id_receiver = "CAACAgIAAxkBAAE9OxxpBRLZ5OANTuRD-97sRPdCONwv0AACU0YAAkVlEErI0vjxKMrHnTYE"
                    self.bot.send_sticker(target_telegram_id, sticker_id_receiver)
                    
                    receiver_text = f"""*💌 Тебе подарок!*
_{sender_name} подарил тебе {chibi_name}!_"""
                    
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
                    
                # Обработчики для кантины
                elif call.data == "cantina_create_order":
                    telegram_id_str = str(call.from_user.id)
                    
                    # Проверяем уровень пользователя
                    user_level = self.user_levels.get(telegram_id_str, 1)
                    if user_level < 7:
                        self.bot.answer_callback_query(call.id, "📊 *Ты еще не дорос!* Минимальный уровень - 7")
                        return
                    
                    # Проверяем, есть ли уже активный заказ
                    existing_order_id, existing_order_data = self.get_user_active_order(call.from_user.id)
                    if existing_order_id is not None:
                        self.bot.answer_callback_query(call.id, "🔄 *У тебя уже есть активный заказ!*")
                        return
                    
                    self.user_order_creation[telegram_id_str] = {
                        "chibi_name": None,
                        "reward": None
                    }
                    
                    create_text = """🕍 *Создаем заказ*
_Укажи, какого чибика охотники будут искать, и цену, которую ты готов заплатить. Помни, цена влияет на твою репутацию_"""
                    
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
_Выбери чибика, которого_ *хочешь получить*"""
                    
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
_Выбери чибика, которого_ *хочешь получить*"""
                    
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
_Укажи, какого чибика охотники будут искать, и цену, которую ты готов заплатить. Помни, цена влияет на твою репутацию_"""
                    
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
_Установи награду, которую_ *ты* _заплатишь за выбранного чибика, если охотник доставит его тебе. Помни, что зарплата влияет на репутацию_
_•••••••••••••••••_
Введи цену и отправь мне. Рекомендованная цена : *{recommended_price}*"""
                    
                    # Устанавливаем состояние ожидания ввода цены
                    self.user_states[telegram_id_str] = "waiting_for_reward"
                    
                    # Редактируем текущее сообщение вместо отправки нового
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
_Финальный шаг. Проверь все, чтобы не было неприятностей. Имей в виду, что твоя награда_ *охотнику* _за заказ будет заложена, и вернуть ее можно будет только отменив свой заказ_
_••••••••••••••••••_
_Ты заказываешь:_ *{order_data['chibi_name']}* 
_Ты платишь:_ *{order_data['reward']}*"""
                    
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
                    
                    # Проверяем, есть ли уже активный заказ
                    existing_order_id, existing_order_data = self.get_user_active_order(call.from_user.id)
                    if existing_order_id is not None:
                        self.bot.answer_callback_query(call.id, "🔄 *У тебя уже есть активный заказ!*")
                        return
                    
                    # Проверяем баланс
                    coins = self.user_coins.get(telegram_id_str, 0)
                    if coins < order_data["reward"]:
                        self.bot.answer_callback_query(call.id, f"💸 *Недостаточно коинов!* Нужно {order_data['reward']}")
                        return
                    
                    # Списываем коины
                    self.user_coins[telegram_id_str] = coins - order_data["reward"]
                    
                    # Создаем заказ
                    order_id = self.next_order_id
                    self.cantina_orders[order_id] = {
                        "creator_id": telegram_id_str,
                        "chibi_name": order_data["chibi_name"],
                        "reward": order_data["reward"],
                        "status": "active",
                        "date_created": datetime.now()
                    }
                    self.next_order_id += 1
                    
                    # Инициализируем список принявших
                    self.order_accepted_by[order_id] = []
                    
                    # Удаляем сообщение
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    # Очищаем данные создания заказа
                    del self.user_order_creation[telegram_id_str]
                    
                    # Отправляем сообщение кантины заново
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        "✅ *Заказ создан!*",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                    # Показываем обновленную кантину
                    cantina_text = """*🕍 Кантина*
_Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…_"""
                    
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
                        creator_name = self.users.get(order_data["creator_id"], {}).get('first_name', 'Неизвестный')
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = self.users.get(order_data["creator_id"], {}).get('username')
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
_Укажи, какого чибика охотники будут искать, и цену, которую ты готов заплатить. Помни, цена влияет на твою репутацию_"""
                    
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
_Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…_"""
                    
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
                        creator_name = self.users.get(order_data["creator_id"], {}).get('first_name', 'Неизвестный')
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = self.users.get(order_data["creator_id"], {}).get('username')
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
_Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…_"""
                    
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
                        creator_name = self.users.get(order_data["creator_id"], {}).get('first_name', 'Неизвестный')
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = self.users.get(order_data["creator_id"], {}).get('username')
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
_Выбери, что хочешь сделать_
_•••••••••••••••••_
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
                    
                    # Возвращаем деньги
                    reward = order_data["reward"]
                    if telegram_id_str not in self.user_coins:
                        self.user_coins[telegram_id_str] = 0
                    self.user_coins[telegram_id_str] += reward
                    
                    # Удаляем заказ
                    self.cantina_orders[order_id]["status"] = "cancelled"
                    
                    # Уведомляем всех принявших
                    accepted_users = self.order_accepted_by.get(order_id, [])
                    for user_id in accepted_users:
                        if user_id in self.user_active_hunts:
                            del self.user_active_hunts[user_id]
                        
                        # Удаляем время начала охоты
                        if user_id in self.hunt_start_times and order_id in self.hunt_start_times[user_id]:
                            del self.hunt_start_times[user_id][order_id]
                        
                        user_name = self.users.get(user_id, {}).get('first_name', 'Игрок')
                        sent_message = self.bot.send_message(
                            user_id,
                            f"*Хей, {user_name}!*\n_Заказ, который ты принял, был отозван! Соболезную_",
                            parse_mode='Markdown'
                        )
                        self.message_owners[(user_id, sent_message.message_id)] = user_id
                    
                    # Очищаем список принявших
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
                    
                    if order_id not in self.cantina_orders:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    order_data = self.cantina_orders[order_id]
                    
                    # Проверяем, активен ли еще заказ
                    if order_data["status"] != "active":
                        self.bot.answer_callback_query(call.id, "✅ *Заказ уже завершен или отменен!*")
                        self.bot.edit_message_text(
                            "🕍 *Заказ завершен*",
                            call.message.chat.id,
                            call.message.message_id,
                            parse_mode='Markdown'
                        )
                        return
                    
                    # Проверяем, принял ли пользователь уже этот заказ
                    is_accepted = telegram_id_str in self.order_accepted_by.get(order_id, [])
                    
                    if is_accepted:
                        # Показываем интерфейс сдачи заказа
                        hunt_start_time = self.hunt_start_times.get(telegram_id_str, {}).get(order_id)
                        if not hunt_start_time:
                            hunt_start_time = datetime.now()
                            if telegram_id_str not in self.hunt_start_times:
                                self.hunt_start_times[telegram_id_str] = {}
                            self.hunt_start_times[telegram_id_str][order_id] = hunt_start_time
                        
                        has_fresh_chibi = self.get_fresh_chibi_count(call.from_user.id, order_data["chibi_name"], hunt_start_time) > 0
                        button_text = "✅ Сдать заказ (1/1)" if has_fresh_chibi else "Сдать заказ (0/1)"
                        
                        order_text = f"""🕍*Твой текущий заказ*
_Это заказ от игрока {self.users.get(order_data['creator_id'], {}).get('first_name', 'Неизвестный')}, который ты принял в кантине, и вся о нем инфа_ 
_•••••••••••••••••_
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
                        # Показываем интерфейс принятия заказа
                        creator_name = self.users.get(order_data["creator_id"], {}).get('first_name', 'Неизвестный')
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = self.users.get(order_data["creator_id"], {}).get('username')
                            if creator_username:
                                creator_name = f"@{creator_username}"
                            else:
                                creator_name = "Неизвестный"
                        
                        # Проверяем уровень пользователя
                        user_level = self.user_levels.get(telegram_id_str, 1)
                        if user_level < 3:
                            self.bot.answer_callback_query(call.id, "📊 *Ты еще не дорос!* Минимальный уровень - 3")
                            return
                        
                        order_text = f"""*🕍 Заказ игрока {creator_name}*
_Подумай, насколько тебе это выгодно, и прими решение_ 
_•••••••••••••••••_
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
                    
                    if order_id not in self.cantina_orders:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    # Проверяем, активен ли заказ
                    if self.cantina_orders[order_id]["status"] != "active":
                        self.bot.answer_callback_query(call.id, "✅ *Заказ уже завершен или отменен!*")
                        return
                    
                    # Проверяем уровень пользователя
                    user_level = self.user_levels.get(telegram_id_str, 1)
                    if user_level < 3:
                        self.bot.answer_callback_query(call.id, "📊 *Ты еще не дорос!* Минимальный уровень - 3")
                        return
                    
                    # Проверяем, нет ли уже активной охоты
                    if telegram_id_str in self.user_active_hunts:
                        self.bot.answer_callback_query(call.id, "🔄 *У тебя уже есть активный заказ!*")
                        return
                    
                    # Добавляем пользователя в список принявших
                    if order_id not in self.order_accepted_by:
                        self.order_accepted_by[order_id] = []
                    
                    if telegram_id_str not in self.order_accepted_by[order_id]:
                        self.order_accepted_by[order_id].append(telegram_id_str)
                    
                    # Устанавливаем активную охоту
                    self.user_active_hunts[telegram_id_str] = order_id
                    
                    # Сохраняем время начала охоты
                    if telegram_id_str not in self.hunt_start_times:
                        self.hunt_start_times[telegram_id_str] = {}
                    self.hunt_start_times[telegram_id_str][order_id] = datetime.now()
                    
                    self.bot.answer_callback_query(call.id, "✅ *Заказ принят!*")
                    
                    # Возвращаем к просмотру заказа (теперь он будет показывать интерфейс сдачи)
                    order_data = self.cantina_orders[order_id]
                    
                    hunt_start_time = self.hunt_start_times[telegram_id_str][order_id]
                    has_fresh_chibi = self.get_fresh_chibi_count(call.from_user.id, order_data["chibi_name"], hunt_start_time) > 0
                    button_text = "✅ Сдать заказ (1/1)" if has_fresh_chibi else "Сдать заказ (0/1)"
                    
                    order_text = f"""🕍*Твой текущий заказ*
_Это заказ от игрока {self.users.get(order_data['creator_id'], {}).get('first_name', 'Неизвестный')}, который ты принял в кантине, и вся о нем инфа_ 
_•••••••••••••••••_
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
                    
                    if order_id not in self.cantina_orders:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    # Удаляем пользователя из списка принявших
                    if order_id in self.order_accepted_by and telegram_id_str in self.order_accepted_by[order_id]:
                        self.order_accepted_by[order_id].remove(telegram_id_str)
                    
                    # Удаляем активную охоту
                    if telegram_id_str in self.user_active_hunts:
                        del self.user_active_hunts[telegram_id_str]
                    
                    # Удаляем время начала охоты
                    if telegram_id_str in self.hunt_start_times and order_id in self.hunt_start_times[telegram_id_str]:
                        del self.hunt_start_times[telegram_id_str][order_id]
                    
                    self.bot.answer_callback_query(call.id, "✅ *Отказ от заказа принят!*")
                    
                    # Возвращаем в кантину
                    cantina_text = """*🕍 Кантина*
_Отличное место! Сборище наемников. Здесь можно дать работу, или найти нужный товар…_"""
                    
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
                        creator_name = self.users.get(order_data["creator_id"], {}).get('first_name', 'Неизвестный')
                        if not creator_name or creator_name == 'Неизвестный':
                            creator_username = self.users.get(order_data["creator_id"], {}).get('username')
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
                    
                    if order_id not in self.cantina_orders:
                        self.bot.answer_callback_query(call.id, "🔍 *Заказ не найден!*")
                        return
                    
                    order_data = self.cantina_orders[order_id]
                    
                    # Проверяем, активен ли заказ
                    if order_data["status"] != "active":
                        self.bot.answer_callback_query(call.id, "✅ *Заказ уже завершен или отменен!*")
                        return
                    
                    # Проверяем, есть ли свежий чибик
                    hunt_start_time = self.hunt_start_times.get(telegram_id_str, {}).get(order_id)
                    if not hunt_start_time:
                        self.bot.answer_callback_query(call.id, "⏰ *Ошибка времени охоты!*")
                        return
                    
                    if self.get_fresh_chibi_count(call.from_user.id, order_data["chibi_name"], hunt_start_time) == 0:
                        self.bot.answer_callback_query(call.id, "🎒 *У тебя нет свежего чибика для этого заказа!*")
                        return
                    
                    # Удаляем свежий чибик у охотника (первый попавшийся)
                    if telegram_id_str in self.user_chibis and order_data["chibi_name"] in self.user_chibis[telegram_id_str]:
                        # Находим индекс первого свежего чибика
                        for i, chibi in enumerate(self.user_chibis[telegram_id_str]):
                            if chibi == order_data["chibi_name"]:
                                chibi_time = self.user_chibi_timestamps[telegram_id_str].get(order_data["chibi_name"])
                                if chibi_time and chibi_time > hunt_start_time:
                                    del self.user_chibis[telegram_id_str][i]
                                    # Обновляем временные метки
                                    if (order_data["chibi_name"] in self.user_chibi_timestamps[telegram_id_str] and
                                        self.user_chibi_timestamps[telegram_id_str][order_data["chibi_name"]] == chibi_time):
                                        del self.user_chibi_timestamps[telegram_id_str][order_data["chibi_name"]]
                                    break
                    
                    # Начисляем награду охотнику
                    reward = order_data["reward"]
                    if telegram_id_str not in self.user_coins:
                        self.user_coins[telegram_id_str] = 0
                    self.user_coins[telegram_id_str] += reward
                    
                    # Начисляем опыт за выполнение заказа
                    exp_gained = random.randint(14, 21)
                    level_ups, new_level = self.add_exp(call.from_user.id, exp_gained)
                    
                    # Добавляем чибик создателю заказа
                    creator_id = order_data["creator_id"]
                    if creator_id not in self.user_chibis:
                        self.user_chibis[creator_id] = []
                    self.user_chibis[creator_id].append(order_data["chibi_name"])
                    
                    # Удаляем сообщение с заказом
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    # Отправляем стикер
                    sticker_id = "CAACAgIAAxkBAAE9Js1pAzTTQ9xRej9YYWAs_M_2sMGFnQAC2kkAAkZFCUqenx6Y9nShgTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id)
                    
                    # Сообщение об успешном выполнении
                    user_name = call.from_user.first_name or "путешественник"
                    complete_text = f"""*{user_name}, ты выполнил заказ!*
_Мои поздравления! Думаю, это было достаточно непросто, но ты — первый из наемников, кто справился с ним_ 
_••••••••••••••••••_
+ *💰 {reward}* чибикоинов
+ ⭐️ *{exp_gained}* опыта"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        complete_text,
                        parse_mode='Markdown'
                    )
                    self.message_owners[(call.message.chat.id, sent_message.message_id)] = telegram_id_str
                    
                    # Уведомляем создателя заказа
                    creator_name = self.users.get(creator_id, {}).get('first_name', 'Игрок')
                    sent_message = self.bot.send_message(
                        creator_id,
                        f"*🎉 Твой заказ выполнен!*\n_Охотник {user_name} доставил тебе {order_data['chibi_name']}!_",
                        parse_mode='Markdown'
                    )
                    self.message_owners[(creator_id, sent_message.message_id)] = creator_id
                    
                    # Уведомляем всех остальных принявших
                    accepted_users = self.order_accepted_by.get(order_id, [])
                    for user_id in accepted_users:
                        if user_id != telegram_id_str:  # Не уведомляем исполнителя
                            if user_id in self.user_active_hunts:
                                del self.user_active_hunts[user_id]
                            
                            # Удаляем время начала охоты
                            if user_id in self.hunt_start_times and order_id in self.hunt_start_times[user_id]:
                                del self.hunt_start_times[user_id][order_id]
                            
                            user_name = self.users.get(user_id, {}).get('first_name', 'Игрок')
                            sent_message = self.bot.send_message(
                                user_id,
                                f"*Хей, {user_name}!*\n_Заказ, который ты принял, был завершен! Соболезную_",
                                parse_mode='Markdown'
                            )
                            self.message_owners[(user_id, sent_message.message_id)] = user_id
                    
                    # Удаляем заказ
                    self.cantina_orders[order_id]["status"] = "completed"
                    
                    # Очищаем список принявших
                    if order_id in self.order_accepted_by:
                        del self.order_accepted_by[order_id]
                    
                    # Удаляем активные охоты для этого заказа
                    for user_id in list(self.user_active_hunts.keys()):
                        if self.user_active_hunts[user_id] == order_id:
                            del self.user_active_hunts[user_id]
                    
                    # Удаляем временные метки охоты
                    for user_id in list(self.hunt_start_times.keys()):
                        if order_id in self.hunt_start_times[user_id]:
                            del self.hunt_start_times[user_id][order_id]
                    
                    # Отправляем сообщение о повышении уровня с задержкой
                    if level_ups > 0:
                        threading.Thread(target=self.send_level_up_message, 
                                       args=(call.from_user.id, new_level - level_ups, new_level)).start()
                    
                elif call.data == "cantina_cannot_complete":
                    self.bot.answer_callback_query(call.id, "🎒 *У тебя нет свежего чибика для этого заказа!*")
                    
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
                self.bot.answer_callback_query(call.id, "⛓️‍💥 *Ой, что-то пошло не так!*")

    def run(self):
        logger.info("🤖 Чиби-бот запущен!")
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
            return "🤖 Чиби-бот работает!"
        def run_flask():
            app.run(host='0.0.0.0', port=PORT)
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
    
    bot = ChibiBot(token)
    bot.run()
