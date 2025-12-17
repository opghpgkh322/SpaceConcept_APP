# database.py - РАСШИРЕННАЯ ВЕРСИЯ С ПОДДЕРЖКОЙ СОСТАВНЫХ ИЗДЕЛИЙ

import sqlite3
import os


def check_table_structure(cursor, table_name, expected_columns):
    """Проверяет структуру таблицы и добавляет отсутствующие столбцы"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    existing_columns = {col[1] for col in cursor.fetchall()}

    for column, col_type in expected_columns.items():
        if column not in existing_columns:
            try:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {col_type}")
                print(f"✅ Добавлена колонка {column} в таблицу {table_name}")
            except sqlite3.Error as e:
                print(f"❌ Ошибка при добавлении колонки {column}: {e}")


def create_database(db_path):
    """Создает базу данных и таблицы с поддержкой составных изделий"""
    data_dir = os.path.dirname(db_path)
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Существующие таблицы
    cursor.execute("""CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        type TEXT NOT NULL CHECK(type IN ('Пиломатериал', 'Метиз')),
        price REAL NOT NULL,
        unit TEXT NOT NULL
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS warehouse (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        material_id INTEGER NOT NULL,
        length REAL NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (material_id) REFERENCES materials(id)
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        cost REAL NOT NULL DEFAULT 0.0,
        is_composite BOOLEAN NOT NULL DEFAULT 0
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS product_composition (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        material_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        length REAL,
        FOREIGN KEY (product_id) REFERENCES products(id),
        FOREIGN KEY (material_id) REFERENCES materials(id)
    )""")

    # НОВАЯ ТАБЛИЦА: Составные изделия
    cursor.execute("""CREATE TABLE IF NOT EXISTS composite_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        composite_id INTEGER NOT NULL,
        component_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (composite_id) REFERENCES products(id),
        FOREIGN KEY (component_id) REFERENCES products(id)
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS stages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        cost REAL NOT NULL DEFAULT 0.0,
        description TEXT,
        category TEXT DEFAULT 'Статика' CHECK(category IN ('Статика', 'Динамика', 'Зип'))
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS stage_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        part TEXT NOT NULL DEFAULT 'meter' CHECK(part IN ('start','meter','end')),
        FOREIGN KEY (stage_id) REFERENCES stages(id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS stage_materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage_id INTEGER NOT NULL,
        material_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        length REAL,
        part TEXT NOT NULL DEFAULT 'meter' CHECK(part IN ('start','meter','end')),
        merge_to_single INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (stage_id) REFERENCES stages(id),
        FOREIGN KEY (material_id) REFERENCES materials(id)
    )""")

    cursor.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        total_cost REAL NOT NULL DEFAULT 0.0,
        instructions TEXT,
        pdf_filename TEXT
    )""")

    # Проверяем существование таблицы order_items
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='order_items'")
    table_exists = cursor.fetchone()

    existing_data = []
    if table_exists:
        cursor.execute("PRAGMA table_info(order_items)")
        old_columns = [col[1] for col in cursor.fetchall()]
        cursor.execute("SELECT * FROM order_items")
        existing_data = cursor.fetchall()
        cursor.execute("DROP TABLE order_items")

    cursor.execute("""CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER,
        stage_id INTEGER,
        quantity INTEGER NOT NULL,
        length_meters REAL,
        product_name TEXT NOT NULL DEFAULT '',
        cost REAL NOT NULL DEFAULT 0.0,
        item_type TEXT NOT NULL DEFAULT 'product' CHECK(item_type IN ('product', 'stage')),
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (product_id) REFERENCES products(id),
        FOREIGN KEY (stage_id) REFERENCES stages(id)
    )""")

    # Восстанавливаем данные order_items если они были
    if existing_data:
        for row in existing_data:
            try:
                if len(row) >= 7:
                    cursor.execute(
                        "INSERT INTO order_items (id, order_id, product_id, quantity, product_name, cost, item_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (row[0], row[1], row[2], row[3], row[6], row[7], 'product'))
            except Exception:
                pass

    conn.commit()

    # Обновляем структуру существующих таблиц
    try:
        check_table_structure(cursor, 'orders', {'pdf_filename': 'TEXT'})
        check_table_structure(cursor, 'stages', {'category': 'TEXT DEFAULT \'Статика\''})
        check_table_structure(cursor, 'stage_products', {'part': 'TEXT NOT NULL DEFAULT \'meter\''})
        check_table_structure(cursor, 'stage_materials', {'part': 'TEXT NOT NULL DEFAULT \'meter\'', 'merge_to_single': "INTEGER NOT NULL DEFAULT 0"})
        check_table_structure(cursor, 'order_items', {'length_meters': 'REAL'})
        check_table_structure(cursor, 'products', {'is_composite': 'BOOLEAN NOT NULL DEFAULT 0'})
        conn.commit()
    except sqlite3.Error as e:
        print(f"Ошибка при обновлении структуры БД: {e}")
        conn.rollback()
    finally:
        conn.close()


def add_stage_category_column(db_path):
    """Добавляет колонку category в таблицу stages"""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        # Проверяем, есть ли колонка category
        cursor.execute("PRAGMA table_info(stages)")
        columns = [col[1] for col in cursor.fetchall()]

        if 'category' not in columns:
            cursor.execute("ALTER TABLE stages ADD COLUMN category TEXT DEFAULT 'Статика'")
            print("✅ Добавлена колонка category в таблицу stages")

        conn.commit()
    except Exception as e:
        print(f"❌ Ошибка при добавлении колонки category: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    test_db = "test_composite.db"
    create_database(test_db)
    print(f"✅ База данных с поддержкой составных изделий создана: {test_db}")