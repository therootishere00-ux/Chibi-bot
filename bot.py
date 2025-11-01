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
        self.active_trades = {} # Храним активные трейды: {trade_id: {"from_user": user_id, "to_user": user_id, "chibi": "имя", "price": amount, "message_id": id}}
        
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

        @self.bot.message_handler(commands=['trade'])
        def trade_handler(message):
            try:
                trade_text = """🔥 *Как кинуть трейд*
_Мини-гайд, читай и запоминай!_
||•••••••••••••||
1) Напиши *в ответ* игроку это сообщение: ||дам чибик за (твоя цена)||
2) Установи свою цену. Советую использовать таблицу примерных цен (можно найти в нашем канале)
3) Выбери чибика из своей коллекции и жди, пока другой игрок, которому ты кинул обмен, *примет* его или *отклонит*"""
                
                self.bot.send_message(
                    message.chat.id,
                    trade_text,
                    parse_mode='Markdown'
                )
                
            except Exception as e:
                logger.error(f"Ошибка при показе инструкции трейда: {e}")
                self.bot.send_message(message.chat.id, "❌ Ошибка. Попробуйте позже.")

        # Обработчик текстовых сообщений для трейдов
        @self.bot.message_handler(func=lambda message: True, content_types=['text'])
        def text_message_handler(message):
            try:
                # Проверяем, является ли сообщение ответом и содержит ли ключевые слова для трейда
                if (message.reply_to_message and 
                    message.reply_to_message.from_user.id == self.bot.get_me().id and
                    "дам чибик за" in message.text.lower()):
                    
                    # Извлекаем цену из сообщения
                    text_lower = message.text.lower()
                    price_part = text_lower.split("дам чибик за")[1].strip()
                    
                    # Пытаемся извлечь число
                    try:
                        # Убираем все нецифровые символы, кроме минуса
                        price_str = ''.join(c for c in price_part.split()[0] if c.isdigit() or c == '-')
                        if price_str and price_str != '-':
                            price = int(price_str)
                            if price < 0:
                                self.bot.reply_to(message, "❌ Цена не может быть отрицательной!")
                                return
                        else:
                            price = 0
                    except (ValueError, IndexError):
                        price = 0
                    
                    # Проверяем, не пытается ли пользователь отправить трейд самому себе
                    if message.reply_to_message.forward_from and message.reply_to_message.forward_from.id == message.from_user.id:
                        self.bot.reply_to(message, "❌ Сам с собой торговаться собрался? 🤷‍♂️")
                        return
                    
                    # Получаем ID пользователя, которому предназначается трейд
                    # Это сложно, так как мы не знаем точно, кому было исходное сообщение
                    # В реальном боте нужно хранить информацию о том, кому были отправлены сообщения
                    # Для простоты будем считать, что трейд можно отправить только в ответ на сообщение бота
                    
                    # Показываем выбор чибика для трейда
                    trade_text = f"🔥* Отлично! Теперь выбери чибика*\n_Тапни по нужному, которого хочешь обменять на {price} коинов_"
                    
                    # Получаем чибиков пользователя с пагинацией
                    chibis, current_page, total_pages = self.get_user_chibis_paginated(message.from_user.id, 1, 6)
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    # Добавляем кнопки чибиков
                    if chibis:
                        for chibi_name, count in chibis:
                            if count > 1:
                                btn_text = f"{chibi_name} ({count})"
                            else:
                                btn_text = chibi_name
                            callback_data = f"trade_select_{price}_{chibi_name.replace(' ', '_')}"
                            markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
                    else:
                        markup.add(types.InlineKeyboardButton("У тебя нет чибиков!", callback_data="no_chibis"))
                    
                    # Добавляем навигацию
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"trade_page_{((current_page-2) % total_pages) + 1}_{price}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Отменить", callback_data="trade_cancel"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"trade_page_{(current_page % total_pages) + 1}_{price}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.send_message(
                        message.chat.id,
                        trade_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
            except Exception as e:
                logger.error(f"Ошибка при обработке текстового сообщения: {e}")

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
                    
                elif call.data == "menu_warehouse":
                    # Показываем меню склада
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
                    # Показываем коллекцию чибиков
                    page = int(call.data.split("_")[2])
                    chibis, current_page, total_pages = self.get_user_chibis_paginated(call.from_user.id, page)
                    
                    chibis_text = f"""📦 *Твои чибики*
_Великолепные и неповторимые. Ну, почти…
Страница {current_page}/{total_pages}_"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    # Добавляем кнопки чибиков
                    if chibis:
                        for chibi_name, count in chibis:
                            if count > 1:
                                btn_text = f"{chibi_name} ({count})"
                            else:
                                btn_text = chibi_name
                            markup.add(types.InlineKeyboardButton(btn_text, callback_data="chibi_click"))
                    else:
                        markup.add(types.InlineKeyboardButton("Пусто", callback_data="empty"))
                    
                    # Добавляем навигацию
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
                    # Показываем коллекцию предметов
                    page = int(call.data.split("_")[2])
                    items, current_page, total_pages = self.get_user_items_paginated(call.from_user.id, page)
                    
                    items_text = f"""*📦 Твои предметы* 
