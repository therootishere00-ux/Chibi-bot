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
from bson import ObjectId
from flask_cors import CORS

from config import BOT_CONFIG, BOT_TEXTS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ChibiBot:
    def __init__(self, token):
        self.bot = telebot.TeleBot(token)
        self.test_users = ['ya_admin7', 'tmkazavr'] 
        
        if "RENDER" in os.environ:
            self.app = Flask(__name__)
            CORS(self.app)
        
        self.mongo_uri = os.getenv('MONGODB_URI')
        if not self.mongo_uri:
            logger.error("MONGODB_URI not found!")
            raise ValueError("MONGODB_URI not found")
        
        try:
            self.client = MongoClient(self.mongo_uri)
            self.db = self.client.chibibot
            self.users = self.db.users
            self.system = self.db.system
            self.temp = self.db.temp_data
            
            self.temp.create_index("created_at", expireAfterSeconds=3600)
            logger.info("✅ MongoDB connected")
        except Exception as e:
            logger.error(f"❌ MongoDB error: {e}")
            raise
        
        self.common_chibis = self._scan_chibis("chibis/common")
        self.secret_chibis = self._scan_chibis("chibis/secret")
        self.prize_chibis = self._scan_chibis("chibis/prize")
        
        self._init_db()
        self._init_admins()
        self._init_system()
        
        self.user_reqs = {}
        self.MAX_REQS_PER_MIN = 30
    
    def _init_system(self):
        if not self.system.find_one({"type": "used_ids"}):
            self.system.insert_one({
                "type": "used_ids",
                "ids": [],
                "created_at": datetime.now()
            })
    
    def _scan_chibis(self, path):
        if not os.path.exists(path):
            logger.error(f"Folder {path} not found!")
            return []
        
        files = [f for f in os.listdir(path) if f.lower().endswith('.png')]
        names = [os.path.splitext(f)[0].replace('_', ' ') for f in files]
        return sorted(names)
    
    def _init_admins(self):
        for username in self.test_users:
            user = self.users.find_one({"username": username})
            if user:
                all_chibis = self.common_chibis + self.secret_chibis + self.prize_chibis
                timestamps = {chibi: datetime.now() for chibi in all_chibis}
                
                self.users.update_one(
                    {"username": username},
                    {"$set": {
                        "chibis": all_chibis,
                        "chibi_timestamps": timestamps,
                        "coins": 999999,
                        "items": {"🧧 Чиби-пак": 99},
                        "infinite_chibis": True
                    }}
                )
                logger.info(f"✅ Admin {username} initialized")
            
    def _init_db(self):
        self.users.create_index("telegram_id", unique=True)
        self.users.create_index("user_id", unique=True)
        self.users.create_index("last_active")
        self.temp.create_index("telegram_id")
        
    def check_rate(self, user_id):
        now = time.time()
        user_str = str(user_id)
        
        if user_str not in self.user_reqs:
            self.user_reqs[user_str] = []
        
        self.user_reqs[user_str] = [t for t in self.user_reqs[user_str] if now - t < 60]
        
        if len(self.user_reqs[user_str]) >= self.MAX_REQS_PER_MIN:
            return False
        
        self.user_reqs[user_str].append(now)
        return True
        
    def is_test_user(self, username):
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
        
    def clear_user(self, telegram_id):
        self.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {
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
            }}
        )
            
    def ban_user(self, user_id, days=7):
        user_str = str(user_id)
        ban_until = datetime.now() + timedelta(days=days)
        
        self.users.update_one(
            {"telegram_id": user_str},
            {"$set": {"banned_until": ban_until}}
        )
        
    def unban_user(self, user_id):
        user_str = str(user_id)
        self.users.update_one(
            {"telegram_id": user_str},
            {"$unset": {"banned_until": ""}}
        )
            
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
            
        if self.is_test_user(user.get('username')):
            return None
            
        if user.get('last_chibi_time'):
            last_time = user['last_chibi_time']
            time_passed = (datetime.now() - last_time).total_seconds()
            if time_passed < 3 * 3600:
                return 3 * 3600 - time_passed
        return None
        
    def check_task_cd(self, user_id):
        user = self.users.find_one({"telegram_id": str(user_id)})
        if not user:
            return None
            
        if self.is_test_user(user.get('username')):
            return None
            
        if user.get('last_task_time'):
            last_time = user['last_task_time']
            task_type = user.get('last_task_type', 'completed')
            
            time_passed = (datetime.now() - last_time).total_seconds()
            
            cooldown = 4 * 3600 if task_type == 'completed' else 5.5 * 3600
                
            if time_passed < cooldown:
                return cooldown - time_passed
        return None
        
    def check_bonus_cd(self, user_id):
        user = self.users.find_one({"telegram_id": str(user_id)})
        if not user:
            return None
            
        if self.is_test_user(user.get('username')):
            return None
            
        if user.get('last_bonus_time'):
            now = datetime.now()
            last_bonus = user['last_bonus_time']
            
            moscow_time = now + timedelta(hours=3)
            last_bonus_moscow = last_bonus + timedelta(hours=3)
            
            if last_bonus_moscow.date() == moscow_time.date():
                next_midnight = datetime(moscow_time.year, moscow_time.month, moscow_time.day) + timedelta(days=1)
                time_left = next_midnight - moscow_time
                return time_left.total_seconds()
        return None
        
    def gen_user_id(self):
        attempts = 0
        while attempts < 100:
            letter = random.choice(string.ascii_uppercase)
            numbers = ''.join(random.choices(string.digits, k=4))
            position = random.randint(0, 1)
            user_id = letter + numbers if position == 0 else numbers + letter
            
            existing = self.users.find_one({"user_id": user_id})
            system_data = self.system.find_one({"type": "used_ids"})
            used_ids = system_data.get("ids", []) if system_data else []
            
            if not existing and user_id not in used_ids:
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
    
    def get_user(self, telegram_id, first_name=None, username=None):
        user_str = str(telegram_id)
        
        if self.is_banned(telegram_id):
            return None, False
            
        user = self.users.find_one({"telegram_id": user_str})
        
        if user:
            self.users.update_one(
                {"telegram_id": user_str},
                {"$set": {"last_active": datetime.now()}}
            )
            return user, False
        else:
            user_id = self.gen_user_id()
            user_data = {
                "telegram_id": user_str,
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
            
            if self.is_test_user(username):
                user_data["coins"] = 1000
                user_data["items"]["🧧 Чиби-пак"] = 5
                user_data["infinite_chibis"] = True
            
            self.users.insert_one(user_data)
            logger.info(f"New user: {user_id}")
            return user_data, True

    def user_started(self, user_id):
        user = self.users.find_one({"telegram_id": str(user_id)})
        return user is not None

    def send_start_msg(self, chat_id, msg_id=None):
        text = "⭐️ *Советую сначала запустить бота*"
        markup = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton("Запуск", url=f"https://t.me/{self.bot.get_me().username}?start=start")
        markup.add(btn)
        
        if msg_id:
            try:
                self.bot.edit_message_text(text, chat_id, msg_id, reply_markup=markup, parse_mode='Markdown')
            except:
                self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
        else:
            self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')

    def add_chibi(self, telegram_id, chibi_name, rarity="Common"):
        user_str = str(telegram_id)
        
        user = self.users.find_one({"telegram_id": user_str})
        if not user:
            return
            
        if user.get('infinite_chibis'):
            return
            
        current_chibis = user.get('chibis', [])
        current_timestamps = user.get('chibi_timestamps', {})
        
        current_chibis.append(chibi_name)
        current_timestamps[chibi_name] = datetime.now()
        
        self.users.update_one(
            {"telegram_id": user_str},
            {"$set": {
                "chibis": current_chibis,
                "chibi_timestamps": current_timestamps
            }}
        )

    def get_random_chibi(self, from_pack=False):
        if from_pack and random.random() <= 0.05:
            folder = "chibis/secret"
            all_chibis = self.secret_chibis
        else:
            folder = "chibis/common"
            all_chibis = self.common_chibis
        
        if not os.path.exists(folder) or not all_chibis:
            logger.error(f"Folder {folder} not found!")
            return None, None, "Common"
        
        chibi_name = random.choice(all_chibis)
        file_path = os.path.join(folder, f"{chibi_name.replace(' ', '_')}.png")
        
        if not os.path.exists(file_path):
            logger.error(f"Chibi file not found: {file_path}")
            files = [f for f in os.listdir(folder) if f.lower().endswith('.png')]
            if not files:
                return None, None, "Common"
            random_file = random.choice(files)
            file_path = os.path.join(folder, random_file)
            chibi_name = os.path.splitext(random_file)[0].replace('_', ' ')
        
        rarity = "Secret" if from_pack and folder == "chibis/secret" else "Common"
        
        return file_path, chibi_name, rarity

    def get_prize_chibi(self, chibi_name):
        folder = "chibis/prize"
        
        if not os.path.exists(folder):
            logger.error(f"Folder {folder} not found!")
            return None, None, "Prize"
        
        file_path = os.path.join(folder, f"{chibi_name.replace(' ', '_')}.png")
        if not os.path.exists(file_path):
            logger.error(f"Prize chibi {chibi_name} not found!")
            return None, None, "Prize"
        
        return file_path, chibi_name, "Prize"

    def get_chibi_count(self, telegram_id, chibi_name):
        user_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": user_str})
        if not user:
            return 0
            
        if user.get('infinite_chibis'):
            return 1
            
        chibis = user.get('chibis', [])
        return chibis.count(chibi_name)

    def gen_task(self, telegram_id):
        user_str = str(telegram_id)
        
        user = self.users.find_one({"telegram_id": user_str})
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
        
        self.users.update_one(
            {"telegram_id": user_str},
            {"$set": {"current_task": task_data}}
        )
        
        return task_data

    def get_task_text(self, task_data, telegram_id):
        user_str = str(telegram_id)
        has_chibi = self.get_chibi_count(telegram_id, task_data["chibi"]) > 0
        btn_text = "✅ Сдать задание (1/1)" if has_chibi else "Сдать задание (0/1)"
        
        text = f"""*{task_data['emoji']} {task_data['name']}*
{task_data['phrase']}
•••••••••••••••••••
Дам *💰 {task_data['reward']}* за {task_data['chibi']}"""
        
        return text, btn_text, has_chibi

    def get_page(self, items, page=1, per_page=8):
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        start = (page - 1) * per_page
        end = start + per_page
        page_items = items[start:end]
        
        return page_items, page, total_pages

    def get_user_chibis_page(self, telegram_id, page=1, per_page=8):
        user_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": user_str})
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

    def get_user_items_page(self, telegram_id, page=1, per_page=8):
        user_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": user_str})
        if not user:
            return [], 1, 1
        
        items = user.get('items', {})
        active = {name: count for name, count in items.items() if count > 0}
        
        sorted_items = sorted(
            [(name, count) for name, count in active.items()],
            key=lambda x: (-x[1], x[0])
        )
        
        return self.get_page(sorted_items, page, per_page)

    def get_gift_chibis(self, telegram_id, page=1, per_page=6):
        return self.get_user_chibis_page(telegram_id, page, per_page)

    def check_msg_owner(self, call):
        if call.message.chat.type == 'private':
            return True
            
        user_str = str(call.from_user.id)
        msg_key = f"{call.message.chat.id}_{call.message.message_id}"
        
        owner = self.get_temp(f"msg_owner_{msg_key}")
        if owner and owner != user_str:
            self.bot.answer_callback_query(call.id, "🙈 *Не твое!*", parse_mode='Markdown')
            return False
        return True

    def get_user_collection(self, telegram_id):
        user_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": user_str})
        
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

    def send_chibi_img(self, chat_id, file_path, caption, user_str):
        try:
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                msg = self.bot.send_message(
                    chat_id,
                    f"🌀 *Чибик временно недоступен!*\n{caption}",
                    parse_mode='Markdown'
                )
                self.set_temp(f"msg_owner_{chat_id}_{msg.message_id}", user_str)
                return msg
            
            with open(file_path, 'rb') as photo:
                msg = self.bot.send_photo(
                    chat_id,
                    photo,
                    caption=caption,
                    parse_mode='Markdown'
                )
                self.set_temp(f"msg_owner_{chat_id}_{msg.message_id}", user_str)
                return msg
                
        except Exception as e:
            logger.error(f"Send photo error: {e}")
            msg = self.bot.send_message(
                chat_id,
                f"🌀 *Не удалось отправить чибика!*\n{caption}",
                parse_mode='Markdown'
            )
            self.set_temp(f"msg_owner_{chat_id}_{msg.message_id}", user_str)
            return msg

    def setup_flask(self):
        @self.app.route('/')
        def home():
            return "🤖 Чиби-бот работает!"
        
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
                logger.error(f"Collection error: {e}")
                return jsonify({"error": "Internal server error"}), 500
        
        @self.app.route('/get_all_chibis', methods=['GET'])
        def get_chibis():
            try:
                return jsonify({
                    "common": self.common_chibis,
                    "secret": self.secret_chibis,
                    "prize": self.prize_chibis
                })
            except Exception as e:
                logger.error(f"Chibis error: {e}")
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
        def check_access(user_id, chat_type="private"):
            if self.is_banned(user_id):
                days = self.get_ban_time(user_id)
                msg = f"🤡 *Ты в бане!* Доступ через *{days}* дней."
                return False, msg
            
            if not self.user_started(user_id):
                return False, None
            
            if not self.check_rate(user_id):
                return False, "⚡️ *Слишком много запросов!*"
            
            return True, None

        def send_msg(chat_id, text, user_id, markup=None, edit_msg_id=None):
            if edit_msg_id:
                try:
                    msg = self.bot.edit_message_text(text, chat_id, edit_msg_id, reply_markup=markup, parse_mode='Markdown')
                except:
                    msg = self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
            else:
                msg = self.bot.send_message(chat_id, text, reply_markup=markup, parse_mode='Markdown')
            
            self.set_temp(f"msg_owner_{chat_id}_{msg.message_id}", str(user_id))
            return msg

        @self.bot.message_handler(commands=['start'])
        def start_cmd(message):
            if message.chat.type != 'private':
                return
                
            try:
                access, msg = check_access(message.from_user.id)
                if not access:
                    if msg:
                        send_msg(message.chat.id, msg, message.from_user.id)
                    return
                    
                user, is_new = self.get_user(
                    message.from_user.id,
                    message.from_user.first_name,
                    message.from_user.username
                )
                
                if user is None:
                    return
                    
                name = message.from_user.first_name or "путешественник"
                
                if is_new:
                    sticker = "CAACAgIAAxkBAAE9JsNpAzQZv6b4b-KZ3ftL2Sld0kUjDQAC400AAkuWEEosjitzZk8fzDYE"
                else:
                    sticker = "CAACAgIAAxkBAAE9JstpAzTQNnpt9KcoUte9P7K3CiHpswACmEQAAk-mEEqVynQKXagSVjYE"
                
                self.bot.send_sticker(message.chat.id, sticker)
                
                if is_new:
                    text = BOT_TEXTS['welcome'].format(name=name)
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton('📢 Наш тгк', url=BOT_CONFIG['telegram_channel'])
                    markup.add(btn)
                    send_msg(message.chat.id, text, message.from_user.id, markup)
                else:
                    send_msg(message.chat.id, BOT_TEXTS['already_started'], message.from_user.id)
                    
            except Exception as e:
                logger.error(f"Start error: {e}")
                send_msg(message.chat.id, "⛓️‍💥* Ошибка!* Попробуй снова!", message.from_user.id)

        @self.bot.message_handler(commands=['dice'])
        def dice_cmd(message):
            if message.chat.type != 'private':
                self.bot.reply_to(message, "🎲 *Только в личке!*", parse_mode='Markdown')
                return
                
            try:
                access, msg = check_access(message.from_user.id)
                if not access:
                    if msg:
                        send_msg(message.chat.id, msg, message.from_user.id)
                    return

                parts = message.text.split()
                if len(parts) < 2:
                    send_msg(message.chat.id, "🎲 *Формат:* `/dice 100`", message.from_user.id)
                    return

                try:
                    bet = int(parts[1])
                except ValueError:
                    send_msg(message.chat.id, "🎲 *Формат:* `/dice 100`", message.from_user.id)
                    return

                if bet < 1:
                    self.bot.reply_to(message, "❌ *Ставка > 0!*", parse_mode='Markdown')
                    return

                if bet > 10000:
                    self.bot.reply_to(message, "❌ *Макс: 10,000 коинов!*", parse_mode='Markdown')
                    return

                user_str = str(message.from_user.id)
                user = self.users.find_one({"telegram_id": user_str})
                if not user:
                    self.send_start_msg(message.chat.id)
                    return

                coins = user.get('coins', 0)
                if coins < bet:
                    self.bot.reply_to(message, f"❌ *Недостаточно!* У тебя {coins}💰", parse_mode='Markdown')
                    return

                # Списываем ставку
                self.users.update_one(
                    {"telegram_id": user_str},
                    {"$set": {"coins": coins - bet}}
                )

                dice_msg = self.bot.send_dice(message.chat.id, emoji='🎲')
                dice_value = dice_msg.dice.value

                time.sleep(2)

                # Новые условия: 2,4,6 - выигрыш, 1,3,5 - проигрыш
                if dice_value in [2, 4, 6]:
                    win_amount = math.ceil(bet * 1.7)
                    # Возвращаем ставку + выигрыш
                    total = (coins - bet) + bet + win_amount
                    
                    self.users.update_one(
                        {"telegram_id": user_str},
                        {"$set": {"coins": total}}
                    )

                    win_text = f"""*👽 Победа! {message.from_user.first_name}, забирай {win_amount}!*
_Ты обыграл дилера!_
_•••••••••••••••_
+ 💰*{win_amount}* коинов"""

                    self.bot.send_message(message.chat.id, win_text, parse_mode='Markdown')
                else:
                    lose_text = f"""*👽 Проигрыш! {message.from_user.first_name}, ставка сгорела!*
_Все честно. Попробуй еще_"""

                    self.bot.send_message(message.chat.id, lose_text, parse_mode='Markdown')

            except Exception as e:
                logger.error(f"Dice error: {e}")
                send_msg(message.chat.id, "⛓️‍💥* Ошибка!*", message.from_user.id)

        @self.bot.message_handler(commands=['ban'])
        def ban_cmd(message):
            try:
                if not self.user_started(message.from_user.id):
                    self.send_start_msg(message.chat.id)
                    return
                    
                user_str = str(message.from_user.id)
                user = self.users.find_one({"telegram_id": user_str})
                
                if not self.is_test_user(user.get('username')):
                    self.bot.reply_to(message, "❌ *Нет прав!*", parse_mode='Markdown')
                    return
                    
                if len(message.text.split()) < 2:
                    self.bot.reply_to(message, "🤷‍♂️ *Использование:* `/ban @username`", parse_mode='Markdown')
                    return
                    
                target = message.text.split()[1].strip()
                
                target_user = self.users.find_one({
                    "$or": [
                        {"username": target.replace('@', '')},
                        {"user_id": target}
                    ]
                })
                
                if not target_user:
                    self.bot.reply_to(message, "👻 *Не найден!*", parse_mode='Markdown')
                    return
                    
                self.ban_user(target_user['telegram_id'])
                self.bot.reply_to(message, f"✅ *Забанен на 7 дней!*", parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Ban error: {e}")
                self.bot.reply_to(message, "⛓️‍💥* Ошибка!*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['unban'])
        def unban_cmd(message):
            try:
                if not self.user_started(message.from_user.id):
                    self.send_start_msg(message.chat.id)
                    return
                    
                user_str = str(message.from_user.id)
                user = self.users.find_one({"telegram_id": user_str})
                
                if not self.is_test_user(user.get('username')):
                    self.bot.reply_to(message, "❌ *Нет прав!*", parse_mode='Markdown')
                    return
                    
                if len(message.text.split()) < 2:
                    self.bot.reply_to(message, "🤷‍♂️ *Использование:* `/unban @username`", parse_mode='Markdown')
                    return
                    
                target = message.text.split()[1].strip()
                
                target_user = self.users.find_one({
                    "$or": [
                        {"username": target.replace('@', '')},
                        {"user_id": target}
                    ]
                })
                        
                if not target_user:
                    self.bot.reply_to(message, "👻 *Не найден!*", parse_mode='Markdown')
                    return
                    
                self.unban_user(target_user['telegram_id'])
                self.bot.reply_to(message, f"✅ *Разбанен!*", parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Unban error: {e}")
                self.bot.reply_to(message, "⛓️‍💥* Ошибка!*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['myid'])
        def myid_cmd(message):
            try:
                access, msg = check_access(message.from_user.id, message.chat.type)
                if not access:
                    if msg:
                        if message.chat.type == 'private':
                            send_msg(message.chat.id, msg, message.from_user.id)
                        else:
                            self.bot.reply_to(message, msg, parse_mode='Markdown')
                    return
                    
                user, _ = self.get_user(message.from_user.id)
                user_id = user['user_id']
                
                text = f"⭐️ Твой айди — `{user_id}`"
                if message.chat.type == 'private':
                    send_msg(message.chat.id, text, message.from_user.id)
                else:
                    self.bot.reply_to(message, text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"MyID error: {e}")
                if message.chat.type == 'private':
                    send_msg(message.chat.id, "⛓️‍💥* Ошибка!*", message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Ошибка!*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['balance'])
        def balance_cmd(message):
            try:
                access, msg = check_access(message.from_user.id, message.chat.type)
                if not access:
                    if msg:
                        if message.chat.type == 'private':
                            send_msg(message.chat.id, msg, message.from_user.id)
                        else:
                            self.bot.reply_to(message, msg, parse_mode='Markdown')
                    return
                    
                user_str = str(message.from_user.id)
                user = self.users.find_one({"telegram_id": user_str})
                coins = user.get('coins', 0) if user else 0
                
                text = f"💰 У тебя — *{coins}* коинов!"
                if message.chat.type == 'private':
                    send_msg(message.chat.id, text, message.from_user.id)
                else:
                    self.bot.reply_to(message, text, parse_mode='Markdown')
                
            except Exception as e:
                logger.error(f"Balance error: {e}")
                if message.chat.type == 'private':
                    send_msg(message.chat.id, "⛓️‍💥* Ошибка!*", message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Ошибка!*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['mart'])
        def mart_cmd(message):
            try:
                access, msg = check_access(message.from_user.id, message.chat.type)
                if not access:
                    if msg:
                        if message.chat.type == 'private':
                            send_msg(message.chat.id, msg, message.from_user.id)
                        else:
                            self.bot.reply_to(message, msg, parse_mode='Markdown')
                    return
                    
                text = """🎏 *Лавка джавы*
Джавы знают толк в ценах!"""
                
                markup = types.InlineKeyboardMarkup()
                btn = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_pack")
                markup.add(btn)
                
                if message.chat.type == 'private':
                    send_msg(message.chat.id, text, message.from_user.id, markup)
                else:
                    reply = self.bot.reply_to(message, text, reply_markup=markup, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{reply.message_id}", str(message.from_user.id))
                
            except Exception as e:
                logger.error(f"Mart error: {e}")
                if message.chat.type == 'private':
                    send_msg(message.chat.id, "⛓️‍💥* Ошибка!*", message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Ошибка!*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['chibi'])
        def chibi_cmd(message):
            try:
                access, msg = check_access(message.from_user.id, message.chat.type)
                if not access:
                    if msg:
                        if message.chat.type == 'private':
                            send_msg(message.chat.id, msg, message.from_user.id)
                        else:
                            self.bot.reply_to(message, msg, parse_mode='Markdown')
                    return
                    
                cd = self.check_chibi_cd(message.from_user.id)
                if cd:
                    time_left = self.format_time(int(cd))
                    text = f"⚡️ *Вернись через *{time_left}*!"
                    if message.chat.type == 'private':
                        send_msg(message.chat.id, text, message.from_user.id)
                    else:
                        self.bot.reply_to(message, text, parse_mode='Markdown')
                    return
                    
                user_str = str(message.from_user.id)
                file_path, chibi_name, rarity = self.get_random_chibi(from_pack=False)
                
                if file_path is None:
                    text = "🌀 *Чибики отдыхают!* Загляни позже"
                    if message.chat.type == 'private':
                        send_msg(message.chat.id, text, message.from_user.id)
                    else:
                        self.bot.reply_to(message, text, parse_mode='Markdown')
                    return
                
                self.add_chibi(message.from_user.id, chibi_name)
                count = self.get_chibi_count(message.from_user.id, chibi_name)
                
                self.users.update_one(
                    {"telegram_id": user_str},
                    {"$set": {"last_chibi_time": datetime.now()}}
                )
                
                emoji = "🔷" if rarity == "Common" else "🔶"
                if rarity == "Prize":
                    emoji = "♦️"
                
                text = f"""*Тебе выпал — {chibi_name}!*
Надеюсь, он тебе понравился! 
Приходи еще через *2ч 59м*
•••••••••••••••••••
Редкость: {emoji} {rarity}
У тебя: {count}"""
                
                self.send_chibi_img(message.chat.id, file_path, text, user_str)
                    
                logger.info(f"Sent chibi: {chibi_name} ({rarity})")
                    
            except Exception as e:
                logger.error(f"Chibi error: {e}")
                if message.chat.type == 'private':
                    send_msg(message.chat.id, "⛓️‍💥* Ошибка!*", message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Ошибка!*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['task'])
        def task_cmd(message):
            try:
                access, msg = check_access(message.from_user.id, message.chat.type)
                if not access:
                    if msg:
                        if message.chat.type == 'private':
                            send_msg(message.chat.id, msg, message.from_user.id)
                        else:
                            self.bot.reply_to(message, msg, parse_mode='Markdown')
                    return
                    
                cd = self.check_task_cd(message.from_user.id)
                if cd:
                    time_left = self.format_time(int(cd))
                    user = self.users.find_one({"telegram_id": str(message.from_user.id)})
                    task_type = user.get('last_task_type', 'completed') if user else 'completed'
                    
                    if task_type == 'completed':
                        text = f"🎯 *Выполнил таск недавно. Жди* *{time_left}*"
                    else:
                        text = f"🎯 *Пропустил таск, жди* *{time_left}*"
                    
                    if message.chat.type == 'private':
                        send_msg(message.chat.id, text, message.from_user.id)
                    else:
                        self.bot.reply_to(message, text, parse_mode='Markdown')
                    return
                    
                task_data = self.gen_task(message.from_user.id)
                task_text, btn_text, has_chibi = self.get_task_text(task_data, message.from_user.id)
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn1 = types.InlineKeyboardButton(
                    btn_text, 
                    callback_data="task_do" if has_chibi else "task_no"
                )
                btn2 = types.InlineKeyboardButton("Пропустить", callback_data="task_skip_ask")
                markup.add(btn1, btn2)
                
                if message.chat.type == 'private':
                    send_msg(message.chat.id, task_text, message.from_user.id, markup)
                else:
                    reply = self.bot.reply_to(message, task_text, reply_markup=markup, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{reply.message_id}", str(message.from_user.id))
                
            except Exception as e:
                logger.error(f"Task error: {e}")
                if message.chat.type == 'private':
                    send_msg(message.chat.id, "⛓️‍💥* Ошибка!*", message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Ошибка!*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['menu'])
        def menu_cmd(message):
            try:
                access, msg = check_access(message.from_user.id, message.chat.type)
                if not access:
                    if msg:
                        if message.chat.type == 'private':
                            send_msg(message.chat.id, msg, message.from_user.id)
                        else:
                            self.bot.reply_to(message, msg, parse_mode='Markdown')
                    return
                    
                text = """*✨ Меню* 
Здесь все что нужно"""
                
                markup = types.InlineKeyboardMarkup(row_width=2)
                btn1 = types.InlineKeyboardButton("📦 Склад", callback_data="menu_storage")
                btn2 = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
                
                bonus_cd = self.check_bonus_cd(message.from_user.id)
                if bonus_cd:
                    time_left = self.format_time(int(bonus_cd))
                    btn3 = types.InlineKeyboardButton(f"🔒 Через {time_left}", callback_data="bonus_wait")
                else:
                    btn3 = types.InlineKeyboardButton("🎁 Бонус", callback_data="menu_bonus")
                
                markup.add(btn1, btn2)
                markup.add(btn3)
                
                if message.chat.type == 'private':
                    send_msg(message.chat.id, text, message.from_user.id, markup)
                else:
                    reply = self.bot.reply_to(message, text, reply_markup=markup, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{reply.message_id}", str(message.from_user.id))
                
            except Exception as e:
                logger.error(f"Menu error: {e}")
                if message.chat.type == 'private':
                    send_msg(message.chat.id, "⛓️‍💥* Ошибка!*", message.from_user.id)
                else:
                    self.bot.reply_to(message, "⛓️‍💥* Ошибка!*", parse_mode='Markdown')

        @self.bot.message_handler(commands=['gift'])
        def gift_cmd(message):
            if message.chat.type != 'private':
                self.bot.reply_to(message, "🙅‍♂️ *Только в личке!*", parse_mode='Markdown')
                return
                
            try:
                access, msg = check_access(message.from_user.id)
                if not access:
                    if msg:
                        send_msg(message.chat.id, msg, message.from_user.id)
                    return
                    
                if len(message.text.split()) < 2:
                    send_msg(message.chat.id, "🤷‍♂️ *Формат:* `/gift 1234Е`", message.from_user.id)
                    return
                
                target_id = message.text.split()[1].strip()
                
                target = self.users.find_one({"user_id": target_id})
                
                if not target:
                    send_msg(message.chat.id, "👻 *Не найден!*", message.from_user.id)
                    return
                
                if str(message.from_user.id) in self.users.find_one({"user_id": target_id}).get('telegram_id', ''):
                    send_msg(message.chat.id, "🐲 *Себе нельзя!*", message.from_user.id)
                    return
                
                user_str = str(message.from_user.id)
                self.set_temp("gift_data", {
                    "target_id": target_id,
                    "target_tg": target.get('telegram_id'),
                    "target_name": target.get('first_name', 'пользователь'),
                    "is_admin": self.is_test_user(message.from_user.username)
                }, user_str)
                
                chibis, page, total = self.get_gift_chibis(message.from_user.id, 1)
                
                if not chibis:
                    send_msg(message.chat.id, "🎁 *Нечего дарить!*", message.from_user.id)
                    return
                
                text = f"""✨ *Выбери чибика для подарка*"""
                
                markup = types.InlineKeyboardMarkup()
                
                for name, count in chibis:
                    markup.add(types.InlineKeyboardButton(name, callback_data=f"gift_pick_{name}"))
                
                markup.add(types.InlineKeyboardButton("💰 Коины", callback_data="gift_money"))
                
                nav = []
                if total > 1:
                    nav.append(types.InlineKeyboardButton("◀️", callback_data=f"gift_page_{((page-2) % total) + 1}"))
                
                nav.append(types.InlineKeyboardButton("Отмена", callback_data="gift_stop"))
                
                if total > 1:
                    nav.append(types.InlineKeyboardButton("▶️", callback_data=f"gift_page_{(page % total) + 1}"))
                
                markup.row(*nav)
                
                send_msg(message.chat.id, text, message.from_user.id, markup)
                
            except Exception as e:
                logger.error(f"Gift error: {e}")
                send_msg(message.chat.id, "⛓️‍💥* Ошибка!*", message.from_user.id)

        @self.bot.message_handler(func=lambda message: True, content_types=['text'])
        def text_msg(message):
            user_str = str(message.from_user.id)
            
            if self.get_temp("wait_coins", user_str):
                try:
                    amount = int(message.text)
                    
                    if amount < 1:
                        self.bot.reply_to(message, "❌ *Число > 0!*", parse_mode='Markdown')
                        return
                        
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user:
                        return
                        
                    if not self.is_test_user(user.get('username')):
                        if user.get('coins', 0) < amount:
                            self.bot.reply_to(message, f"❌ *Не хватает!* У тебя {user.get('coins', 0)}💰", parse_mode='Markdown')
                            return
                    
                    gift_data = self.get_temp("gift_data", user_str)
                    target_name = gift_data.get("target_name", "пользователь")
                    
                    text = f"""*✨ Дарим {amount} коинов?*
_Назад вернуть не получится_
_•••••••••••••••_
Кому: *{target_name}* 
Сколько: *{amount}*"""

                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("✅ Да", callback_data=f"gift_coin_ok_{amount}")
                    btn2 = types.InlineKeyboardButton("🙅‍♂️ Нет", callback_data="gift_stop")
                    markup.add(btn1, btn2)
                    
                    self.bot.reply_to(message, text, reply_markup=markup, parse_mode='Markdown')
                    self.del_temp("wait_coins", user_str)
                    
                except ValueError:
                    self.bot.reply_to(message, "❌ *Введи число!*", parse_mode='Markdown')

        @self.bot.callback_query_handler(func=lambda call: True)
        def callback(call):
            try:
                if not self.check_msg_owner(call):
                    return

                if call.data == "task_do":
                    user_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user or not user.get('current_task'):
                        self.bot.answer_callback_query(call.id, "🎯 Уже выполнено!")
                        return
                    
                    task = user['current_task']
                    
                    if task["chibi"] in user.get('chibis', []) or user.get('infinite_chibis'):
                        if not user.get('infinite_chibis'):
                            # Удаляем только ОДНОГО чибика
                            chibis = user.get('chibis', [])
                            if task["chibi"] in chibis:
                                index = chibis.index(task["chibi"])
                                new_chibis = chibis[:index] + chibis[index+1:]
                                self.users.update_one(
                                    {"telegram_id": user_str},
                                    {"$set": {"chibis": new_chibis}}
                                )
                    else:
                        self.bot.answer_callback_query(call.id, "🤷‍♂️ Нет чибика!")
                        return
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sticker = "CAACAgIAAxkBAAE9Js9pAzTWs9gLLtl9Gqz_9V_4sbwXqgAC7EYAAjNREEqhVSL_nxyHZTYE"
                    self.bot.send_sticker(call.message.chat.id, sticker)
                    
                    reward = task["reward"]
                    new_coins = user.get('coins', 0) + reward
                    self.users.update_one(
                        {"telegram_id": user_str},
                        {"$set": {
                            "coins": new_coins,
                            "current_task": None,
                            "last_task_time": datetime.now(),
                            "last_task_type": 'completed'
                        }}
                    )
                    
                    name = call.from_user.first_name or "путешественник"
                    text = f"""*Ес! {name}, ты выполнил таск!*
•••••••••••••••••••
+ 💰*{reward}* коинов"""
                    
                    send_msg(call.message.chat.id, text, call.from_user.id)
                    
                elif call.data == "task_no":
                    self.bot.answer_callback_query(call.id, "🤷‍♂️ Нет чибика!")
                    
                elif call.data == "task_skip":
                    user_str = str(call.from_user.id)
                    self.users.update_one(
                        {"telegram_id": user_str},
                        {"$set": {
                            "current_task": None,
                            "last_task_time": datetime.now(),
                            "last_task_type": 'skipped'
                        }}
                    )
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    text = """✨*Пропустил таск. Жди новый!*
Осталось 5ч 29м"""
                    
                    send_msg(call.message.chat.id, text, call.from_user.id)
                    
                elif call.data == "task_skip_ask":
                    user_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user or not user.get('current_task'):
                        self.bot.answer_callback_query(call.id, "🎯 Нет задания!")
                        return
                    
                    task = user['current_task']
                    
                    text = f"""{task['emoji']}* Точно пропустить?*
Пропуск бесплатный"""
                    
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
                    user_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user or not user.get('current_task'):
                        self.bot.answer_callback_query(call.id, "🎯 Нет задания!")
                        return
                    
                    task = user['current_task']
                    task_text, btn_text, has_chibi = self.get_task_text(task, call.from_user.id)
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn1 = types.InlineKeyboardButton(
                        btn_text, 
                        callback_data="task_do" if has_chibi else "task_no"
                    )
                    btn2 = types.InlineKeyboardButton("Пропустить", callback_data="task_skip_ask")
                    markup.add(btn1, btn2)
                    
                    self.bot.edit_message_text(
                        task_text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "menu_storage":
                    text = """*📦 Склад*
Выбери раздел"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn1 = types.InlineKeyboardButton("Чибики", callback_data="store_chibis_1")
                    btn2 = types.InlineKeyboardButton("Предметы", callback_data="store_items_1")
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
                    
                elif call.data.startswith("store_chibis_"):
                    page = int(call.data.split("_")[2])
                    chibis, curr, total = self.get_user_chibis_page(call.from_user.id, page)
                    
                    text = f"""📦 *Твои чибики*
Страница {curr}/{total}"""
                    
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
                        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"store_chibis_{((curr-2) % total) + 1}"))
                    
                    nav.append(types.InlineKeyboardButton("Назад", callback_data="menu_storage"))
                    
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"store_chibis_{(curr % total) + 1}"))
                    
                    markup.row(*nav)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("store_items_"):
                    page = int(call.data.split("_")[2])
                    items, curr, total = self.get_user_items_page(call.from_user.id, page)
                    
                    text = f"""*📦 Твои предметы*
Страница {curr}/{total}"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if items:
                        for name, count in items:
                            if count > 1:
                                btn_text = f"{name} ({count})"
                            else:
                                btn_text = name
                            if name == "🧧 Чиби-пак":
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="open_pack"))
                            else:
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="item_click"))
                    else:
                        markup.add(types.InlineKeyboardButton("Пусто", callback_data="empty"))
                    
                    nav = []
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"store_items_{((curr-2) % total) + 1}"))
                    
                    nav.append(types.InlineKeyboardButton("Назад", callback_data="menu_storage"))
                    
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"store_items_{(curr % total) + 1}"))
                    
                    markup.row(*nav)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "open_pack":
                    user_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user:
                        return
                        
                    count = user.get('items', {}).get("🧧 Чиби-пак", 0)
                    
                    text = f"""*Открыть 🧧 Чиби-пак?*"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    
                    if count == 1:
                        btn1 = types.InlineKeyboardButton("Открыть х1", callback_data="open_1")
                        markup.add(btn1)
                    else:
                        btn1 = types.InlineKeyboardButton("Открыть х1", callback_data="open_1")
                        btn2 = types.InlineKeyboardButton(f"Открыть х{count}", callback_data=f"open_{count}")
                        markup.add(btn1, btn2)
                    
                    btn3 = types.InlineKeyboardButton("Назад", callback_data="store_items_1")
                    markup.add(btn3)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data.startswith("open_"):
                    count = int(call.data.split("_")[1])
                    user_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user:
                        return
                    
                    current = user.get('items', {}).get("🧧 Чиби-пак", 0)
                    if current < count:
                        self.bot.answer_callback_query(call.id, "🎒 *Не хватает паков!*")
                        return
                    
                    new_count = current - count
                    self.users.update_one(
                        {"telegram_id": user_str},
                        {"$set": {"items.🧧 Чиби-пак": new_count}}
                    )
                    
                    for i in range(count):
                        file_path, chibi_name, rarity = self.get_random_chibi(from_pack=True)
                        
                        if file_path is not None:
                            self.add_chibi(call.from_user.id, chibi_name)
                            chibi_count = self.get_chibi_count(call.from_user.id, chibi_name)
                            
                            emoji = "🔷" if rarity == "Common" else "🔶"
                            if rarity == "Prize":
                                emoji = "♦️"
                            
                            text = f"""*Тебе выпал — {chibi_name}!*
•••••••••••••••••••
Редкость: {emoji} {rarity}
У тебя: {chibi_count}"""
                            
                            self.send_chibi_img(
                                call.message.chat.id,
                                file_path,
                                text,
                                user_str
                            )
                    
                    self.bot.answer_callback_query(call.id, f"🎉 Открыто {count} паков!")
                    
                    items, curr, total = self.get_user_items_page(call.from_user.id, 1)
                    
                    text = f"""*📦 Твои предметы*
Страница {curr}/{total}"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if items:
                        for name, count in items:
                            if count > 1:
                                btn_text = f"{name} ({count})"
                            else:
                                btn_text = name
                            if name == "🧧 Чиби-пак":
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="open_pack"))
                            else:
                                markup.add(types.InlineKeyboardButton(btn_text, callback_data="item_click"))
                    else:
                        markup.add(types.InlineKeyboardButton("Пусто", callback_data="empty"))
                    
                    nav = []
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"store_items_{((curr-2) % total) + 1}"))
                    
                    nav.append(types.InlineKeyboardButton("Назад", callback_data="menu_storage"))
                    
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"store_items_{(curr % total) + 1}"))
                    
                    markup.row(*nav)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "mart_pack":
                    text = """🎏 *Хочешь купить Чиби-пак?*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("Купить (120)", callback_data="buy_pack")
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
                    
                elif call.data == "buy_pack":
                    user_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user:
                        return
                    
                    coins = user.get('coins', 0)
                    
                    if coins < 120:
                        need = 120 - coins
                        self.bot.answer_callback_query(call.id, f"✨ Не хватает {need} коинов")
                        return
                    
                    new_coins = coins - 120
                    items = user.get('items', {})
                    if "🧧 Чиби-пак" not in items:
                        items["🧧 Чиби-пак"] = 0
                    items["🧧 Чиби-пак"] += 1
                    
                    self.users.update_one(
                        {"telegram_id": user_str},
                        {"$set": {
                            "coins": new_coins,
                            "items": items
                        }}
                    )
                    
                    self.bot.answer_callback_query(call.id, "🎉 Куплен!")
                    
                    text = """🎏 *Лавка джавы*
