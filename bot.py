import telebot
from telebot import types
import random
import string
import os
import logging
import threading
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
        self.gift_selections = {}  # Храним выбранных чибиков для подарка: {user_id: {"target_user_id": "123", "chibi_name": "имя"}}
        self.cantina_orders = {}   # Храним заказы кантины
        self.user_order_creation = {}  # Храним данные создания заказа
        self.user_active_hunts = {}    # Храним активные охоты пользователей: {user_id: order_id}
        self.order_accepted_by = {}    # Храним кто принял заказы: {order_id: [user_id1, user_id2]}
        self.user_states = {}          # Храним состояния пользователей для ввода текста
        self.user_chibi_timestamps = {} # Храним когда получены чибики: {user_id: {chibi_name: datetime}}
        self.hunt_start_times = {}     # Храним время начала охоты: {user_id: {order_id: datetime}}
        self.next_order_id = 1
        self.user_message_ownership = {} # Храним владельцев сообщений: {message_id: user_id}
        self.admin_usernames = ['temkazavr', 'ribapibaa']  # Администраторы
        
        # Система уровней
        self.user_levels = {}  # {user_id: текущий уровень}
        self.user_exp = {}     # {user_id: текущий опыт}
        self.level_requirements = {
            1: 0,
            2: 100,
            3: 230,
            4: 300,
            5: 385,
            6: 435,
            7: 520
        }
        
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
            # Инициализируем временные метки чибиков
            self.user_chibi_timestamps[telegram_id_str] = {}
            # Инициализируем уровень и опыт
            self.user_levels[telegram_id_str] = 1
            self.user_exp[telegram_id_str] = 0
            logger.info(f"Новый пользователь: {user_id}")
            return user_data, True

    def add_exp(self, telegram_id, exp_range):
        """Добавляет опыт пользователю и проверяет повышение уровня"""
        telegram_id_str = str(telegram_id)
        
        if telegram_id_str not in self.user_exp:
            self.user_exp[telegram_id_str] = 0
        if telegram_id_str not in self.user_levels:
            self.user_levels[telegram_id_str] = 1
            
        exp_gained = random.randint(exp_range[0], exp_range[1])
        old_level = self.user_levels[telegram_id_str]
        self.user_exp[telegram_id_str] += exp_gained
        
        # Проверяем повышение уровня
        new_level = self.calculate_level(telegram_id_str)
        
        level_up = new_level > old_level
        if level_up:
            self.user_levels[telegram_id_str] = new_level
            # Награда за уровень
            self.give_level_reward(telegram_id_str, new_level)
            
        return exp_gained, level_up, new_level
    
    def calculate_level(self, telegram_id_str):
        """Рассчитывает текущий уровень на основе опыта"""
        current_exp = self.user_exp[telegram_id_str]
        level = 1
        
        # Проверяем стандартные уровни
        for lvl, exp_req in sorted(self.level_requirements.items()):
            if current_exp >= exp_req:
                level = lvl
            else:
                break
                
        # Авто-уровни после 7
        if level == 7:
            additional_exp = current_exp - self.level_requirements[7]
            additional_levels = additional_exp // 100
            level += additional_levels
            
        return level
    
    def get_level_info(self, telegram_id_str):
        """Получает информацию об уровне пользователя"""
        current_level = self.user_levels.get(telegram_id_str, 1)
        current_exp = self.user_exp.get(telegram_id_str, 0)
        
        # Определяем требование для следующего уровня
        if current_level in self.level_requirements:
            next_level = current_level + 1
            if next_level in self.level_requirements:
                exp_needed = self.level_requirements[next_level]
            else:
                # Для авто-уровней после 7
                base_exp = self.level_requirements[7]
                levels_above = current_level - 7
                exp_needed = base_exp + (levels_above * 100) + 100
        else:
            # Для авто-уровней
            base_exp = self.level_requirements[7]
            levels_above = current_level - 7
            exp_needed = base_exp + (levels_above * 100) + 100
            
        return current_level, current_exp, exp_needed
    
    def give_level_reward(self, telegram_id_str, new_level):
        """Выдает награду за повышение уровня"""
        # Всегда даем чиби-пак
        if telegram_id_str not in self.user_items:
            self.user_items[telegram_id_str] = {}
        if "🧧 Чиби-пак" not in self.user_items[telegram_id_str]:
            self.user_items[telegram_id_str]["🧧 Чиби-пак"] = 0
        self.user_items[telegram_id_str]["🧧 Чиби-пак"] += 1
        
        # С 5 уровня добавляем коины
        coins_reward = 0
        if new_level >= 5:
            coins_reward = random.randint(10, 20)
            if telegram_id_str not in self.user_coins:
                self.user_coins[telegram_id_str] = 0
            self.user_coins[telegram_id_str] += coins_reward
            
        return coins_reward

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
        """Проверяет, принадлежит ли сообщение пользователю"""
        # В личных сообщениях разрешаем все
        if call.message.chat.type == 'private':
            return True
            
        telegram_id_str = str(call.from_user.id)
        message_id = call.message.message_id
        
        if message_id in self.user_message_ownership:
            if self.user_message_ownership[message_id] != telegram_id_str:
                # Случайные ответы для чужих кнопок в группах
                responses = [
                    "Не твое!",
                    "Хватит тыкать, бесполезно же!",
                    "Эй, это не твое сообщение!",
                    "Псс, это не твои кнопки!",
                    "Не-а, это не для тебя!"
                ]
                self.bot.answer_callback_query(call.id, random.choice(responses))
                return False
        return True

    def find_user_by_identifier(self, identifier):
        """Находит пользователя по user_id, username или telegram_id"""
        # Убираем @ если есть
        if identifier.startswith('@'):
            identifier = identifier[1:]
            
        # Поиск по user_id (сгенерированному ID)
        for telegram_id_str, user_data in self.users.items():
            if user_data.get('user_id') == identifier:
                return user_data, telegram_id_str
                
        # Поиск по username
        for telegram_id_str, user_data in self.users.items():
            if user_data.get('username') == identifier:
                return user_data, telegram_id_str
                
        # Поиск по telegram_id (число или строка)
        if identifier in self.users:
            return self.users[identifier], identifier
            
        # Если identifier - число, пробуем найти как telegram_id
        try:
            if str(int(identifier)) in self.users:
                return self.users[str(int(identifier))], str(int(identifier))
        except ValueError:
            pass
            
        return None, None

    def setup_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start_handler(message):
            # Запрещаем команду в группах
            if message.chat.type != 'private':
                markup = types.InlineKeyboardMarkup()
                btn_go = types.InlineKeyboardButton("перейти", url=f"https://t.me/{self.bot.get_me().username}?start=start")
                markup.add(btn_go)
                self.bot.reply_to(message, "🙅‍♂️ *Не-не, дружок, эти команды доступны только в личке с ботом*", reply_markup=markup, parse_mode='Markdown')
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
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    sent_message = self.bot.send_message(message.chat.id, BOT_TEXTS['already_started'], parse_mode='Markdown')
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                    
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')
                self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)

        @self.bot.message_handler(commands=['abme'])
        def abme_handler(message):
            try:
                user_data, _ = self.get_or_create_user(message.from_user.id)
                user_id = user_data['user_id']
                user_name = user_data['first_name'] or "путешественник"
                
                telegram_id_str = str(message.from_user.id)
                level, current_exp, exp_needed = self.get_level_info(telegram_id_str)
                
                profile_text = f"""*💫 Профиль игрока {user_name}*
_Твой профиль и вся инфа о тебе в рамках этого прекрасного бота_
_••••••••••••••••_
Твой айди: `{user_id}`
Уровень: *{level}* ({current_exp}/{exp_needed})"""
                
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, profile_text, parse_mode='Markdown')
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, profile_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['balance'])
        def balance_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                coins = self.user_coins.get(telegram_id_str, 0)
                
                balance_text = f"💰 У тебя — *{coins}* коинов!"
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, balance_text, parse_mode='Markdown')
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, balance_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')

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
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, mart_text, reply_markup=markup, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка при открытии лавки: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['chibi'])
        def chibi_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                file_path, chibi_name, rarity = self.get_random_chibi(from_pack=False)
                
                if file_path is None:
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Чиби временно недоступны. Попробуй позже*", parse_mode='Markdown')
                        self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                    else:
                        self.bot.reply_to(message, "🙅‍♂️ *Чиби временно недоступны. Попробуй позже*", parse_mode='Markdown')
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
                
                # Добавляем опыт за чибика
                exp_gained, level_up, new_level = self.add_exp(message.from_user.id, (12, 21))
                
                # Получаем количество этого чибика у пользователя
                chibi_count = self.get_chibi_count(message.from_user.id, chibi_name)
                
                # Формируем текст сообщения
                rarity_emoji = "🔷" if rarity == "Common" else "💠"
                
                base_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Надеюсь, он тебе понравился! Приходи еще через *3ч 59м*_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _{rarity}_
