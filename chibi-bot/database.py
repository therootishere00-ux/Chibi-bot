import sqlite3
import os
from typing import List, Dict, Optional

class Database:
    def __init__(self):
        self.db_path = os.path.join(os.path.dirname(__file__), 'chibi_bot.db')
        self.init_db()
    
    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Пользователи
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Чибики пользователя
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_chibis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    chibi_id INTEGER,
                    quantity INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Предметы пользователя
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    item_type TEXT,
                    quantity INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Каталог чибиков
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chibi_catalog (
                    chibi_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    rarity TEXT DEFAULT 'common'
                )
            ''')
            
            # Начальные данные чибиков
            cursor.execute('''
                INSERT OR IGNORE INTO chibi_catalog (chibi_id, name, rarity) VALUES
                (1, 'Джанго Фетт', 'rare'),
                (2, 'Мейс Винду', 'epic'),
                (3, 'Оби-Ван Кеноби', 'common'),
                (4, 'Энакин Скайуокер', 'epic'),
                (5, 'Йода', 'legendary'),
                (6, 'Люк Скайуокер', 'common'),
                (7, 'Принцесса Лея', 'rare'),
                (8, 'Хан Соло', 'common'),
                (9, 'Чубакка', 'rare'),
                (10, 'Дарт Вейдер', 'legendary')
            ''')
            
            conn.commit()
    
    def get_or_create_user(self, user_id: int, username: str, first_name: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                (user_id, username, first_name)
            )
            conn.commit()
    
    def add_chibi_to_user(self, user_id: int, chibi_id: int, quantity: int = 1):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_chibis (user_id, chibi_id, quantity)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, chibi_id) DO UPDATE SET 
                quantity = quantity + excluded.quantity
            ''', (user_id, chibi_id, quantity))
            conn.commit()
    
    def add_item_to_user(self, user_id: int, item_type: str, quantity: int = 1):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_items (user_id, item_type, quantity)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, item_type) DO UPDATE SET 
                quantity = quantity + excluded.quantity
            ''', (user_id, item