Джавы знают толк в ценах!"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_pack")
                    markup.add(btn)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "mart_back":
                    text = """🎏 *Лавка джавы*
Джавы знают толк в ценах!"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton("🧧 Чиби-пак", callback_data="mart_pack")
                    markup.add(btn)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "menu_bonus":
                    user_str = str(call.from_user.id)
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user:
                        return
                    
                    bonus_cd = self.check_bonus_cd(call.from_user.id)
                    if bonus_cd and not self.is_test_user(user.get('username')):
                        time_left = self.format_time(int(bonus_cd))
                        self.bot.answer_callback_query(call.id, f"🔒 Через {time_left}")
                        return
                    
                    bonus = random.randint(7, 19)
                    
                    new_coins = user.get('coins', 0) + bonus
                    self.users.update_one(
                        {"telegram_id": user_str},
                        {"$set": {
                            "coins": new_coins,
                            "last_bonus_time": datetime.now()
                        }}
                    )
                    
                    name = user.get('first_name', 'путешественник')
                    text = f"""🎁 *Эй, {name}!*
Ты получил бонус! 
•••••••••••••••••
+ 💰*{bonus}* коинов"""
                    
                    send_msg(call.message.chat.id, text, call.from_user.id)
                    
                elif call.data == "bonus_wait":
                    user_str = str(call.from_user.id)
                    bonus_cd = self.check_bonus_cd(call.from_user.id)
                    if bonus_cd:
                        time_left = self.format_time(int(bonus_cd))
                        self.bot.answer_callback_query(call.id, f"🔒 Через {time_left}")
                    
                elif call.data == "menu_back":
                    text = """*✨ Меню* 