_Тут хранятся твои боксы. Других предметов в боте пока и нет…
Страница {current_page}/{total_pages}_"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    # Добавляем кнопки предметов
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
                    
                    # Добавляем навигацию
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
                    # Подтверждение открытия Чиби-пака
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
                    # Открываем Чиби-пак
                    count = int(call.data.split("_")[2])
                    telegram_id_str = str(call.from_user.id)
                    
                    # Проверяем, есть ли достаточно паков
                    current_packs = self.user_items.get(telegram_id_str, {}).get("🧧 Чиби-пак", 0)
                    if current_packs < count:
                        self.bot.answer_callback_query(call.id, "Недостаточно Чиби-паков!")
                        return
                    
                    # Уменьшаем количество паков
                    self.user_items[telegram_id_str]["🧧 Чиби-пак"] = current_packs - count
                    
                    # Открываем паки и получаем чибиков
                    for i in range(count):
                        file_path, chibi_name, rarity = self.get_random_chibi(from_pack=True)
                        
                        if file_path is not None:
                            # Добавляем чибика в коллекцию пользователя
                            if telegram_id_str not in self.user_chibis:
                                self.user_chibis[telegram_id_str] = []
                            self.user_chibis[telegram_id_str].append(chibi_name)
                            
                            # Получаем количество этого чибика у пользователя
                            chibi_count = self.get_chibi_count(call.from_user.id, chibi_name)
                            
                            # Формируем текст сообщения для выпавшего чибика
                            rarity_emoji = "🔷" if rarity == "Common" else "💠"
                            chibi_text = f"""*🔥 Тебе выпал — {chibi_name}!*
_Надеюсь, он тебе понравился!_
`•••••••••••••••••••`
Редкость: {rarity_emoji} _{rarity}_
У тебя: {chibi_count}"""
                            
                            # Отправляем картинку с текстом
                            with open(file_path, 'rb') as photo:
                                self.bot.send_photo(
                                    call.message.chat.id,
                                    photo,
                                    caption=chibi_text,
                                    parse_mode='Markdown'
                                )
                    
                    self.bot.answer_callback_query(call.id, f"Открыто {count} Чиби-пак(ов)!")
                    
                    # Возвращаемся к предметам
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
                    # Показываем покупку Чиби-пака
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
                    # Покупаем Чиби-пак
                    telegram_id_str = str(call.from_user.id)
                    coins = self.user_coins.get(telegram_id_str, 0)
                    
                    if coins < 120:
                        self.bot.answer_callback_query(call.id, "Недостаточно коинов! Нужно 120.")
                        return
                    
                    # Списываем коины
                    self.user_coins[telegram_id_str] = coins - 120
                    
                    # Добавляем Чиби-пак
                    if telegram_id_str not in self.user_items:
                        self.user_items[telegram_id_str] = {}
                    
                    if "🧧 Чиби-пак" not in self.user_items[telegram_id_str]:
                        self.user_items[telegram_id_str]["🧧 Чиби-пак"] = 0
                    
                    self.user_items[telegram_id_str]["🧧 Чиби-пак"] += 1
                    
                    self.bot.answer_callback_query(call.id, "Чиби-пак куплен!")
                    
                    # Возвращаемся в лавку
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
                    # Возвращаемся в лавку
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
                    # Ежедневный бонус
                    telegram_id_str = str(call.from_user.id)
                    bonus = random.randint(7, 19)
                    
                    # Начисляем бонус
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
                    # Возвращаемся к главному меню
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
                    
                # Обработчики для системы трейдов
                elif call.data.startswith("trade_page_"):
                    # Переключение страницы при выборе чибика для трейда
                    parts = call.data.split("_")
                    page = int(parts[2])
                    price = int(parts[3])
                    
                    chibis, current_page, total_pages = self.get_user_chibis_paginated(call.from_user.id, page, 6)
                    
                    trade_text = f"🔥* Отлично! Теперь выбери чибика*\n_Тапни по нужному, которого хочешь обменять на {price} коинов_"
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if chibis:
                        for chibi_name, count in chibis:
                            if count > 1:
                                btn_text = f"{chibi_name} ({count})"
                            else:
                                btn_text = chibi_name
                            callback_data = f"trade_select_{price}_{chibi_name.replace(' ', '_')}"
                            markup.add(types.InlineKeyboardButton(btn_text, callback_data=callback_data))
                    else:
                        markup.add(types.InlineKeyboardButton("У тебя нет чибиков!", callback_data="no_chibis"))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"trade_page_{((current_page-2) % total_pages) + 1}_{price}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Отменить", callback_data="trade_cancel"))
                    
                    if total_pages > 1:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"trade_page_{(current_page % total_pages) + 1}_{price}"))
                    
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        trade_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("trade_select_"):
                    # Выбор чибика для трейда
                    parts = call.data.split("_")
                    price = int(parts[2])
                    chibi_name = " ".join(parts[3:])  # Восстанавливаем имя с пробелами
                    
                    # Удаляем сообщение с выбором чибика
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    # Отправляем предложение трейда
                    from_user_name = call.from_user.first_name or "Неизвестный"
                    price_text = f"💰*{price}*" if price > 0 else "бесплатно"
                    
                    trade_offer_text = f"""🔥*Эй, {from_user_name}!*
_Кажется, у кого-то для тебя сделка! Решай, соглашаться или нет_"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn_accept = types.InlineKeyboardButton("Принять", callback_data=f"trade_accept_{call.from_user.id}_{chibi_name.replace(' ', '_')}_{price}")
                    btn_decline = types.InlineKeyboardButton("Отклонить", callback_data=f"trade_decline_{call.from_user.id}")
                    markup.add(btn_accept, btn_decline)
                    
                    # В реальном боте здесь нужно отправить сообщение конкретному пользователю
                    # Для демонстрации отправляем в тот же чат
                    self.bot.send_message(
                        call.message.chat.id,
                        trade_offer_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "trade_cancel":
                    # Отмена трейда
                    self.bot.edit_message_text(
                        "✨ *Трейд отменен*",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("trade_accept_"):
                    # Принятие трейда
                    parts = call.data.split("_")
                    from_user_id = int(parts[2])
                    chibi_name = " ".join(parts[3:-1])  # Восстанавливаем имя с пробелами
                    price = int(parts[-1])
                    
                    # Проверяем, не пытается ли пользователь принять свой же трейд
                    if from_user_id == call.from_user.id:
                        self.bot.answer_callback_query(call.id, "❌ Нельзя принять свой же трейд!")
                        return
                    
                    # Проверяем, есть ли у принимающего достаточно коинов
                    telegram_id_str = str(call.from_user.id)
                    coins = self.user_coins.get(telegram_id_str, 0)
                    
                    if price > 0 and coins < price:
                        self.bot.answer_callback_query(call.id, "❌ Недостаточно коинов!")
                        return
                    
                    # Проверяем, есть ли у отправителя выбранный чибик
                    from_user_str = str(from_user_id)
                    if (from_user_str not in self.user_chibis or 
                        chibi_name not in self.user_chibis[from_user_str]):
                        self.bot.answer_callback_query(call.id, "❌ У отправителя больше нет этого чибика!")
                        return
                    
                    # Выполняем обмен
                    # Убираем чибик у отправителя
                    self.user_chibis[from_user_str].remove(chibi_name)
                    
                    # Добавляем чибик получателю
                    if telegram_id_str not in self.user_chibis:
                        self.user_chibis[telegram_id_str] = []
                    self.user_chibis[telegram_id_str].append(chibi_name)
                    
                    # Переводим коины
                    if price > 0:
                        # Списываем у получателя
                        self.user_coins[telegram_id_str] = coins - price
                        # Начисляем отправителю
                        if from_user_str not in self.user_coins:
                            self.user_coins[from_user_str] = 0
                        self.user_coins[from_user_str] += price
                    
                    # Удаляем сообщение с трейдом
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    # Отправляем стикер
                    sticker_id = "CAACAgIAAxkBAAE9Js1pAzTTQ9xRej9YYWAs_M_2sMGFnQAC2kkAAkZFCUqenx6Y9nShgTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker_id)
                    
                    # Отправляем сообщение об успешном трейде
                    from_user_name = "Неизвестный"
                    to_user_name = call.from_user.first_name or "Неизвестный"
                    
                    # Получаем имя отправителя из данных пользователя
                    if from_user_str in self.users:
                        from_user_name = self.users[from_user_str].get('first_name', 'Неизвестный')
                    
                    price_text = f"💰*{price}*" if price > 0 else "бесплатно"
                    
                    trade_success_text = f"""*🔥 {to_user_name} выменял у {from_user_name}*
||••••••••••••••••||
*{chibi_name}* за {price_text}"""
                    
                    self.bot.send_message(
                        call.message.chat.id,
                        trade_success_text,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("trade_decline_"):
                    # Отклонение трейда
                    from_user_id = int(call.data.split("_")[2])
                    from_user_name = "Неизвестный"
                    
                    # Получаем имя отправителя из данных пользователя
                    from_user_str = str(from_user_id)
                    if from_user_str in self.users:
                        from_user_name = self.users[from_user_str].get('first_name', 'Неизвестный')
                    
                    decliner_name = call.from_user.first_name or "Неизвестный"
                    
                    self.bot.edit_message_text(
                        f"✨ {decliner_name} отклонил трейд",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "chibi_click":
                    # При нажатии на чибика ничего не происходит
                    self.bot.answer_callback_query(call.id)
                    
                elif call.data == "item_click":
                    self.bot.answer_callback_query(call.id, "Этот предмет нельзя использовать!")
                    
                elif call.data == "empty":
                    self.bot.answer_callback_query(call.id, "Здесь пусто!")
                    
                elif call.data == "no_chibis":
                    self.bot.answer_callback_query(call.id, "У тебя нет чибиков для трейда!")
                    
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
