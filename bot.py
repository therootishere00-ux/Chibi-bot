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
        self.share_sessions = {}  # Храним сессии обмена: {user_id: {"selected_chibi": "имя", "recipient_id": "ID"}}
        
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

    def get_share_chibis_paginated(self, telegram_id, page=1, per_page=6):
        """Получает чибиков пользователя для команды /share с пагинацией по 6"""
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
                
                telegram_id_str = str(message.from_user.id)
                if telegram_id_str not in self.user_chibis:
                    self.user_chibis[telegram_id_str] = []
                self.user_chibis[telegram_id_str].append(chibi_name)
                
                chibi_count = self.get_chibi_count(message.from_user.id, chibi_name)
                
                rarity_emoji = "🔷" if rarity == "Common" else "💠"
                chibi_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Надеюсь, он тебе понравился! Приходи еще через *3ч 59м*_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _Common_
У тебя: {chibi_count}"""
                
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
                btn_bonus = types.InlineKeyboardButton("🎁 Ежедневный бонус", callback_data="menu_bonus")
                
                markup.add(btn_warehouse, btn_channel)
                markup.add(btn_bonus)
                
                self.bot.send_message(
                    message.chat.id,
                    menu_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Ошибка при открытии меню: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка при открытии меню. Попробуйте позже.")

        @self.bot.message_handler(commands=['share'])
        def share_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                
                # Проверяем, есть ли чибики для обмена
                if telegram_id_str not in self.user_chibis or not self.user_chibis[telegram_id_str]:
                    self.bot.send_message(message.chat.id, "❌ У тебя нет чибиков для обмена!")
                    return
                
                # Инициализируем сессию обмена
                self.share_sessions[telegram_id_str] = {
                    "selected_chibi": None,
                    "recipient_id": None,
                    "message_id": None
                }
                
                # Показываем первый список чибиков
                self.show_share_chibis_page(message.chat.id, telegram_id_str, 1)
                
            except Exception as e:
                logger.error(f"Ошибка при запуске обмена: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка при запуске обмена. Попробуйте позже.")

        def show_share_chibis_page(self, chat_id, telegram_id_str, page):
            """Показывает страницу с чибиками для обмена"""
            chibis, current_page, total_pages = self.get_share_chibis_paginated(int(telegram_id_str), page, per_page=6)
            
            share_text = """*✨ О, да ты у нас щедрый!*
_Выбери чибика, которого хочешь передать другому игроку_"""
            
            markup = types.InlineKeyboardMarkup()
            
            # Добавляем кнопки чибиков (по одной в ряд)
            for chibi_name, count in chibis:
                if count > 1:
                    btn_text = f"{chibi_name} ({count})"
                else:
                    btn_text = chibi_name
                markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"share_select_{chibi_name}"))
            
            # Добавляем навигацию
            nav_buttons = []
            if total_pages > 1:
                nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"share_page_{((current_page-2) % total_pages) + 1}"))
            
            nav_buttons.append(types.InlineKeyboardButton("Отмена", callback_data="share_cancel"))
            
            if total_pages > 1:
                nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"share_page_{(current_page % total_pages) + 1}"))
            
            markup.row(*nav_buttons)
            
            # Отправляем или редактируем сообщение
            if telegram_id_str in self.share_sessions and self.share_sessions[telegram_id_str].get("message_id"):
                self.bot.edit_message_text(
                    share_text,
                    chat_id,
                    self.share_sessions[telegram_id_str]["message_id"],
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
            else:
                msg = self.bot.send_message(
                    chat_id,
                    share_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                if telegram_id_str in self.share_sessions:
                    self.share_sessions[telegram_id_str]["message_id"] = msg.message_id

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
                        self.bot.answer_callback_query(call.id, "Недостаточно Чиби-паков!")
                        return
                    
                    self.user_items[telegram_id_str]["🧧 Чиби-пак"] = current_packs - count
                    
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

                # Обработчики для команды /share
                elif call.data.startswith("share_page_"):
                    page = int(call.data.split("_")[2])
                    telegram_id_str = str(call.from_user.id)
                    self.show_share_chibis_page(call.message.chat.id, telegram_id_str, page)
                    
                elif call.data.startswith("share_select_"):
                    chibi_name = call.data.split("_", 2)[2]
                    telegram_id_str = str(call.from_user.id)
                    
                    # Сохраняем выбранного чибика в сессии
                    if telegram_id_str in self.share_sessions:
                        self.share_sessions[telegram_id_str]["selected_chibi"] = chibi_name
                    
                    share_confirm_text = f"""*✨ {chibi_name} — хороший выбор!*