Здесь все что нужно"""
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    btn1 = types.InlineKeyboardButton("📦 Склад", callback_data="menu_storage")
                    btn2 = types.InlineKeyboardButton("Наш тгк", url=BOT_CONFIG['telegram_channel'])
                    
                    bonus_cd = self.check_bonus_cd(call.from_user.id)
                    user = self.users.find_one({"telegram_id": str(call.from_user.id)})
                    if bonus_cd and not self.is_test_user(user.get('username') if user else None):
                        time_left = self.format_time(int(bonus_cd))
                        btn3 = types.InlineKeyboardButton(f"🔒 Через {time_left}", callback_data="bonus_wait")
                    else:
                        btn3 = types.InlineKeyboardButton("🎁 Бонус", callback_data="menu_bonus")
                    
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
                    user_str = str(call.from_user.id)
                    
                    if not self.get_temp("gift_data", user_str):
                        self.bot.answer_callback_query(call.id, "⏰ Устарело...")
                        return
                    
                    chibis, curr, total = self.get_gift_chibis(call.from_user.id, page)
                    
                    text = f"""✨ *Выбери чибика для подарка*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    for name, count in chibis:
                        markup.add(types.InlineKeyboardButton(name, callback_data=f"gift_pick_{name}"))
                    
                    markup.add(types.InlineKeyboardButton("💰 Коины", callback_data="gift_money"))
                    
                    nav = []
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("◀️", callback_data=f"gift_page_{((curr-2) % total) + 1}"))
                    
                    nav.append(types.InlineKeyboardButton("Отмена", callback_data="gift_stop"))
                    
                    if total > 1:
                        nav.append(types.InlineKeyboardButton("▶️", callback_data=f"gift_page_{(curr % total) + 1}"))
                    
                    markup.row(*nav)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "gift_money":
                    user_str = str(call.from_user.id)
                    
                    if not self.get_temp("gift_data", user_str):
                        self.bot.answer_callback_query(call.id, "⏰ Устарело...")
                        return
                    
                    text = """*✨ Введи число коинов*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton("Отмена", callback_data="gift_stop")
                    markup.add(btn)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                    self.set_temp("wait_coins", True, user_str)
                    
                elif call.data.startswith("gift_coin_ok_"):
                    amount = int(call.data.split("_")[3])
                    user_str = str(call.from_user.id)
                    
                    gift_data = self.get_temp("gift_data", user_str)
                    if not gift_data:
                        self.bot.answer_callback_query(call.id, "⏰ Устарело...")
                        return
                    
                    target_tg = gift_data["target_tg"]
                    target_name = gift_data["target_name"]
                    is_admin = gift_data["is_admin"]
                    
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user:
                        self.bot.answer_callback_query(call.id, "❌ *Ошибка!*")
                        return

                    if not is_admin:
                        if user.get('coins', 0) < amount:
                            self.bot.answer_callback_query(call.id, "❌ *Не хватает!*")
                            return

                        new_coins = user.get('coins', 0) - amount
                        self.users.update_one(
                            {"telegram_id": user_str},
                            {"$set": {"coins": new_coins}}
                        )
                    
                    target = self.users.find_one({"telegram_id": target_tg})
                    if target:
                        target_coins = target.get('coins', 0) + amount
                        self.users.update_one(
                            {"telegram_id": target_tg},
                            {"$set": {"coins": target_coins}}
                        )
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sender_name = call.from_user.first_name or "Отправитель"
                    text = f"""*✨ Коины отправлены! 
