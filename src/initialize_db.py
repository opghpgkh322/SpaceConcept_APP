import os
import sqlite3
import sys
from database import create_database


def initialize_database():
    # Определяем путь к базе данных так же, как в основном приложении
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
        db_path = os.path.join(base_dir, 'data', 'database.db')
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(base_dir, 'data', 'database.db')

    # Создаем папку, если не существует
    data_dir = os.path.dirname(db_path)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    # Создаем базу данных
    create_database(db_path)
    print(f"База данных создана: {db_path}")


if __name__ == "__main__":
    initialize_database()