_Надеюсь, тому кому ты его даришь, он понравится! Хотя как такой милашка может не понравиться?_
||•••••••••••••••••||
*Укажи АЙДИ игрока, которому хочешь подарить чибика*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="share_back_to_select")
                    markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        share_confirm_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "share_back_to_select":
                    telegram_id_str = str(call.from_user.id)
                    self.show_share_chibis_page(call.message.chat.id, telegram_id_str, 1)
                    
                elif call.data == "share_cancel":
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str in self.share_sessions:
                        del self.share_sessions[telegram_id_str]
                    
                    self.bot.edit_message_text(
                        "✨ Отправка отменена",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "share_final_confirm":
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str not in self.share_sessions:
                        self.bot.answer_callback_query(call.id, "Сессия истекла!")
                        return
                    
                    session = self.share_sessions[telegram_id_str]
                    chibi_name = session["selected_chibi"]
                    recipient_id = session["recipient_id"]
                    
                    # Проверяем, есть ли чибик у отправителя
                    if (telegram_id_str not in self.user_chibis or 
                        chibi_name not in self.user_chibis[telegram_id_str]):
                        self.bot.answer_callback_query(call.id, "У тебя больше нет этого чибика!")
                        return
                    
                    # Удаляем чибика у отправителя
                    self.user_chibis[telegram_id_str].remove(chibi_name)
                    
                    # Добавляем чибика получателю
                    if recipient_id not in self.user_chibis:
                        self.user_chibis[recipient_id] = []
                    self.user_chibis[recipient_id].append(chibi_name)
                    
                    # Удаляем сообщение с подтверждением
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    # Отправляем стикер
                    sticker_id = "CAACAgIAAxkBAAE9OxppBRLT9hWlWfG7yBpIsWHP2C1RDAACmEgAArVBEUrgISK9DPQ8-jYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id)
                    
                    # Отправляем сообщение о возможности комментария
                    user_name = call.from_user.first_name or "путешественник"
                    comment_text = f"""✨ *Так держать, {user_name}!*
_Ты отправил этого чибика прямиком {session['recipient_name']}_
||•••••••••••••••••||
*P.S* Если хочешь, у тебя есть 15 секунд чтобы написать комментарий к подарку. Его увидит получатель. Только постарайся покороче, лимит — 60 символов!"""
                    
                    self.bot.send_message(
                        call.message.chat.id,
                        comment_text,
                        parse_mode='Markdown'
                    )
                    
                    # Сохраняем информацию для обработки комментария
                    self.share_sessions[telegram_id_str]["waiting_comment"] = True
                    self.share_sessions[telegram_id_str]["recipient_info"] = {
                        "id": recipient_id,
                        "name": session['recipient_name']
                    }
                    self.share_sessions[telegram_id_str]["chibi_name"] = chibi_name
                    self.share_sessions[telegram_id_str]["sender_name"] = user_name
                    
                elif call.data == "share_final_cancel":
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str in self.share_sessions:
                        del self.share_sessions[telegram_id_str]
                    
                    self.bot.edit_message_text(
                        "✨ Отправка отменена",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "chibi_click":
                    self.bot.answer_callback_query(call.id)
                    
                elif call.data == "item_click":
                    self.bot.answer_callback_query(call.id, "Этот предмет нельзя использовать!")
                    
                elif call.data == "empty":
                    self.bot.answer_callback_query(call.id, "Здесь пусто!")
                    
                else:
                    self.bot.answer_callback_query(call.id)
                    
            except Exception as e:
                logger.error(f"Ошибка в callback: {e}")
                self.bot.answer_callback_query(call.id, "❌ Ошибка!")

        # Обработчик текстовых сообщений для команды /share
        @self.bot.message_handler(func=lambda message: True)
        def text_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                
                # Проверяем, ожидаем ли мы ID получателя для обмена
                if (telegram_id_str in self.share_sessions and 
                    self.share_sessions[telegram_id_str].get("selected_chibi") and 
                    not self.share_sessions[telegram_id_str].get("recipient_id")):
                    
                    recipient_id = message.text.strip()
                    
                    # Проверяем, не пытается ли пользователь отправить самому себе
                    user_data, _ = self.get_or_create_user(message.from_user.id)
                    if recipient_id == user_data['user_id']:
                        self.bot.send_message(message.chat.id, "Сам себе дарить собрался?")
                        return
                    
                    # Ищем получателя по ID
                    recipient_telegram_id = None
                    recipient_name = "ноунейм"
                    
                    for tg_id, user_info in self.users.items():
                        if user_info['user_id'] == recipient_id:
                            recipient_telegram_id = tg_id
                            recipient_name = user_info.get('first_name') or user_info.get('username') or "ноунейм"
                            break
                    
                    if not recipient_telegram_id:
                        self.bot.send_message(message.chat.id, "❌ Игрок с таким ID не найден!")
                        return
                    
                    # Сохраняем информацию о получателе
                    self.share_sessions[telegram_id_str]["recipient_id"] = recipient_telegram_id
                    self.share_sessions[telegram_id_str]["recipient_name"] = recipient_name
                    
                    chibi_name = self.share_sessions[telegram_id_str]["selected_chibi"]
                    
                    # Показываем финальное подтверждение
                    final_text = f"""✨* Финальный шаг*
_Ты УВЕРЕН, что хочешь подарить его? Проверь, чтобы все данные были указаны верно и был выбран нужный чибик_
||•••••••••••••••••||
Что дарим: *{chibi_name}*
Кто получит: *{recipient_name}*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_send = types.InlineKeyboardButton("Отправить", callback_data="share_final_confirm")
                    btn_cancel = types.InlineKeyboardButton("Отмена", callback_data="share_final_cancel")
                    markup.add(btn_send, btn_cancel)
                    
                    # Удаляем предыдущее сообщение с просьбой ввести ID
                    if self.share_sessions[telegram_id_str].get("message_id"):
                        self.bot.delete_message(message.chat.id, self.share_sessions[telegram_id_str]["message_id"])
                    
                    msg = self.bot.send_message(
                        message.chat.id,
                        final_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.share_sessions[telegram_id_str]["message_id"] = msg.message_id
                    
                # Проверяем, ожидаем ли мы комментарий к подарку
                elif (telegram_id_str in self.share_sessions and 
                      self.share_sessions[telegram_id_str].get("waiting_comment")):
                    
                    comment = message.text.strip()
                    session = self.share_sessions[telegram_id_str]
                    
                    # Обрезаем комментарий до 60 символов
                    if len(comment) > 60:
                        comment = comment[:60] + "..."
                    
                    # Отправляем уведомление получателю
                    recipient_id = session["recipient_info"]["id"]
                    chibi_name = session["chibi_name"]
                    sender_name = session["sender_name"]
                    
                    # Находим файл чибика
                    file_path = None
                    for folder in ["chibis/common", "chibis/secret"]:
                        if os.path.exists(folder):
                            for file in os.listdir(folder):
                                if file.lower().endswith('.png') and chibi_name.replace(' ', '_') in file:
                                    file_path = os.path.join(folder, file)
                                    break
                            if file_path:
                                break
                    
                    gift_text = f"""*✨ Эй, {session['recipient_info']['name']}!*
_Кажется, у кого-то для тебя подгон!_ 
||•••••••••••••••••||
Тебе подарили: *{chibi_name}*
Отправитель: *{sender_name}*"""
                    
                    if comment:
                        gift_text += f"\n\nКомментарий: _{comment}_"
                    
                    if file_path and os.path.exists(file_path):
                        with open(file_path, 'rb') as photo:
                            self.bot.send_photo(
                                recipient_id,
                                photo,
                                caption=gift_text,
                                parse_mode='Markdown'
                            )
                    else:
                        self.bot.send_message(
                            recipient_id,
                            gift_text,
                            parse_mode='Markdown'
                        )
                    
                    # Завершаем сессию
                    del self.share_sessions[telegram_id_str]
                    
                    self.bot.send_message(message.chat.id, "✅ Комментарий отправлен!")
                    
            except Exception as e:
                logger.error(f"Ошибка в текстовом обработчике: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка при обработке запроса.")

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