Надеюсь, {target_name} они пригодятся!*"""

                    send_msg(call.message.chat.id, text, call.from_user.id)

                    target_text = f"""*💌 Тебе подарок!*
{sender_name} подарил тебе {amount} коинов!"""

                    send_msg(target_tg, target_text, target_tg)

                    self.del_temp("gift_data", user_str)
                    
                elif call.data.startswith("gift_pick_"):
                    chibi_name = call.data.replace("gift_pick_", "")
                    user_str = str(call.from_user.id)
                    
                    gift_data = self.get_temp("gift_data", user_str)
                    if not gift_data:
                        self.bot.answer_callback_query(call.id, "⏰ Устарело...")
                        return
                    
                    gift_data["chibi_name"] = chibi_name
                    self.set_temp("gift_data", gift_data, user_str)
                    
                    target_name = gift_data["target_name"]
                    
                    text = f"""✨ *Дарим чибика?*
Назад вернуть не получится
•••••••••••••••
Кому: *{target_name}*
Кого: *{chibi_name}*"""
                    
                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("✅ Да", callback_data="gift_ok")
                    btn2 = types.InlineKeyboardButton("🙅‍♂️ Нет", callback_data="gift_stop")
                    markup.add(btn1, btn2)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                elif call.data == "gift_ok":
                    user_str = str(call.from_user.id)
                    
                    gift_data = self.get_temp("gift_data", user_str)
                    if not gift_data:
                        self.bot.answer_callback_query(call.id, "⏰ Устарело...")
                        return
                    
                    chibi_name = gift_data["chibi_name"]
                    target_tg = gift_data["target_tg"]
                    target_name = gift_data["target_name"]
                    is_admin = gift_data["is_admin"]
                    
                    user = self.users.find_one({"telegram_id": user_str})
                    if not user or (chibi_name not in user.get('chibis', []) and not user.get('infinite_chibis')):
                        self.bot.answer_callback_query(call.id, "🎒 Нет чибика! :(")
                        return
                    
                    if not is_admin and not user.get('infinite_chibis'):
                        # Удаляем только ОДНОГО чибика
                        chibis = user.get('chibis', [])
                        if chibi_name in chibis:
                            index = chibis.index(chibi_name)
                            new_chibis = chibis[:index] + chibis[index+1:]
                            self.users.update_one(
                                {"telegram_id": user_str},
                                {"$set": {"chibis": new_chibis}}
                            )
                    
                    target = self.users.find_one({"telegram_id": target_tg})
                    if target:
                        target_chibis = target.get('chibis', [])
                        target_chibis.append(chibi_name)  # Добавляем одного чибика
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
                            text = f"""*🍀 Эй, {target_name}!* 