У тебя: {chibi_count}"""
                
                if hunt_chibi_needed and chibi_name == hunt_chibi_needed:
                    chibi_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Этот чибик нужен тебе, чтобы выполнить заказ в кантине! Скорее сдай его, пока конкуренты тебя не опередили_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _{rarity}_
У тебя: *{chibi_count}*"""
                else:
                    chibi_text = base_text
                
                # Добавляем информацию об опыте
                if level_up:
                    chibi_text += f"\n\n+ *⭐️ {exp_gained}*"
                else:
                    chibi_text += f"\n\n+ *⭐️ {exp_gained}*"
                
                # Отправляем картинку с текстом
                with open(file_path, 'rb') as photo:
                    if message.chat.type == 'private':
                        sent_message = self.bot.send_photo(
                            message.chat.id,
                            photo,
                            caption=chibi_text,
                            parse_mode='Markdown'
                        )
                        self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                    else:
                        # В группах отправляем без реплая
                        sent_message = self.bot.send_photo(
                            message.chat.id,
                            photo,
                            caption=chibi_text,
                            parse_mode='Markdown'
                        )
                        self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                
                # Если был уровень up, отправляем отдельное сообщение с наградой
                if level_up:
                    sticker_id = "CAACAgIAAxkBAAE9Ox5pBRLv2Hxcf4ocN9T7WMDxyvUutQADSwAC8d0RSrm2zs5__WV5NgQ"
                    self.bot.send_sticker(message.chat.id, sticker_id)
                    
                    coins_reward = self.give_level_reward(telegram_id_str, new_level)
                    
                    level_up_text = f"""*Эй, {user_data['first_name']}!* 
_Ты только что апнул уровень {new_level}! Поздравляю!_ 
_•••••••••••••••••••_
+ 🧧 *1* Чиби-пак"""
                    
                    if coins_reward > 0:
                        level_up_text += f"\n+ *💰 {coins_reward}* коинов"
                    
                    level_up_text += "\n\n_Это тебе небольшой подгон, чтоб не расслаблялся!_"
                    
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        level_up_text,
                        parse_mode='Markdown'
                    )
                    self.user_message_ownership[sent_message.message_id] = telegram_id_str
                    
                logger.info(f"Отправлен чиби: {chibi_name} (Редкость: {rarity})")
                    
            except Exception as e:
                logger.error(f"Ошибка при отправке чиби: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')

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
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, task_text, reply_markup=markup, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка при генерации задания: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')

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
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, menu_text, reply_markup=markup, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка при открытии меню: {e}")
                if message.chat.type == 'private':
                    sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                else:
                    self.bot.reply_to(message, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['gift'])
        def gift_handler(message):
            # Запрещаем команду в группах
            if message.chat.type != 'private':
                markup = types.InlineKeyboardMarkup()
                btn_go = types.InlineKeyboardButton("перейти", url=f"https://t.me/{self.bot.get_me().username}?start=gift")
                markup.add(btn_go)
                self.bot.reply_to(message, "🙅‍♂️ *Не-не, дружок, эти команды доступны только в личке с ботом*", reply_markup=markup, parse_mode='Markdown')
                return
                
            try:
                if len(message.text.split()) < 2:
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "🙅‍♂️ *Нет, дружище, ты ввел что-то не так*\n_Попробуй:_ `/gift 1234А`",
                        parse_mode='Markdown'
                    )
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
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
                        "🙅‍♂️ *Такого пользователя нет в наших записях! Проверь айди и попробуй снова*",
                        parse_mode='Markdown'
                    )
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                    return
                
                if str(message.from_user.id) in self.users and self.users[str(message.from_user.id)]['user_id'] == target_user_id:
                    sent_message = self.bot.send_message(
                        message.chat.id,
                        "🙅‍♂️ *Не-не, самому себе подарки не дарим! Найдите себе друзей*",
                        parse_mode='Markdown'
                    )
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
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
                        "🙅‍♂️ *А дарить-то нечего! Сначала собери коллекцию чибиков*",
                        parse_mode='Markdown'
                    )
                    self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
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
                self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                
            except Exception as e:
                logger.error(f"Ошибка при отправке подарка: {e}")
                sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')
                self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)

        @self.bot.message_handler(commands=['cantina'])
        def cantina_handler(message):
            # Запрещаем команду в группах
            if message.chat.type != 'private':
                markup = types.InlineKeyboardMarkup()
                btn_go = types.InlineKeyboardButton("перейти", url=f"https://t.me/{self.bot.get_me().username}?start=cantina")
                markup.add(btn_go)
                self.bot.reply_to(message, "🙅‍♂️ *Не-не, дружок, эти команды доступны только в личке с ботом*", reply_markup=markup, parse_mode='Markdown')
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
                self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)
                
            except Exception as e:
                logger.error(f"Ошибка при открытии кантины: {e}")
                sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Ой-ой, что-то пошло не так! Попробуй позже*", parse_mode='Markdown')
                self.user_message_ownership[sent_message.message_id] = str(message.from_user.id)

        @self.bot.message_handler(func=lambda message: True)
        def text_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                
                # Проверяем административные команды
                if message.from_user.username in self.admin_usernames:
                    text = message.text.strip()
                    
                    # Обработка выдачи паков
                    if text.startswith('reclaim_') and '_packs.value=' in text and '_status=true' in text:
                        try:
                            # Парсим команду
                            parts = text.split('_')
                            user_identifier = parts[1]
                            value_part = text.split('packs.value=')[1].split('_status=true')[0]
                            amount = int(value_part)
                            
                            # Находим пользователя
                            user_data, target_telegram_id = self.find_user_by_identifier(user_identifier)
                            if not user_data:
                                if message.chat.type == 'private':
                                    sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Такого пользователя нет в наших записях!*", parse_mode='Markdown')
                                    self.user_message_ownership[sent_message.message_id] = telegram_id_str
                                else:
                                    self.bot.reply_to(message, "🙅‍♂️ *Такого пользователя нет в наших записях!*", parse_mode='Markdown')
                                return
                            
                            # Выдаем паки
                            if target_telegram_id not in self.user_items:
                                self.user_items[target_telegram_id] = {}
                            if "🧧 Чиби-пак" not in self.user_items[target_telegram_id]:
                                self.user_items[target_telegram_id]["🧧 Чиби-пак"] = 0
                            self.user_items[target_telegram_id]["🧧 Чиби-пак"] += amount
                            
                            # Отправляем стикер
                            sticker_id = "CAACAgIAAxkBAAE9Ox5pBRLv2Hxcf4ocN9T7WMDxyvUutQADSwAC8d0RSrm2zs5__WV5NgQ"
                            self.bot.send_sticker(message.chat.id, sticker_id)
                            
                            # Отправляем сообщение
                            response_text = f"*{amount} 🧧 Чиби-паков выдано игроку {user_data['first_name']}!*"
                            if message.chat.type == 'private':
                                sent_message = self.bot.send_message(message.chat.id, response_text, parse_mode='Markdown')
                                self.user_message_ownership[sent_message.message_id] = telegram_id_str
                            else:
                                self.bot.reply_to(message, response_text, parse_mode='Markdown')
                                
                        except Exception as e:
                            logger.error(f"Ошибка в команде выдачи паков: {e}")
                            if message.chat.type == 'private':
                                sent_message = self.bot.send_message(message.chat.id, "🙅‍♂️ *Что-то пошло не так! Проверь формат команды*", parse_mode='Markdown')
                                self.user_message_ownership[sent_message.message_id] = telegram_id_str
                            else:
                                self.bot.reply_to(message, "🙅‍♂️ *Что-то пошло не так! Проверь формат команды*", parse_mode='Markdown')
                
                # Обработка обычных состояний
                elif self.user_states.get(telegram_id_str) == "waiting_for_reward":
                    try:
                        reward = int(message.text)
                        recommended_price = random.randint(32, 45)
                        
                        if reward < 25:
                            if message.chat.type == 'private':
                                sent_message = self.bot.send_message(
                                    message.chat.id,
                                    "🙅‍♂️ *Слишком мало! Минимум — 25*",
                                    parse_mode='Markdown'
                                )
                                self.user_message_ownership[sent_message.message_id] = telegram_id_str
                            else:
                                self.bot.reply_to(message, "🙅‍♂️ *Слишком мало! Минимум — 25*", parse_mode='Markdown')
                            return
                        elif reward > 440:
                            if message.chat.type == 'private':
                                sent_message = self.bot.send_message(
                                    message.chat.id,
                                    "🙅‍♂️ *Слишком много! Максимум — 440*",
                                    parse_mode='Markdown'
                                )
                                self.user_message_ownership[sent_message.message_id] = telegram_id_str
                            else:
                                self.bot.reply_to(message, "🙅‍♂️ *Слишком много! Максимум — 440*", parse_mode='Markdown')
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
                                "🙅‍♂️ *Эй, это не число! Введи нормальную цену*",
                                parse_mode='Markdown'
                            )
                            self.user_message_ownership[sent_message.message_id] = telegram_id_str
                        else:
                            self.bot.reply_to(message, "🙅‍♂️ *Эй, это не число! Введи нормальную цену*", parse_mode='Markdown')
                
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
                        self.bot.answer_callback_query(call.id, "Задание уже выполнено!")
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
                    
                    # Добавляем опыт за задание
                    exp_gained, level_up, new_level = self.add_exp(call.from_user.id, (21, 32))
                    
                    user_nick = call.from_user.first_name or "путешественник"
                    complete_text = f"""*Ес! {user_nick}, ты выполнил таск!*
_За это ты получаешь обещанную награду. Даже не буду гадать, сколько ты выбивал нужного чибика_
`•••••••••••••••`
+ 💰*{reward}* коинов
+ *⭐️ {exp_gained}*"""
                    
                    sent_message = self.bot.send_message(
                        call.message.chat.id,
                        complete_text,
                        parse_mode='Markdown'
                    )
                    self.user_message_ownership[sent_message.message_id] = telegram_id_str
                    
                    self.user_tasks[telegram_id_str] = None
                    
                    # Если был уровень up, отправляем отдельное сообщение с наградой
                    if level_up:
                        sticker_id = "CAACAgIAAxkBAAE9Ox5pBRLv2Hxcf4ocN9T7WMDxyvUutQADSwAC8d0RSrm2zs5__WV5NgQ"
                        self.bot.send_sticker(call.message.chat.id, sticker_id)
                        
                        user_data = self.users.get(telegram_id_str, {})
                        coins_reward = self.give_level_reward(telegram_id_str, new_level)
                        
                        level_up_text = f"""*Эй, {user_data.get('first_name', 'путешественник')}!* 
_Ты только что апнул уровень {new_level}! Поздравляю!_ 
_•••••••••••••••••••_
+ 🧧 *1* Чиби-пак"""
                        
                        if coins_reward > 0:
                            level_up_text += f"\n+ *💰 {coins_reward}* коинов"
                        
                        level_up_text += "\n\n_Это тебе небольшой подгон, чтоб не расслаблялся!_"
                        
                        sent_message = self.bot.send_message(
                            call.message.chat.id,
                            level_up_text,
                            parse_mode='Markdown'
                        )
                        self.user_message_ownership[sent_message.message_id] = telegram_id_str
                    
                elif call.data == "task_cannot_complete":
                    self.bot.answer_callback_query(call.id, "У тебя нет нужного чибика!")
                    
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
                    self.user_message_ownership[sent_message.message_id] = telegram_id_str
                    
                elif call.data == "task_skip_confirm":
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str not in self.user_tasks or self.user_tasks[telegram_id_str] is None:
                        self.bot.answer_callback_query(call.id, "Нет активного задания!")
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
                        self.bot.answer_callback_query(call.id, "Нет активного задания!")
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
                    
                # ... (остальные обработчики callback остаются без изменений, кроме добавления проверок уровней)

                elif call.data == "cantina_create_order":
                    telegram_id_str = str(call.from_user.id)
                    
                    # Проверяем уровень для создания заказа
                    user_level = self.user_levels.get(telegram_id_str, 1)
                    if user_level < 7:
                        self.bot.answer_callback_query(call.id, "✨ Ты еще не дорос, минимальный уровень - 7")
                        return
                    
                    # Проверяем, есть ли уже активный заказ
                    existing_order_id, existing_order_data = self.get_user_active_order(call.from_user.id)
                    if existing_order_id is not None:
                        self.bot.answer_callback_query(call.id, "У тебя уже есть активный заказ!")
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

                elif call.data.startswith("cantina_accept_order_"):
                    order_id = int(call.data.split("_")[3])
                    telegram_id_str = str(call.from_user.id)
                    
                    # Проверяем уровень для принятия заказа
                    user_level = self.user_levels.get(telegram_id_str, 1)
                    if user_level < 3:
                        self.bot.answer_callback_query(call.id, "✨ Ты еще не дорос, минимальный уровень - 3")
                        return
                    
                    if order_id not in self.cantina_orders:
                        self.bot.answer_callback_query(call.id, "Заказ не найден!")
                        return
                    
                    # ... (остальная логика принятия заказа)

                # ... (остальные обработчики остаются без изменений)

            except Exception as e:
                logger.error(f"Ошибка в callback: {e}")
                self.bot.answer_callback_query(call.id, "🙅‍♂️ *Ой-ой, что-то пошло не так!*")

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
