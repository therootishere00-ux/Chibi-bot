import os
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

class MongoDB:
    def __init__(self):
        self.uri = os.getenv('MONGODB_URI')
        self.client = None
        self.db = None
        self.users = None
        self.connect()
    
    def connect(self):
        try:
            self.client = MongoClient(self.uri)
            self.db = self.client['ChibiBot']
            self.users = self.db['users']
            self.users.create_index('telegram_id', unique=True)
            print("✅ MongoDB подключена")
        except ConnectionFailure as e:
            print(f"❌ Ошибка MongoDB: {e}")
            raise
    
    def user_exists(self, telegram_id):
        return self.users.count_documents({'telegram_id': str(telegram_id)}) > 0
    
    def get_user(self, telegram_id):
        return self.users.find_one({'telegram_id': str(telegram_id)})
    
    def create_user(self, telegram_id, user_data):
        user_data['telegram_id'] = str(telegram_id)
        user_data['created_at'] = datetime.now()
        user_data['updated_at'] = datetime.now()
        try:
            result = self.users.insert_one(user_data)
            return True
        except:
            return False
    
    def update_user(self, telegram_id, updates):
        updates['updated_at'] = datetime.now()
        result = self.users.update_one(
            {'telegram_id': str(telegram_id)},
            {'$set': updates}
        )
        return result.modified_count > 0
    
    def get_all_used_ids(self):
        users = list(self.users.find({}, {'user_id': 1}))
        return {user.get('user_id') for user in users if user.get('user_id')}
