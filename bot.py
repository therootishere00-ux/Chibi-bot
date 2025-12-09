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
            self.market.create_index("seller_id")
            self.market.create_index("chibi_name")
            self.market.create_index("created_at")
            logger.info("✅ Успешное подключение к MongoDB")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к MongoDB: {e}")
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
                logger.info(f"✅ Админ {username} инициализирован")

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
        if from_pack and random.random() <= 0.05:
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
            {"telegram_id": telegram_id_str},
            {"$set": {"current_task": task_data}}
        )
        
        return task_data

    def task_text(self, task_data, telegram_id):
        telegram_id_str = str(telegram_id)
        has_chibi = self.chibi_count(telegram_id, task_data["chibi"]) > 0
        btn_text = "✅ Сдать задание (1/1)" if has_chibi else "Сдать задание (0/1)"
        
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
                    f"🌀 *Чибик временно недоступен!*\n{caption}",
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
                f"🌀 *Не удалось отправить чибика!*\n{caption}",
                parse_mode='Markdown'
            )
            self.set_temp(f"msg_owner_{chat_id}_{sent.message_id}", telegram_id_str)
            return sent

    # Методы для рынка
    def get_market_lots(self, page=1, per_page=8):
        total_lots = self.market.count_documents({})
        total_pages = max(1, (total_lots + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        
        skip = (page - 1) * per_page
        lots = list(self.market.find().sort("created_at", -1).skip(skip).limit(per_page))
        
        return lots, page, total_pages, total_lots

    def get_user_market_chibis(self, telegram_id, page=1, per_page=6):
        telegram_id_str = str(telegram_id)
        user = self.users.find_one({"telegram_id": telegram_id_str})
        if not user:
            return [], 1, 1
        
        user_chibis = user.get('chibis', [])
        counts = {}
        for chibi in user_chibis:
            counts[chibi] = counts.get(chibi, 0) + 1
        
        market_chibis = []
        for chibi_name, count in counts.items():
            existing_lot = self.market.find_one({
                "seller_id": telegram_id_str,
                "chibi_name": chibi_name
            })
            if not existing_lot:
                market_chibis.append((chibi_name, count))
        
        return self.get_page(market_chibis, page, per_page)

    def create_market_lot(self, seller_id, chibi_name, price):
        seller_id_str = str(seller_id)
        
        user = self.users.find_one({"telegram_id": seller_id_str})
        if not user:
            return False
        
        if user.get('infinite_chibis'):
            return True
        
        existing_lot = self.market.find_one({
            "seller_id": seller_id_str,
            "chibi_name": chibi_name
        })
        
        if existing_lot:
            return False
        
        chibis = user.get('chibis', [])
        if chibi_name not in chibis:
            return False
        
        new_chibis = chibis.copy()
        new_chibis.remove(chibi_name)
        
        self.users.update_one(
            {"telegram_id": seller_id_str},
            {"$set": {"chibis": new_chibis}}
        )
        
        lot_data = {
            "seller_id": seller_id_str,
            "seller_name": user.get('first_name', 'Игрок'),
            "chibi_name": chibi_name,
            "price": price,
            "created_at": datetime.now()
        }
        
        self.market.insert_one(lot_data)
        return True

    def buy_market_lot(self, buyer_id, lot_id):
        buyer_id_str = str(buyer_id)
        
        lot = self.market.find_one({"_id": lot_id})
        if not lot:
            return False, "Лот не найден"
        
        if lot["seller_id"] == buyer_id_str:
            return False, "own_lot"
        
        buyer = self.users.find_one({"telegram_id": buyer_id_str})
        if not buyer:
            return False, "Покупатель не найден"
        
        if buyer.get('coins', 0) < lot["price"]:
            return False, "not_enough_coins"
        
        seller = self.users.find_one({"telegram_id": lot["seller_id"]})
        if not seller:
            return False, "Продавец не найден"
        
        buyer_coins = buyer.get('coins', 0) - lot["price"]
        seller_coins = seller.get('coins', 0) + lot["price"]
        
        buyer_chibis = buyer.get('chibis', [])
        buyer_chibis.append(lot["chibi_name"])
        
        self.users.update_one(
            {"telegram_id": buyer_id_str},
            {"$set": {"coins": buyer_coins, "chibis": buyer_chibis}}
        )
        
        self.users.update_one(
            {"telegram_id": lot["seller_id"]},
            {"$set": {"coins": seller_coins}}
        )
        
        self.market.delete_one({"_id": lot_id})
        
        return True, {
            "buyer_name": buyer.get('first_name', 'Игрок'),
            "seller_name": lot["seller_name"],
            "chibi_name": lot["chibi_name"],
            "price": lot["price"]
        }

    def remove_market_lot(self, seller_id, lot_id):
        seller_id_str = str(seller_id)
        
        lot = self.market.find_one({"_id": lot_id})
        if not lot:
            return False
        
        if lot["seller_id"] != seller_id_str:
            return False
        
        user = self.users.find_one({"telegram_id": seller_id_str})
        if user and not user.get('infinite_chibis'):
            user_chibis = user.get('chibis', [])
            user_chibis.append(lot["chibi_name"])
            
            self.users.update_one(
                {"telegram_id": seller_id_str},
                {"$set": {"chibis": user_chibis}}
            )
        
        self.market.delete_one({"_id": lot_id})
        return True

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
                    btn = types.InlineKeyboardButton('📢 Наш тгк', url=BOT_CONFIG['telegram_channel'])
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
                self.bot.reply_to(message, "🎲 *Игра доступна только в личке!*", parse_mode='Markdown')
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
                    error = """🎲 *Неправильный формат!*
_Попробуй: /dice 100_"""
                    sent = self.bot.send_message(message.chat.id, error, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return

                try:
                    bet = int(parts[1])
                except ValueError:
                    error = """🎲 *Неправильный формат!*
_Попробуй: /dice 100_"""
                    sent = self.bot.send_message(message.chat.id, error, parse_mode='Markdown')
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", str(message.from_user.id))
                    return

                if bet < 1:
                    self.bot.reply_to(message, "💀 *Ставка должна быть больше 0!*", parse_mode='Markdown')
                    return

                if bet > 10000:
                    self.bot.reply_to(message, "💀 *Максимальная ставка - 10,000 коинов!*", parse_mode='Markdown')
                    return

                telegram_id_str = str(message.from_user.id)
                user = self.users.find_one({"telegram_id": telegram_id_str})
                if not user:
                    self.send_start_sug(message.chat.id)
                    return

                coins = user.get('coins', 0)
                if coins < bet:
                    self.bot.reply_to(message, f"🤷‍♂️ *Недостаточно коинов!* У тебя {coins}💰", parse_mode='Markdown')
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

                    win_text = f"""*👽 Черт! {message.from_user.first_name}, тебя сегодня повезло… Забирай свой выигрыш!*
_Поздравляю, ты обыграл дилера!_
_•••••••••••••••_
+ 💰*{win}* коинов
Всего: *{total}* коинов"""

                    self.bot.send_message(message.chat.id, win_text, parse_mode='Markdown')
                else:
                    lose_text = f"""*👽 Ха-ха! {message.from_user.first_name}, кажется ты слил!*
_Ты проиграл, все честно. Ставку уже не вернуть_
_•••••••••••••••_
- 💰*{bet}* коинов
Осталось: *{coins - bet}* коинов"""

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
                
                lots, page, total_pages, total_lots = self.get_market_lots(1)
                
                text = BOT_TEXTS['market_welcome'].format(total_lots=total_lots)
                
                markup = types.InlineKeyboardMarkup()
                
                if total_lots == 0:
                    markup.add(types.InlineKeyboardButton(BOT_TEXTS['market_empty'], callback_data="market_empty"))
                else:
                    for lot in lots:
                        btn_text = f"{lot['chibi_name']} - 💰{lot['price']}"
                        if lot['seller_id'] == str(message.from_user.id):
                            btn_text = f"🔥 {btn_text}"
                        markup.add(types.InlineKeyboardButton(
                            btn_text,
                            callback_data=f"market_lot_{lot['_id']}"
                        ))
                
                markup.add(types.InlineKeyboardButton("✨ Создать лот", callback_data="market_create_1"))
                
                if total_pages > 1:
                    nav_buttons = []
                    if page > 1:
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"market_page_{page-1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="market_current"))
                    
                    if page < total_pages:
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"market_page_{page+1}"))
                    
                    markup.row(*nav_buttons)
                
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

        @self.bot.message_handler(func=lambda message: True, content_types=['text'])
        def text_msg(message):
            telegram_id_str = str(message.from_user.id)
            
            waiting_price = self.get_temp("waiting_price", telegram_id_str)
            if waiting_price:
                try:
                    chibi_name = waiting_price
                    price = int(message.text)
                    
                    if price < BOT_CONFIG['min_market_price']:
                        self.bot.reply_to(message, BOT_TEXTS['market_price_too_low'], parse_mode='Markdown')
                        return
                    
                    if price > BOT_CONFIG['max_market_price']:
                        self.bot.reply_to(message, BOT_TEXTS['market_price_too_high'], parse_mode='Markdown')
                        return
                    
                    self.bot.delete_message(message.chat.id, message.message_id)
                    
                    msg_to_delete = self.get_temp("price_msg_id", telegram_id_str)
                    if msg_to_delete:
                        try:
                            self.bot.delete_message(message.chat.id, msg_to_delete)
                        except:
                            pass
                    
                    text = BOT_TEXTS['market_create_confirm'].format(chibi_name=chibi_name, price=price)
                    
                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("✅ Выставить", callback_data=f"market_confirm_{chibi_name}_{price}")
                    btn2 = types.InlineKeyboardButton("🙅‍♂️ Отмена", callback_data="market_cancel_create")
                    markup.add(btn1, btn2)
                    
                    sent = self.bot.send_message(
                        message.chat.id,
                        text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{message.chat.id}_{sent.message_id}", telegram_id_str)
                    
                    self.del_temp("waiting_price", telegram_id_str)
                    self.del_temp("price_msg_id", telegram_id_str)
                    
                except ValueError:
                    self.bot.reply_to(message, "❌ *Введи число!*", parse_mode='Markdown')
            
            waiting_coins = self.get_temp("waiting_coins", telegram_id_str)
            if waiting_coins:
                try:
                    amount = int(message.text)
                    
                    if amount < 1:
                        self.bot.reply_to(message, "❌ *Число должно быть положительным!*", parse_mode='Markdown')
                        return
                        
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user:
                        return
                        
                    if not self.is_test(user.get('username')):
                        if user.get('coins', 0) < amount:
                            self.bot.reply_to(message, f"❌ *Недостаточно коинов!* У тебя {user.get('coins', 0)}💰", parse_mode='Markdown')
                            return
                    
                    gift_data = self.get_temp("gift_data", telegram_id_str)
                    target_name = gift_data.get("target_name", "пользователь")
                    
                    text = f"""*✨ Дарим {amount} коинов?*
_Ты уверен, что хочешь этого? Назад вернуть уже не получится_
_•••••••••••••••_
Кому: *{target_name}* 
Сколько: *{amount}*"""

                    markup = types.InlineKeyboardMarkup()
                    btn1 = types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"gift_confirm_coins_{amount}")
                    btn2 = types.InlineKeyboardButton("🙅‍♂️ Отмена", callback_data="gift_cancel")
                    markup.add(btn1, btn2)
                    
                    self.bot.reply_to(message, text, reply_markup=markup, parse_mode='Markdown')
                    self.del_temp("waiting_coins", telegram_id_str)
                    
                except ValueError:
                    self.bot.reply_to(message, "❌ *Введи число!*", parse_mode='Markdown')

        @self.bot.callback_query_handler(func=lambda call: True)
        def callback(call):
            try:
                if not self.check_msg_owner(call):
                    return

                telegram_id_str = str(call.from_user.id)
                
                if call.data == "task_complete":
                    user = self.users.find_one({"telegram_id": telegram_id_str})
                    if not user or not user.get('current_task'):
                        self.bot.answer_callback_query(call.id, "🎯 Задание уже выполнено!")
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
                        self.bot.answer_callback_query(call.id, "🤷‍♂️ И что ты собрался сдавать?")
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
                    text = f"""*Ес! {name}, ты выполнил таск!*
За это ты получаешь обещанную награду. Даже не буду гадать, сколько ты выбивал нужного чибика
•••••••••••••••••••
+ 💰*{reward}* коинов"""
                    
                    sent = self.bot.send_message(
                        call.message.chat.id,
                        text,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                    
                elif call.data == "market_page_1":
                    lots, page, total_pages, total_lots = self.get_market_lots(1)
                    
                    text = BOT_TEXTS['market_welcome'].format(total_lots=total_lots)
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if total_lots == 0:
                        markup.add(types.InlineKeyboardButton(BOT_TEXTS['market_empty'], callback_data="market_empty"))
                    else:
                        for lot in lots:
                            btn_text = f"{lot['chibi_name']} - 💰{lot['price']}"
                            if lot['seller_id'] == telegram_id_str:
                                btn_text = f"🔥 {btn_text}"
                            markup.add(types.InlineKeyboardButton(
                                btn_text,
                                callback_data=f"market_lot_{lot['_id']}"
                            ))
                    
                    markup.add(types.InlineKeyboardButton("✨ Создать лот", callback_data="market_create_1"))
                    
                    if total_pages > 1:
                        nav_buttons = []
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"market_page_{page-1}"))
                        nav_buttons.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="market_current"))
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"market_page_{page+1}"))
                        markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                
                elif call.data.startswith("market_page_"):
                    page = int(call.data.split("_")[2])
                    lots, cur_page, total_pages, total_lots = self.get_market_lots(page)
                    
                    text = BOT_TEXTS['market_welcome'].format(total_lots=total_lots)
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if total_lots == 0:
                        markup.add(types.InlineKeyboardButton(BOT_TEXTS['market_empty'], callback_data="market_empty"))
                    else:
                        for lot in lots:
                            btn_text = f"{lot['chibi_name']} - 💰{lot['price']}"
                            if lot['seller_id'] == telegram_id_str:
                                btn_text = f"🔥 {btn_text}"
                            markup.add(types.InlineKeyboardButton(
                                btn_text,
                                callback_data=f"market_lot_{lot['_id']}"
                            ))
                    
                    markup.add(types.InlineKeyboardButton("✨ Создать лот", callback_data="market_create_1"))
                    
                    if total_pages > 1:
                        nav_buttons = []
                        if cur_page > 1:
                            nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"market_page_{cur_page-1}"))
                        
                        nav_buttons.append(types.InlineKeyboardButton(f"{cur_page}/{total_pages}", callback_data="market_current"))
                        
                        if cur_page < total_pages:
                            nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"market_page_{cur_page+1}"))
                        
                        markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                
                elif call.data.startswith("market_lot_"):
                    from bson.objectid import ObjectId
                    lot_id = ObjectId(call.data.split("_")[2])
                    
                    lot = self.market.find_one({"_id": lot_id})
                    if not lot:
                        self.bot.answer_callback_query(call.id, "❌ Лот не найден!")
                        return
                    
                    text = BOT_TEXTS['market_lot_view'].format(
                        seller_name=lot['seller_name'],
                        chibi_name=lot['chibi_name'],
                        price=lot['price']
                    )
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if lot['seller_id'] == telegram_id_str:
                        btn1 = types.InlineKeyboardButton("🗑️ Убрать лот", callback_data=f"market_remove_{lot_id}")
                    else:
                        btn1 = types.InlineKeyboardButton(f"Купить (💰{lot['price']})", callback_data=f"market_buy_{lot_id}")
                    
                    btn2 = types.InlineKeyboardButton("Назад", callback_data="market_back")
                    
                    markup.add(btn1)
                    markup.add(btn2)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                
                elif call.data.startswith("market_buy_"):
                    from bson.objectid import ObjectId
                    lot_id = ObjectId(call.data.split("_")[2])
                    
                    success, result = self.buy_market_lot(call.from_user.id, lot_id)
                    
                    if not success:
                        if result == "own_lot":
                            self.bot.answer_callback_query(call.id, BOT_TEXTS['market_own_lot'], parse_mode='Markdown')
                        elif result == "not_enough_coins":
                            self.bot.answer_callback_query(call.id, BOT_TEXTS['market_not_enough_coins'], parse_mode='Markdown')
                        else:
                            self.bot.answer_callback_query(call.id, "❌ Ошибка покупки!")
                        return
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    text = BOT_TEXTS['market_buy_success'].format(
                        buyer_name=result['buyer_name'],
                        chibi_name=result['chibi_name'],
                        seller_name=result['seller_name'],
                        price=result['price']
                    )
                    
                    sent = self.bot.send_message(
                        call.message.chat.id,
                        text,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                
                elif call.data.startswith("market_remove_"):
                    from bson.objectid import ObjectId
                    lot_id = ObjectId(call.data.split("_")[2])
                    
                    success = self.remove_market_lot(call.from_user.id, lot_id)
                    
                    if not success:
                        self.bot.answer_callback_query(call.id, "❌ Нельзя убрать чужой лот!")
                        return
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    sent = self.bot.send_message(
                        call.message.chat.id,
                        BOT_TEXTS['market_lot_removed'],
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                
                elif call.data == "market_back":
                    lots, page, total_pages, total_lots = self.get_market_lots(1)
                    
                    text = BOT_TEXTS['market_welcome'].format(total_lots=total_lots)
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if total_lots == 0:
                        markup.add(types.InlineKeyboardButton(BOT_TEXTS['market_empty'], callback_data="market_empty"))
                    else:
                        for lot in lots:
                            btn_text = f"{lot['chibi_name']} - 💰{lot['price']}"
                            if lot['seller_id'] == telegram_id_str:
                                btn_text = f"🔥 {btn_text}"
                            markup.add(types.InlineKeyboardButton(
                                btn_text,
                                callback_data=f"market_lot_{lot['_id']}"
                            ))
                    
                    markup.add(types.InlineKeyboardButton("✨ Создать лот", callback_data="market_create_1"))
                    
                    if total_pages > 1:
                        nav_buttons = []
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"market_page_{page-1}"))
                        nav_buttons.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="market_current"))
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"market_page_{page+1}"))
                        markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                
                elif call.data.startswith("market_create_"):
                    page = int(call.data.split("_")[2]) if len(call.data.split("_")) > 2 else 1
                    
                    chibis, cur_page, total_pages = self.get_user_market_chibis(call.from_user.id, page, BOT_CONFIG['market_create_per_page'])
                    
                    text = BOT_TEXTS['market_create_select']
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if not chibis:
                        markup.add(types.InlineKeyboardButton(BOT_TEXTS['market_create_empty'], callback_data="market_empty"))
                    else:
                        for chibi_name, count in chibis:
                            markup.add(types.InlineKeyboardButton(
                                f"{chibi_name} ({count})",
                                callback_data=f"market_select_{chibi_name}"
                            ))
                    
                    nav_buttons = []
                    if total_pages > 1:
                        if cur_page > 1:
                            nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"market_create_{cur_page-1}"))
                        
                        nav_buttons.append(types.InlineKeyboardButton(f"{cur_page}/{total_pages}", callback_data="market_current"))
                        
                        if cur_page < total_pages:
                            nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"market_create_{cur_page+1}"))
                    
                    nav_buttons.append(types.InlineKeyboardButton("Назад", callback_data="market_back"))
                    markup.row(*nav_buttons)
                    
                    self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                
                elif call.data.startswith("market_select_"):
                    chibi_name = call.data.replace("market_select_", "")
                    
                    text = BOT_TEXTS['market_create_set_price'].format(chibi_name=chibi_name)
                    
                    markup = types.InlineKeyboardMarkup()
                    btn = types.InlineKeyboardButton("Назад", callback_data="market_create_1")
                    markup.add(btn)
                    
                    sent = self.bot.edit_message_text(
                        text,
                        call.message.chat.id,
                        call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    
                    self.set_temp("waiting_price", chibi_name, call.from_user.id)
                    self.set_temp("price_msg_id", sent.message_id, call.from_user.id)
                
                elif call.data.startswith("market_confirm_"):
                    parts = call.data.split("_")
                    chibi_name = parts[2]
                    price = int(parts[3])
                    
                    success = self.create_market_lot(call.from_user.id, chibi_name, price)
                    
                    if not success:
                        self.bot.answer_callback_query(call.id, BOT_TEXTS['market_already_listed'], parse_mode='Markdown')
                        return
                    
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    lots, page, total_pages, total_lots = self.get_market_lots(1)
                    
                    text = BOT_TEXTS['market_welcome'].format(total_lots=total_lots)
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if total_lots == 0:
                        markup.add(types.InlineKeyboardButton(BOT_TEXTS['market_empty'], callback_data="market_empty"))
                    else:
                        for lot in lots:
                            btn_text = f"{lot['chibi_name']} - 💰{lot['price']}"
                            if lot['seller_id'] == telegram_id_str:
                                btn_text = f"🔥 {btn_text}"
                            markup.add(types.InlineKeyboardButton(
                                btn_text,
                                callback_data=f"market_lot_{lot['_id']}"
                            ))
                    
                    markup.add(types.InlineKeyboardButton("✨ Создать лот", callback_data="market_create_1"))
                    
                    if total_pages > 1:
                        nav_buttons = []
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"market_page_{page-1}"))
                        nav_buttons.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="market_current"))
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"market_page_{page+1}"))
                        markup.row(*nav_buttons)
                    
                    sent = self.bot.send_message(
                        call.message.chat.id,
                        text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                    
                    self.bot.answer_callback_query(call.id, BOT_TEXTS['market_lot_created'])
                
                elif call.data == "market_cancel_create":
                    self.bot.delete_message(call.message.chat.id, call.message.message_id)
                    
                    lots, page, total_pages, total_lots = self.get_market_lots(1)
                    
                    text = BOT_TEXTS['market_welcome'].format(total_lots=total_lots)
                    
                    markup = types.InlineKeyboardMarkup()
                    
                    if total_lots == 0:
                        markup.add(types.InlineKeyboardButton(BOT_TEXTS['market_empty'], callback_data="market_empty"))
                    else:
                        for lot in lots:
                            btn_text = f"{lot['chibi_name']} - 💰{lot['price']}"
                            if lot['seller_id'] == telegram_id_str:
                                btn_text = f"🔥 {btn_text}"
                            markup.add(types.InlineKeyboardButton(
                                btn_text,
                                callback_data=f"market_lot_{lot['_id']}"
                            ))
                    
                    markup.add(types.InlineKeyboardButton("✨ Создать лот", callback_data="market_create_1"))
                    
                    if total_pages > 1:
                        nav_buttons = []
                        nav_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"market_page_{page-1}"))
                        nav_buttons.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="market_current"))
                        nav_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"market_page_{page+1}"))
                        markup.row(*nav_buttons)
                    
                    sent = self.bot.send_message(
                        call.message.chat.id,
                        text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                    self.set_temp(f"msg_owner_{call.message.chat.id}_{sent.message_id}", telegram_id_str)
                    
                    self.del_temp("waiting_price", call.from_user.id)
                    self.del_temp("price_msg_id", call.from_user.id)
                
                elif call.data == "market_current":
                    self.bot.answer_callback_query(call.id)
                
                elif call.data == "market_empty":
                    self.bot.answer_callback_query(call.id, BOT_TEXTS['empty'])
                
                else:
                    self.bot.answer_callback_query(call.id)
                    
            except Exception as e:
                logger.error(f"Ошибка в callback: {e}")
                self.bot.answer_callback_query(call.id, BOT_TEXTS['not_yours'], parse_mode='Markdown')

    def run(self):
        logger.info("ОНО ЖИВОЕ!")
        self.setup_handlers()
        
        if "RENDER" in os.environ:
            self.setup_flask_routes()
            PORT = int(os.environ.get('PORT', 5000))
            
            def run_flask():
                self.app.run(host='0.0.0.0', port=PORT)
            
            flask_thread = threading.Thread(target=run_flask)
            flask_thread.daemon = True
            flask_thread.start()
            logger.info(f"фласк работает {PORT}")
        
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
        print("Токен вставь")
        exit(1)
    
    bot = ChibiBot(token)
    bot.run()
