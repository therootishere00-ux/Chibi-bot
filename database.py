import pymongo
from pymongo import MongoClient
import logging
from config import BOT_CONFIG

logger = logging.getLogger(__name__)

class MongoDB:
    def __init__(self):
        self.uri = BOT_CONFIG['mongodb_uri']
        self.db_name = BOT_CONFIG['db_name']
        self.client = None
        self.db = None
        self.connect()
    
    def connect(self):
        try:
            self.client = MongoClient(self.uri)
            self.db = self.client[self.db_name]
            
            self.client.admin.command('ping')
            logger.info("✅ Успешное подключение к MongoDB")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к MongoDB: {e}")
            raise
    
    def get_collection(self, collection_name):
        return self.db[collection_name]
    
    def close(self):
        if self.client:
            self.client.close()


db = MongoDB()

def get_users_collection():
    return db.get_collection('users')

def get_chibis_collection():
    return db.get_collection('user_chibis')

def get_orders_collection():
    return db.get_collection('orders')

def get_tasks_collection():
    return db.get_collection('tasks')

def get_system_collection():
    return db.get_collection('system')