_Ты выиграл в розыгрыше!_
♦️*{chibi_name}!* 
_Спасибо за участие!_"""
                            
                            self.send_chibi_img(
                                target_tg,
                                file_path,
                                text,
                                target_tg
                            )
                            
                            sender_text = f"""*✨ Приз отправлен!*
{target_name} получил {chibi_name}!"""
                            
                            send_msg(call.message.chat.id, sender_text, call.from_user.id)
                            
                    else:
                        sticker = "CAACAgIAAxkBAAE9JtFpAzTjbRJ884hA4YNjTqPc7Z05lAACQEgAAlZVEUqWc8vDGvLqWTYE"
                        self.bot.send_sticker(call.message.chat.id, sticker)
                        
                        sender_name = call.from_user.first_name or "Отправитель"
                        text = f"""*✨ Чибик отправлен! 
Надеюсь, {target_name} он понравится!*"""
                        
                        send_msg(call.message.chat.id, text, call.from_user.id)
                        
                        sticker = "CAACAgIAAxkBAAE9OxxpBRLZ5OANTuRD-97sRPdCONwv0AACU0YAAkVlEErI0vjxKMrHnTYE"
                        self.bot.send_sticker(target_tg, sticker)
                        
                        target_text = f"""*💌 Тебе подарок!*
{sender_name} подарил тебе {chibi_name}!"""
                        
                        markup = types.InlineKeyboardMarkup()
                        btn = types.InlineKeyboardButton("Посмотреть", callback_data="store_chibis_1")
                        markup.add(btn)
                        
                        send_msg(target_tg, target_text, target_tg, markup)
                    
                    self.del_temp("gift_data", user_str)
                    
                elif call.data == "gift_stop":
                    user_str = str(call.from_user.id)
                    
                    self.del_temp("gift_data", user_str)
                    self.del_temp("wait_coins", user_str)
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                elif call.data == "chibi_click":
                    self.bot.answer_callback_query(call.id)
                    
                elif call.data == "item_click":
                    self.bot.answer_callback_query(call.id, "Не используется")
                    
                elif call.data == "empty":
                    self.bot.answer_callback_query(call.id, "Пусто!")
                    
                else:
                    self.bot.answer_callback_query(call.id)
                    
            except Exception as e:
                logger.error(f"Callback error: {e}")
                self.bot.answer_callback_query(call.id, "Ошибка!", parse_mode='Markdown')

    def run(self):
        logger.info("Бот запущен!")
        self.setup_handlers()
        
        if "RENDER" in os.environ:
            self.setup_flask()
            PORT = int(os.environ.get('PORT', 5000))
            
            def run_flask():
                self.app.run(host='0.0.0.0', port=PORT)
            
            thread = threading.Thread(target=run_flask)
            thread.daemon = True
            thread.start()
            logger.info(f"Flask держится на порту {PORT}")
        
        self.cleanup()
        
        self.bot.infinity_polling()

    def cleanup(self):
        def clean():
            while True:
                try:
                    two_min_ago = time.time() - 120
                    for user_id in list(self.user_reqs.keys()):
                        self.user_reqs[user_id] = [t for t in self.user_reqs[user_id] if t > two_min_ago]
                        if not self.user_reqs[user_id]:
                            del self.user_reqs[user_id]
                    
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
                    time.sleep(60)
        
        thread = threading.Thread(target=clean)
        thread.daemon = True
        thread.start()

def get_token():
    return os.getenv('BOT_TOKEN')

if __name__ == "__main__":
    token = get_token()
    if not token:
        print("Где, блять, токен? ")
        exit(1)
    
    bot = ChibiBot(token)
    bot.run()
