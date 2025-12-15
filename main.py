# main.py - исправленная версия без тестовых этапов
import sys
import os
from gui import MainWindow
from PyQt5.QtWidgets import QApplication
from database import create_database, add_stage_category_column
from cloud_sync import download_db

def get_db_path():
    """Возвращает абсолютный путь к базе данных"""
    if getattr(sys, 'frozen', False):
        # Если приложение запущено как собранный exe
        base_dir = os.path.dirname(sys.executable)
        db_path = os.path.join(base_dir, 'data', 'database.db')
    else:
        # Если приложение запущено из исходного кода
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.join(base_dir, '..', 'data', 'database.db')

    # Преобразуем путь к абсолютному и нормализуем
    db_path = os.path.abspath(db_path)
    data_dir = os.path.dirname(db_path)

    # Создаем папку data, если она не существует
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    return db_path


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dbpath = get_db_path()
    token = "y0__xDGx8DJARjrnzsgnMHG-BR-KZ19Xw3vp5ZtUe-FRHIfDz_1sA"
    remote_path = "/apps/SpaceConcept/database.db"

    need_init_db = False

    if token:
        try:
            download_db(token, remote_path, dbpath)
            # Проверим размер файла после скачивания!
            if (not os.path.exists(dbpath)) or (os.path.getsize(dbpath) < 1000):  # порог на разумный SQLite-файл
                print("!!! Получена пустая или поврежденная база, инициализируем новую")
                need_init_db = True
            else:
                print("БД успешно загружена из облака:", dbpath)
        except Exception as e:
            print("Ошибка загрузки базы из облака:", e)
            need_init_db = True
    else:
        need_init_db = True

    if need_init_db:
        create_database(dbpath)
        add_stage_category_column(dbpath)

    window = MainWindow(dbpath)
    window.show()
    sys.exit(app.exec_())

