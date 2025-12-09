import telebot
from telebot import types
import random
import string
import os
import logging
import threading
import time
import math
from flask import Flask, request, jsonify
from datetime import datetime, timedelta
from pymongo import MongoClient
from flask_cors import CORS
from bson.objectid import ObjectId

from config import BOT_CONFIG, BOT_TEXTS, BOT_SETTINGS, STICKERS, RARITY_EMOJIS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChibiBot:
    def __init__(self, token):
        self.bot = telebot.TeleBot(token)
        self.test_users = BOT_SETTINGS['test_users']
        
        if "RENDER" in os.environ:
            self.app = Flask(__name__)
            CORS(self.app)
        
        self.mongo_uri = os.getenv('MONGODB_URI')
        if not self.mongo_uri:
            logger.error("MONGODB_URI не найден!")
            raise ValueError("MONGODB_URI не найден")
        
        try:
            self.client = MongoClient(self.mongo_uri)
            self.db = self.client.chibibot
            self.users = self.db.users
            self.system = self.db.system
            self.temp = self.db.temp
            self.market = self.db.market
            
            self.temp.create_index("created_at", expireAfterSeconds=3600)
            self.market.create_index("created_at")
            logger.info("Успешное подключение к MongoDB")
        except Exception as e:
            logger.error(f"Ошибка подключения к MongoDB: {e}")
            raise
        
        self.common_chibis = self._scan_chibis("chibis/common")
        self.secret_chibis = self._scan_chibis("chibis/secret")
        self.prize_chibis = self._scan_chibis("chibis/prize")
        
        self._init_db()
        self._init_admins()
        self._init_system()
        
        self.user_reqs = {}
        self.MAX_REQS_PER_MIN = BOT_SETTINGS['max_reqs_per_min']
        self.active_bets = {}

    def _init_system(self):
        if not self.system.find_one({"type": "used_ids"}):
            self.system.insert_one({
                "type": "used_ids",
                "ids": [],
                "created_at": datetime.now()
            })

    def _scan_chibis(self, folder):
        if not os.path.exists(folder):
            logger.error(f"Папка {folder} не найдена!")
            return []
        
        chibi_files = [f for f in os.listdir(folder) if f.lower().endswith('.png')]
        chibi_names = [os.path.splitext(f)[0].replace('_', ' ') for f in chibi_files]
        return sorted(chibi_names)

    def _init_admins(self):
        for username in self.test_users:
            admin = self.users.find_one({"username": username})
            if admin:
                all_chibis = self.common_chibis + self.secret_chibis + self.prize_chibis
                chibi_times = {chibi: datetime.now() for chibi in all_chibis}
                
                self.users.update_one(
                    {"username": username},
                    {"$set": {
                        "chibis": all_chibis,
                        "chibi_timestamps": chibi_times,
                        "coins": 999999,
                        "items": {"🧧 Чиби-пак": 99},
                        "infinite_chibis": True
                    }}
                )
                logger.info(f"Админ {username} инициализирован")

    def _init_db(self):
        self.users.create_index("telegram_id", unique=True)
        self.users.create_index("user_id", unique=True)
        self.users.create_index("last_active")

    def check_req_limit(self, user_id):
        now = time.time()
        user_id_str = str(user_id)
        
        if user_id_str not in self.user_reqs:
            self.user_reqs[user_id_str] = []
        
        self.user_reqs[user_id_str] = [
            t for t in self.user_reqs[user_id_str] if now - t < 60
        ]
        
        if len(self.user_reqs[user_id_str]) >= self.MAX_REQS_PER_MIN:
            return False
        
        self.user_reqs[user_id_str].append(now)
        return True

    def is_test(self, username):
        return username in self.test_users if username else False

    def is_banned(self, user_id):
        user = self.users.find_one({"telegram_id": str(user_id)})
        if user and user.get('banned_until'):
            if datetime.now() < user['banned_until']:
                return True
            else:
                self.users.update_one(
                    {"telegram_id": str(user_id)},
                    {"$unset": {"banned_until": ""}}
                )
        return False

    def get_ban_time(self, user_id):
        user = self.users.find_one({"telegram_id": str(user_id)})
        if user and user.get('banned_until'):
            time_left = user['banned_until'] - datetime.now()
            return max(1, time_left.days)
        return 0

    def format_time(self, seconds):
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}ч {minutes:02d}м"

    def check_chibi_cd(self, user_id):
        user = self.users.find_one({"telegram_id": str(user_id)})
        if not user:
            return None
            
        if self.is_test(user.get('username')):
            return None
            
        if user.get('last_chibi_time'):
            last = user['last_chibi_time']
            passed = (datetime.now() - last).total_seconds()
            if passed < 3 * 3600:
                return 3 * 3600 - passed
        return None

    def check_task_cd(self, user_id):
        user = self.users.find_one({"telegram_id": str(user_id)})
        if not user:
            return None
            
        if self.is_test(user.get('username')):
            return None
            
        if user.get('last_task_time'):
            last = user['last_task_time']
            task_type = user.get('last_task_type', 'completed')
            
            passed = (datetime.now() - last).total_seconds()
            cooldown = 4 * 3600 if task_type == 'completed' else 5.5 * 3600
                
            if passed < cooldown:
                return cooldown - passed
        return None

    def check_bonus_cd(self, user_id):
        user = self.users.find_one({"telegram_id": str(user_id)})
        if not user:
            return None
            
        if self.is_test(user.get('username')):
            return None
            
        if user.get('last_bonus_time'):
            now = datetime.now()
            last = user['last_bonus_time']
            
            moscow_now = now + timedelta(hours=3)
            moscow_last = last + timedelta(hours=3)
            
            if moscow_last.date() == moscow_now.date():
                next_midnight = datetime(moscow_now.year, moscow_now.month, moscow_now.day) + timedelta(days=1)
                left = next_midnight - moscow_now
                return left.total_seconds()
        return None

    def gen_user_id(self):
        attempts = 0
        while attempts < 100:
            letter = random.choice(string.ascii_uppercase)
            numbers = ''.join(random.choices(string.digits, k=4))
            pos = random.randint(0, 1)
            user_id = letter + numbers if pos == 0 else numbers + letter
            
            existing = self.users.find_one({"user_id": user_id})
            sys_data = self.system.find_one({"type": "used_ids"})
            used = sys_data.get("ids", []) if sys_data else []
            
            if not existing and user_id not in used:
                self.system.update_one(
                    {"type": "used_ids"},
                    {"$push": {"ids": user_id}},
                    upsert=True
                )
                return user_id
            attempts += 1
        return f"U{random.randint(10000, 99999)}"

    def get_temp(self, key, telegram_id=None):
        query = {"key": key}
        if telegram_id:
            query["telegram_id"] = str(telegram_id)
        
        data = self.temp.find_one(query)
        return data.get("value") if data else None

    def set_temp(self, key, value, telegram_id=None, ttl=3600):
        doc = {
            "key": key,
            "value": value,
            "created_at": datetime.now()
        }
        if telegram_id:
            doc["telegram_id"] = str(telegram_id)
        
        self.temp.update_one(
            {"key": key, "telegram_id": str(telegram_id) if telegram_id else None},
            {"$set": doc},
            upsert=True
        )

    def del_temp(self, key, telegram_id=None):
        query = {"key": key}
        if telegram_id:
            query["telegram_id"] = str(telegram_id)
        
        self.temp.delete_one(query)

    def get_or_create_user(self, telegram_id, first_name=None, username=None):
        telegram_id_str = str(telegram_id)
        
        if self.is_banned(telegram_id):
            return None, False
            
        user = self.users.find_one({"telegram_id": telegram_id_str})
        
        if user:
            self.users.update_one(
                {"telegram_id": telegram_id_str},
                {"$set": {"last_active": datetime.now()}}
            )
            return user, False
        else:
            user_id = self.gen_user_id()
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
                "chibi_timestamps": {},
                "last_chibi_time": None,
                "last_task_time": None,
                "last_task_type": None,
                "last_bonus_time": None,
                "current_task": None,
                "infinite_chibis": False
            }
            
            if self.is_test(username):
                user_data["coins"] = 1000
                user_data["items"]["🧧 Чиби-пак"] = 5
                user_data["infinite_chibis"] = True
            
            self.users.insert_one(user_data)
            logger.info(f"Новый пользователь: {user_id}")
            return user_data, True

    def user_started(self, user_id):
        return self.users.find_one({"telegram_id": str(user_id)}) is not None

    def send_start_sug(self, chat_id, message_id=None):
        text = BOT_TEXTS['start_suggest']
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

    def add_chibi(self, telegram_id, chibi_name, rarity="Common"):
        telegram_id_str = str(telegram_id)
        
        user = self.users.find_one({"telegram_id": telegram_id_str})
        if not user:
            return
            
        if user.get('infinite_chibis'):
            return
            
        current_chibis = user.get('chibis', [])
        current_timestamps = user.get('chibi_timestamps', {})
        
        current_chibis.append(chibi_name)
        current_timestamps[chibi_name] = datetime.now()
        
        self.users.update_one(
            {"telegram_id": telegram_id_str},
            {"$set": {
                "chibis": current_chibis,
                "chibi_timestamps": current_timestamps
            }}
        )

    def get_random_chibi(self, from_pack=False):
        if from_pack and random.random() <= BOT_SETTINGS['pack_secret_chance']:
            folder = "chibis/secret"
            all_chibis = self.secret_chibis
        else:
            folder = "chibis/common"
            all_chibis = self.common_chibis
        
        if not os.path.exists(folder) or not all_chibis:
            logger.error(f"Папка {folder} не найдена или пуста!")
            return None, None, "Common"
        
        chibi_name = random.choice(all_chibis)
        file_path = os.path.join(folder, f"{chibi_name.replace(' ', '_')}.png")
        
        if not os.path.exists(file_path):
            logger.error(f"Файл чибика не найден: {file_path}")
            chibi_files = [f for f in os.listdir(folder) if f.lower().endswith('.png')]
            if not chibi_files:
                return None, None, "Common"
            random_file = random.choice(chibi_files)
            file_path = os.path.join(folder, random_file)
            chibi_name = os.path.splitext(random_file)[0].replace('_', ' ')
        
        rarity = "Secret" if from_pack and folder == "chibis/secret" else "Common"
        return file_path, chibi_name, rarity

    def get_prize_chibi(self, chibi_name):
        folder = "chibis/prize"
        
        if not os.path.exists(folder):
            logger.error(f"Папка {folder} не найдена!")
            return None, None, "Prize"
        
        file_path = os.path.join(folder, f"{chibi_name.replace(' ', '_')}.png")
        if not os.path.exists(file_path):
            logger.error(f"Призовой чибик {chibi_name} не найден!")
            return None, None, "Prize"
        
        return file_path, chibi_name, "Prize"

    def chibi_count(self, telegram_id, chibi_name):
        telegram_id_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": telegram_id_str})
        if not user:
            return 0
            
        if user.get('infinite_chibis'):
            return 1
            
        chibis = user.get('chibis', [])
        return chibis.count(chibi_name)

    def gen_task(self, telegram_id):
        telegram_id_str = str(telegram_id)
        
        user = self.users.find_one({"telegram_id": telegram_id_str})
        if not user:
            return None
            
        if user.get('current_task') is not None:
            return user['current_task']
        
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
        
        reward = random.randint(BOT_SETTINGS['task_min_reward'], BOT_SETTINGS['task_max_reward'])
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
        
        self.users.update_one(
            {"telegram_id": telegram_id_str},
            {"$set": {"current_task": task_data}}
        )
        
        return task_data

    def task_text(self, task_data, telegram_id):
        telegram_id_str = str(telegram_id)
        has_chibi = self.chibi_count(telegram_id, task_data["chibi"]) > 0
        btn_text = "Сдать задание (1/1)" if has_chibi else "Сдать задание (0/1)"
        
        text = f"""*{task_data['emoji']} {task_data['name']}*
{task_data['phrase']}
•••••••••••••••••••
Дам *💰 {task_data['reward']}* за {task_data['chibi']}"""
        
        return text, btn_text, has_chibi

    def get_page(self, items_list, page=1, per_page=8):
        total = max(1, (len(items_list) + per_page - 1) // per_page)
        page = max(1, min(page, total))
        
        start = (page - 1) * per_page
        end = start + per_page
        page_items = items_list[start:end]
        
        return page_items, page, total

    def user_chibis_page(self, telegram_id, page=1, per_page=8):
        telegram_id_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": telegram_id_str})
        if not user:
            return [], 1, 1
        
        chibis = user.get('chibis', [])
        counts = {}
        for chibi in chibis:
            counts[chibi] = counts.get(chibi, 0) + 1
        
        sorted_chibis = sorted(
            [(name, count) for name, count in counts.items()],
            key=lambda x: (-x[1], x[0])
        )
        
        return self.get_page(sorted_chibis, page, per_page)

    def user_items_page(self, telegram_id, page=1, per_page=8):
        telegram_id_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": telegram_id_str})
        if not user:
            return [], 1, 1
        
        items = user.get('items', {})
        active = {name: count for name, count in items.items() if count > 0}
        
        sorted_items = sorted(
            [(name, count) for name, count in active.items()],
            key=lambda x: (-x[1], x[0])
        )
        
        return self.get_page(sorted_items, page, per_page)

    def chibis_for_gift(self, telegram_id, page=1, per_page=6):
        return self.user_chibis_page(telegram_id, page, per_page)

    def check_msg_owner(self, call):
        if call.message.chat.type == 'private':
            return True
            
        telegram_id_str = str(call.from_user.id)
        msg_key = f"{call.message.chat.id}_{call.message.message_id}"
        
        owner = self.get_temp(f"msg_owner_{msg_key}")
        if owner and owner != telegram_id_str:
            self.bot.answer_callback_query(call.id, BOT_TEXTS['not_yours'], parse_mode='Markdown')
            return False
        return True

    def get_user_collection(self, telegram_id):
        telegram_id_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": telegram_id_str})
        
        if not user:
            return {"common": [], "secret": [], "prize": []}
        
        user_chibis = user.get('chibis', [])
        
        common = []
        secret = []
        prize = []
        
        for chibi in set(user_chibis):
            if chibi in self.common_chibis:
                common.append(chibi)
            elif chibi in self.secret_chibis:
                secret.append(chibi)
            elif chibi in self.prize_chibis:
                prize.append(chibi)
        
        return {
            "common": common,
            "secret": secret,
            "prize": prize,
            "all_common": self.common_chibis,
            "all_secret": self.secret_chibis,
            "all_prize": self.prize_chibis
        }

    def send_chibi_photo(self, chat_id, file_path, caption, telegram_id_str):
        try:
            if not os.path.exists(file_path):
                logger.error(f"Файл не найден: {file_path}")
                sent = self.bot.send_message(
                    chat_id,
                    BOT_TEXTS['chibi_photo_unavailable'].format(caption=caption),
                    parse_mode='Markdown'
                )
                self.set_temp(f"msg_owner_{chat_id}_{sent.message_id}", telegram_id_str)
                return sent
            
            with open(file_path, 'rb') as photo:
                sent = self.bot.send_photo(
                    chat_id,
                    photo,
                    caption=caption,
                    parse_mode='Markdown'
                )
                self.set_temp(f"msg_owner_{chat_id}_{sent.message_id}", telegram_id_str)
                return sent
                
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")
            sent = self.bot.send_message(
                chat_id,
                BOT_TEXTS['chibi_photo_error'].format(caption=caption),
                parse_mode='Markdown'
            )
            self.set_temp(f"msg_owner_{chat_id}_{sent.message_id}", telegram_id_str)
            return sent

    def get_market_lots(self, page=1, per_page=8):
        total = self.market.count_documents({"status": "active"})
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        skip = (page - 1) * per_page
        lots = list(self.market.find({"status": "active"}).sort("created_at", -1).skip(skip).limit(per_page))
        
        return lots, page, total_pages, total

    def get_user_market_chibis(self, telegram_id, page=1, per_page=6):
        telegram_id_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": telegram_id_str})
        if not user:
            return [], 1, 1
        
        chibis = user.get('chibis', [])
        counts = {}
        for chibi in chibis:
            counts[chibi] = counts.get(chibi, 0) + 1
        
        sorted_chibis = sorted(
            [(name, count) for name, count in counts.items()],
            key=lambda x: (-x[1], x[0])
        )
        
        return self.get_page(sorted_chibis, page, per_page)

    def setup_flask_routes(self):
        @self.app.route('/')
        def home():
            return "Датабейз здесь"
        
        @self.app.route('/health')
        def health():
            try:
                self.client.admin.command('ping')
                return jsonify({"status": "healthy", "database": "connected"})
            except Exception as e:
                return jsonify({"status": "unhealthy", "error": str(e)}), 500
        
        @self.app.route('/get_user_collection', methods=['POST'])
        def get_collection():
            try:
                data = request.get_json()
                telegram_id = data.get('telegram_id')
                
                if not telegram_id:
                    return jsonify({"error": "Telegram ID required"}), 400
                
                collection = self.get_user_collection(telegram_id)
                return jsonify(collection)
                
            except Exception as e:
                logger.error(f"Ошибка получения коллекции: {e}")
                return jsonify({"error": "Internal server error"}), 500
        
        @self.app.route('/get_all_chibis', methods=['GET'])
        def all_chibis():
            try:
                return jsonify({
                    "common": self.common_chibis,
                    "secret": self.secret_chibis,
                    "prize": self.prize_chibis
                })
            except Exception as e:
                logger.error(f"Ошибка получения списка чибиков: {e}")
                return jsonify({"error": "Internal server error"}), 500

        @self.app.route('/stats', methods=['GET'])
        def stats():
            try:
                total = self.users.count_documents({})
                active = self.users.count_documents({
                    "last_active": {"$gte": datetime.now() - timedelta(days=1)}
                })
                
                return jsonify({
                    "total_users": total,
                    "active_users": active,
                    "common_chibis": len(self.common_chibis),
                    "secret_chibis": len(self.secret_chibis),
                    "prize_chibis": len(self.prize_chibis)
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    def setup_handlers(self):
        @self.bot.message_handler(commands=['start'])
        def start_msg(message):
            if message.chat.type != 'private':
                return
                
            try:
                if not self.check_req_limit(message.from_user.id):
                    self.bot.reply_to(message, BOT_TEXTS['rate_limit'], parse_mode='Markdown')
                    return
                    
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['ban_message'].format(days_left=days_left),
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return
                    
                user, is_new = self.get_or_create_user(
                    message.from_user.id,
                    message.from_user.first_name,
                    message.from_user.username
                )
                
                if user is None:
                    return
                    
                name = message.from_user.first_name or "путешественник"
                
                if is_new:
                    sticker = STICKERS['welcome']
                else:
                    sticker = STICKERS['already_started']
                
                self.bot.send_sticker(message.chat.id, sticker)
                
                if is_new:
                    welcome = BOT_TEXTS['welcome'].format(name=name)
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton('Наш тгк', url=BOT_CONFIG['telegram_channel'])
                    markup.add(btn)
                    sent = self.bot.send_message(message.chat.id, welcome, reply_markup=markup, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    sent = self.bot.send_message(message.chat.id, BOT_TEXTS['already_started'], parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    
            except Exception as e:
                logger.error(f"Ошибка в start: {e}")
                sent = self.bot.send_message(
                    message.chat.id,
                    BOT_TEXTS['connection_lost'],
                    parse_mode='Markdown'
                )
                self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))

        @self.bot.message_handler(commands=['dice'])
        def dice_msg(message):
            if message.chat.type != 'private':
                self.bot.reply_to(message, BOT_TEXTS['gift_not_private'], parse_mode='Markdown')
                return
                
            try:
                if not self.check_req_limit(message.from_user.id):
                    self.bot.reply_to(message, BOT_TEXTS['rate_limit'], parse_mode='Markdown')
                    return
                    
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['ban_message'].format(days_left=days_left),
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return
                    
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return

                parts = message.text.split()
                if len(parts) < 2:
                    sent = self.bot.send_message(message.chat.id, BOT_TEXTS['dice_format_error'], parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return

                try:
                    bet = int(parts[1])
                except ValueError:
                    sent = self.bot.send_message(message.chat.id, BOT_TEXTS['dice_format_error'], parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return

                if bet < BOT_SETTINGS['min_dice_bet']:
                    self.bot.reply_to(message, BOT_TEXTS['dice_bet_too_low'], parse_mode='Markdown')
                    return

                if bet > BOT_SETTINGS['max_bet']:
                    self.bot.reply_to(message, BOT_TEXTS['dice_bet_too_high'], parse_mode='Markdown')
                    return

                telegram_id_str = str(message.from_user.id)
                user = self.users.find_one({"telegram_id": telegram_id_str})
                if not user:
                    self.send_start_sug(message.chat.id)
                    return

                coins = user.get('coins', 0)
                if coins < bet:
                    self.bot.reply_to(message, BOT_TEXTS['dice_insufficient_coins'].format(coins=coins), parse_mode='Markdown')
                    return

                self.active_bets[telegram_id_str] = bet
                
                dice = self.bot.send_dice(message.chat.id, emoji='🎲')
                value = dice.dice.value

                time.sleep(2)

                if value in [2, 4, 6]:
                    win = math.ceil(bet * 1.7)
                    total = coins + win
                    
                    self.users.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"coins": total}}
                    )

                    win_text = BOT_TEXTS['dice_win'].format(
                        username=message.from_user.first_name,
                        win=win,
                        total=total
                    )

                    self.bot.send_message(message.chat.id, win_text, parse_mode='Markdown')
                else:
                    lose_text = BOT_TEXTS['dice_lose'].format(
                        username=message.from_user.first_name,
                        bet=bet,
                        remaining=coins - bet
                    )

                    new_coins = coins - bet
                    self.users.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"coins": new_coins}}
                    )
                    
                    self.bot.send_message(message.chat.id, lose_text, parse_mode='Markdown')
                
                del self.active_bets[telegram_id_str]

            except Exception as e:
                logger.error(f"Ошибка в dice: {e}")
                telegram_id_str = str(message.from_user.id)
                if telegram_id_str in self.active_bets:
                    bet = self.active_bets[telegram_id_str]
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if user:
                        new_coins = user.get('coins', 0) + bet
                        self.users.update_one(
                            {"telegram_id": telegram_id_str},
                            {"$set": {"coins": new_coins}}
                        )
                    del self.active_bets[telegram_id_str]
                
                sent = self.bot.send_message(
                    message.chat.id,
                    BOT_TEXTS['connection_lost'],
                    parse_mode='Markdown'
                )
                self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))

        @self.bot.message_handler(commands=['ban'])
        def ban_msg(message):
            try:
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                telegram_id_str = str(message.from_user.id)
                user = self.users.find_one({"telegram_id": telegram_id_str})
                
                if not self.is_test(user.get('username')):
                    self.bot.reply_to(message, BOT_TEXTS['admin_no_permission'], parse_mode='Markdown')
                    return
                    
                if len(message.text.split()) < 2:
                    self.bot.reply_to(message, BOT_TEXTS['ban_usage'], parse_mode='Markdown')
                    return
                    
                target = message.text.split()[1].strip()
                
                target_user = self.users.find_one({
                    "$or": [
                        {"username": target.replace('@', '')},
                        {"user_id": target}
                    ]
                })
                
                if not target_user:
                    self.bot.reply_to(message, BOT_TEXTS['user_not_found'], parse_mode='Markdown')
                    return
                    
                ban_until = datetime.now() + timedelta(days=7)
                self.users.update_one(
                    {"telegram_id": target_user['telegram_id']},
                    {"$set": {"banned_until": ban_until}}
                )
                self.bot.reply_to(message, BOT_TEXTS['ban_success'], parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка бана: {e}")
                self.bot.reply_to(message, BOT_TEXTS['connection_lost'], parse_mode='Markdown')

        @self.bot.message_handler(commands=['unban'])
        def unban_msg(message):
            try:
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                telegram_id_str = str(message.from_user.id)
                user = self.users.find_one({"telegram_id": telegram_id_str})
                
                if not self.is_test(user.get('username')):
                    self.bot.reply_to(message, BOT_TEXTS['admin_no_permission'], parse_mode='Markdown')
                    return
                    
                if len(message.text.split()) < 2:
                    self.bot.reply_to(message, BOT_TEXTS['unban_usage'], parse_mode='Markdown')
                    return
                    
                target = message.text.split()[1].strip()
                
                target_user = self.users.find_one({
                    "$or": [
                        {"username": target.replace('@', '')},
                        {"user_id": target}
                    ]
                })
                        
                if not target_user:
                    self.bot.reply_to(message, BOT_TEXTS['user_not_found'], parse_mode='Markdown')
                    return
                    
                self.users.update_one(
                    {"telegram_id": target_user['telegram_id']},
                    {"$unset": {"banned_until": ""}}
                )
                self.bot.reply_to(message, BOT_TEXTS['unban_success'], parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка разбана: {e}")
                self.bot.reply_to(message, BOT_TEXTS['connection_lost'], parse_mode='Markdown')

        @self.bot.message_handler(commands=['myid'])
        def myid_msg(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(
                            message.chat.id,
                            BOT_TEXTS['ban_message'].format(days_left=days_left),
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, BOT_TEXTS['ban_message'].format(days_left=days_left), parse_mode='Markdown')
                    return
                    
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                user, _ = self.get_or_create_user(message.from_user.id)
                user_id = user['user_id']
                
                response = BOT_TEXTS['myid_response'].format(user_id=user_id)
                if message.chat.type == 'private':
                    sent = self.bot.send_message(message.chat.id, response, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    self.bot.reply_to(message, response, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['connection_lost'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    self.bot.reply_to(message, BOT_TEXTS['connection_lost'], parse_mode='Markdown')

        @self.bot.message_handler(commands=['balance'])
        def balance_msg(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(
                            message.chat.id,
                            BOT_TEXTS['ban_message'].format(days_left=days_left),
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, BOT_TEXTS['ban_message'].format(days_left=days_left), parse_mode='Markdown')
                    return
                    
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                telegram_id_str = str(message.from_user.id)
                user = self.users.find_one({"telegram_id": telegram_id_str})
                coins = user.get('coins', 0) if user else 0
                
                text = BOT_TEXTS['balance_response'].format(coins=coins)
                if message.chat.type == 'private':
                    sent = self.bot.send_message(message.chat.id, text, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    self.bot.reply_to(message, text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ошибка: {e}")
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['connection_lost'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    self.bot.reply_to(message, BOT_TEXTS['connection_lost'], parse_mode='Markdown')

        @self.bot.message_handler(commands=['mart'])
        def mart_msg(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(
                            message.chat.id,
                            BOT_TEXTS['ban_message'].format(days_left=days_left),
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, BOT_TEXTS['ban_message'].format(days_left=days_left), parse_mode='Markdown')
                    return
                    
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                text = BOT_TEXTS['mart_text']
                
                markup = types.InlineKeyboardMarkup()
                btn = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_chibi_pack")
                markup.add(btn)
                
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    reply = self.bot.reply_to(message, text, reply_markup=markup, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{reply.message_id}", str(message.from_user.id))
                
            except Exception as e:
                logger.error(f"Ошибка при открытии лавки: {e}")
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['connection_lost'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    self.bot.reply_to(message, BOT_TEXTS['connection_lost'], parse_mode='Markdown')

        @self.bot.message_handler(commands=['hub'])
        def hub_msg(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(
                            message.chat.id,
                            BOT_TEXTS['ban_message'].format(days_left=days_left),
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, BOT_TEXTS['ban_message'].format(days_left=days_left), parse_mode='Markdown')
                    return
                    
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                telegram_id_str = str(message.from_user.id)
                self.show_hub_page(message.chat.id, telegram_id_str, 1)
                
            except Exception as e:
                logger.error(f"Ошибка при открытии рынка: {e}")
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['connection_lost'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    self.bot.reply_to(message, BOT_TEXTS['connection_lost'], parse_mode='Markdown')

        @self.bot.message_handler(commands=['chibi'])
        def chibi_msg(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(
                            message.chat.id,
                            BOT_TEXTS['ban_message'].format(days_left=days_left),
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, BOT_TEXTS['ban_message'].format(days_left=days_left), parse_mode='Markdown')
                    return
                    
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                cd = self.check_chibi_cd(message.from_user.id)
                if cd:
                    time_left = self.format_time(int(cd))
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(
                            message.chat.id,
                            BOT_TEXTS['chibi_cooldown'].format(time_left=time_left),
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, BOT_TEXTS['chibi_cooldown'].format(time_left=time_left), parse_mode='Markdown')
                    return
                    
                telegram_id_str = str(message.from_user.id)
                file_path, chibi_name, rarity = self.get_random_chibi(from_pack=False)
                
                if file_path is None:
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(message.chat.id, BOT_TEXTS['chibi_unavailable'], parse_mode='Markdown')
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, BOT_TEXTS['chibi_unavailable'], parse_mode='Markdown')
                    return
                
                self.add_chibi(message.from_user.id, chibi_name)
                count = self.chibi_count(message.from_user.id, chibi_name)
                
                self.users.update_one(
                    {"telegram_id": telegram_id_str},
                    {"$set": {"last_chibi_time": datetime.now()}}
                )
                
                emoji = RARITY_EMOJIS.get(rarity, '🔷')
                
                text = BOT_TEXTS['chibi_caption'].format(
                    chibi_name=chibi_name,
                    emoji=emoji,
                    rarity=rarity,
                    count=count
                )
                
                self.send_chibi_photo(message.chat.id, file_path, text, telegram_id_str)
                    
                logger.info(f"Отправлен чиби: {chibi_name} (Редкость: {rarity})")
                    
            except Exception as e:
                logger.error(f"Ошибка при отправке чиби: {e}")
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['connection_lost'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    self.bot.reply_to(message, BOT_TEXTS['connection_lost'], parse_mode='Markdown')

        @self.bot.message_handler(commands=['task'])
        def task_msg(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(
                            message.chat.id,
                            BOT_TEXTS['ban_message'].format(days_left=days_left),
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, BOT_TEXTS['ban_message'].format(days_left=days_left), parse_mode='Markdown')
                    return
                    
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                cd = self.check_task_cd(message.from_user.id)
                if cd:
                    time_left = self.format_time(int(cd))
                    user = self.users.find_one({"telegram_id": str(message.from_user.id)})
                    task_type = user.get('last_task_type', 'completed') if user else 'completed'
                    
                    if task_type == 'completed':
                        text = BOT_TEXTS['task_cooldown_completed'].format(time_left=time_left)
                    else:
                        text = BOT_TEXTS['task_cooldown_skipped'].format(time_left=time_left)
                    
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(message.chat.id, text, parse_mode='Markdown')
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, text, parse_mode='Markdown')
                    return
                    
                task = self.gen_task(message.from_user.id)
                task_text, btn_text, has_chibi = self.task_text(task, message.from_user.id)
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn1 = types.InlineKeyboardButton(
                    btn_text, 
                    callback_data="task_complete" if has_chibi else "task_cannot_complete"
                )
                btn2 = types.InlineKeyboardButton(
                    "Пропустить", 
                    callback_data="task_skip_confirm"
                )
                markup.add(btn1, btn2)
                
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        task_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    reply = self.bot.reply_to(message, task_text, reply_markup=markup, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{reply.message_id}", str(message.from_user.id))
                
            except Exception as e:
                logger.error(f"Ошибка при генерации задания: {e}")
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['connection_lost'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    self.bot.reply_to(message, BOT_TEXTS['connection_lost'], parse_mode='Markdown')

        @self.bot.message_handler(commands=['menu'])
        def menu_msg(message):
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    if message.chat.type == 'private':
                        sent = self.bot.send_message(
                            message.chat.id,
                            BOT_TEXTS['ban_message'].format(days_left=days_left),
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    else:
                        self.bot.reply_to(message, BOT_TEXTS['ban_message'].format(days_left=days_left), parse_mode='Markdown')
                    return
                    
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                text = BOT_TEXTS['menu_text']
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn1 = types.InlineKeyboardButton("Склад", callback_data="menu_warehouse")
                btn2 = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
                
                cd = self.check_bonus_cd(message.from_user.id)
                user = self.users.find_one({"telegram_id": str(message.from_user.id)})
                if cd and not self.is_test(user.get('username') if user else None):
                    time_left = self.format_time(int(cd))
                    btn3 = types.InlineKeyboardButton(f"Приходи через {time_left}", callback_data="bonus_cooldown")
                else:
                    btn3 = types.InlineKeyboardButton("Ежедневный бонус", callback_data="menu_bonus")
                
                markup.add(btn1, btn2)
                markup.add(btn3)
                
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    reply = self.bot.reply_to(message, text, reply_markup=markup, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{reply.message_id}", str(message.from_user.id))
                
            except Exception as e:
                logger.error(f"Ошибка при открытии меню: {e}")
                if message.chat.type == 'private':
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['connection_lost'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                else:
                    self.bot.reply_to(message, BOT_TEXTS['connection_lost'], parse_mode='Markdown')

        @self.bot.message_handler(commands=['gift'])
        def gift_msg(message):
            if message.chat.type != 'private':
                self.bot.reply_to(message, BOT_TEXTS['gift_not_private'], parse_mode='Markdown')
                return
                
            try:
                if self.is_banned(message.from_user.id):
                    days_left = self.get_ban_time(message.from_user.id)
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['ban_message'].format(days_left=days_left),
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return
                    
                if not self.user_started(message.from_user.id):
                    self.send_start_sug(message.chat.id)
                    return
                    
                if len(message.text.split()) < 2:
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['gift_usage'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return
                
                target_id = message.text.split()[1].strip()
                
                target = self.users.find_one({"user_id": target_id})
                
                if not target:
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['user_not_found'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return
                
                if str(message.from_user.id) in self.users.find_one({"user_id": target_id}).get('telegram_id', ''):
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['gift_self'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return
                
                telegram_id_str = str(message.from_user.id)
                self.set_temp("gift_data", {
                    "target_id": target_id,
                    "target_tg": target.get('telegram_id'),
                    "target_name": target.get('first_name', 'пользователь'),
                    "is_admin": self.is_test(message.from_user.username)
                }, telegram_id_str)
                
                chibis, page, total = self.chibis_for_gift(message.from_user.id, 1)
                
                if not chibis:
                    sent = self.bot.send_message(
                        message.chat.id,
                        BOT_TEXTS['gift_no_chibis'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return
                
                text = BOT_TEXTS['gift_select']
                
                markup = types.InlineKeyboardMarkup()
                
                for name, count in chibis:
                    markup.add(types.InlineKeyboardButton(name, callback_data=f"gift_select_{name}"))
                
                markup.add(types.InlineKeyboardButton("Подарить коины", callback_data="gift_coins"))
                
                nav = []
                if total > 1:
                    nav.append(types.InlineKeyboardButton("◀️", callback_data=f"gift_page_{((page-2) % total) + 1}"))
                
                nav.append(types.InlineKeyboardButton("Отменить", callback_data="gift_cancel"))
                
                if total > 1:
                    nav.append(types.InlineKeyboardButton("▶️", callback_data=f"gift_page_{(page % total) + 1}"))
                
                markup.row(*nav)
                
                sent = self.bot.send_message(
                    message.chat.id,
                    text,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                
            except Exception as e:
                logger.error(f"Ошибка при отправке подарка: {e}")
                sent = self.bot.send_message(
                    message.chat.id,
                    BOT_TEXTS['connection_lost'],
                    parse_mode='Markdown'
                )
                self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))

        @self.bot.message_handler(func=lambda message: True, content_types=['text'])
        def text_msg(message):
            telegram_id_str = str(message.from_user.id)
            
            waiting_coins = self.get_temp("waiting_coins", telegram_id_str)
            waiting_lot_price = self.get_temp("waiting_lot_price", telegram_id_str)
            
            if waiting_coins:
                if not message.reply_to_message:
                    return
                    
                try:
                    amount = int(message.text)
                    
                    if amount < 1:
                        self.bot.reply_to(message, BOT_TEXTS['text_positive_error'], parse_mode='Markdown')
                        return
                        
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user:
                        return
                        
                    if not self.is_test(user.get('username')):
                        if user.get('coins', 0) < amount:
                            self.bot.reply_to(message, BOT_TEXTS['dice_insufficient_coins'].format(coins=user.get('coins', 0)), parse_mode='Markdown')
                            return
                    
                    gift_data = self.get_temp("gift_data", telegram_id_str)
                    target_name = gift_data.get("target_name", "пользователь")
                    
                    text = BOT_TEXTS['gift_coins_confirm'].format(
                        amount=amount,
                        target_name=target_name
                    )

                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("Подтвердить", callback_data=f"gift_confirm_coins_{amount}")
                    btn2 = types.InlineKeyboardButton("Отмена", callback_data="gift_cancel")
                    markup.add(btn1)
                    markup.add(btn2)
                    
                    try:
                        self.bot.delete_message(message.chat.id, message.message_id)
                    except:
                        pass
                    
                    self.bot.send_message(
                        message.chat.id,
                        text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.del_temp("waiting_coins", telegram_id_str)
                    
                except ValueError:
                    self.bot.reply_to(message, BOT_TEXTS['text_input_error'], parse_mode='Markdown')
            
            elif waiting_lot_price:
                if not message.reply_to_message:
                    return
                    
                try:
                    price = int(message.text)
                    
                    if price < BOT_SETTINGS['min_lot_price']:
                        self.bot.reply_to(message, BOT_TEXTS['create_lot_price_too_low'], parse_mode='Markdown')
                        return
                        
                    if price > BOT_SETTINGS['max_lot_price']:
                        self.bot.reply_to(message, BOT_TEXTS['create_lot_price_too_high'], parse_mode='Markdown')
                        return
                    
                    lot_data = self.get_temp("creating_lot", telegram_id_str)
                    if not lot_data:
                        return
                    
                    message_id = lot_data.get("message_id")
                    if not message_id:
                        return
                    
                    lot_data["price"] = price
                    self.set_temp("creating_lot", lot_data, telegram_id_str)
                    
                    try:
                        self.bot.delete_message(message.chat.id, message.message_id)
                    except:
                        pass
                    
                    text = BOT_TEXTS['create_lot_confirm'].format(
                        chibi_name=lot_data["chibi_name"],
                        price=price
                    )
                    
                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("Выставить", callback_data="create_lot_confirm")
                    btn2 = types.InlineKeyboardButton("Отмена", callback_data="create_lot_cancel")
                    markup.add(btn1)
                    markup.add(btn2)
                    
                    self.bot.edit_message_text(
                        text,
                        message.chat.id,
                        message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                    self.del_temp("waiting_lot_price", telegram_id_str)
                    
                except ValueError:
                    self.bot.reply_to(message, BOT_TEXTS['text_input_error'], parse_mode='Markdown')

        @self.bot.callback_query_handler(func=lambda call: True)
        def callback(call):
            try:
                if not self.check_msg_owner(call):
                    return

                if call.data == "task_complete":
                    telegram_id_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user or not user.get('current_task'):
                        self.bot.answer_callback_query(call.id, BOT_TEXTS['task_already_done'])
                        return
                    
                    task = user['current_task']
                    
                    if task["chibi"] in user.get('chibis', []) or user.get('infinite_chibis'):
                        if not user.get('infinite_chibis'):
                            new_chibis = user.get('chibis', []).copy()
                            if task["chibi"] in new_chibis:
                                new_chibis.remove(task["chibi"])
                            self.users.update_one(
                                {"telegram_id": telegram_id_str},
                                {"$set": {"chibis": new_chibis}}
                            )
                    else:
                        self.bot.answer_callback_query(call.id, BOT_TEXTS['task_cannot_complete'])
                        return
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sticker = STICKERS['task_complete']
                    self.bot.send_sticker(call.message.chat.id, sticker)
                    
                    reward = task["reward"]
                    new_coins = user.get('coins', 0) + reward
                    self.users.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {
                            "coins": new_coins,
                            "current_task": None,
                            "last_task_time": datetime.now(),
                            "last_task_type": 'completed'
                        }}
                    )
                    
                    name = call.from_user.first_name or "путешественник"
                    text = BOT_TEXTS['task_complete_success'].format(username=name, reward=reward)
                    
                    sent = self.bot.send_message(
                        call.message.chat.id,
                        text,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                    
                elif call.data == "task_cannot_complete":
                    self.bot.answer_callback_query(call.id, BOT_TEXTS['task_cannot_complete'])
                    
                elif call.data == "task_skip":
                    telegram_id_str = str(call.from_user.id)
                    self.users.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {
                            "current_task": None,
                            "last_task_time": datetime.now(),
                            "last_task_type": 'skipped'
                        }}
                    )
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    text = BOT_TEXTS['task_skip_done']
                    
                    sent = self.bot.send_message(
                        call.message.chat.id,
                        text,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                    
                elif call.data == "task_skip_confirm":
                    telegram_id_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user or not user.get('current_task'):
                        self.bot.answer_callback_query(call.id, "Нет активного задания!")
                        return
                    
                    task = user['current_task']
                    
                    text = BOT_TEXTS['task_skip_confirm'].format(emoji=task['emoji'])
                    
                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("Пропустить", callback_data="task_skip")
                    btn2 = types.InlineKeyboardButton("Назад", callback_data="task_back")
                    markup.add(btn1, btn2)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "task_back":
                    telegram_id_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user or not user.get('current_task'):
                        self.bot.answer_callback_query(call.id, "Нет активного задания!")
                        return
                    
                    task = user['current_task']
                    text, btn_text, has_chibi = self.task_text(task, call.from_user.id)
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn1 = types.InlineKeyboardButton(
                        btn_text, 
                        callback_data="task_complete" if has_chibi else "task_cannot_complete"
                    )
                    btn2 = types.InlineKeyboardButton(
                        "Пропустить", 
                        callback_data="task_skip_confirm"
                    )
                    markup.add(btn1, btn2)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "menu_warehouse":
                    text = """*Перепутье*
Выбери, на какой раздел склада хочешь глянуть"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn1 = types.InlineKeyboardButton("Чибики", callback_data="warehouse_chibis_1")
                    btn2 = types.InlineKeyboardButton("Предметы", callback_data="warehouse_items_1")
                    btn3 = types.InlineKeyboardButton("Назад", callback_data="menu_back")
                    
                    markup.add(btn1, btn2)
                    markup.add(btn3)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("warehouse_chibis_"):
                    page = int(call.data.split("_")[2])
                    chibis, cur_page, total = self.user_chibis_page(call.from_user.id, page)
                    
                    text = BOT_TEXTS['warehouse_chibis_text'].format(page=cur_page, total=total)
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if chibis:
                        for name, count in chibis:
                            if count > 1:
                                btn_text = f"{name} ({count})"
                            else:
                                btn_text = name
                            markup.add(types.InlineKeyboardButton(btn_text, callback_data="chibi_click"))
                    else:
                        markup.add(types.InlineKeyboardButton("Пусто", callback_data="empty"))
                    
                    nav = []
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"warehouse_chibis_{((cur_page-2) % total) + 1}"))
                    
                    nav.append(types.InlineKeyboardButton("Назад", callback_data="menu_warehouse"))
                    
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"warehouse_chibis_{(cur_page % total) + 1}"))
                    
                    markup.row(*nav)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("warehouse_items_"):
                    page = int(call.data.split("_")[2])
                    items, cur_page, total = self.user_items_page(call.from_user.id, page)
                    
                    text = BOT_TEXTS['warehouse_items_text'].format(page=cur_page, total=total)
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if items:
                        for name, count in items:
                            if count > 1:
                                btn_text = f"{name} ({count})"
                            else:
                                btn_text = name
                            if name == "🧧 Чиби-пак":
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="open_chibi_pack"))
                            else:
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="item_click"))
                    else:
                        markup.add(types.InlineKeyboardButton("Пусто", callback_data="empty"))
                    
                    nav = []
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"warehouse_items_{((cur_page-2) % total) + 1}"))
                    
                    nav.append(types.InlineKeyboardButton("Назад", callback_data="menu_warehouse"))
                    
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"warehouse_items_{(cur_page % total) + 1}"))
                    
                    markup.row(*nav)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "open_chibi_pack":
                    telegram_id_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user:
                        return
                        
                    count = user.get('items', {}).get("🧧 Чиби-пак", 0)
                    
                    text = BOT_TEXTS['open_pack_confirm']
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    
                    if count == 1:
                        btn1 = types.InlineKeyboardButton("Открыть х1", callback_data="open_pack_1")
                        markup.add(btn1)
                    else:
                        btn1 = types.InlineKeyboardButton("Открыть х1", callback_data="open_pack_1")
                        btn2 = types.InlineKeyboardButton(f"Открыть х{count}", callback_data=f"open_pack_{count}")
                        markup.add(btn1, btn2)
                    
                    btn3 = types.InlineKeyboardButton("Назад", callback_data="warehouse_items_1")
                    markup.add(btn3)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("open_pack_"):
                    count = int(call.data.split("_")[2])
                    telegram_id_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user:
                        return
                    
                    current = user.get('items', {}).get("🧧 Чиби-пак", 0)
                    if current < count:
                        self.bot.answer_callback_query(call.id, "Недостаточно Чиби-паков!")
                        return
                    
                    new = current - count
                    self.users.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"items.🧧 Чиби-пак": new}}
                    )
                    
                    for i in range(count):
                        file_path, chibi_name, rarity = self.get_random_chibi(from_pack=True)
                        
                        if file_path is not None:
                            self.add_chibi(call.from_user.id, chibi_name)
                            chibi_count = self.chibi_count(call.from_user.id, chibi_name)
                            
                            emoji = RARITY_EMOJIS.get(rarity, '🔷')
                            
                            text = BOT_TEXTS['chibi_caption'].format(
                                chibi_name=chibi_name,
                                emoji=emoji,
                                rarity=rarity,
                                count=chibi_count
                            )
                            
                            self.send_chibi_photo(
                                call.message.chat.id,
                                file_path,
                                text,
                                telegram_id_str
                            )
                    
                    self.bot.answer_callback_query(call.id, f"Открыто {count} Чиби-пак(ов)!")
                    
                    items, cur_page, total = self.user_items_page(call.from_user.id, 1)
                    
                    text = BOT_TEXTS['warehouse_items_text'].format(page=cur_page, total=total)
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if items:
                        for name, count in items:
                            if count > 1:
                                btn_text = f"{name} ({count})"
                            else:
                                btn_text = name
                            if name == "🧧 Чиби-пак":
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="open_chibi_pack"))
                            else:
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="item_click"))
                    else:
                        markup.add(types.InlineKeyboardButton("Пусто", callback_data="empty"))
                    
                    nav = []
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"warehouse_items_{((cur_page-2) % total) + 1}"))
                    
                    nav.append(types.InlineKeyboardButton("Назад", callback_data="menu_warehouse"))
                    
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"warehouse_items_{(cur_page % total) + 1}"))
                    
                    markup.row(*nav)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "mart_chibi_pack":
                    text = BOT_TEXTS['buy_pack_confirm']
                    
                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("Купить (120)", callback_data="buy_chibi_pack")
                    btn2 = types.InlineKeyboardButton("Назад", callback_data="mart_back")
                    markup.add(btn1)
                    markup.add(btn2)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "buy_chibi_pack":
                    telegram_id_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user:
                        return
                    
                    coins = user.get('coins', 0)
                    
                    if coins < BOT_SETTINGS['chibi_pack_price']:
                        missing = BOT_SETTINGS['chibi_pack_price'] - coins
                        self.bot.answer_callback_query(call.id, BOT_TEXTS['buy_pack_insufficient_coins'].format(missing=missing))
                        return
                    
                    new_coins = coins - BOT_SETTINGS['chibi_pack_price']
                    current = user.get('items', {})
                    if "🧧 Чиби-пак" not in current:
                        current["🧧 Чиби-пак"] = 0
                    current["🧧 Чиби-пак"] += 1
                    
                    self.users.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {
                            "coins": new_coins,
                            "items": current
                        }}
                    )
                    
                    self.bot.answer_callback_query(call.id, "Чиби-пак куплен!")
                    
                    text = BOT_TEXTS['mart_text']
                    
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_chibi_pack")
                    markup.add(btn)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "mart_back":
                    text = BOT_TEXTS['mart_text']
                    
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_chibi_pack")
                    markup.add(btn)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "menu_bonus":
                    telegram_id_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user:
                        return
                    
                    cd = self.check_bonus_cd(call.from_user.id)
                    if cd and not self.is_test(user.get('username')):
                        time_left = self.format_time(int(cd))
                        self.bot.answer_callback_query(call.id, BOT_TEXTS['bonus_cooldown'].format(time_left=time_left))
                        return
                    
                    bonus = random.randint(BOT_SETTINGS['bonus_min'], BOT_SETTINGS['bonus_max'])
                    
                    new_coins = user.get('coins', 0) + bonus
                    self.users.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {
                            "coins": new_coins,
                            "last_bonus_time": datetime.now()
                        }}
                    )
                    
                    name = user.get('first_name', 'путешественник')
                    text = BOT_TEXTS['bonus_received'].format(username=name, bonus=bonus)
                    
                    sent = self.bot.send_message(
                        call.message.chat.id,
                        text,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                    
                elif call.data == "bonus_cooldown":
                    telegram_id_str = str(call.from_user.id)
                    cd = self.check_bonus_cd(call.from_user.id)
                    if cd:
                        time_left = self.format_time(int(cd))
                        self.bot.answer_callback_query(call.id, BOT_TEXTS['bonus_cooldown'].format(time_left=time_left))
                    
                elif call.data == "menu_back":
                    text = BOT_TEXTS['menu_text']
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn1 = types.InlineKeyboardButton("Склад", callback_data="menu_warehouse")
                    btn2 = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
                    
                    cd = self.check_bonus_cd(call.from_user.id)
                    user = self.users.find_one({"telegram_id": str(call.from_user.id)})
                    if cd and not self.is_test(user.get('username') if user else None):
                        time_left = self.format_time(int(cd))
                        btn3 = types.InlineKeyboardButton(f"Приходи через {time_left}", callback_data="bonus_cooldown")
                    else:
                        btn3 = types.InlineKeyboardButton("Ежедневный бонус", callback_data="menu_bonus")
                    
                    markup.add(btn1, btn2)
                    markup.add(btn3)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("gift_page_"):
                    page = int(call.data.split("_")[2])
                    telegram_id_str = str(call.from_user.id)
                    
                    if not self.get_temp("gift_data", telegram_id_str):
                        self.bot.answer_callback_query(call.id, "Сообщение устарело...")
                        return
                    
                    chibis, cur_page, total = self.chibis_for_gift(call.from_user.id, page)
                    
                    text = BOT_TEXTS['gift_select']
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    for name, count in chibis:
                        markup.add(types.InlineKeyboardButton(name, callback_data=f"gift_select_{name}"))
                    
                    markup.add(types.InlineKeyboardButton("Подарить коины", callback_data="gift_coins"))
                    
                    nav = []
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"gift_page_{((cur_page-2) % total) + 1}"))
                    
                    nav.append(types.InlineKeyboardButton("Отменить", callback_data="gift_cancel"))
                    
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"gift_page_{(cur_page % total) + 1}"))
                    
                    markup.row(*nav)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "gift_coins":
                    telegram_id_str = str(call.from_user.id)
                    
                    if not self.get_temp("gift_data", telegram_id_str):
                        self.bot.answer_callback_query(call.id, "Сообщение устарело...")
                        return
                    
                    text = BOT_TEXTS['gift_coins_input']
                    
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton("Отменить", callback_data="gift_cancel")
                    markup.add(btn)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                    self.set_temp("waiting_coins", True, telegram_id_str)
                    
                elif call.data.startswith("gift_confirm_coins_"):
                    amount = int(call.data.split("_")[3])
                    telegram_id_str = str(call.from_user.id)
                    
                    gift_data = self.get_temp("gift_data", telegram_id_str)
                    if not gift_data:
                        self.bot.answer_callback_query(call.id, "Сообщение устарело...")
                        return
                    
                    target_tg = gift_data["target_tg"]
                    target_name = gift_data["target_name"]
                    is_admin = gift_data["is_admin"]
                    
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user:
                        self.bot.answer_callback_query(call.id, "Ошибка")
                        return

                    if not is_admin:
                        if user.get('coins', 0) < amount:
                            self.bot.answer_callback_query(call.id, "Недостаточно коинов!")
                            return

                        new_coins_sender = user.get('coins', 0) - amount
                        self.users.update_one(
                            {"telegram_id": telegram_id_str},
                            {"$set": {"coins": new_coins_sender}}
                        )
                    
                    target = self.users.find_one({"telegram_id": target_tg})
                    if target:
                        new_coins_receiver = target.get('coins', 0) + amount
                        self.users.update_one(
                            {"telegram_id": target_tg},
                            {"$set": {"coins": new_coins_receiver}}
                        )
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sender_name = call.from_user.first_name or "Отправитель"
                    text = BOT_TEXTS['gift_coins_sent'].format(target_name=target_name)

                    sent = self.bot.send_message(
                        call.message.chat.id,
                        text,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)

                    text2 = BOT_TEXTS['gift_coins_received'].format(sender_name=sender_name, amount=amount)

                    sent = self.bot.send_message(
                        target_tg,
                        text2,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{target_tg}_{sent.message_id}", target_tg)

                    self.del_temp("gift_data", telegram_id_str)
                    
                elif call.data.startswith("gift_select_"):
                    chibi_name = call.data.replace("gift_select_", "")
                    telegram_id_str = str(call.from_user.id)
                    
                    gift_data = self.get_temp("gift_data", telegram_id_str)
                    if not gift_data:
                        self.bot.answer_callback_query(call.id, "Сообщение устарело...")
                        return
                    
                    gift_data["chibi_name"] = chibi_name
                    self.set_temp("gift_data", gift_data, telegram_id_str)
                    
                    target_name = gift_data["target_name"]
                    
                    text = BOT_TEXTS['gift_chibi_confirm'].format(
                        target_name=target_name,
                        chibi_name=chibi_name
                    )
                    
                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("Подтвердить", callback_data="gift_confirm")
                    btn2 = types.InlineKeyboardButton("Отмена", callback_data="gift_cancel")
                    markup.add(btn1)
                    markup.add(btn2)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "gift_confirm":
                    telegram_id_str = str(call.from_user.id)
                    
                    gift_data = self.get_temp("gift_data", telegram_id_str)
                    if not gift_data:
                        self.bot.answer_callback_query(call.id, "Сообщение устарело...")
                        return
                    
                    chibi_name = gift_data["chibi_name"]
                    target_tg = gift_data["target_tg"]
                    target_name = gift_data["target_name"]
                    is_admin = gift_data["is_admin"]
                    
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user or (chibi_name not in user.get('chibis', []) and not user.get('infinite_chibis')):
                        self.bot.answer_callback_query(call.id, "У тебя больше нет этого чибика!")
                        return
                    
                    if not is_admin and not user.get('infinite_chibis'):
                        new_chibis = user.get('chibis', []).copy()
                        if chibi_name in new_chibis:
                            new_chibis.remove(chibi_name)
                        self.users.update_one(
                            {"telegram_id": telegram_id_str},
                            {"$set": {"chibis": new_chibis}}
                        )
                    
                    target = self.users.find_one({"telegram_id": target_tg})
                    if target:
                        target_chibis = target.get('chibis', [])
                        target_chibis.append(chibi_name)
                        target_times = target.get('chibi_timestamps', {})
                        target_times[chibi_name] = datetime.now()
                        
                        self.users.update_one(
                            {"telegram_id": target_tg},
                            {"$set": {
                                "chibis": target_chibis,
                                "chibi_timestamps": target_times
                            }}
                        )
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    is_prize = chibi_name in self.prize_chibis
                    
                    if is_admin and is_prize:
                        file_path, _, _ = self.get_prize_chibi(chibi_name)
                        
                        if file_path:
                            text = BOT_TEXTS['gift_prize_received'].format(target_name=target_name, chibi_name=chibi_name)
                            
                            self.send_chibi_photo(
                                target_tg,
                                file_path,
                                text,
                                target_tg
                            )
                            
                            text2 = BOT_TEXTS['gift_prize_sent'].format(target_name=target_name, chibi_name=chibi_name)
                            
                            sent = self.bot.send_message(
                                call.message.chat.id,
                                text2,
                                parse_mode='Markdown'
                            )
                            self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                            
                    else:
                        sticker = STICKERS['gift_sent']
                        self.bot.send_sticker(call.message.chat.id, sticker)
                        
                        sender_name = call.from_user.first_name or "Отправитель"
                        text = BOT_TEXTS['gift_chibi_sent'].format(target_name=target_name)
                        
                        sent = self.bot.send_message(
                            call.message.chat.id,
                            text,
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                        
                        sticker2 = STICKERS['gift_received']
                        self.bot.send_sticker(target_tg, sticker2)
                        
                        text2 = BOT_TEXTS['gift_chibi_received'].format(sender_name=sender_name, chibi_name=chibi_name)
                        
                        markup = types.InlineKeyboardMarkup()
                        btn = types.InlineKeyboardButton("Посмотреть", callback_data="warehouse_chibis_1")
                        markup.add(btn)
                        
                        sent = self.bot.send_message(
                            target_tg,
                            text2,
                            reply_markup=markup,
                            parse_mode='Markdown'
                        )
                        self.set_temp(f"msg_owner_{target_tg}_{sent.message_id}", target_tg)
                    
                    self.del_temp("gift_data", telegram_id_str)
                    
                elif call.data == "gift_cancel":
                    telegram_id_str = str(call.from_user.id)
                    
                    self.del_temp("gift_data", telegram_id_str)
                    self.del_temp("waiting_coins", telegram_id_str)
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                elif call.data.startswith("hub_page_"):
                    page = int(call.data.split("_")[2])
                    telegram_id_str = str(call.from_user.id)
                    self.show_hub_page(call.message.chat.id, telegram_id_str, page, call.message.message_id)
                    
                elif call.data.startswith("hub_lot_"):
                    lot_id = call.data.split("_")[2]
                    telegram_id_str = str(call.from_user.id)
                    self.show_lot_details(call.message.chat.id, telegram_id_str, lot_id, call.message.message_id)
                    
                elif call.data.startswith("hub_buy_"):
                    lot_id = call.data.split("_")[2]
                    telegram_id_str = str(call.from_user.id)
                    self.buy_lot(call, lot_id, telegram_id_str)
                    
                elif call.data.startswith("hub_remove_"):
                    lot_id = call.data.split("_")[2]
                    telegram_id_str = str(call.from_user.id)
                    self.show_remove_confirmation(call.message.chat.id, telegram_id_str, lot_id, call.message.message_id)
                    
                elif call.data.startswith("hub_confirm_remove_"):
                    lot_id = call.data.split("_")[3]
                    telegram_id_str = str(call.from_user.id)
                    self.remove_lot(call, lot_id, telegram_id_str)
                    
                elif call.data == "hub_create":
                    telegram_id_str = str(call.from_user.id)
                    self.show_create_lot_page(call.message.chat.id, telegram_id_str, 1, call.message.message_id)
                    
                elif call.data.startswith("create_lot_page_"):
                    page = int(call.data.split("_")[3])
                    telegram_id_str = str(call.from_user.id)
                    self.show_create_lot_page(call.message.chat.id, telegram_id_str, page, call.message.message_id)
                    
                elif call.data.startswith("create_lot_select_"):
                    chibi_name = call.data.replace("create_lot_select_", "")
                    telegram_id_str = str(call.from_user.id)
                    
                    if self.chibi_count(call.from_user.id, chibi_name) == 0:
                        self.bot.answer_callback_query(call.id, BOT_TEXTS['not_enough_chibi'])
                        return
                    
                    text = BOT_TEXTS['create_lot_price'].format(chibi_name=chibi_name)
                    
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton("Отмена", callback_data="create_lot_cancel")
                    markup.add(btn)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                    self.set_temp("creating_lot", {
                        "chibi_name": chibi_name,
                        "seller_id": telegram_id_str,
                        "message_id": call.message.message_id
                    }, telegram_id_str)
                    
                    self.set_temp("waiting_lot_price", True, telegram_id_str)
                    
                elif call.data == "create_lot_confirm":
                    telegram_id_str = str(call.from_user.id)
                    lot_data = self.get_temp("creating_lot", telegram_id_str)
                    
                    if not lot_data:
                        self.bot.answer_callback_query(call.id, "Сессия истекла!")
                        return
                    
                    if self.chibi_count(call.from_user.id, lot_data["chibi_name"]) == 0:
                        self.bot.answer_callback_query(call.id, BOT_TEXTS['not_enough_chibi'])
                        return
                    
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    
                    new_chibis = user.get('chibis', []).copy()
                    if lot_data["chibi_name"] in new_chibis:
                        new_chibis.remove(lot_data["chibi_name"])
                    
                    self.users.update_one(
                        {"telegram_id": telegram_id_str},
                        {"$set": {"chibis": new_chibis}}
                    )
                    
                    lot = {
                        "seller_id": telegram_id_str,
                        "seller_name": user.get('first_name', 'Игрок'),
                        "chibi_name": lot_data["chibi_name"],
                        "price": lot_data["price"],
                        "created_at": datetime.now(),
                        "status": "active"
                    }
                    
                    self.market.insert_one(lot)
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    self.del_temp("creating_lot", telegram_id_str)
                    
                    sent = self.bot.send_message(
                        call.message.chat.id,
                        BOT_TEXTS['create_lot_success'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                    
                    time.sleep(1)
                    self.show_hub_page(call.message.chat.id, telegram_id_str, 1)
                    
                elif call.data == "create_lot_cancel":
                    telegram_id_str = str(call.from_user.id)
                    self.del_temp("creating_lot", telegram_id_str)
                    self.del_temp("waiting_lot_price", telegram_id_str)
                    self.show_hub_page(call.message.chat.id, telegram_id_str, 1, call.message.message_id)
                    
                elif call.data == "hub_back_from_lot":
                    telegram_id_str = str(call.from_user.id)
                    self.show_hub_page(call.message.chat.id, telegram_id_str, 1, call.message.message_id)
                    
                elif call.data == "hub_back_from_remove":
                    telegram_id_str = str(call.from_user.id)
                    lot_id = self.get_temp(f"removing_lot_{telegram_id_str}")
                    if lot_id:
                        self.show_lot_details(call.message.chat.id, telegram_id_str, lot_id, call.message.message_id)
                        self.del_temp(f"removing_lot_{telegram_id_str}")
                    
                elif call.data == "chibi_click":
                    self.bot.answer_callback_query(call.id)
                    
                elif call.data == "item_click":
                    self.bot.answer_callback_query(call.id, BOT_TEXTS['item_cannot_use'])
                    
                elif call.data == "empty":
                    self.bot.answer_callback_query(call.id, BOT_TEXTS['empty'])
                    
                else:
                    self.bot.answer_callback_query(call.id)
                    
            except Exception as e:
                logger.error(f"Ошибка в callback: {e}")
                self.bot.answer_callback_query(call.id, BOT_TEXTS['not_yours'], parse_mode='Markdown')

    def show_hub_page(self, chat_id, telegram_id_str, page=1, message_id=None):
        lots, cur_page, total_pages, total_lots = self.get_market_lots(page)
        
        text = BOT_TEXTS['hub_intro'].format(total_lots=total_lots)
        
        markup = types.InlineKeyboardMarkup()
        
        if not lots:
            markup.add(types.InlineKeyboardButton(BOT_TEXTS['hub_no_lots'], callback_data="empty"))
        else:
            for lot in lots:
                btn_text = f"{lot['chibi_name']} - 💰{lot['price']}"
                markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"hub_lot_{str(lot['_id'])}"))
        
        markup.add(types.InlineKeyboardButton("Создать лот", callback_data="hub_create"))
        
        nav = []
        if total_pages > 1:
            nav.append(types.InlineKeyboardButton("◀️", callback_data=f"hub_page_{((cur_page-2) % total_pages) + 1}"))
        
        nav.append(types.InlineKeyboardButton(f"{cur_page}/{total_pages}", callback_data="empty"))
        
        if total_pages > 1:
            nav.append(types.InlineKeyboardButton("▶️", callback_data=f"hub_page_{(cur_page % total_pages) + 1}"))
        
        markup.row(*nav)
        
        if message_id:
            self.bot.edit_message_text(
                text,
                chat_id,
                message_id,
                reply_markup=markup,
                parse_mode='Markdown'
            )
        else:
            sent = self.bot.send_message(
                chat_id,
                text,
                reply_markup=markup,
                parse_mode='Markdown'
            )
            self.set_temp(f"msg_owner_{chat_id}_{sent.message_id}", telegram_id_str)

    def show_lot_details(self, chat_id, telegram_id_str, lot_id, message_id):
        try:
            lot = self.market.find_one({"_id": ObjectId(lot_id)})
            if not lot or lot['status'] != 'active':
                self.bot.answer_callback_query(call.id, "Лот уже не доступен!")
                return
            
            user = self.users.find_one({"telegram_id": telegram_id_str})
            is_owner = lot['seller_id'] == telegram_id_str
            
            text = BOT_TEXTS['hub_lot_details'].format(
                seller_name=lot['seller_name'],
                chibi_name=lot['chibi_name'],
                price=lot['price']
            )
            
            markup = types.InlineKeyboardMarkup()
            
            if is_owner:
                btn1 = types.InlineKeyboardButton("Убрать лот", callback_data=f"hub_remove_{lot_id}")
            else:
                btn1 = types.InlineKeyboardButton(f"Купить (💰{lot['price']})", callback_data=f"hub_buy_{lot_id}")
            
            btn2 = types.InlineKeyboardButton("Назад", callback_data="hub_back_from_lot")
            markup.add(btn1)
            markup.add(btn2)
            
            self.bot.edit_message_text(
                text,
                chat_id,
                message_id,
                reply_markup=markup,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка показа деталей лота: {e}")

    def show_remove_confirmation(self, chat_id, telegram_id_str, lot_id, message_id):
        text = BOT_TEXTS['lot_remove_confirm']
        
        markup = types.InlineKeyboardMarkup()
        btn1 = types.InlineKeyboardButton("Да, убрать", callback_data=f"hub_confirm_remove_{lot_id}")
        btn2 = types.InlineKeyboardButton("Назад", callback_data="hub_back_from_remove")
        markup.add(btn1)
        markup.add(btn2)
        
        self.set_temp(f"removing_lot_{telegram_id_str}", lot_id)
        
        self.bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode='Markdown'
        )

    def buy_lot(self, call, lot_id, telegram_id_str):
        try:
            lot = self.market.find_one({"_id": ObjectId(lot_id)})
            if not lot or lot['status'] != 'active':
                self.bot.answer_callback_query(call.id, "Лот уже не доступен!")
                return
            
            if lot['seller_id'] == telegram_id_str:
                self.bot.answer_callback_query(call.id, BOT_TEXTS['cannot_buy_own'])
                return
            
            buyer = self.users.find_one({"telegram_id": telegram_id_str})
            if not buyer:
                self.bot.answer_callback_query(call.id, "Ошибка!")
                return
            
            if buyer.get('coins', 0) < lot['price']:
                self.bot.answer_callback_query(call.id, BOT_TEXTS['not_enough_money'])
                return
            
            seller = self.users.find_one({"telegram_id": lot['seller_id']})
            if not seller:
                self.bot.answer_callback_query(call.id, "Продавец не найден!")
                return
            
            new_buyer_coins = buyer.get('coins', 0) - lot['price']
            new_seller_coins = seller.get('coins', 0) + lot['price']
            
            buyer_chibis = buyer.get('chibis', [])
            buyer_chibis.append(lot['chibi_name'])
            buyer_times = buyer.get('chibi_timestamps', {})
            buyer_times[lot['chibi_name']] = datetime.now()
            
            self.users.update_one(
                {"telegram_id": telegram_id_str},
                {"$set": {
                    "coins": new_buyer_coins,
                    "chibis": buyer_chibis,
                    "chibi_timestamps": buyer_times
                }}
            )
            
            self.users.update_one(
                {"telegram_id": lot['seller_id']},
                {"$set": {"coins": new_seller_coins}}
            )
            
            self.market.delete_one({"_id": ObjectId(lot_id)})
            
            self.bot.delete_message(call.message.chat.id, call.message.message_id)
            
            text = BOT_TEXTS['hub_buy_success'].format(
                buyer_name=buyer.get('first_name', 'Покупатель'),
                chibi_name=lot['chibi_name'],
                seller_name=seller.get('first_name', 'Продавец'),
                price=lot['price']
            )
            
            sent = self.bot.send_message(
                call.message.chat.id,
                text,
                parse_mode='Markdown'
            )
            self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
            
            if seller.get('telegram_id'):
                notify_text = f"*Твой лот продан!*\n{text}"
                try:
                    self.bot.send_message(
                        seller['telegram_id'],
                        notify_text,
                        parse_mode='Markdown'
                    )
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Ошибка покупки лота: {e}")
            self.bot.answer_callback_query(call.id, "Ошибка покупки!")

    def remove_lot(self, call, lot_id, telegram_id_str):
        try:
            lot = self.market.find_one({"_id": ObjectId(lot_id)})
            if not lot or lot['status'] != 'active':
                self.bot.answer_callback_query(call.id, "Лот уже не доступен!")
                return
            
            if lot['seller_id'] != telegram_id_str:
                self.bot.answer_callback_query(call.id, "Это не твой лот!")
                return
            
            user = self.users.find_one({"telegram_id": telegram_id_str})
            if user:
                user_chibis = user.get('chibis', [])
                user_chibis.append(lot['chibi_name'])
                user_times = user.get('chibi_timestamps', {})
                user_times[lot['chibi_name']] = datetime.now()
                
                self.users.update_one(
                    {"telegram_id": telegram_id_str},
                    {"$set": {
                        "chibis": user_chibis,
                        "chibi_timestamps": user_times
                    }}
                )
            
            self.market.delete_one({"_id": ObjectId(lot_id)})
            
            self.bot.delete_message(call.message.chat.id, call.message.message_id)
            
            sent = self.bot.send_message(
                call.message.chat.id,
                BOT_TEXTS['lot_removed'],
                parse_mode='Markdown'
            )
            self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
            
        except Exception as e:
            logger.error(f"Ошибка удаления лота: {e}")
            self.bot.answer_callback_query(call.id, "Ошибка удаления!")

    def show_create_lot_page(self, chat_id, telegram_id_str, page=1, message_id=None):
        chibis, cur_page, total = self.get_user_market_chibis(telegram_id_str, page, 6)
        
        text = BOT_TEXTS['create_lot_choose']
        
        markup = types.InlineKeyboardMarkup()
        
        if not chibis:
            markup.add(types.InlineKeyboardButton(BOT_TEXTS['empty'], callback_data="empty"))
        else:
            for name, count in chibis:
                markup.add(types.InlineKeyboardButton(f"{name}", callback_data=f"create_lot_select_{name}"))
        
        nav = []
        if total > 1:
            nav.append(types.InlineKeyboardButton("◀️", callback_data=f"create_lot_page_{((cur_page-2) % total) + 1}"))
        
        nav.append(types.InlineKeyboardButton("Назад", callback_data="create_lot_cancel"))
        
        if total > 1:
            nav.append(types.InlineKeyboardButton("▶️", callback_data=f"create_lot_page_{(cur_page % total) + 1}"))
        
        markup.row(*nav)
        
        self.bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode='Markdown'
        )

    def run(self):
        logger.info("Бот запущен!")
        self.setup_handlers()
        
        if "RENDER" in os.environ:
            self.setup_flask_routes()
            PORT = int(os.environ.get('PORT', 5000))
            
            def run_flask():
                self.app.run(host='0.0.0.0', port=PORT)
            
            flask_thread = threading.Thread(target=run_flask)
            flask_thread.daemon = True
            flask_thread.start()
            logger.info(f"Фласк работает на порту {PORT}")
        
        self.cleanup()
        
        self.bot.infinity_polling()

    def cleanup(self):
        def clean():
            while True:
                try:
                    two_min = time.time() - 120
                    for user_id in list(self.user_reqs.keys()):
                        self.user_reqs[user_id] = [
                            t for t in self.user_reqs[user_id] 
                            if t > two_min
                        ]
                        if not self.user_reqs[user_id]:
                            del self.user_reqs[user_id]
                    
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"Ошибка в cleanup: {e}")
                    time.sleep(60)
        
        thread = threading.Thread(target=clean)
        thread.daemon = True
        thread.start()

def get_token():
    return os.getenv('BOT_TOKEN')

if __name__ == "__main__":
    token = get_token()
    if not token:
        print("Токена нема")
        exit(1)
    
    bot = ChibiBot(token)
    bot.run()
