import telebot
from telebot import types
import random
import string
import os
import logging
import threading
from flask import Flask
from datetime import datetime, timedelta
import time

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
        
        # Система ежедневных заданий
        self.user_daily_tasks = {}  # {user_id: {"task_type": "roll_chibi", "target": 5, "progress": 3, "completed": False}}
        self.user_experience = {}   # {user_id: experience_points}
        self.daily_stats = {}       # {user_id: {"chibi_rolls": 0, "tasks_completed": 0, "packs_opened": 0, "bonuses_claimed": 0}}
        
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
            # Инициализируем опыт
            self.user_experience[telegram_id_str] = 0
            # Инициализируем статистику
            self.daily_stats[telegram_id_str] = {"chibi_rolls": 0, "tasks_completed": 0, "packs_opened": 0, "bonuses_claimed": 0}
            
            logger.info(f"Новый пользователь: {user_id}")
            return user_data, True

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

    def generate_daily_task(self, telegram_id):
        """Генерирует случайное ежедневное задание для пользователя"""
        telegram_id_str = str(telegram_id)
        
        # Типы заданий
        task_types = [
            {
                "type": "roll_chibi",
                "templates": ["Залутай {count} чибиков", "Залутай {count} чибика"],
                "emoji": "⚡️",
                "target_range": (3, 5)
            },
            {
                "type": "complete_task",
                "templates": ["Выполни {count} таск", "Выполни {count} таска"],
                "emoji": "🐲",
                "target_range": (1, 2)
            },
            {
                "type": "open_pack", 
                "templates": ["Открой {count} пак", "Открой {count} пака"],
                "emoji": "🧧",
                "target_range": (2, 4)
            },
            {
                "type": "claim_bonus",
                "templates": ["Получи {count} ежедневных бонуса", "Получи {count} ежедневных бонусов"],
                "emoji": "🎁",
                "target_range": (2, 4)
            }
        ]
        
        # Выбираем случайный тип задания
        task_type_data = random.choice(task_types)
        task_type = task_type_data["type"]
        target = random.randint(task_type_data["target_range"][0], task_type_data["target_range"][1])
        
        # Формируем текст задания
        if target == 1:
            task_text = random.choice(task_type_data["templates"][0:1]).format(count=target)
        else:
            task_text = random.choice(task_type_data["templates"]).format(count=target)
        
        # Создаем задание
        task_data = {
            "type": task_type,
            "target": target,
            "progress": 0,
            "completed": False,
            "text": f"{task_type_data['emoji']} {task_text}",
            "short_text": f"{task_type_data['emoji']} {task_text.split()[0]} {task_text.split()[1]}"
        }
        
        self.user_daily_tasks[telegram_id_str] = task_data
        return task_data

    def get_daily_task_progress_text(self, task_data, telegram_id):
        """Получает текст прогресса для ежедневного задания"""
        telegram_id_str = str(telegram_id)
        
        if task_data["completed"]:
            return "✅ Задание выполнено"
        
        progress_text = f"{task_data['short_text']} ({task_data['progress']}/{task_data['target']})"
        return progress_text

    def update_daily_progress(self, telegram_id, action_type):
        """Обновляет прогресс ежедневных заданий"""
        telegram_id_str = str(telegram_id)
        
        # Обновляем статистику
        if telegram_id_str not in self.daily_stats:
            self.daily_stats[telegram_id_str] = {"chibi_rolls": 0, "tasks_completed": 0, "packs_opened": 0, "bonuses_claimed": 0}
        
        if action_type == "roll_chibi":
            self.daily_stats[telegram_id_str]["chibi_rolls"] += 1
        elif action_type == "complete_task":
            self.daily_stats[telegram_id_str]["tasks_completed"] += 1
        elif action_type == "open_pack":
            self.daily_stats[telegram_id_str]["packs_opened"] += 1
        elif action_type == "claim_bonus":
            self.daily_stats[telegram_id_str]["bonuses_claimed"] += 1
        
        # Проверяем активное задание
        if telegram_id_str in self.user_daily_tasks:
            task_data = self.user_daily_tasks[telegram_id_str]
            
            if not task_data["completed"] and task_data["type"] == action_type:
                task_data["progress"] += 1
                
                if task_data["progress"] >= task_data["target"]:
                    task_data["completed"] = True

    def get_leaderboard(self):
        """Получает топ-10 пользователей по опыту"""
        # Фильтруем пользователей с опытом > 0
        users_with_exp = [(user_id, exp) for user_id, exp in self.user_experience.items() if exp > 0]
        
        # Сортируем по убыванию опыта
        sorted_users = sorted(users_with_exp, key=lambda x: x[1], reverse=True)
        
        # Берем топ-10
        top_10 = sorted_users[:10]
        
        leaderboard_data = []
        for i, (user_id, exp) in enumerate(top_10, 1):
            user_data = self.users.get(user_id, {})
            user_name = user_data.get('first_name', 'Ноунейм')
            leaderboard_data.append({
                "position": i,
                "name": user_name,
                "experience": exp
            })
        
        return leaderboard_data

    def get_time_until_midnight(self):
        """Получает время до 00:00 по МСК"""
        now = datetime.now()
        moscow_time = now + timedelta(hours=3)  # UTC+3 для МСК
        midnight = moscow_time.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        time_left = midnight - moscow_time
        
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        return f"{hours}ч {minutes}м"

    def setup_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start_handler(message):
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
                    self.bot.send_message(message.chat.id, welcome_text, reply_markup=markup, parse_mode='Markdown')
                else:
                    self.bot.send_message(message.chat.id, BOT_TEXTS['already_started'], parse_mode='Markdown')
                    
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте позже.")

        @self.bot.message_handler(commands=['myid'])
        def myid_handler(message):
            try:
                user_data, _ = self.get_or_create_user(message.from_user.id)
                user_id = user_data['user_id']
                
                response_text = f"⭐️ Твой айди — `{user_id}`"
                self.bot.send_message(message.chat.id, response_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте позже.")

        @self.bot.message_handler(commands=['balance'])
        def balance_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                coins = self.user_coins.get(telegram_id_str, 0)
                
                balance_text = f"💰 У тебя — *{coins}* коинов!"
                self.bot.send_message(message.chat.id, balance_text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте позже.")

        @self.bot.message_handler(commands=['mart'])
        def mart_handler(message):
            try:
                mart_text = """🎏 *Лавка джавы*
_Джавы, может, и не отличаются умом, но зато точно знают толк в ценах!_"""
                
                markup = types.InlineKeyboardMarkup()
                btn_pack = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_chibi_pack")
                markup.add(btn_pack)
                
                self.bot.send_message(
                    message.chat.id,
                    mart_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Ошибка при открытии лавки: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка при открытии лавки. Попробуйте позже.")

        @self.bot.message_handler(commands=['chibi'])
        def chibi_handler(message):
            try:
                file_path, chibi_name, rarity = self.get_random_chibi(from_pack=False)
                
                if file_path is None:
                    self.bot.send_message(message.chat.id, "❌ Чиби временно недоступны. Попробуйте позже.")
                    return
                
                # Добавляем чибика в коллекцию пользователя
                telegram_id_str = str(message.from_user.id)
                if telegram_id_str not in self.user_chibis:
                    self.user_chibis[telegram_id_str] = []
                self.user_chibis[telegram_id_str].append(chibi_name)
                
                # Обновляем прогресс ежедневных заданий
                self.update_daily_progress(message.from_user.id, "roll_chibi")
                
                # Получаем количество этого чибика у пользователя
                chibi_count = self.get_chibi_count(message.from_user.id, chibi_name)
                
                # Формируем текст сообщения
                rarity_emoji = "🔷" if rarity == "Common" else "💠"
                chibi_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Надеюсь, он тебе понравился! Приходи еще через *3ч 59м*_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _Common_
У тебя: {chibi_count}"""
                
                # Отправляем картинку с текстом
                with open(file_path, 'rb') as photo:
                    self.bot.send_photo(
                        message.chat.id,
                        photo,
                        caption=chibi_text,
                        parse_mode='Markdown'
                    )
                    
                logger.info(f"Отправлен чиби: {chibi_name} (Редкость: {rarity})")
                    
            except Exception as e:
                logger.error(f"Ошибка при отправке чиби: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка при получении чиби. Попробуйте позже.")

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
                
                self.bot.send_message(
                    message.chat.id,
                    task_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Ошибка при генерации задания: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка при создании задания. Попробуйте позже.")

        @self.bot.message_handler(commands=['menu'])
        def menu_handler(message):
            try:
                menu_text = """*✨ Меню* 
_Здесь ты найдешь все, что нужно, но не имеет команды. Мы постарались_"""
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn_warehouse = types.InlineKeyboardButton("📦 Склад", callback_data="menu_warehouse")
                btn_channel = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
                btn_daily = types.InlineKeyboardButton("🎁 Ежедневные штучки", callback_data="menu_daily")
                
                markup.add(btn_warehouse, btn_channel)
                markup.add(btn_daily)
                
                self.bot.send_message(
                    message.chat.id,
                    menu_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Ошибка при открытии меню: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка при открытии меню. Попробуйте позже.")

        @self.bot.message_handler(commands=['daily'])
        def daily_handler(message):
            try:
                daily_text = """🎁 *Ежедневные штучки*
_Выбери, что хочешь глянуть_"""
                
                markup = types.InlineKeyboardMarkup()
                btn_tasks = types.InlineKeyboardButton("Задания", callback_data="daily_tasks")
                btn_bonus = types.InlineKeyboardButton("Получить бонус", callback_data="menu_bonus")
                btn_back = types.InlineKeyboardButton("Назад", callback_data="daily_back")
                markup.add(btn_tasks)
                markup.add(btn_bonus, btn_back)
                
                self.bot.send_message(
                    message.chat.id,
                    daily_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Ошибка при открытии ежедневных штучек: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте позже.")

        @self.bot.message_handler(commands=['gift'])
        def gift_handler(message):
            try:
                if len(message.text.split()) < 2:
                    self.bot.send_message(
                        message.chat.id,
                        "❌ Неверный формат команды. Используй: `/gift [ID_пользователя]`",
                        parse_mode='Markdown'
                    )
                    return
                
                target_user_id = message.text.split()[1].strip()
                
                # Проверяем, существует ли пользователь с таким ID
                target_user_found = False
                target_user_data = None
                target_telegram_id = None
                
                for telegram_id_str, user_data in self.users.items():
                    if user_data['user_id'] == target_user_id:
                        target_user_found = True
                        target_user_data = user_data
                        target_telegram_id = telegram_id_str
                        break
                
                if not target_user_found:
                    self.bot.send_message(
                        message.chat.id,
                        "❌ Такого игрока нет",
                        parse_mode='Markdown'
                    )
                    return
                
                # Проверяем, не пытается ли пользователь отправить подарок самому себе
                sender_user_data = self.users.get(str(message.from_user.id))
                if sender_user_data and sender_user_data['user_id'] == target_user_id:
                    self.bot.send_message(
                        message.chat.id,
                        "❌ Сам себе дарить собрался?",
                        parse_mode='Markdown'
                    )
                    return
                
                # Получаем имя получателя
                target_name = target_user_data.get('first_name', 'Ноунейм')
                if not target_name or target_name == 'None':
                    target_name = 'Ноунейм'
                
                # Сохраняем выбор пользователя для подарка
                telegram_id_str = str(message.from_user.id)
                self.gift_selections[telegram_id_str] = {
                    "target_user_id": target_user_id,
                    "target_telegram_id": target_telegram_id,
                    "target_name": target_name
                }
                
                # Показываем выбор чибиков для подарка
                chibis, current_page, total_pages = self.get_user_chibis_for_gift(message.from_user.id, 1)
                
                if not chibis:
                    self.bot.send_message(
                        message.chat.id,
                        "❌ У тебя нет чибиков для подарка!",
                        parse_mode='Markdown'
                    )
                    return
                
                gift_text = """✨ *О, да ты у нас щедрый!*
_Выбери, какого чибика подаришь_"""
                
                markup = types.InlineKeyboardMarkup()
                
                # Добавляем кнопки чибиков (по одной в ряд)
                for chibi_name, count in chibis:
                    if count > 1:
                        btn_text = f"{chibi_name} ({count})"
                    else:
                        btn_text = chibi_name
                    markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"gift_select_{chibi_name}"))
                
                # Добавляем навигацию
                nav_buttons = []
                if total_pages > 1:
                    nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"gift_page_{((current_page-2) % total_pages) + 1}"))
                
                nav_buttons.append(types.InlineKeyboardButton("Отменить", callback_data="gift_cancel"))
                
                if total_pages > 1:
                    nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"gift_page_{(current_page % total_pages) + 1}"))
                
                markup.row(*nav_buttons)
                
                self.bot.send_message(
                    message.chat.id,
                    gift_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Ошибка при отправке подарка: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка при отправке подарка. Попробуйте позже.")

        # Обработчик callback для кнопок
        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call):
            try:
                if call.data == "task_complete":
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str not in self.user_tasks or self.user_tasks[telegram_id_str] is None:
                        self.bot.answer_callback_query(call.id, "Задание уже выполнено!")
                        return
                    
                    task_data = self.user_tasks[telegram_id_str]
                    
                    if telegram_id_str in self.user_chibis and task_data["chibi"] in self.user_chibis[telegram_id_str]:
                        self.user_chibis[telegram_id_str].remove(task_data["chibi"])
                    
                    # Обновляем прогресс ежедневных заданий
                    self.update_daily_progress(call.from_user.id, "complete_task")
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sticker_id = "CAACAgIAAxkBAAE9Js9pAzTWs9gLLtl9Gqz_9V_4sbwXqgAC7EYAAjNREEqhVSL_nxyHZTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id)
                    
                    reward = task_data["reward"]
                    if telegram_id_str not in self.user_coins:
                        self.user_coins[telegram_id_str] = 0
                    self.user_coins[telegram_id_str] += reward
                    
                    user_nick = call.from_user.first_name or "путешественник"
                    complete_text = f"""*Ес! {user_nick}, ты выполнил таск!*
_За это ты получаешь обещанную награду. Даже не буду гадать, сколько ты выбивал нужного чибика_
`•••••••••••••••`
+ 💰*{reward}* коинов"""
                    
                    self.bot.send_message(
                        call.message.chat.id,
                        complete_text,
                        parse_mode='Markdown'
                    )
                    
                    self.user_tasks[telegram_id_str] = None
                    
                elif call.data == "task_cannot_complete":
                    self.bot.answer_callback_query(call.id, "У тебя нет нужного чибика!")
                    
                elif call.data == "task_skip":
                    telegram_id_str = str(call.from_user.id)
                    self.user_tasks[telegram_id_str] = None
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    skip_text = """✨*Ты пропустил таск. Жди новый!*
_Осталось 8ч 59м_"""
                    
                    self.bot.send_message(
                        call.message.chat.id,
                        skip_text,
                        parse_mode='Markdown'
                    )
                    
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
                    
                    confirm_text = """*Ты точно хочешь открыть 🧧 Чиби-пак?*
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
                        self.bot.answer_callback_query(call.id, "Недостаточно Чиби-паков!")
                        return
                    
                    self.user_items[telegram_id_str]["🧧 Чиби-пак"] = current_packs - count
                    
                    # Обновляем прогресс ежедневных заданий
                    for i in range(count):
                        self.update_daily_progress(call.from_user.id, "open_pack")
                    
                    for i in range(count):
                        file_path, chibi_name, rarity = self.get_random_chibi(from_pack=True)
                        
                        if file_path is not None:
                            if telegram_id_str not in self.user_chibis:
                                self.user_chibis[telegram_id_str] = []
                            self.user_chibis[telegram_id_str].append(chibi_name)
                            
                            chibi_count = self.get_chibi_count(call.from_user.id, chibi_name)
                            
                            rarity_emoji = "🔷" if rarity == "Common" else "💠"
                            chibi_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Надеюсь, он тебе понравился!_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _{rarity}_
У тебя: {chibi_count}"""
                            
                            with open(file_path, 'rb') as photo:
                                self.bot.send_photo(
                                    call.message.chat.id,
                                    photo,
                                    caption=chibi_text,
                                    parse_mode='Markdown'
                                )
                    
                    self.bot.answer_callback_query(call.id, f"Открыто {count} Чиби-пак(ов)!")
                    
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
                        self.bot.answer_callback_query(call.id, "Недостаточно коинов! Нужно 120.")
                        return
                    
                    self.user_coins[telegram_id_str] = coins - 120
                    
                    if telegram_id_str not in self.user_items:
                        self.user_items[telegram_id_str] = {}
                    
                    if "🧧 Чиби-пак" not in self.user_items[telegram_id_str]:
                        self.user_items[telegram_id_str]["🧧 Чиби-пак"] = 0
                    
                    self.user_items[telegram_id_str]["🧧 Чиби-пак"] += 1
                    
                    self.bot.answer_callback_query(call.id, "Чиби-пак куплен!")
                    
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
                    
                    # Обновляем прогресс ежедневных заданий
                    self.update_daily_progress(call.from_user.id, "claim_bonus")
                    
                    user_name = call.from_user.first_name or "путешественник"
                    bonus_text = f"""🎁 *Эй, {user_name}!*
_Ты только что получил ежедневный бонус!_ 
`•••••••••••••••••`
+ 💰*{bonus}* коинов"""
                    
                    self.bot.send_message(
                        call.message.chat.id,
                        bonus_text,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "menu_daily":
                    daily_text = """🎁 *Ежедневные штучки*
_Выбери, что хочешь глянуть_"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_tasks = types.InlineKeyboardButton("Задания", callback_data="daily_tasks")
                    btn_bonus = types.InlineKeyboardButton("Получить бонус", callback_data="menu_bonus")
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="menu_back")
                    markup.add(btn_tasks)
                    markup.add(btn_bonus, btn_back)
                    
                    self.bot.edit_message_text(
                        daily_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "daily_tasks":
                    telegram_id_str = str(call.from_user.id)
                    
                    # Генерируем задание, если его нет
                    if telegram_id_str not in self.user_daily_tasks:
                        task_data = self.generate_daily_task(call.from_user.id)
                    else:
                        task_data = self.user_daily_tasks[telegram_id_str]
                    
                    tasks_text = f"""*🎁 Твои задания*
_Выполняй задания, чтобы получать опыт! Десять лидеров по опыту получат эксклюзивные подарки в конце сезона_
`•••••••••••••••••••`
_{task_data['text']}_"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    # Кнопка задания
                    progress_text = self.get_daily_task_progress_text(task_data, call.from_user.id)
                    if task_data["completed"]:
                        btn_task = types.InlineKeyboardButton(progress_text, callback_data="daily_task_completed")
                    else:
                        btn_task = types.InlineKeyboardButton(progress_text, callback_data="daily_task_progress")
                    
                    markup.add(btn_task)
                    
                    # Кнопки навигации
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="daily_back")
                    btn_leaderboard = types.InlineKeyboardButton("🏆", callback_data="daily_leaderboard")
                    markup.add(btn_back, btn_leaderboard)
                    
                    self.bot.edit_message_text(
                        tasks_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "daily_task_progress":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str not in self.user_daily_tasks:
                        self.bot.answer_callback_query(call.id, "Задание не найдено!")
                        return
                    
                    task_data = self.user_daily_tasks[telegram_id_str]
                    
                    if task_data["completed"]:
                        time_left = self.get_time_until_midnight()
                        completed_text = f"""🔒 *Ты уже выполнил задание сегодня*
_Возвращайся через {time_left}, и надейся на свою удачу!_"""
                        
                        self.bot.edit_message_text(
                            completed_text,
                            call.message.chat.id,
                            call.message.message_id,
                            parse_mode='Markdown'
                        )
                        
                        # Отправляем стикер
                        sticker_id = "CAACAgIAAxkBAAE9Js1pAzTTQ9xRej9YYWAs_M_2sMGFnQAC2kkAAkZFCUqenx6Y9nShgTYE"
                        self.bot.send_sticker(call.message.chat.id, sticker_id)
                        
                        # Начисляем опыт
                        experience = random.randint(83, 137)
                        if telegram_id_str not in self.user_experience:
                            self.user_experience[telegram_id_str] = 0
                        self.user_experience[telegram_id_str] += experience
                        
                        user_name = call.from_user.first_name or "путешественник"
                        exp_text = f"""*🎁 {user_name}, ты выполнил ежедневное задание!* 
_Так держать! Помни, чем больше опыта — тем круче твоя награда!_
`•••••••••••••••••••`
+ ⭐️ *{experience}* опыта!"""
                        
                        self.bot.send_message(
                            call.message.chat.id,
                            exp_text,
                            parse_mode='Markdown'
                        )
                        
                        # Генерируем новое задание
                        self.generate_daily_task(call.from_user.id)
                    else:
                        self.bot.answer_callback_query(call.id, "Задание еще не выполнено!")
                    
                elif call.data == "daily_task_completed":
                    time_left = self.get_time_until_midnight()
                    completed_text = f"""🔒 *Ты уже выполнил задание сегодня*
_Возвращайся через {time_left}, и надейся на свою удачу!_"""
                    
                    self.bot.edit_message_text(
                        completed_text,
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "daily_leaderboard":
                    leaderboard = self.get_leaderboard()
                    
                    leaderboard_text = """🏆 *Лидеры по заданиям* 
_Вот они, те, кто больше всего вкалывает ради приза_"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if leaderboard:
                        for user in leaderboard:
                            btn_text = f"{user['name']} — ⭐️{user['experience']}"
                            markup.add(types.InlineKeyboardButton(btn_text, callback_data="leaderboard_user"))
                    else:
                        markup.add(types.InlineKeyboardButton("✨ Пустой слот", callback_data="empty"))
                    
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="daily_tasks")
                    markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        leaderboard_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "daily_back":
                    daily_text = """🎁 *Ежедневные штучки*
_Выбери, что хочешь глянуть_"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_tasks = types.InlineKeyboardButton("Задания", callback_data="daily_tasks")
                    btn_bonus = types.InlineKeyboardButton("Получить бонус", callback_data="menu_bonus")
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="menu_back")
                    markup.add(btn_tasks)
                    markup.add(btn_bonus, btn_back)
                    
                    self.bot.edit_message_text(
                        daily_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "menu_back":
                    menu_text = """*✨ Меню* 
_Здесь ты найдешь все, что нужно, но не имеет команды. Мы постарались_"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn_warehouse = types.InlineKeyboardButton("📦 Склад", callback_data="menu_warehouse")
                    btn_channel = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
                    btn_daily = types.InlineKeyboardButton("🎁 Ежедневные штучки", callback_data="menu_daily")
                    
                    markup.add(btn_warehouse, btn_channel)
                    markup.add(btn_daily)
                    
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
                        self.bot.answer_callback_query(call.id, "Сессия подарка истекла!")
                        return
                    
                    chibis, current_page, total_pages = self.get_user_chibis_for_gift(call.from_user.id, page)
                    
                    gift_text = """✨ *О, да ты у нас щедрый!*
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
                        self.bot.answer_callback_query(call.id, "Сессия подарка истекла!")
                        return
                    
                    self.gift_selections[telegram_id_str]["chibi_name"] = chibi_name
                    
                    target_name = self.gift_selections[telegram_id_str]["target_name"]
                    
                    confirm_text = f"""✨ *Дарим чибика?*
_Ты уверен, что хочешь этого? Назад вернуть уже не получится_
||•••••••••••••••||
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
                        self.bot.answer_callback_query(call.id, "Сессия подарка истекла!")
                        return
                    
                    gift_data = self.gift_selections[telegram_id_str]
                    chibi_name = gift_data["chibi_name"]
                    target_telegram_id = gift_data["target_telegram_id"]
                    target_name = gift_data["target_name"]
                    
                    if telegram_id_str not in self.user_chibis or chibi_name not in self.user_chibis[telegram_id_str]:
                        self.bot.answer_callback_query(call.id, "У тебя больше нет этого чибика!")
                        return
                    
                    self.user_chibis[telegram_id_str].remove(chibi_name)
                    
                    if target_telegram_id not in self.user_chibis:
                        self.user_chibis[target_telegram_id] = []
                    self.user_chibis[target_telegram_id].append(chibi_name)
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sticker_id_sender = "CAACAgIAAxkBAAE9JtFpAzTjbRJ884hA4YNjTqPc7Z05lAACQEgAAlZVEUqWc8vDGvLqWTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id_sender)
                    
                    sender_text = f"""✨* Чибик отправлен! *
_Надеюсь, {target_name} он понравится!_"""
                    
                    self.bot.send_message(
                        call.message.chat.id,
                        sender_text,
                        parse_mode='Markdown'
                    )
                    
                    sticker_id_receiver = "CAACAgIAAxkBAAE9OxxpBRLZ5OANTuRD-97sRPdCONwv0AACU0YAAkVlEErI0vjxKMrHnTYE"
                    self.bot.send_sticker(target_telegram_id, sticker_id_receiver)
                    
                    sender_name = call.from_user.first_name or "Отправитель"
                    receiver_text = f"""*💌 Тебе подарок!*
_{sender_name} подарил тебе {chibi_name}!_"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_view = types.InlineKeyboardButton("Посмотреть", callback_data="warehouse_chibis_1")
                    markup.add(btn_view)
                    
                    self.bot.send_message(
                        target_telegram_id,
                        receiver_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                    del self.gift_selections[telegram_id_str]
                    
                elif call.data == "gift_cancel":
                    telegram_id_str = str(call.from_user.id)
                    
                    if telegram_id_str in self.gift_selections:
                        del self.gift_selections[telegram_id_str]
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                elif call.data == "chibi_click":
                    self.bot.answer_callback_query(call.id)
                    
                elif call.data == "item_click":
                    self.bot.answer_callback_query(call.id, "Этот предмет нельзя использовать!")
                    
                elif call.data == "empty":
                    self.bot.answer_callback_query(call.id, "Здесь пусто!")
                    
                elif call.data == "leaderboard_user":
                    self.bot.answer_callback_query(call.id)
                    
                else:
                    self.bot.answer_callback_query(call.id)
                    
            except Exception as e:
                logger.error(f"Ошибка в callback: {e}")
                self.bot.answer_callback_query(call.id, "❌ Ошибка!")

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
