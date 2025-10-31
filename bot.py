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
    def __init__(self, telegram_bot):
        self.bot = telegram_bot
        self.users = {}  # Храним в памяти
        self.used_ids = set()
        self.user_chibis = {}  # Храним чибиков пользователей: {user_id: [chibi_name1, chibi_name2, ...]}
        self.user_items = {}   # Храним предметы пользователей: {user_id: {"🧧 Чиби-пак": 1}}
        self.user_tasks = {}   # Храним текущие задания пользователей: {user_id: {"chibi": "имя", "reward": 35, "emoji": "🐊", "name": "Грирт"}}
        self.user_coins = {}   # Храним коины пользователей: {user_id: 0}
        self.user_gift_data = {}  # Храним данные о подарках: {user_id: {"chibi": "имя", "recipient_id": "123"}}
        
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

    def get_user_chibis_paginated_for_gift(self, telegram_id, page=1, per_page=6):
        """Получает чибиков пользователя с пагинацией для подарка"""
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
            key=lambda x: (-x[1], x[0])  # Сначала по количеству (убывание), потом по имени
        )
        
        # Пагинация
        total_pages = max(1, (len(sorted_chibis) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_chibis = sorted_chibis[start_idx:end_idx]
        
        return page_chibis, page, total_pages

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
        phrase = random.choice(phrases).format(chibi=chibi_name)  # Убрали ** из курсивных реплик
        
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
            key=lambda x: (-x[1], x[0])  # Сначала по количеству (убывание), потом по имени
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
            key=lambda x: (-x[1], x[0])  # Сначала по количеству (убывание), потом по имени
        )
        
        # Пагинация
        total_pages = max(1, (len(sorted_items) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_items = sorted_items[start_idx:end_idx]
        
        return page_items, page, total_pages

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
                    # Стикер для нового пользователя (waving hand)
                    sticker_id = "CAACAgIAAxkBAAE9JsNpAzQZv6b4b-KZ3ftL2Sld0kUjDQAC400AAkuWEEosjitzZk8fzDYE"
                else:
                    # Стикер для существующего пользователя (rainbow)
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
                
                # Используем моноширинный шрифт (обратные кавычки)
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

        @self.bot.message_handler(commands=['share'])
        def share_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                
                # Проверяем, есть ли чибики для подарка
                if telegram_id_str not in self.user_chibis or not self.user_chibis[telegram_id_str]:
                    self.bot.send_message(message.chat.id, "❌ У тебя нет чибиков для подарка!")
                    return
                
                share_text = """*✨ О, да у нас ты щедрый!*
_Выбери чибика, которого хочешь передать другому игроку_"""
                
                chibis, current_page, total_pages = self.get_user_chibis_paginated_for_gift(message.from_user.id, 1)
                
                markup = types.InlineKeyboardMarkup()
                
                # Добавляем кнопки чибиков (по 6 в ряд)
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
                
                self.bot.send_message(
                    message.chat.id,
                    share_text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Ошибка при открытии подарков: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка при открытии подарков. Попробуйте позже.")

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
                
                # Создаем инлайн-кнопки
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
                
                # Создаем кнопки меню
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn_warehouse = types.InlineKeyboardButton("📦 Склад", callback_data="menu_warehouse")
                btn_channel = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
                btn_bonus = types.InlineKeyboardButton("🎁 Ежедневный бонус", callback_data="menu_bonus")
                
                # Располагаем кнопки по две в ряд
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

        # Обработчик текстовых сообщений для комментария к подарку
        @self.bot.message_handler(func=lambda message: True, content_types=['text'])
        def text_handler(message):
            try:
                telegram_id_str = str(message.from_user.id)
                
                # Проверяем, ожидается ли комментарий к подарку
                if (telegram_id_str in self.user_gift_data and 
                    'waiting_comment' in self.user_gift_data[telegram_id_str] and
                    self.user_gift_data[telegram_id_str]['waiting_comment']):
                    
                    comment = message.text[:60]  # Обрезаем до 60 символов
                    self.user_gift_data[telegram_id_str]['comment'] = comment
                    self.user_gift_data[telegram_id_str]['waiting_comment'] = False
                    
                    # Отправляем подарок получателю
                    self.send_gift_to_recipient(telegram_id_str)
                    
                    # Удаляем сообщение с комментарием
                    self.bot.delete_message(message.chat.id, message.message_id)
                    
            except Exception as e:
                logger.error(f"Ошибка в обработке текста: {e}")

        # Обработчик callback для кнопок
        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call):
            try:
                if call.data == "task_complete":
                    # Выполняем задание
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str not in self.user_tasks or self.user_tasks[telegram_id_str] is None:
                        self.bot.answer_callback_query(call.id, "Задание уже выполнено!")
                        return
                    
                    task_data = self.user_tasks[telegram_id_str]
                    
                    # Убираем один чибик из коллекции
                    if telegram_id_str in self.user_chibis and task_data["chibi"] in self.user_chibis[telegram_id_str]:
                        # Удаляем первое вхождение чибика
                        self.user_chibis[telegram_id_str].remove(task_data["chibi"])
                    
                    # Удаляем сообщение с заданием
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    # Отправляем стикер
                    sticker_id = "CAACAgIAAxkBAAE9Js9pAzTWs9gLLtl9Gqz_9V_4sbwXqgAC7EYAAjNREEqhVSL_nxyHZTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id)
                    
                    # Начисляем награду
                    reward = task_data["reward"]
                    if telegram_id_str not in self.user_coins:
                        self.user_coins[telegram_id_str] = 0
                    self.user_coins[telegram_id_str] += reward
                    
                    # Отправляем сообщение о выполнении
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
                    
                    # Удаляем задание
                    self.user_tasks[telegram_id_str] = None
                    
                elif call.data == "task_cannot_complete":
                    self.bot.answer_callback_query(call.id, "У тебя нет нужного чибика!")
                    
                elif call.data == "task_skip":
                    # Пропускаем задание
                    telegram_id_str = str(call.from_user.id)
                    self.user_tasks[telegram_id_str] = None  # Удаляем задание
                    
                    # Удаляем сообщение с заданием
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    # Отправляем сообщение о пропуске
                    skip_text = """✨*Ты пропустил таск. Жди новый!*
_Осталось 8ч 59м_"""
                    
                    self.bot.send_message(
                        call.message.chat.id,
                        skip_text,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "task_skip_confirm":
                    # Подтверждение пропуска задания
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
                    # Возвращаемся к заданию
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

                # Обработчики для системы подарков
                elif call.data.startswith("share_page_"):
                    # Переключение страницы в подарках
                    page = int(call.data.split("_")[2])
                    chibis, current_page, total_pages = self.get_user_chibis_paginated_for_gift(call.from_user.id, page)
                    
                    share_text = """*✨ О, да у нас ты щедрый!*
_Выбери чибика, которого хочешь передать другому игроку_"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    for chibi_name, count in chibis:
                        if count > 1:
                            btn_text = f"{chibi_name} ({count})"
                        else:
                            btn_text = chibi_name
                        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"share_select_{chibi_name}"))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"share_page_{((current_page-2) % total_pages) + 1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Отмена", callback_data="share_cancel"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"share_page_{(current_page % total_pages) + 1}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        share_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("share_select_"):
                    # Выбор чибика для подарка
                    chibi_name = call.data[13:]
                    telegram_id_str = str(call.from_user.id)
                    
                    # Сохраняем выбранного чибика
                    if telegram_id_str not in self.user_gift_data:
                        self.user_gift_data[telegram_id_str] = {}
                    self.user_gift_data[telegram_id_str]['chibi'] = chibi_name
                    self.user_gift_data[telegram_id_str]['waiting_id'] = True
                    
                    select_text = f"""*✨ {chibi_name} — хороший выбор!*
_Надеюсь, тому кому ты его даришь, он понравится! Хотя как такой милашка может не понравиться?_
`•••••••••••••••••`
*Укажи АЙДИ игрока, которому хочешь подарить чибика*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn_back = types.InlineKeyboardButton("Назад", callback_data="share_back_to_select")
                    markup.add(btn_back)
                    
                    self.bot.edit_message_text(
                        select_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "share_back_to_select":
                    # Возврат к выбору чибика
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str in self.user_gift_data:
                        self.user_gift_data[telegram_id_str]['waiting_id'] = False
                    
                    chibis, current_page, total_pages = self.get_user_chibis_paginated_for_gift(call.from_user.id, 1)
                    
                    share_text = """*✨ О, да у нас ты щедрый!*
_Выбери чибика, которого хочешь передать другому игроку_"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    for chibi_name, count in chibis:
                        if count > 1:
                            btn_text = f"{chibi_name} ({count})"
                        else:
                            btn_text = chibi_name
                        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"share_select_{chibi_name}"))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"share_page_{((current_page-2) % total_pages) + 1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Отмена", callback_data="share_cancel"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"share_page_{(current_page % total_pages) + 1}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        share_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "share_cancel":
                    # Отмена подарка
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str in self.user_gift_data:
                        del self.user_gift_data[telegram_id_str]
                    
                    self.bot.edit_message_text(
                        "✨ Отправка отменена",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "share_send":
                    # Отправка подарка
                    telegram_id_str = str(call.from_user.id)
                    if (telegram_id_str not in self.user_gift_data or 
                        'chibi' not in self.user_gift_data[telegram_id_str] or
                        'recipient_id' not in self.user_gift_data[telegram_id_str]):
                        self.bot.answer_callback_query(call.id, "Ошибка данных!")
                        return
                    
                    # Удаляем сообщение с подтверждением
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    # Отправляем стикер
                    sticker_id = "CAACAgIAAxkBAAE9OxppBRLT9hWlWfG7yBpIsWHP2C1RDAACmEgAArVBEUrgISK9DPQ8-jYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id)
                    
                    # Сообщение об успешной отправке
                    user_name = call.from_user.first_name or "путешественник"
                    recipient_name = self.user_gift_data[telegram_id_str].get('recipient_name', 'ноунейм')
                    chibi_name = self.user_gift_data[telegram_id_str]['chibi']
                    
                    success_text = f"""✨ *Так держать, {user_name}!*
_Ты отправил этого чибика прямиком {recipient_name}_
`•••••••••••••••••`
*P.S* Если хочешь, у тебя есть 15 секунд чтобы написать комментарий к подарку. Его увидит получатель. Только постарайся покороче, лимит — 60 символов!"""
                    
                    self.bot.send_message(
                        call.message.chat.id,
                        success_text,
                        parse_mode='Markdown'
                    )
                    
                    # Устанавливаем флаг ожидания комментария
                    self.user_gift_data[telegram_id_str]['waiting_comment'] = True
                    
                elif call.data == "share_final_cancel":
                    # Отмена на финальном шаге
                    telegram_id_str = str(call.from_user.id)
                    if telegram_id_str in self.user_gift_data:
                        del self.user_gift_data[telegram_id_str]
                    
                    self.bot.edit_message_text(
                        "✨ Отправка отменена",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                # Остальные обработчики...
                # ... (остальной код остается без изменений)

            except Exception as e:
                logger.error(f"Ошибка в callback: {e}")
                self.bot.answer_callback_query(call.id, "❌ Ошибка!")

    def send_gift_to_recipient(self, sender_id_str):
        """Отправляет подарок получателю"""
        try:
            gift_data = self.user_gift_data[sender_id_str]
            chibi_name = gift_data['chibi']
            recipient_id = gift_data['recipient_id']
            comment = gift_data.get('comment', '')
            sender_name = self.users.get(sender_id_str, {}).get('first_name', 'ноунейм')
            
            # Убираем чибика у отправителя
            if sender_id_str in self.user_chibis and chibi_name in self.user_chibis[sender_id_str]:
                self.user_chibis[sender_id_str].remove(chibi_name)
            
            # Добавляем чибика получателю
            if recipient_id not in self.user_chibis:
                self.user_chibis[recipient_id] = []
            self.user_chibis[recipient_id].append(chibi_name)
            
            # Формируем сообщение для получателя
            recipient_text = f"""*✨ Эй, {self.users.get(recipient_id, {}).get('first_name', 'путешественник')}!*
_Кажется, у кого-то для тебя подгон!_ 
`•••••••••••••••••`
Тебе подарили: *{chibi_name}*
Отправитель: *{sender_name}*"""
            
            if comment:
                recipient_text += f"\n\nКомментарий: _{comment}_"
            
            # Отправляем сообщение получателю
            self.bot.send_message(
                int(recipient_id),
                recipient_text,
                parse_mode='Markdown'
            )
            
            # Очищаем данные о подарке
            del self.user_gift_data[sender_id_str]
            
        except Exception as e:
            logger.error(f"Ошибка при отправке подарка: {e}")

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
