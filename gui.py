# gui.py - ВЕРСИЯ С АВТОЗАПОЛНЕНИЕМ ПОЛЕЙ

from cloud_sync import download_db, upload_db
import re
import sys
import os
import math
import subprocess
import sqlite3
import platform
from functools import partial
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from datetime import datetime
from cutting_optimizer import CuttingOptimizer
from collections import defaultdict
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTabWidget, QTableWidget,
                             QTableWidgetItem, QPushButton, QVBoxLayout, QWidget,
                             QHeaderView, QMessageBox, QLabel, QLineEdit, QComboBox,
                             QHBoxLayout, QFormLayout, QGroupBox, QSpinBox, QDoubleSpinBox, QTextEdit,
                             QDialog, QSplitter, QFileDialog, QAbstractItemView, QCheckBox)
from PyQt5.QtCore import Qt

# ИСПРАВЛЕНИЕ 1: Улучшенная регистрация шрифта Arial
ARIAL_FONT_REGISTERED = False


def setup_arial_font():
    global ARIAL_FONT_REGISTERED
    try:
        if getattr(sys, 'frozen', False):
            font_path = os.path.join(os.path.dirname(sys.executable), 'fonts', 'arial.ttf')
        else:
            font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'arial.ttf')
        print(f"Попытка загрузить шрифт: {font_path}")
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('Arial', font_path))
            ARIAL_FONT_REGISTERED = True
            print("✓ Шрифт Arial успешно зарегистрирован")
        else:
            print(f"✗ Файл шрифта не найден: {font_path}")
            ARIAL_FONT_REGISTERED = False
    except Exception as e:
        print(f"✗ Ошибка регистрации шрифта Arial: {e}")
        ARIAL_FONT_REGISTERED = False


# Вызываем функцию регистрации
setup_arial_font()


class RoutesPlanningDialog(QDialog):
    """Диалог для планирования трасс веревочного парка"""

    def __init__(self, stages, parent=None):
        super().__init__(parent)
        self.stages = stages
        self.routes = []
        self.setWindowTitle("Планирование трасс веревочного парка")
        self.setModal(True)
        self.resize(800, 600)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Упрощенная инструкция
        info_label = QLabel("""**Планирование трасс веревочного парка:**
• **Статические этапы** - требуют страховочный трос

• **Динамические/Зип этапы** - НЕ требуют трос и разрывают трассу

• Укажите для каждого статического этапа: номер трассы и позицию в ней

• Динамические этапы автоматически исключаются из расчета троса
""")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Таблица планирования (убрали лишний столбец)
        self.planning_table = QTableWidget()
        self.planning_table.setColumnCount(5)  # БЫЛО 6, СТАЛО 5
        self.planning_table.setHorizontalHeaderLabels([
            "Этап", "Длина (м)", "Категория", "№ трассы", "№ в трассе"
        ])
        self.planning_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.planning_table.setRowCount(len(self.stages))

        for row, stage in enumerate(self.stages):
            # Название этапа
            name_item = QTableWidgetItem(stage['name'])
            name_item.setFlags(name_item.flags() ^ Qt.ItemIsEditable)
            self.planning_table.setItem(row, 0, name_item)

            # Длина
            length_item = QTableWidgetItem(f"{stage['length']:.2f}")
            length_item.setFlags(length_item.flags() ^ Qt.ItemIsEditable)
            self.planning_table.setItem(row, 1, length_item)

            # Категория с цветовой индикацией
            category_item = QTableWidgetItem(stage['category'])
            category_item.setFlags(category_item.flags() ^ Qt.ItemIsEditable)
            if stage['category'] == 'Статика':
                category_item.setBackground(Qt.green)
                category_item.setToolTip("Требует страховочный трос")
            else:
                category_item.setBackground(Qt.red)
                category_item.setToolTip("НЕ требует трос, разрывает трассу")
            self.planning_table.setItem(row, 2, category_item)

            # № трассы
            route_spin = QSpinBox()
            route_spin.setMinimum(1)
            route_spin.setMaximum(10)
            route_spin.setValue(1)
            route_spin.setToolTip("Номер трассы для страховочного троса")
            route_spin.valueChanged.connect(self.validate_positions)
            self.planning_table.setCellWidget(row, 3, route_spin)

            # № в трассе
            position_spin = QSpinBox()
            position_spin.setMinimum(1)
            position_spin.setMaximum(20)
            position_spin.setValue(row + 1)
            position_spin.setToolTip("Позиция этапа внутри трассы троса")
            position_spin.valueChanged.connect(self.validate_positions)
            self.planning_table.setCellWidget(row, 4, position_spin)

        layout.addWidget(self.planning_table)

        # ДОБАВЛЕНО: Лейбл для отображения ошибок валидации
        self.validation_label = QLabel("")
        self.validation_label.setStyleSheet("color: red; font-weight: bold;")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        # Кнопки
        btn_layout = QHBoxLayout()
        auto_btn = QPushButton("Автоматическое планирование")
        auto_btn.clicked.connect(self.auto_planning)
        auto_btn.setToolTip("Автоматически расставить этапы по трассам без конфликтов")
        btn_layout.addWidget(auto_btn)

        preview_btn = QPushButton("Предварительный просмотр")
        preview_btn.clicked.connect(self.show_preview)
        preview_btn.setToolTip("Показать, как будут рассчитаны трассы троса")
        btn_layout.addWidget(preview_btn)

        btn_layout.addStretch()

        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.accept_with_validation)
        btn_layout.addWidget(self.ok_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        # Выполняем начальную валидацию
        self.validate_positions()

    def validate_positions(self):
        """Проверяет, чтобы ни две строки не имели один и тот же (трасса, позиция)."""
        seen = {}
        conflicts = []

        for row in range(self.planning_table.rowCount()):
            route = self.planning_table.cellWidget(row, 3).value()
            pos = self.planning_table.cellWidget(row, 4).value()
            key = (route, pos)
            name = self.stages[row]['name']
            seen.setdefault(key, []).append(name)

        for key, names in seen.items():
            if len(names) > 1:
                r, p = key
                conflicts.append(f"Трасса {r}, позиция {p}: {', '.join(names)}")

        if conflicts:
            self.validation_label.setText("⚠️ Конфликты позиций:\n" + "\n".join(conflicts))
            self.ok_btn.setEnabled(False)
        else:
            self.validation_label.setText("✅ Конфликтов позиций нет")
            self.ok_btn.setEnabled(True)

    def accept_with_validation(self):
        """ДОБАВЛЕНО: Принятие диалога только при отсутствии конфликтов"""
        self.validate_positions()
        if self.ok_btn.isEnabled():
            self.accept()
        else:
            QMessageBox.warning(self, "Ошибка валидации",
                                "Есть конфликты позиций! Несколько этапов не могут находиться "
                                "на одной позиции в одной трассе.")

    def auto_planning(self):
        """Автоматическое планирование без конфликтов"""
        # Получаем только статические этапы
        static_stages = []
        for row in range(len(self.stages)):
            if self.stages[row]['category'] == 'Статика':
                static_stages.append(row)

        if not static_stages:
            QMessageBox.information(self, "Информация", "Нет статических этапов для планирования")
            return

        # Размещаем статические этапы в одну трассу по порядку
        for i, row in enumerate(static_stages):
            route_widget = self.planning_table.cellWidget(row, 3)
            position_widget = self.planning_table.cellWidget(row, 4)

            route_widget.setValue(1)  # Все в первую трассу
            position_widget.setValue(i + 1)  # По порядку без конфликтов

        # Запускаем валидацию
        self.validate_positions()

    def show_preview(self):
        """Исправленный предварительный просмотр расчета трасс"""
        # Проверяем позиции
        self.validate_positions()
        if not self.ok_btn.isEnabled():
            QMessageBox.warning(self, "Ошибка", "Устраните конфликты позиций перед просмотром")
            return

        # Получаем трассы
        routes = self.get_routes()

        # Общая статистика
        total_stages = len(self.stages)
        static_count = sum(1 for s in self.stages if s['category'] == "Статика")
        dynamic_count = total_stages - static_count

        preview = f"🔍 Предварительный расчет трасс:\n"
        preview += f"Всего этапов: {total_stages} (Статика: {static_count}, Динамика/Зип: {dynamic_count})\n"
        preview += f"Трасс страховочного троса: {len(routes)}\n\n"

        total_rope = 0.0
        total_clamps = 0

        for idx, route in enumerate(routes, 1):
            preview += f"=== Трасса {idx} ===\n"
            preview += f"Статических этапов: {len(route)}\n"

            # Восстанавливаем полную трассу с динамическими этапами
            full_route = []
            for row in range(len(self.stages)):
                route_widget = self.planning_table.cellWidget(row, 3)
                position_widget = self.planning_table.cellWidget(row, 4)
                stage = self.stages[row]

                if route_widget and position_widget:
                    if route_widget.value() == idx:
                        full_route.append((position_widget.value(), stage))

            # Сортируем по позиции и разбиваем на сегменты
            full_route.sort(key=lambda x: x[0])
            segments = []
            current_segment = None

            for pos, stage in full_route:
                stage_type = 'static' if stage['category'] == 'Статика' else 'dynamic'

                if current_segment is None or current_segment['type'] != stage_type:
                    current_segment = {'type': stage_type, 'stages': [stage]}
                    segments.append(current_segment)
                else:
                    current_segment['stages'].append(stage)

            # Расчет для этой трассы - только статические сегменты
            route_rope = 0.0
            route_clamps = 0

            for segment in segments:
                if segment['type'] == 'static':
                    N = len(segment['stages'])
                    L = sum(s['length'] for s in segment['stages'])
                    rope = 5 + 5 * N + L
                    clamps = 6 + 6 * N
                    route_rope += rope
                    route_clamps += clamps
                    preview += f" Статический сегмент: {N} этапов, {L:.2f}м → "
                    preview += f"Трос: {rope:.2f}м, Зажимы: {clamps}шт\n"
                elif segment['type'] == 'dynamic':
                    preview += f" Динамический сегмент: игнорируется (разрывает трассу)\n"

            total_rope += route_rope
            total_clamps += route_clamps
            preview += f"Итого по трассе {idx}: {route_rope:.2f}м троса, {route_clamps} зажимов\n\n"

        preview += f"📊 ОБЩИЙ ИТОГ: {total_rope:.2f}м троса М12, {total_clamps} зажимов М12"

        QMessageBox.information(self, "Предварительный расчет", preview)

    def get_routes(self):
        """Возвращает список трасс с этапами (включая динамические для правильного разбиения)"""
        routes_dict = {}

        # Собираем ВСЕ этапы с их позициями в трассах
        for row in range(len(self.stages)):
            stage = self.stages[row]
            route_widget = self.planning_table.cellWidget(row, 3)
            position_widget = self.planning_table.cellWidget(row, 4)

            route_num = route_widget.value()
            position = position_widget.value()

            if route_num not in routes_dict:
                routes_dict[route_num] = {}
            routes_dict[route_num][position] = stage

        # Преобразуем в список трасс, отсортированных по позициям
        routes = []
        for route_num in sorted(routes_dict.keys()):
            route_stages = []
            for position in sorted(routes_dict[route_num].keys()):
                route_stages.append(routes_dict[route_num][position])
            if route_stages:  # Добавляем только непустые трассы
                routes.append(route_stages)

        return routes


# КЛАСС ЭТАПОВ С АВТОЗАПОЛНЕНИЕМ
class StagesTab(QWidget):
    def __init__(self, db_path, main_window=None):
        super().__init__()
        self.db_path = db_path
        self.main_window = main_window
        self.selected_stage_id = None
        self.selected_stage_name = None
        self.init_ui()
        self.load_stages()

    def init_ui(self):
        main_splitter = QSplitter(Qt.Horizontal)

        # Левая панель
        left_panel = QWidget()
        left_layout = QVBoxLayout()

        # Поисковое поле
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по этапам…")
        self.search_input.textChanged.connect(self.filter_table)
        left_layout.addWidget(self.search_input)

        stages_group = QGroupBox("Этапы")
        stages_layout = QVBoxLayout()

        # Таблица этапов
        self.stages_table = QTableWidget()
        self.stages_table.setColumnCount(5)
        self.stages_table.setHorizontalHeaderLabels(["ID", "Название", "Категория", "Себестоимость", "Описание"])
        self.stages_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.stages_table.cellClicked.connect(self.on_stage_selected)
        self.stages_table.cellChanged.connect(self.on_stage_cell_edited)
        stages_layout.addWidget(self.stages_table)

        # Форма добавления этапа
        form_layout = QFormLayout()

        self.stage_name_input = QLineEdit()
        self.stage_name_input.setPlaceholderText("Название этапа")
        form_layout.addRow(QLabel("Название этапа:"), self.stage_name_input)

        # Выбор категории этапа
        self.stage_category_combo = QComboBox()
        self.stage_category_combo.addItems(["Статика", "Динамика", "Зип"])
        form_layout.addRow(QLabel("Категория:"), self.stage_category_combo)

        self.stage_description_input = QTextEdit()
        self.stage_description_input.setPlaceholderText("Описание этапа работ...")
        self.stage_description_input.setMaximumHeight(60)
        form_layout.addRow(QLabel("Описание:"), self.stage_description_input)

        btn_layout = QHBoxLayout()
        self.add_stage_btn = QPushButton("Добавить этап")
        self.add_stage_btn.clicked.connect(self.add_stage)
        btn_layout.addWidget(self.add_stage_btn)

        self.delete_stage_btn = QPushButton("Удалить этап")
        self.delete_stage_btn.clicked.connect(self.delete_stage)
        btn_layout.addWidget(self.delete_stage_btn)

        form_layout.addRow(btn_layout)
        stages_layout.addLayout(form_layout)
        stages_group.setLayout(stages_layout)
        left_layout.addWidget(stages_group)
        left_panel.setLayout(left_layout)
        main_splitter.addWidget(left_panel)

        # Правая панель - состав этапа
        self.composition_group = QGroupBox("Состав этапа")
        self.composition_group.setEnabled(False)
        composition_layout = QVBoxLayout()

        composition_tabs = QTabWidget()

        # Вкладка "Изделия в этапе"
        products_tab = QWidget()
        products_layout = QVBoxLayout()

        self.stage_products_table = QTableWidget()
        self.stage_products_table.setColumnCount(5)
        self.stage_products_table.setHorizontalHeaderLabels(
            ["ID", "Изделие", "Часть", "Количество", "Стоимость"]
        )
        self.stage_products_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.stage_products_table.cellChanged.connect(self.on_stage_product_cell_edited)
        products_layout.addWidget(self.stage_products_table)

        product_form = QFormLayout()

        self.product_combo = QComboBox()
        product_form.addRow(QLabel("Изделие:"), self.product_combo)

        self.product_part_combo = QComboBox()
        self.product_part_combo.addItems(["start", "meter", "end"])
        product_form.addRow(QLabel("Часть:"), self.product_part_combo)

        self.product_quantity_input = QSpinBox()
        self.product_quantity_input.setMinimum(1)
        self.product_quantity_input.setMaximum(999)
        self.product_quantity_input.setValue(1)
        product_form.addRow(QLabel("Количество:"), self.product_quantity_input)

        product_btn_layout = QHBoxLayout()
        self.add_product_to_stage_btn = QPushButton("Добавить изделие")
        self.add_product_to_stage_btn.clicked.connect(self.add_product_to_stage)
        product_btn_layout.addWidget(self.add_product_to_stage_btn)

        self.remove_product_from_stage_btn = QPushButton("Удалить изделие")
        self.remove_product_from_stage_btn.clicked.connect(self.remove_product_from_stage)
        product_btn_layout.addWidget(self.remove_product_from_stage_btn)

        product_form.addRow(product_btn_layout)
        products_layout.addLayout(product_form)
        products_tab.setLayout(products_layout)
        composition_tabs.addTab(products_tab, "Изделия")

        # Вкладка "Материалы в этапе" С АВТОЗАПОЛНЕНИЕМ
        materials_tab = QWidget()
        materials_layout = QVBoxLayout()

        self.stage_materials_table = QTableWidget()
        self.stage_materials_table.setColumnCount(8)
        self.stage_materials_table.setHorizontalHeaderLabels(
            ["ID", "Материал", "Тип", "Часть", "Количество", "Длина", "Цельный", "Стоимость"]
        )
        self.stage_materials_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.stage_materials_table.cellChanged.connect(self.on_stage_material_cell_edited)
        materials_layout.addWidget(self.stage_materials_table)

        material_form = QFormLayout()

        self.material_combo = QComboBox()
        # АВТОЗАПОЛНЕНИЕ: подключаем обработчик изменения материала
        self.material_combo.currentTextChanged.connect(self.on_material_changed)
        material_form.addRow(QLabel("Материал:"), self.material_combo)

        self.material_part_combo = QComboBox()
        self.material_part_combo.addItems(["start", "meter", "end"])
        material_form.addRow(QLabel("Часть:"), self.material_part_combo)

        self.material_quantity_input = QSpinBox()
        self.material_quantity_input.setMinimum(1)
        self.material_quantity_input.setMaximum(999)
        self.material_quantity_input.setValue(1)
        material_form.addRow(QLabel("Количество:"), self.material_quantity_input)

        self.material_length_input = QLineEdit()
        self.material_length_input.setPlaceholderText("0.75 (для пиломатериалов)")
        material_form.addRow(QLabel("Длина (м):"), self.material_length_input)

        self.material_merge_checkbox = QCheckBox("Цельный отрезок (объединять в 1 распил)")
        self.material_merge_checkbox.setChecked(False)
        material_form.addRow(QLabel("Режим распила:"), self.material_merge_checkbox)

        material_btn_layout = QHBoxLayout()
        self.add_material_to_stage_btn = QPushButton("Добавить материал")
        self.add_material_to_stage_btn.clicked.connect(self.add_material_to_stage)
        material_btn_layout.addWidget(self.add_material_to_stage_btn)

        self.remove_material_from_stage_btn = QPushButton("Удалить материал")
        self.remove_material_from_stage_btn.clicked.connect(self.remove_material_from_stage)
        material_btn_layout.addWidget(self.remove_material_from_stage_btn)

        material_form.addRow(material_btn_layout)
        materials_layout.addLayout(material_form)
        materials_tab.setLayout(materials_layout)
        composition_tabs.addTab(materials_tab, "Материалы")

        composition_layout.addWidget(composition_tabs)

        self.cost_label = QLabel("Себестоимость этапа: 0.00 руб")
        self.cost_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        composition_layout.addWidget(self.cost_label)

        self.composition_group.setLayout(composition_layout)
        main_splitter.addWidget(self.composition_group)

        main_splitter.setSizes([300, 700])

        main_layout = QVBoxLayout()
        main_layout.addWidget(main_splitter)
        self.setLayout(main_layout)

    # НОВАЯ ФУНКЦИЯ АВТОЗАПОЛНЕНИЯ ДЛЯ МАТЕРИАЛОВ
    def on_material_changed(self, material_text):
        """АВТОЗАПОЛНЕНИЕ: Заполняет длину в зависимости от типа материала"""
        if not material_text:
            return

        try:
            # Извлекаем ID материала из ComboBox
            material_id = self.material_combo.currentData()
            if not material_id:
                return

            # Получаем тип материала из БД
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT type FROM materials WHERE id = ?", (material_id,))
            result = cursor.fetchone()
            conn.close()

            if result:
                material_type = result[0]
                if material_type == "Метиз":
                    # Для метизов автоматически ставим длину 0
                    self.material_length_input.setText("0")
                    self.material_length_input.setEnabled(False)
                    self.material_length_input.setToolTip("Длина для метизов всегда 0")
                else:
                    # Для пиломатериалов включаем поле и очищаем
                    self.material_length_input.setEnabled(True)
                    if self.material_length_input.text() == "0":
                        self.material_length_input.clear()
                    self.material_length_input.setToolTip("Введите длину в метрах")

        except Exception as e:
            print(f"Ошибка при автозаполнении материала: {e}")

    def on_stage_product_cell_edited(self, row, column):
        """Редактирование части/количества изделия в этапе"""
        try:
            sp_id = int(self.stage_products_table.item(row, 0).text())

            if column == 2:  # Часть
                new_part = self.stage_products_table.item(row, column).text().strip()
                if new_part not in ("start", "meter", "end"):
                    QMessageBox.warning(self, "Ошибка", "Часть должна быть: start, meter или end")
                    self.load_stage_products()
                    return

                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE stage_products SET part = ? WHERE id = ?", (new_part, sp_id))
                conn.commit()
                conn.close()

                self.load_stage_products()
                self.calculate_stage_cost()

            elif column == 3:  # Количество
                new_quantity = int(self.stage_products_table.item(row, column).text())
                if new_quantity < 1:
                    QMessageBox.warning(self, "Ошибка", "Количество должно быть больше 0")
                    self.load_stage_products()
                    return

                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE stage_products SET quantity = ? WHERE id = ?", (new_quantity, sp_id))
                conn.commit()
                conn.close()

                self.load_stage_products()
                self.calculate_stage_cost()

        except (ValueError, TypeError):
            QMessageBox.warning(self, "Ошибка", "Некорректное значение")
            self.load_stage_products()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при обновлении: {str(e)}")
            self.load_stage_products()

    def on_category_changed(self, row, new_category):
        """Обновляет категорию этапа в БД"""
        try:
            stage_id = int(self.stages_table.item(row, 0).text())
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE stages SET category = ? WHERE id = ?", (new_category, stage_id))
            conn.commit()
            conn.close()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось обновить категорию: {str(e)}")
            self.load_stages()

    def on_stage_material_cell_edited(self, row, column):
        """Редактирование части/количества/длины материалов этапа"""
        try:
            sm_id = int(self.stage_materials_table.item(row, 0).text())

            if column == 3:  # Часть
                new_part = self.stage_materials_table.item(row, column).text().strip()
                if new_part not in ("start", "meter", "end"):
                    QMessageBox.warning(self, "Ошибка", "Часть должна быть: start, meter или end")
                    self.load_stage_materials()
                    return

                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE stage_materials SET part = ? WHERE id = ?", (new_part, sm_id))
                conn.commit()
                conn.close()

                self.load_stage_materials()
                self.calculate_stage_cost()

            elif column == 4:  # Количество
                new_quantity = int(self.stage_materials_table.item(row, column).text())
                if new_quantity < 1:
                    QMessageBox.warning(self, "Ошибка", "Количество должно быть больше 0")
                    self.load_stage_materials()
                    return

                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE stage_materials SET quantity = ? WHERE id = ?", (new_quantity, sm_id))
                conn.commit()
                conn.close()

                self.load_stage_materials()
                self.calculate_stage_cost()

            elif column == 5:  # Длина
                new_length_text = self.stage_materials_table.item(row, column).text().strip()
                new_length = float(new_length_text) if new_length_text else None

                if new_length is not None and new_length < 0:
                    QMessageBox.warning(self, "Ошибка", "Длина не может быть отрицательной")
                    self.load_stage_materials()
                    return

                elif column == 6:  # Цельный отрезок (merge_to_single)
                    item = self.stage_materials_table.item(row, column)
                    new_val = 1 if item and item.checkState() == Qt.Checked else 0

                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE stage_materials SET merge_to_single = ? WHERE id = ?", (new_val, sm_id))
                    conn.commit()
                    conn.close()

                    self.load_stage_materials()
                    self.calculate_stage_cost()

                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE stage_materials SET length = ? WHERE id = ?", (new_length, sm_id))
                    conn.commit()
                    conn.close()

                    self.load_stage_materials()
                    self.calculate_stage_cost()

        except (ValueError, TypeError):
            QMessageBox.warning(self, "Ошибка", "Некорректное значение")
            self.load_stage_materials()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при обновлении: {str(e)}")
            self.load_stage_materials()

    def on_stage_material_item_changed(self, item):
        # Реагируем только на колонку "Цельный"
        if item is None or item.column() != 6:
            return

        try:
            row = item.row()
            sm_id = int(self.stage_materials_table.item(row, 0).text())
            new_val = 1 if item.checkState() == Qt.Checked else 0

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE stage_materials SET merge_to_single = ? WHERE id = ?",
                (new_val, sm_id)
            )
            conn.commit()
            conn.close()

            # чтобы стоимость этапа пересчиталась
            self.calculate_stage_cost()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при обновлении merge_to_single: {e}")
            self.load_stage_materials()

    def on_stage_cell_edited(self, row, column):
        """Обработка редактирования ячеек с учетом новой колонки категории"""
        try:
            stage_id = int(self.stages_table.item(row, 0).text())

            if column == 1:  # Название этапа
                new_name = self.stages_table.item(row, column).text().strip()
                if not new_name:
                    QMessageBox.warning(self, "Ошибка", "Название этапа не может быть пустым")
                    self.load_stages()
                    return

                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE stages SET name = ? WHERE id = ?", (new_name, stage_id))
                conn.commit()
                conn.close()

            elif column == 4:  # Описание этапа
                new_description = self.stages_table.item(row, column).text()
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE stages SET description = ? WHERE id = ?", (new_description, stage_id))
                conn.commit()
                conn.close()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при обновлении: {str(e)}")
            self.load_stages()

    def load_stages(self):
        """Загружает список этапов с категориями"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, category, cost, description FROM stages ORDER BY name")
        stages = cursor.fetchall()
        conn.close()

        self.stages_table.setRowCount(len(stages))
        self.stages_table.cellChanged.disconnect()

        for row_idx, (stage_id, stage_name, category, cost, description) in enumerate(stages):
            # ID (только для чтения)
            id_item = QTableWidgetItem(str(stage_id))
            id_item.setFlags(id_item.flags() ^ Qt.ItemIsEditable)
            self.stages_table.setItem(row_idx, 0, id_item)

            # Название (редактируемое)
            self.stages_table.setItem(row_idx, 1, QTableWidgetItem(stage_name))

            # Категория (редактируемое)
            category_combo = QComboBox()
            category_combo.addItems(["Статика", "Динамика", "Зип"])
            category_combo.setCurrentText(category or "Статика")
            category_combo.currentTextChanged.connect(
                lambda new_cat, r=row_idx: self.on_category_changed(r, new_cat)
            )
            self.stages_table.setCellWidget(row_idx, 2, category_combo)

            # Себестоимость (только для чтения)
            cost_item = QTableWidgetItem(f"{cost:.2f} руб")
            cost_item.setFlags(cost_item.flags() ^ Qt.ItemIsEditable)
            self.stages_table.setItem(row_idx, 3, cost_item)

            # Описание (редактируемое)
            self.stages_table.setItem(row_idx, 4, QTableWidgetItem(description or ""))

        self.stages_table.cellChanged.connect(self.on_stage_cell_edited)

    def load_stage_products(self):
        """Загружает изделия в составе выбранного этапа с поддержкой части"""
        if not self.selected_stage_id:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sp.id, p.name, sp.part, sp.quantity, (p.cost * sp.quantity) as total_cost
            FROM stage_products sp
            JOIN products p ON sp.product_id = p.id
            WHERE sp.stage_id = ?
        """, (self.selected_stage_id,))
        stage_products = cursor.fetchall()
        conn.close()

        self.stage_products_table.cellChanged.disconnect()
        self.stage_products_table.setRowCount(len(stage_products))

        for row_idx, (sp_id, prod_name, part, quantity, total_cost) in enumerate(stage_products):
            id_item = QTableWidgetItem(str(sp_id))
            id_item.setFlags(id_item.flags() ^ Qt.ItemIsEditable)
            self.stage_products_table.setItem(row_idx, 0, id_item)

            name_item = QTableWidgetItem(prod_name)
            name_item.setFlags(name_item.flags() ^ Qt.ItemIsEditable)
            self.stage_products_table.setItem(row_idx, 1, name_item)

            self.stage_products_table.setItem(row_idx, 2, QTableWidgetItem(part))
            self.stage_products_table.setItem(row_idx, 3, QTableWidgetItem(str(quantity)))

            cost_item = QTableWidgetItem(f"{total_cost:.2f} руб")
            cost_item.setFlags(cost_item.flags() ^ Qt.ItemIsEditable)
            self.stage_products_table.setItem(row_idx, 4, cost_item)

        self.stage_products_table.cellChanged.connect(self.on_stage_product_cell_edited)

    def load_stage_materials(self):
        """Загружает материалы в составе выбранного этапа с поддержкой редактирования и части"""
        if not self.selected_stage_id:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sm.id, m.name, m.type, sm.part, sm.quantity, sm.length, sm.merge_to_single, m.price,
                   CASE 
                       WHEN m.type = 'Пиломатериал' AND sm.length IS NOT NULL 
                       THEN (m.price * sm.quantity * sm.length)
                       ELSE (m.price * sm.quantity)
                   END as total_cost
            FROM stage_materials sm
            JOIN materials m ON sm.material_id = m.id
            WHERE sm.stage_id = ?
        """, (self.selected_stage_id,))
        stage_materials = cursor.fetchall()
        conn.close()

        self.stage_materials_table.blockSignals(True)
        self.stage_materials_table.cellChanged.disconnect()
        self.stage_materials_table.setRowCount(len(stage_materials))

        for row_idx, (sm_id, mat_name, mat_type, part, quantity, length, merge_to_single, price, total_cost) in enumerate(stage_materials):
            id_item = QTableWidgetItem(str(sm_id))
            id_item.setFlags(id_item.flags() ^ Qt.ItemIsEditable)
            self.stage_materials_table.setItem(row_idx, 0, id_item)

            name_item = QTableWidgetItem(mat_name)
            name_item.setFlags(name_item.flags() ^ Qt.ItemIsEditable)
            self.stage_materials_table.setItem(row_idx, 1, name_item)

            type_item = QTableWidgetItem(mat_type)
            type_item.setFlags(type_item.flags() ^ Qt.ItemIsEditable)
            self.stage_materials_table.setItem(row_idx, 2, type_item)

            self.stage_materials_table.setItem(row_idx, 3, QTableWidgetItem(part))
            self.stage_materials_table.setItem(row_idx, 4, QTableWidgetItem(str(quantity)))

            length_item = QTableWidgetItem(str(length) if length else "")
            if mat_type == "Метиз":
                length_item.setFlags(length_item.flags() ^ Qt.ItemIsEditable)
            self.stage_materials_table.setItem(row_idx, 5, length_item)

            cost_item = QTableWidgetItem(f"{total_cost:.2f} руб")
            cost_item.setFlags(cost_item.flags() ^ Qt.ItemIsEditable)
            self.stage_materials_table.setItem(row_idx, 7, cost_item)

            merge_item = QTableWidgetItem()
            merge_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            merge_item.setCheckState(Qt.Checked if int(merge_to_single) == 1 else Qt.Unchecked)
            self.stage_materials_table.setItem(row_idx, 6, merge_item)

        self.stage_materials_table.cellChanged.connect(self.on_stage_material_cell_edited)
        self.stage_materials_table.itemChanged.connect(self.on_stage_material_item_changed)
        self.stage_materials_table.blockSignals(False)

    def calculate_stage_cost(self):
        """Рассчитывает себестоимость этапа с учетом составных изделий"""
        if not hasattr(self, 'selected_stage_id') or self.selected_stage_id is None:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Стоимость изделий в этапе (включая составные)
            cursor.execute("""
                SELECT SUM(p.cost * sp.quantity) as products_cost
                FROM stage_products sp
                JOIN products p ON sp.product_id = p.id
                WHERE sp.stage_id = ?
            """, (self.selected_stage_id,))
            products_cost = cursor.fetchone()[0] or 0

            # Стоимость материалов этапа (как и раньше)
            cursor.execute("""
                SELECT sm.quantity, sm.length, m.price, m.type
                FROM stage_materials sm
                JOIN materials m ON sm.material_id = m.id
                WHERE sm.stage_id = ?
            """, (self.selected_stage_id,))

            materials_cost = 0
            for quantity, length, price, material_type in cursor.fetchall():
                if material_type == "Пиломатериал" and length:
                    materials_cost += price * quantity * length
                else:
                    materials_cost += price * quantity

            total_cost = products_cost + materials_cost

            self.cost_label.setText(f"Себестоимость этапа: {total_cost:.2f} руб")

            # Обновляем в БД
            cursor.execute("UPDATE stages SET cost = ? WHERE id = ?", (total_cost, self.selected_stage_id))
            conn.commit()

            # Обновляем таблицу этапов
            self.load_stages()

            # Очищаем кэш в заказах
            if self.main_window and hasattr(self.main_window, 'orders_tab'):
                if hasattr(self.main_window.orders_tab, 'stage_cost_cache'):
                    if self.selected_stage_id in self.main_window.orders_tab.stage_cost_cache:
                        del self.main_window.orders_tab.stage_cost_cache[self.selected_stage_id]

        except Exception as e:
            QMessageBox.critical(self, "Ошибка расчета", f"Произошла ошибка: {str(e)}")
        finally:
            conn.close()

    # Остальные методы без изменений
    def on_stage_selected(self, row, col):
        try:
            if row < 0 or row >= self.stages_table.rowCount():
                return

            id_item = self.stages_table.item(row, 0)
            name_item = self.stages_table.item(row, 1)

            if not id_item or not name_item:
                return

            self.selected_stage_id = int(id_item.text())
            self.selected_stage_name = name_item.text()

            self.composition_group.setEnabled(True)
            self.composition_group.setTitle(f"Состав этапа: {self.selected_stage_name}")

            self.load_products()
            self.load_materials()
            self.load_stage_products()
            self.load_stage_materials()
            self.calculate_stage_cost()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка выбора", f"Произошла ошибка: {str(e)}")

    def load_products(self):
        """Загружает ВСЕ изделия для добавления в этапы"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, is_composite FROM products ORDER BY is_composite, name")
        products = cursor.fetchall()
        conn.close()

        self.product_combo.clear()
        for prod_id, prod_name, is_composite in products:
            display_name = f"[Составное] {prod_name}" if is_composite else prod_name
            self.product_combo.addItem(display_name, prod_id)

    def load_materials(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, type FROM materials ORDER BY name")
        materials = cursor.fetchall()
        conn.close()

        self.material_combo.clear()
        for mat_id, mat_name, mat_type in materials:
            self.material_combo.addItem(f"{mat_name} ({mat_type})", mat_id)

    def add_stage(self):
        """Добавляет этап с категорией"""
        name = self.stage_name_input.text().strip()
        category = self.stage_category_combo.currentText()
        description = self.stage_description_input.toPlainText().strip()

        if not name:
            QMessageBox.warning(self, "Ошибка", "Введите название этапа")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO stages (name, category, description) VALUES (?, ?, ?)",
                (name, category, description)
            )
            conn.commit()
            self.load_stages()
            self.stage_name_input.clear()
            self.stage_description_input.clear()
            QMessageBox.information(self, "Успех", "Этап добавлен!")
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Ошибка", "Этап с таким названием уже существует")
        finally:
            conn.close()

    def delete_stage(self):
        selected_row = self.stages_table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите этап для удаления")
            return

        stage_id = int(self.stages_table.item(selected_row, 0).text())
        stage_name = self.stages_table.item(selected_row, 1).text()

        reply = QMessageBox.question(self, "Подтверждение",
                                     f"Вы уверены, что хотите удалить этап '{stage_name}'?",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM stage_products WHERE stage_id = ?", (stage_id,))
                cursor.execute("DELETE FROM stage_materials WHERE stage_id = ?", (stage_id,))
                cursor.execute("DELETE FROM stages WHERE id = ?", (stage_id,))
                conn.commit()
                self.load_stages()
                self.composition_group.setEnabled(False)
                QMessageBox.information(self, "Успех", "Этап удален")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка базы данных", str(e))
            finally:
                conn.close()

    def add_product_to_stage(self):
        if not self.selected_stage_id:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите этап")
            return

        product_id = self.product_combo.currentData()
        part = self.product_part_combo.currentText()
        quantity = self.product_quantity_input.value()

        if not product_id:
            QMessageBox.warning(self, "Ошибка", "Выберите изделие")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO stage_products (stage_id, product_id, quantity, part) VALUES (?, ?, ?, ?)",
                (self.selected_stage_id, product_id, quantity, part)
            )
            conn.commit()
            self.load_stage_products()
            self.calculate_stage_cost()
            QMessageBox.information(self, "Успех", "Изделие добавлено в этап")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка базы данных", str(e))
        finally:
            conn.close()

    def remove_product_from_stage(self):
        selected_row = self.stage_products_table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите изделие для удаления")
            return

        sp_id = int(self.stage_products_table.item(selected_row, 0).text())
        product_name = self.stage_products_table.item(selected_row, 1).text()

        reply = QMessageBox.question(self, "Подтверждение",
                                     f"Удалить изделие '{product_name}' из этапа?",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stage_products WHERE id = ?", (sp_id,))
            conn.commit()
            conn.close()
            self.load_stage_products()
            self.calculate_stage_cost()
            QMessageBox.information(self, "Успех", "Изделие удалено из этапа")

    def add_material_to_stage(self):
        if not self.selected_stage_id:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите этап")
            return

        material_id = self.material_combo.currentData()
        part = self.material_part_combo.currentText()
        quantity = self.material_quantity_input.value()
        length = self.material_length_input.text().strip()

        if not material_id:
            QMessageBox.warning(self, "Ошибка", "Выберите материал")
            return

        try:
            length_val = float(length) if length else None
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Длина должна быть числом")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        merge_to_single = 1 if self.material_merge_checkbox.isChecked() else 0
        try:
            cursor.execute(
                "INSERT INTO stage_materials (stage_id, material_id, quantity, length, part, merge_to_single) VALUES (?, ?, ?, ?, ?, ?)",
                (self.selected_stage_id, material_id, quantity, length_val, part, merge_to_single)
            )
            conn.commit()
            self.load_stage_materials()
            self.calculate_stage_cost()
            QMessageBox.information(self, "Успех", "Материал добавлен в этап")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка базы данных", str(e))
        finally:
            conn.close()

    def remove_material_from_stage(self):
        selected_row = self.stage_materials_table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите материал для удаления")
            return

        sm_id = int(self.stage_materials_table.item(selected_row, 0).text())
        material_name = self.stage_materials_table.item(selected_row, 1).text()

        reply = QMessageBox.question(self, "Подтверждение",
                                     f"Удалить материал '{material_name}' из этапа?",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM stage_materials WHERE id = ?", (sm_id,))
            conn.commit()
            conn.close()
            self.load_stage_materials()
            self.calculate_stage_cost()
            QMessageBox.information(self, "Успех", "Материал удален из этапа")

    def recalculate_all_stages_cost(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM stages")
            stage_ids = [row[0] for row in cursor.fetchall()]

            for stage_id in stage_ids:
                cursor.execute("""
                    SELECT SUM(p.cost * sp.quantity) as products_cost
                    FROM stage_products sp
                    JOIN products p ON sp.product_id = p.id
                    WHERE sp.stage_id = ?
                """, (stage_id,))
                products_cost = cursor.fetchone()[0] or 0

                cursor.execute("""
                    SELECT sm.quantity, sm.length, m.price, m.type
                    FROM stage_materials sm
                    JOIN materials m ON sm.material_id = m.id
                    WHERE sm.stage_id = ?
                """, (stage_id,))

                materials_cost = 0
                for quantity, length, price, material_type in cursor.fetchall():
                    if material_type == "Пиломатериал" and length:
                        materials_cost += price * quantity * length
                    else:
                        materials_cost += price * quantity

                total_cost = products_cost + materials_cost
                cursor.execute("UPDATE stages SET cost = ? WHERE id = ?", (total_cost, stage_id))

            conn.commit()
        except Exception as e:
            print(f"Ошибка при пересчете себестоимости этапов: {str(e)}")
            conn.rollback()
        finally:
            conn.close()

    def filter_table(self, text: str):
        """Скрывает строки, где не найден текст ни в одной ячейке."""
        text = text.lower()
        for r in range(self.stages_table.rowCount()):  # НЕ self.table, А self.stages_table
            row_text = " ".join(
                self.stages_table.item(r, c).text().lower()  # НЕ self.table, А self.stages_table
                for c in range(self.stages_table.columnCount())  # НЕ self.table, А self.stages_table
                if self.stages_table.item(r, c)  # НЕ self.table, А self.stages_table
            )
            self.stages_table.setRowHidden(r, text not in row_text)  # НЕ self.table, А self.stages_table


# КЛАСС МАТЕРИАЛОВ С АВТОЗАПОЛНЕНИЕМ
class MaterialsTab(QWidget):
    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по материалам…")
        self.search_input.textChanged.connect(self.filter_table)
        layout.addWidget(self.search_input)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "Название", "Тип", "Цена"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        self._materials_loading = False
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.itemChanged.connect(self.on_materials_item_changed)

        form_layout = QFormLayout()

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Брус 100x100")
        form_layout.addRow(QLabel("Название:"), self.name_input)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Пиломатериал", "Метиз"])
        # АВТОЗАПОЛНЕНИЕ: подключаем обработчик изменения типа
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        form_layout.addRow(QLabel("Тип:"), self.type_combo)

        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText("5.00")
        form_layout.addRow(QLabel("Цена:"), self.price_input)

        self.unit_label = QLabel("м")
        form_layout.addRow(QLabel("Ед. изм:"), self.unit_label)

        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()

        self.add_btn = QPushButton("Добавить")
        self.add_btn.clicked.connect(self.add_material)
        btn_layout.addWidget(self.add_btn)

        self.edit_btn = QPushButton("Редактировать")
        self.edit_btn.clicked.connect(self.edit_material)
        btn_layout.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.clicked.connect(self.delete_material)
        btn_layout.addWidget(self.delete_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        self.table.cellClicked.connect(self.on_table_cell_clicked)

    def on_type_changed(self, material_type):
        """АВТОЗАПОЛНЕНИЕ: Изменяет единицу измерения в зависимости от типа"""
        if material_type == "Пиломатериал":
            self.unit_label.setText("м")
        else:
            self.unit_label.setText("шт")

    def on_table_cell_clicked(self, row, column):
        try:
            if row >= 0 and self.table.item(row, 0) is not None:
                material_id = self.table.item(row, 0).text()
                name = self.table.item(row, 1).text()
                m_type = self.table.item(row, 2).text()
                price = self.table.item(row, 3).text()

                self.selected_material_id = material_id
                self.name_input.setText(name)
                self.type_combo.setCurrentText(m_type)
                self.price_input.setText(price)

                # АВТОЗАПОЛНЕНИЕ: обновляем единицу измерения
                if m_type == "Пиломатериал":
                    self.unit_label.setText("м")
                else:
                    self.unit_label.setText("шт")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка при выборе материала: {str(e)}")

    def edit_material(self):
        if not hasattr(self, 'selected_material_id'):
            QMessageBox.warning(self, "Ошибка", "Выберите материал для редактирования")
            return

        name = self.name_input.text().strip()
        m_type = self.type_combo.currentText()
        price = self.price_input.text().strip()
        unit = self.unit_label.text()

        if not name or not price:
            QMessageBox.warning(self, "Ошибка", "Название и цена обязательны для заполнения")
            return

        try:
            price_val = float(price)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Цена должна быть числом")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM materials WHERE name = ? AND id != ?", (name, self.selected_material_id))
        existing = cursor.fetchone()
        if existing:
            QMessageBox.warning(self, "Ошибка", "Материал с таким названием уже существует")
            conn.close()
            return

        try:
            cursor.execute("UPDATE materials SET name = ?, type = ?, price = ?, unit = ? WHERE id = ?",
                           (name, m_type, price_val, unit, self.selected_material_id))
            conn.commit()
            self.recalculate_products_with_material(self.selected_material_id)
            conn.close()
            self.load_data()
            self.clear_form()
            QMessageBox.information(self, "Успех", "Материал обновлен!")
        except sqlite3.Error as e:
            QMessageBox.critical(self, "Ошибка базы данных", f"Ошибка при обновлении материала: {str(e)}")
        finally:
            conn.close()

    def recalculate_products_with_material(self, material_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT DISTINCT product_id FROM product_composition WHERE material_id = ?", (material_id,))
            product_ids = [row[0] for row in cursor.fetchall()]

            for product_id in product_ids:
                cursor.execute("""SELECT m.price, pc.quantity, pc.length
                               FROM product_composition pc
                               JOIN materials m ON pc.material_id = m.id
                               WHERE pc.product_id = ?""", (product_id,))
                composition = cursor.fetchall()

                total_cost = 0
                for row in composition:
                    price, quantity, length = row
                    if length:
                        total_cost += price * quantity * length
                    else:
                        total_cost += price * quantity

                cursor.execute("UPDATE products SET cost = ? WHERE id = ?", (total_cost, product_id))

            conn.commit()
        except Exception as e:
            print(f"Ошибка при пересчете себестоимости: {str(e)}")
            conn.rollback()
        finally:
            conn.close()

    def clear_form(self):
        self.name_input.clear()
        self.price_input.clear()
        if hasattr(self, 'selected_material_id'):
            delattr(self, 'selected_material_id')

    def load_data(self):
        self._materials_loading = True
        self.table.blockSignals(True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT id, name, type, price FROM materials')
        materials = cursor.fetchall()
        conn.close()

        self.table.setRowCount(len(materials))
        for row_idx, (mid, name, mtype, price) in enumerate(materials):
            values = [mid, name, mtype, price]
            for col_idx, val in enumerate(values):
                if col_idx == 3:
                    item = QTableWidgetItem(f"{float(val or 0):.2f}")
                else:
                    item = QTableWidgetItem(str(val))

                flags = item.flags()
                if col_idx == 3:  # редактируем только цену
                    item.setFlags(flags | Qt.ItemIsEditable)
                else:
                    item.setFlags(flags & ~Qt.ItemIsEditable)

                self.table.setItem(row_idx, col_idx, item)

        self.table.blockSignals(False)
        self._materials_loading = False


    def on_materials_item_changed(self, item):
        if getattr(self, "_materials_loading", False):
            return

        row = item.row()
        col = item.column()
        if col != 3:
            return

        try:
            material_id = int(self.table.item(row, 0).text())
        except Exception:
            return

        raw = (item.text() or "").strip().replace(",", ".")
        try:
            new_price = float(raw)
        except ValueError:
            new_price = None

        if new_price is None or new_price < 0:
            QMessageBox.warning(self, "Ошибка", "Цена должна быть числом >= 0")
            self.load_data()
            return

        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("UPDATE materials SET price=? WHERE id=?", (new_price, material_id))
            conn.commit()
        finally:
            conn.close()

        # Отформатируем цену обратно в 2 знака
        self._materials_loading = True
        self.table.blockSignals(True)
        item.setText(f"{new_price:.2f}")
        self.table.blockSignals(False)
        self._materials_loading = False

        # Если у тебя есть пересчёт себестоимости изделий от материалов:
        # self.recalculate_products_with_material(material_id)

    def add_material(self):
        name = self.name_input.text().strip()
        m_type = self.type_combo.currentText()
        price = self.price_input.text().strip()
        unit = self.unit_label.text()

        if not name or not price:
            QMessageBox.warning(self, "Ошибка", "Название и цена обязательны для заполнения")
            return

        try:
            price_val = float(price)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Цена должна быть числом")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO materials (name, type, price, unit) VALUES (?, ?, ?, ?)",
                           (name, m_type, price_val, unit))
            conn.commit()
            conn.close()
            self.load_data()
            self.name_input.clear()
            self.price_input.clear()
            QMessageBox.information(self, "Успех", "Материал добавлен!")
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Ошибка", "Материал с таким названием уже существует")

    def delete_material(self):
        selected_row = self.table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите материал для удаления")
            return

        material_id = int(self.table.item(selected_row, 0).text())
        reply = QMessageBox.question(self, "Подтверждение",
                                     f"Вы уверены, что хотите удалить этот материал?",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM materials WHERE id = ?", (material_id,))
            conn.commit()
            conn.close()
            self.load_data()
            QMessageBox.information(self, "Успех", "Материал удален")

    def filter_table(self, text: str):
        """Скрывает строки, где не найден текст ни в одной ячейке."""
        text = text.lower()
        for r in range(self.table.rowCount()):
            row_text = " ".join(
                self.table.item(r, c).text().lower()
                for c in range(self.table.columnCount())
                if self.table.item(r, c)
            )
            self.table.setRowHidden(r, text not in row_text)


# КЛАСС ИЗДЕЛИЙ С АВТОЗАПОЛНЕНИЕМ
class ProductsTab(QWidget):
    def __init__(self, db_path, main_window=None):
        super().__init__()
        self.db_path = db_path
        self.main_window = main_window
        self.selected_product_id = None
        self.selected_product_name = None
        self.init_ui()
        self.load_products()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # Поисковое поле
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по изделиям…")
        self.search_input.textChanged.connect(self.filter_table)
        main_layout.addWidget(self.search_input)

        # ОСНОВНЫЕ ВКЛАДКИ: Базовые изделия и Составные изделия
        self.tabs = QTabWidget()

        # ===== ВКЛАДКА 1: БАЗОВЫЕ ИЗДЕЛИЯ =====
        basic_products_tab = QWidget()
        basic_layout = QVBoxLayout()

        products_group = QGroupBox("Базовые изделия")
        products_layout = QVBoxLayout()

        self.products_table = QTableWidget()
        self.products_table.setColumnCount(3)
        self.products_table.setHorizontalHeaderLabels(["ID", "Название", "Себестоимость"])
        self.products_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.products_table.cellClicked.connect(self.on_product_selected)
        products_layout.addWidget(self.products_table)

        form_layout = QFormLayout()
        self.product_name_input = QLineEdit()
        self.product_name_input.setPlaceholderText("Островок")
        form_layout.addRow(QLabel("Название изделия:"), self.product_name_input)

        btn_layout = QHBoxLayout()
        self.add_product_btn = QPushButton("Добавить изделие")
        self.add_product_btn.clicked.connect(self.add_product)
        btn_layout.addWidget(self.add_product_btn)

        self.delete_product_btn = QPushButton("Удалить изделие")
        self.delete_product_btn.clicked.connect(self.delete_product)
        btn_layout.addWidget(self.delete_product_btn)

        form_layout.addRow(btn_layout)
        products_layout.addLayout(form_layout)
        products_group.setLayout(products_layout)
        basic_layout.addWidget(products_group)

        # Состав базового изделия
        self.composition_group = QGroupBox("Состав изделия")
        self.composition_group.setEnabled(False)
        composition_layout = QVBoxLayout()

        self.composition_table = QTableWidget()
        self.composition_table.setColumnCount(5)
        self.composition_table.setHorizontalHeaderLabels(["ID", "Материал", "Тип", "Количество", "Длина (м)"])
        self.composition_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        composition_layout.addWidget(self.composition_table)
        self._composition_loading = False
        self.composition_table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.composition_table.itemChanged.connect(self.on_composition_item_changed)

        add_form_layout = QFormLayout()
        self.material_combo = QComboBox()
        self.material_combo.currentTextChanged.connect(self.on_material_changed_in_products)
        add_form_layout.addRow(QLabel("Материал:"), self.material_combo)

        self.quantity_input = QLineEdit()
        self.quantity_input.setPlaceholderText("1")
        add_form_layout.addRow(QLabel("Количество:"), self.quantity_input)

        self.length_input = QLineEdit()
        self.length_input.setPlaceholderText("0.75 (для пиломатериалов)")
        add_form_layout.addRow(QLabel("Длина (м):"), self.length_input)

        comp_btn_layout = QHBoxLayout()
        self.add_to_composition_btn = QPushButton("Добавить в состав")
        self.add_to_composition_btn.clicked.connect(self.add_to_composition)
        comp_btn_layout.addWidget(self.add_to_composition_btn)

        self.remove_from_composition_btn = QPushButton("Удалить из состава")
        self.remove_from_composition_btn.clicked.connect(self.remove_from_composition)
        comp_btn_layout.addWidget(self.remove_from_composition_btn)

        add_form_layout.addRow(comp_btn_layout)
        composition_layout.addLayout(add_form_layout)

        self.cost_label = QLabel("Себестоимость: 0.00 руб")
        composition_layout.addWidget(self.cost_label)

        self.composition_group.setLayout(composition_layout)
        basic_layout.addWidget(self.composition_group)

        basic_products_tab.setLayout(basic_layout)
        self.tabs.addTab(basic_products_tab, "Базовые изделия")

        # ===== ВКЛАДКА 2: СОСТАВНЫЕ ИЗДЕЛИЯ =====
        composite_tab = QWidget()
        composite_layout = QVBoxLayout()

        composite_group = QGroupBox("Составные изделия")
        composite_group_layout = QVBoxLayout()

        self.composite_table = QTableWidget()
        self.composite_table.setColumnCount(3)
        self.composite_table.setHorizontalHeaderLabels(["ID", "Название", "Себестоимость"])
        self.composite_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.composite_table.cellClicked.connect(self.on_composite_selected)
        composite_group_layout.addWidget(self.composite_table)

        composite_form = QFormLayout()
        self.composite_name_input = QLineEdit()
        self.composite_name_input.setPlaceholderText("Веревочная трасса №1")
        composite_form.addRow(QLabel("Название составного изделия:"), self.composite_name_input)

        composite_btn_layout = QHBoxLayout()
        self.add_composite_btn = QPushButton("Создать составное изделие")
        self.add_composite_btn.clicked.connect(self.add_composite_product)
        composite_btn_layout.addWidget(self.add_composite_btn)

        self.delete_composite_btn = QPushButton("Удалить составное изделие")
        self.delete_composite_btn.clicked.connect(self.delete_composite_product)
        composite_btn_layout.addWidget(self.delete_composite_btn)

        self.calculate_composite_cost_btn = QPushButton("Рассчитать себестоимость")
        self.calculate_composite_cost_btn.clicked.connect(self.calculate_composite_cost)
        composite_btn_layout.addWidget(self.calculate_composite_cost_btn)

        composite_form.addRow(composite_btn_layout)
        composite_group_layout.addLayout(composite_form)
        composite_group.setLayout(composite_group_layout)
        composite_layout.addWidget(composite_group)

        # Состав составного изделия
        self.composite_composition_group = QGroupBox("Состав составного изделия")
        self.composite_composition_group.setEnabled(False)
        comp_composition_layout = QVBoxLayout()

        self.composite_composition_table = QTableWidget()
        self.composite_composition_table.setColumnCount(4)
        self.composite_composition_table.setHorizontalHeaderLabels(["ID", "Базовое изделие", "Количество", "Стоимость"])
        self.composite_composition_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        comp_composition_layout.addWidget(self.composite_composition_table)
        self._composite_loading = False
        self.composite_composition_table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.composite_composition_table.itemChanged.connect(self.on_composite_item_changed)

        comp_add_form = QFormLayout()
        self.basic_product_combo = QComboBox()
        comp_add_form.addRow(QLabel("Базовое изделие:"), self.basic_product_combo)

        self.comp_quantity_input = QLineEdit()
        self.comp_quantity_input.setPlaceholderText("1")
        comp_add_form.addRow(QLabel("Количество:"), self.comp_quantity_input)

        comp_comp_btn_layout = QHBoxLayout()
        self.add_to_composite_btn = QPushButton("Добавить в составное изделие")
        self.add_to_composite_btn.clicked.connect(self.add_to_composite_composition)
        comp_comp_btn_layout.addWidget(self.add_to_composite_btn)

        self.remove_from_composite_btn = QPushButton("Удалить из составного")
        self.remove_from_composite_btn.clicked.connect(self.remove_from_composite_composition)
        comp_comp_btn_layout.addWidget(self.remove_from_composite_btn)

        comp_add_form.addRow(comp_comp_btn_layout)
        comp_composition_layout.addLayout(comp_add_form)

        self.composite_cost_label = QLabel("Себестоимость составного изделия: 0.00 руб")
        comp_composition_layout.addWidget(self.composite_cost_label)

        self.composite_composition_group.setLayout(comp_composition_layout)
        composite_layout.addWidget(self.composite_composition_group)

        composite_tab.setLayout(composite_layout)
        self.tabs.addTab(composite_tab, "Составные изделия")

        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

    def add_composite_product(self):
        """Создает новое составное изделие"""
        name = self.composite_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Введите название составного изделия")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO products (name, is_composite) VALUES (?, 1)", (name,))
            conn.commit()
            self.load_composite_products()
            self.load_basic_products_for_composite()
            self.composite_name_input.clear()
            QMessageBox.information(self, "Успех", "Составное изделие создано")
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Ошибка", "Изделие с таким названием уже существует")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка базы данных", str(e))
        finally:
            conn.close()

    def on_composite_selected(self, row, column):
        """Обработка выбора составного изделия"""
        try:
            if row >= 0 and self.composite_table.item(row, 0) is not None:
                self.selected_composite_id = int(self.composite_table.item(row, 0).text())
                self.composite_composition_group.setEnabled(True)
                self.load_composite_composition()
                self.calculate_composite_cost()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка при выборе составного изделия: {str(e)}")

    def load_composite_products(self):
        """Загружает составные изделия"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, cost FROM products WHERE is_composite = 1 ORDER BY name")
        products = cursor.fetchall()
        conn.close()

        self.composite_table.setRowCount(len(products))
        for row_idx, (product_id, name, cost) in enumerate(products):
            self.composite_table.setItem(row_idx, 0, QTableWidgetItem(str(product_id)))
            self.composite_table.setItem(row_idx, 1, QTableWidgetItem(name))
            self.composite_table.setItem(row_idx, 2, QTableWidgetItem(f"{cost:.2f} руб"))

    def load_basic_products_for_composite(self):
        """Загружает базовые изделия для добавления в составные"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM products WHERE is_composite = 0 ORDER BY name")
        products = cursor.fetchall()
        conn.close()

        self.basic_product_combo.clear()
        for prod_id, prod_name in products:
            self.basic_product_combo.addItem(prod_name, prod_id)

    def load_composite_composition(self):
        """Загружает состав выбранного составного изделия"""
        if not hasattr(self, 'selected_composite_id'):
            return

        self._composite_loading = True
        self.composite_composition_table.blockSignals(True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""SELECT cp.id, p.name, cp.quantity, p.cost * cp.quantity
                         FROM composite_products cp
                         JOIN products p ON cp.component_id = p.id
                         WHERE cp.composite_id = ?""", (self.selected_composite_id,))
        composition = cursor.fetchall()
        conn.close()

        self.composite_composition_table.setRowCount(len(composition))
        for row_idx, (comp_id, name, quantity, cost) in enumerate(composition):
            row_items = [
                QTableWidgetItem(str(comp_id)),
                QTableWidgetItem(name),
                QTableWidgetItem(str(quantity)),
                QTableWidgetItem(f"{cost:.2f}")
            ]

            for col_idx, it in enumerate(row_items):
                flags = it.flags()
                if col_idx == 2:  # редактируем только количество
                    it.setFlags(flags | Qt.ItemIsEditable)
                else:
                    it.setFlags(flags & ~Qt.ItemIsEditable)
                self.composite_composition_table.setItem(row_idx, col_idx, it)

        self.composite_composition_table.blockSignals(False)
        self._composite_loading = False

    def on_composite_item_changed(self, item):
        if getattr(self, "_composite_loading", False):
            return

        row = item.row()
        col = item.column()
        if col != 2:
            return

        try:
            comp_id = int(self.composite_composition_table.item(row, 0).text())
        except Exception:
            return

        raw = (item.text() or "").strip().replace(",", ".")
        try:
            q = int(float(raw))
        except ValueError:
            q = None

        if q is None or q < 0:
            QMessageBox.warning(self, "Ошибка", "Количество должно быть целым числом >= 0")
            self.load_composite_composition()
            return

        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            if q == 0:
                cur.execute("DELETE FROM composite_products WHERE id=?", (comp_id,))
            else:
                cur.execute("UPDATE composite_products SET quantity=? WHERE id=?", (q, comp_id))
            conn.commit()
        finally:
            conn.close()

        self.load_composite_composition()
        self.calculate_composite_cost()

    def add_to_composite_composition(self):
        """Добавляет базовое изделие в состав составного"""
        if not hasattr(self, 'selected_composite_id'):
            QMessageBox.warning(self, "Ошибка", "Сначала выберите составное изделие")
            return

        component_id = self.basic_product_combo.currentData()
        quantity = self.comp_quantity_input.text().strip()

        if not component_id or not quantity:
            QMessageBox.warning(self, "Ошибка", "Выберите изделие и укажите количество")
            return

        try:
            quantity_val = int(quantity)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Количество должно быть целым числом")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO composite_products (composite_id, component_id, quantity) VALUES (?, ?, ?)",
                (self.selected_composite_id, component_id, quantity_val))
            conn.commit()
            self.load_composite_composition()
            self.calculate_composite_cost()
            self.comp_quantity_input.clear()
            QMessageBox.information(self, "Успех", "Изделие добавлено в состав")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка базы данных", str(e))
        finally:
            conn.close()

    def remove_from_composite_composition(self):
        """Удаляет изделие из состава составного изделия"""
        selected_row = self.composite_composition_table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите изделие для удаления")
            return

        comp_id = int(self.composite_composition_table.item(selected_row, 0).text())
        component_name = self.composite_composition_table.item(selected_row, 1).text()

        reply = QMessageBox.question(self, "Подтверждение",
                                     f"Удалить изделие '{component_name}' из состава?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM composite_products WHERE id = ?", (comp_id,))
            conn.commit()
            conn.close()
            self.load_composite_composition()
            self.calculate_composite_cost()
            QMessageBox.information(self, "Успех", "Изделие удалено из состава")

    def calculate_composite_cost(self):
        """Рассчитывает себестоимость составного изделия"""
        if not hasattr(self, 'selected_composite_id') or self.selected_composite_id is None:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # Рассчитываем стоимость через составляющие изделия
            cursor.execute("""SELECT SUM(p.cost * cp.quantity)
                             FROM composite_products cp
                             JOIN products p ON cp.component_id = p.id
                             WHERE cp.composite_id = ?""", (self.selected_composite_id,))

            result = cursor.fetchone()
            total_cost = result[0] if result[0] else 0.0

            self.composite_cost_label.setText(f"Себестоимость составного изделия: {total_cost:.2f} руб")

            # Обновляем стоимость в БД
            cursor.execute("UPDATE products SET cost = ? WHERE id = ?", (total_cost, self.selected_composite_id))
            conn.commit()

            # Обновляем таблицу составных изделий
            self.load_composite_products()

            # Очищаем кэш в заказах если есть
            if self.main_window and hasattr(self.main_window, 'orders_tab'):
                if hasattr(self.main_window.orders_tab, 'product_cost_cache'):
                    if self.selected_composite_id in self.main_window.orders_tab.product_cost_cache:
                        del self.main_window.orders_tab.product_cost_cache[self.selected_composite_id]

        except Exception as e:
            QMessageBox.critical(self, "Ошибка расчета", f"Произошла ошибка: {str(e)}")
        finally:
            conn.close()

    def delete_composite_product(self):
        """Удаляет составное изделие"""
        if not hasattr(self, 'selected_composite_id'):
            QMessageBox.warning(self, "Ошибка", "Выберите составное изделие для удаления")
            return

        selected_row = self.composite_table.currentRow()
        if selected_row == -1:
            return

        product_name = self.composite_table.item(selected_row, 1).text()
        reply = QMessageBox.question(self, "Подтверждение",
                                     f"Вы уверены, что хотите удалить составное изделие '{product_name}'?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            try:
                # Удаляем связи составного изделия
                cursor.execute("DELETE FROM composite_products WHERE composite_id = ?", (self.selected_composite_id,))
                # Удаляем само изделие
                cursor.execute("DELETE FROM products WHERE id = ?", (self.selected_composite_id,))
                conn.commit()
                self.load_composite_products()
                self.composite_composition_group.setEnabled(False)
                self.composite_composition_table.setRowCount(0)
                QMessageBox.information(self, "Успех", "Составное изделие удалено")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка базы данных", str(e))
            finally:
                conn.close()

    # НОВАЯ ФУНКЦИЯ АВТОЗАПОЛНЕНИЯ ДЛЯ ИЗДЕЛИЙ
    def on_material_changed_in_products(self, material_text):
        """АВТОЗАПОЛНЕНИЕ: Заполняет длину в зависимости от типа материала в изделиях"""
        if not material_text:
            return

        try:
            # Извлекаем ID материала из ComboBox
            material_id = self.material_combo.currentData()
            if not material_id:
                return

            # Получаем тип материала из БД
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT type FROM materials WHERE id = ?", (material_id,))
            result = cursor.fetchone()
            conn.close()

            if result:
                material_type = result[0]
                if material_type == "Метиз":
                    # Для метизов автоматически ставим длину 0
                    self.length_input.setText("0")
                    self.length_input.setEnabled(False)
                    self.length_input.setToolTip("Длина для метизов всегда 0")
                else:
                    # Для пиломатериалов включаем поле и очищаем
                    self.length_input.setEnabled(True)
                    if self.length_input.text() == "0":
                        self.length_input.clear()
                    self.length_input.setToolTip("Введите длину в метрах")

        except Exception as e:
            print(f"Ошибка при автозаполнении материала в изделиях: {e}")

    def recalculate_all_products_cost(self):
        """Пересчитывает себестоимость ВСЕХ изделий (базовых и составных)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # Сначала пересчитываем базовые изделия (is_composite = 0)
            cursor.execute("SELECT id FROM products WHERE is_composite = 0")
            basic_product_ids = [row[0] for row in cursor.fetchall()]

            for product_id in basic_product_ids:
                cursor.execute("""SELECT m.price, pc.quantity, pc.length
                                 FROM product_composition pc
                                 JOIN materials m ON pc.material_id = m.id
                                 WHERE pc.product_id = ?""", (product_id,))
                composition = cursor.fetchall()

                total_cost = 0
                for row in composition:
                    price, quantity, length = row
                    if length:
                        total_cost += price * quantity * length
                    else:
                        total_cost += price * quantity

                cursor.execute("UPDATE products SET cost = ? WHERE id = ?", (total_cost, product_id))

            # Затем пересчитываем составные изделия (is_composite = 1)
            cursor.execute("SELECT id FROM products WHERE is_composite = 1")
            composite_product_ids = [row[0] for row in cursor.fetchall()]

            for composite_id in composite_product_ids:
                cursor.execute("""SELECT SUM(p.cost * cp.quantity)
                                 FROM composite_products cp
                                 JOIN products p ON cp.component_id = p.id
                                 WHERE cp.composite_id = ?""", (composite_id,))

                result = cursor.fetchone()
                total_cost = result[0] if result[0] else 0.0
                cursor.execute("UPDATE products SET cost = ? WHERE id = ?", (total_cost, composite_id))

            conn.commit()

        except Exception as e:
            print(f"Ошибка при пересчете себестоимости изделий: {str(e)}")
            conn.rollback()
        finally:
            conn.close()

    def load_products(self):
        """Загружает базовые изделия"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, cost FROM products WHERE is_composite = 0 ORDER BY name")
        products = cursor.fetchall()
        conn.close()

        self.products_table.setRowCount(len(products))
        for row_idx, (product_id, name, cost) in enumerate(products):
            self.products_table.setItem(row_idx, 0, QTableWidgetItem(str(product_id)))
            self.products_table.setItem(row_idx, 1, QTableWidgetItem(name))
            self.products_table.setItem(row_idx, 2, QTableWidgetItem(f"{cost:.2f} руб"))

        # Также обновляем составные изделия
        self.load_composite_products()
        self.load_basic_products_for_composite()

    def on_product_selected(self, row, column):
        """Обработка выбора БАЗОВОГО изделия (только is_composite = 0)"""
        try:
            if row >= 0 and self.products_table.item(row, 0) is not None:
                product_id = int(self.products_table.item(row, 0).text())

                # ПРОВЕРЯЕМ, что это базовое изделие
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name, is_composite FROM products WHERE id = ?", (product_id,))
                result = cursor.fetchone()
                conn.close()

                if result and result[1] == 0:  # Только базовые изделия (is_composite = 0)
                    self.selected_product_id = product_id
                    self.selected_product_name = result[0]
                    self.composition_group.setEnabled(True)
                    self.composition_group.setTitle(f"Состав изделия: {self.selected_product_name}")
                    self.load_materials()
                    self.load_composition()
                    self.calculate_product_cost()
                else:
                    QMessageBox.warning(self, "Ошибка", "Выберите базовое изделие для редактирования состава")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка при выборе изделия: {str(e)}")

    def load_materials(self):
        """Загружает материалы для добавления в состав изделия"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, type FROM materials ORDER BY name")
        materials = cursor.fetchall()
        conn.close()

        self.material_combo.clear()
        for mat_id, mat_name, mat_type in materials:
            self.material_combo.addItem(f"{mat_name} ({mat_type})", mat_id)

    def load_composition(self):
        """Загружает состав выбранного БАЗОВОГО изделия"""
        if not hasattr(self, 'selected_product_id') or self.selected_product_id is None:
            return

        self._composition_loading = True
        self.composition_table.blockSignals(True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""SELECT pc.id, m.name, m.type, pc.quantity, pc.length
                         FROM product_composition pc
                         JOIN materials m ON pc.material_id = m.id
                         WHERE pc.product_id = ?""", (self.selected_product_id,))
        composition = cursor.fetchall()
        conn.close()

        self.composition_table.setRowCount(len(composition))
        for row_idx, (comp_id, mat_name, mat_type, quantity, length) in enumerate(composition):
            row = [
                QTableWidgetItem(str(comp_id)),
                QTableWidgetItem(mat_name),
                QTableWidgetItem(mat_type),
                QTableWidgetItem(str(quantity)),
                QTableWidgetItem("" if length is None else str(length)),
            ]

            for col_idx, item in enumerate(row):
                flags = item.flags()
                # Редактируем только: Количество (3) и Длина (4)
                if col_idx in (3, 4):
                    item.setFlags(flags | Qt.ItemIsEditable)
                else:
                    item.setFlags(flags & ~Qt.ItemIsEditable)
                self.composition_table.setItem(row_idx, col_idx, item)

        self.composition_table.blockSignals(False)
        self._composition_loading = False

    def on_composition_item_changed(self, item):
        if getattr(self, "_composition_loading", False):
            return

        row = item.row()
        col = item.column()

        # editable только quantity/length
        if col not in (3, 4):
            return

        try:
            comp_id = int(self.composition_table.item(row, 0).text())
        except Exception:
            return

        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()

            if col == 3:
                raw = (item.text() or "").strip().replace(",", ".")
                try:
                    q = int(float(raw))
                except ValueError:
                    q = None
                if q is None or q < 0:
                    QMessageBox.warning(self, "Ошибка", "Количество должно быть целым числом >= 0")
                    self.load_composition()
                    return
                if q == 0:
                    # логично: 0 => удалить строку состава
                    cur.execute("DELETE FROM product_composition WHERE id=?", (comp_id,))
                else:
                    cur.execute("UPDATE product_composition SET quantity=? WHERE id=?", (q, comp_id))

            else:  # col == 4
                raw = (item.text() or "").strip().replace(",", ".")
                if raw == "":
                    cur.execute("UPDATE product_composition SET length=NULL WHERE id=?", (comp_id,))
                else:
                    try:
                        l = float(raw)
                    except ValueError:
                        l = None
                    if l is None or l < 0:
                        QMessageBox.warning(self, "Ошибка", "Длина должна быть числом >= 0 (или пусто)")
                        self.load_composition()
                        return
                    cur.execute("UPDATE product_composition SET length=? WHERE id=?", (l, comp_id))

            conn.commit()
        finally:
            conn.close()

        self.load_composition()
        self.calculate_product_cost()

    def add_product(self):
        """Добавляет новое базовое изделие"""
        name = self.product_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Введите название изделия")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO products (name, is_composite) VALUES (?, 0)", (name,))
            conn.commit()
            self.load_products()
            self.product_name_input.clear()
            QMessageBox.information(self, "Успех", "Изделие добавлено")
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Ошибка", "Изделие с таким названием уже существует")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка базы данных", str(e))
        finally:
            conn.close()

    def delete_product(self):
        """Удаляет БАЗОВОЕ изделие (только is_composite = 0)"""
        selected_row = self.products_table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите изделие для удаления")
            return

        product_id = int(self.products_table.item(selected_row, 0).text())
        product_name = self.products_table.item(selected_row, 1).text()

        # ПРОВЕРЯЕМ, что это базовое изделие
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT is_composite FROM products WHERE id = ?", (product_id,))
        result = cursor.fetchone()

        if result and result[0] != 0:  # Если составное изделие
            conn.close()
            QMessageBox.warning(self, "Ошибка",
                                "Используйте вкладку 'Составные изделия' для удаления составных изделий")
            return

        # ПРОВЕРЯЕМ, не используется ли в составных изделиях
        cursor.execute("SELECT COUNT(*) FROM composite_products WHERE component_id = ?", (product_id,))
        usage_count = cursor.fetchone()[0]

        if usage_count > 0:
            conn.close()
            QMessageBox.warning(self, "Ошибка",
                                f"Изделие '{product_name}' используется в {usage_count} составных изделиях.\n"
                                "Сначала удалите его из всех составных изделий.")
            return

        conn.close()

        reply = QMessageBox.question(self, "Подтверждение",
                                     f"Вы уверены, что хотите удалить изделие '{product_name}'?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM product_composition WHERE product_id = ?", (product_id,))
                cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
                conn.commit()
                self.load_products()
                self.composition_group.setEnabled(False)
                self.composition_table.setRowCount(0)
                QMessageBox.information(self, "Успех", "Изделие удалено")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка базы данных", str(e))
            finally:
                conn.close()

    def add_to_composition(self):
        """Добавляет материал в состав БАЗОВОГО изделия"""
        if not hasattr(self, 'selected_product_id'):
            QMessageBox.warning(self, "Ошибка", "Сначала выберите базовое изделие")
            return

        material_id = self.material_combo.currentData()
        quantity = self.quantity_input.text().strip()
        length = self.length_input.text().strip()

        if not material_id or not quantity:
            QMessageBox.warning(self, "Ошибка", "Выберите материал и укажите количество")
            return

        try:
            quantity_val = int(quantity)
            length_val = float(length) if length else None
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Количество должно быть целым числом, длина — числом")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO product_composition (product_id, material_id, quantity, length) VALUES (?, ?, ?, ?)",
                (self.selected_product_id, material_id, quantity_val, length_val))
            conn.commit()
            self.load_composition()
            self.calculate_product_cost()
            self.quantity_input.clear()
            self.length_input.clear()
            QMessageBox.information(self, "Успех", "Материал добавлен в состав")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка базы данных", str(e))
        finally:
            conn.close()

    def remove_from_composition(self):
        """Удаляет материал из состава изделия"""
        selected_row = self.composition_table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите материал для удаления")
            return

        comp_id = int(self.composition_table.item(selected_row, 0).text())
        material_name = self.composition_table.item(selected_row, 1).text()

        reply = QMessageBox.question(self, "Подтверждение",
                                   f"Удалить материал '{material_name}' из состава?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM product_composition WHERE id = ?", (comp_id,))
            conn.commit()
            conn.close()
            self.load_composition()
            self.calculate_product_cost()
            QMessageBox.information(self, "Успех", "Материал удален из состава")

    def calculate_product_cost(self):
        """Рассчитывает себестоимость БАЗОВОГО изделия (только is_composite = 0)"""
        if not hasattr(self, 'selected_product_id') or self.selected_product_id is None:
            QMessageBox.warning(self, "Ошибка", "Сначала выберите базовое изделие")
            return

        # ПРОВЕРЯЕМ, что это базовое изделие
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT is_composite FROM products WHERE id = ?", (self.selected_product_id,))
        result = cursor.fetchone()

        if result and result[0] != 0:  # Если составное изделие
            conn.close()
            QMessageBox.warning(self, "Ошибка", "Используйте вкладку 'Составные изделия' для расчета составных изделий")
            return

        try:
            cursor.execute("""SELECT m.price, pc.quantity, pc.length  
                             FROM product_composition pc  
                             JOIN materials m ON pc.material_id = m.id  
                             WHERE pc.product_id = ?""", (self.selected_product_id,))
            composition = cursor.fetchall()

            total_cost = 0
            for row in composition:
                price, quantity, length = row
                if length:
                    total_cost += price * quantity * length
                else:
                    total_cost += price * quantity

            self.cost_label.setText(f"Себестоимость: {total_cost:.2f} руб")

            cursor.execute("UPDATE products SET cost = ? WHERE id = ?", (total_cost, self.selected_product_id))
            conn.commit()

            # Обновляем таблицу продуктов
            self.load_products()

            # Очищаем кэш в заказах если есть
            if self.main_window and hasattr(self.main_window, 'orders_tab'):
                if hasattr(self.main_window.orders_tab, 'product_cost_cache'):
                    if self.selected_product_id in self.main_window.orders_tab.product_cost_cache:
                        del self.main_window.orders_tab.product_cost_cache[self.selected_product_id]

        except Exception as e:
            QMessageBox.critical(self, "Ошибка расчета", f"Произошла ошибка: {str(e)}")
        finally:
            conn.close()

    def filter_table(self, text: str):
        """Скрывает строки, где не найден текст ни в одной ячейке."""
        text = text.lower()

        # Фильтр для базовых изделий
        for r in range(self.products_table.rowCount()):
            row_text = " ".join(
                self.products_table.item(r, c).text().lower()
                for c in range(self.products_table.columnCount())
                if self.products_table.item(r, c)
            )
            self.products_table.setRowHidden(r, text not in row_text)

        # Фильтр для составных изделий
        for r in range(self.composite_table.rowCount()):
            row_text = " ".join(
                self.composite_table.item(r, c).text().lower()
                for c in range(self.composite_table.columnCount())
                if self.composite_table.item(r, c)
            )
            self.composite_table.setRowHidden(r, text not in row_text)


class WarehouseTab(QWidget):

    def __init__(self, db_path, main_window):
        super().__init__()
        self.db_path = db_path
        self.main_window = main_window
        self.init_ui()
        self.load_data()


    def init_ui(self):
        main_layout = QVBoxLayout()
        # Группа для добавления на склад
        add_group = QGroupBox("Добавить на склад")
        add_layout = QFormLayout()

        self.material_combo = QComboBox()
        self.load_materials()
        self.material_combo.currentTextChanged.connect(self.on_warehouse_material_changed)
        add_layout.addRow(QLabel("Материал:"), self.material_combo)

        self.length_input = QLineEdit()
        self.length_input.setPlaceholderText("0 для метизов, иначе длина в метрах")
        add_layout.addRow(QLabel("Длина:"), self.length_input)

        self.quantity_input = QLineEdit()
        self.quantity_input.setPlaceholderText("Количество")
        add_layout.addRow(QLabel("Количество:"), self.quantity_input)

        self.add_btn = QPushButton("Добавить на склад")
        self.add_btn.clicked.connect(self.add_to_warehouse)
        add_layout.addRow(self.add_btn)
        add_group.setLayout(add_layout)
        main_layout.addWidget(add_group)

        # Поиск по складу (по материалам)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по материалам на складе…")
        self.search_input.textChanged.connect(self.filter_warehouse_table)
        main_layout.addWidget(self.search_input)

        # Таблица склада
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["ID", "Материал", "Длина", "Количество"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        main_layout.addWidget(self.table)
        self._warehouse_loading = False
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.table.itemChanged.connect(self.on_warehouse_item_changed)

        # Кнопки управления
        btn_layout = QHBoxLayout()
        self.delete_btn = QPushButton("Удалить выбранное")
        self.delete_btn.clicked.connect(self.delete_item)
        btn_layout.addWidget(self.delete_btn)
        main_layout.addLayout(btn_layout)

        # Группа облачной синхронизации
        cloud_group = QGroupBox("Облачная синхронизация")
        cloud_layout = QHBoxLayout()
        self.cloud_download_btn = QPushButton("Обновить с облака")
        self.cloud_download_btn.clicked.connect(self.cloud_download)
        self.cloud_upload_btn = QPushButton("Сохранить в облако")
        self.cloud_upload_btn.clicked.connect(self.cloud_upload)
        cloud_layout.addWidget(self.cloud_download_btn)
        cloud_layout.addWidget(self.cloud_upload_btn)
        cloud_group.setLayout(cloud_layout)
        main_layout.addWidget(cloud_group)

        self.setLayout(main_layout)



    def cloud_download(self):
        token = "y0__xDGx8DJARjrnzsgnMHG-BR-KZ19Xw3vp5ZtUe-FRHIfDz_1sA"
        remote_path = "/apps/SpaceConcept/database.db"
        if not token:
            QMessageBox.critical(self, "Ошибка", "Переменная YANDEX_TOKEN не задана")
            return
        try:
            download_db(token, remote_path, self.db_path)
            if self.mainwindow and hasattr(self.mainwindow, "reloadAllTabs"):
                self.mainwindow.reloadAllTabs()
            QMessageBox.information(self, "Готово", "Данные обновлены из облака")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сети", str(e))

    def cloud_upload(self):
        token = "y0__xDGx8DJARjrnzsgnMHG-BR-KZ19Xw3vp5ZtUe-FRHIfDz_1sA"
        remote_path = "/apps/SpaceConcept/database.db"
        if not token:
            QMessageBox.critical(self, "Ошибка", "Переменная YANDEX_TOKEN не задана")
            return
        try:
            upload_db(token, remote_path, self.db_path)
            QMessageBox.information(self, "Готово", "Данные успешно сохранены в облако")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка сети", str(e))

    def load_materials(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM materials")
        materials = cursor.fetchall()
        conn.close()

        self.material_combo.clear()
        for mat_id, mat_name in materials:
            self.material_combo.addItem(mat_name, mat_id)

    def load_data(self):
        self._warehouse_loading = True
        self.table.blockSignals(True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""SELECT w.id, m.name, w.length, w.quantity
            FROM warehouse w
            JOIN materials m ON w.material_id = m.id
            ORDER BY m.name""")
        warehouse = cursor.fetchall()
        conn.close()

        self.table.setRowCount(len(warehouse))
        for row_idx, row_data in enumerate(warehouse):
            for col_idx, col_data in enumerate(row_data):
                item = QTableWidgetItem(str(col_data))

                # Разрешаем редактировать ТОЛЬКО "Количество" (колонка 3)
                flags = item.flags()
                if col_idx == 3:
                    item.setFlags(flags | Qt.ItemIsEditable)
                else:
                    item.setFlags(flags & ~Qt.ItemIsEditable)

                self.table.setItem(row_idx, col_idx, item)

        self.table.blockSignals(False)
        self._warehouse_loading = False

    def add_to_warehouse(self):
        material_id = self.material_combo.currentData()
        length = self.length_input.text().strip()
        quantity = self.quantity_input.text().strip()

        if not material_id or not length or not quantity:
            QMessageBox.warning(self, "Ошибка", "Все поля обязательны для заполнения")
            return

        try:
            length_val = float(length)
            quantity_val = int(quantity)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Длина и количество должны быть числами")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT id FROM warehouse WHERE material_id = ? AND length = ?",
                           (material_id, length_val))
            existing = cursor.fetchone()

            if existing:
                cursor.execute("UPDATE warehouse SET quantity = quantity + ? WHERE id = ?",
                               (quantity_val, existing[0]))
            else:
                cursor.execute("INSERT INTO warehouse (material_id, length, quantity) VALUES (?, ?, ?)",
                               (material_id, length_val, quantity_val))

            conn.commit()
            self.load_data()

            # Очищаем только количество — чтобы можно было сразу добавить тот же материал ещё раз
            self.quantity_input.clear()
            self.quantity_input.setFocus()

            # Длину не трогаем: для "Метиз" она должна оставаться 0 и поле часто заблокировано
            # (если вдруг поле отключено и пустое — восстановим 0)
            if not self.length_input.isEnabled() and not self.length_input.text().strip():
                self.length_input.setText("0")

            QMessageBox.information(self, "Успех", "Склад обновлен!")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка базы данных", str(e))
        finally:
            conn.close()

    def delete_item(self):
        selected_row = self.table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите запись для удаления")
            return

        item_id = int(self.table.item(selected_row, 0).text())

        reply = QMessageBox.question(self, "Подтверждение удаления",
                                     "Вы уверены, что хотите удалить эту запись?",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM warehouse WHERE id = ?", (item_id,))
            conn.commit()
            conn.close()
            self.load_data()
            QMessageBox.information(self, "Успех", "Запись удалена")

    def on_warehouse_item_changed(self, item):
        if getattr(self, "_warehouse_loading", False):
            return

        row = item.row()
        col = item.column()

        # редактируем только "Количество"
        if col != 3:
            return

        try:
            item_id = int(self.table.item(row, 0).text())
        except Exception:
            return

        raw = (item.text() or "").strip().replace(",", ".")
        try:
            new_qty = int(float(raw))
        except ValueError:
            new_qty = None

        if new_qty is None or new_qty < 0:
            QMessageBox.warning(self, "Ошибка", "Количество должно быть целым числом >= 0")
            self._warehouse_loading = True
            self.table.blockSignals(True)
            # откатим значение из БД
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT quantity FROM warehouse WHERE id=?", (item_id,))
            db_qty = cur.fetchone()
            conn.close()
            item.setText(str(db_qty[0] if db_qty else 0))
            self.table.blockSignals(False)
            self._warehouse_loading = False
            return

        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            if new_qty == 0:
                cur.execute("DELETE FROM warehouse WHERE id=?", (item_id,))
            else:
                cur.execute("UPDATE warehouse SET quantity=? WHERE id=?", (new_qty, item_id))
            conn.commit()
        finally:
            conn.close()

        # Перезагрузим таблицу, чтобы корректно исчезали строки при qty=0
        self.load_data()

    def on_warehouse_material_changed(self, material_text):
        """
        Автозаполнение: при выборе метиза длина = 0 и блокируется,
        для пиломатериала поле активируется.
        """
        if not material_text:
            return

        try:
            material_id = self.material_combo.currentData()
            if not material_id:
                return

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT type FROM materials WHERE id = ?", (material_id,))
            result = cursor.fetchone()
            conn.close()

            if not result:
                return

            mat_type = result[0]

            if mat_type == "Метиз":
                self.length_input.setText("0")  # ИСПРАВЛЕНО: добавил self перед length_input
                self.length_input.setEnabled(False)
                self.length_input.setToolTip("Длина для метизов всегда 0")
            else:
                self.length_input.setEnabled(True)
                if self.length_input.text() == "0":
                    self.length_input.clear()
                self.length_input.setToolTip("Введите длину в метрах")

        except Exception as e:
            print(f"Ошибка автозаполнения на складе: {e}")

    def filter_table(self, text: str):
        """Скрывает строки, где не найден текст ни в одной ячейке."""
        text = text.lower()
        for r in range(self.table.rowCount()):
            row_text = " ".join(
                self.table.item(r, c).text().lower()
                for c in range(self.table.columnCount())
                if self.table.item(r, c)
            )
            self.table.setRowHidden(r, text not in row_text)

    def filter_warehouse_table(self, text: str):
        """Фильтр на складе: ищем только по колонке 'Материал'."""
        text = (text or "").strip().lower()

        for r in range(self.table.rowCount()):
            item = self.table.item(r, 1)  # 1 = колонка "Материал"
            material = item.text().lower() if item else ""
            self.table.setRowHidden(r, text not in material)

class OrdersTab(QWidget):
    def __init__(self, db_path, main_window):
        super().__init__()
        self.db_path = db_path
        self.main_window = main_window
        self.init_ui()

        # ИСПРАВЛЕНИЕ 3: Загружаем изделия по умолчанию (так как "Изделие" выбрано по умолчанию)
        self.load_products()

        self.current_order = []
        self.product_cost_cache = {}
        self.stage_cost_cache = {}

        self.load_order_history()

    def init_ui(self):
        main_layout = QVBoxLayout()

        order_group = QGroupBox("Создать заказ")
        order_layout = QVBoxLayout()

        self.order_table = QTableWidget()
        self.order_table.setColumnCount(6)
        self.order_table.setHorizontalHeaderLabels(
            ["Тип", "Название", "Количество", "Длина (м)", "Себестоимость", "Действия"])
        self.order_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.order_table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        order_layout.addWidget(self.order_table)

        form_layout = QFormLayout()

        self.item_type_combo = QComboBox()
        self.item_type_combo.addItems(["Изделие", "Этап"])
        self.item_type_combo.currentTextChanged.connect(self.on_item_type_changed)
        form_layout.addRow(QLabel("Тип:"), self.item_type_combo)

        self.item_combo = QComboBox()
        form_layout.addRow(QLabel("Выберите:"), self.item_combo)

        self.quantity_spin = QSpinBox()
        self.quantity_spin.setMinimum(1)
        self.quantity_spin.setMaximum(999)
        self.quantity_spin.setValue(1)
        form_layout.addRow(QLabel("Количество:"), self.quantity_spin)

        self.length_spin = QDoubleSpinBox()
        self.length_spin.setDecimals(2)
        self.length_spin.setMinimum(0.01)
        self.length_spin.setMaximum(9999.0)
        self.length_spin.setSingleStep(0.10)
        form_layout.addRow(QLabel("Длина (м):"), self.length_spin)
        self.length_spin.hide()  # по умолчанию скрыто (для Изделия)

        self.add_to_order_btn = QPushButton("Добавить в заказ")
        self.add_to_order_btn.clicked.connect(self.add_to_order)
        form_layout.addRow(self.add_to_order_btn)

        order_layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        self.calculate_btn = QPushButton("Рассчитать заказ")
        self.calculate_btn.clicked.connect(self.calculate_order)
        btn_layout.addWidget(self.calculate_btn)

        self.confirm_btn = QPushButton("Подтвердить заказ")
        self.confirm_btn.clicked.connect(self.confirm_order)
        btn_layout.addWidget(self.confirm_btn)
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setToolTip("Сначала нажмите «Рассчитать заказ» и убедитесь, что материалов достаточно.")

        self.clear_btn = QPushButton("Очистить заказ")
        self.clear_btn.clicked.connect(self.clear_order)
        btn_layout.addWidget(self.clear_btn)

        order_layout.addLayout(btn_layout)

        self.instructions_text = QTextEdit()
        self.instructions_text.setReadOnly(True)
        self.instructions_text.setMinimumHeight(150)
        order_layout.addWidget(QLabel("Окно сообщений:"))
        order_layout.addWidget(self.instructions_text)

        self.total_cost_label = QLabel("Общая себестоимость: 0.00 руб")
        self.total_cost_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        order_layout.addWidget(self.total_cost_label)

        order_group.setLayout(order_layout)
        main_layout.addWidget(order_group)

        history_group = QGroupBox("История заказов")
        history_layout = QVBoxLayout()
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["ID", "Дата", "Позиций", "Сумма"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.cellDoubleClicked.connect(self.show_order_details)
        history_layout.addWidget(self.history_table)

        history_buttons_layout = QHBoxLayout()
        self.open_pdf_btn = QPushButton("Открыть PDF")
        self.open_pdf_btn.clicked.connect(self.open_selected_pdf)
        history_buttons_layout.addWidget(self.open_pdf_btn)

        self.refresh_history_btn = QPushButton("Обновить историю")
        self.refresh_history_btn.clicked.connect(self.load_order_history)
        history_buttons_layout.addWidget(self.refresh_history_btn)
        history_buttons_layout.addStretch()
        history_layout.addLayout(history_buttons_layout)

        history_group.setLayout(history_layout)
        main_layout.addWidget(history_group)

        # ДОБАВЛЯЕМ КНОПКУ РАСЧЕТА СТРАХОВОЧНОГО ТРОСА
        self.calculate_rope_btn = QPushButton("Рассчитать и добавить страховочный трос к заказу")
        self.calculate_rope_btn.clicked.connect(self.calculate_safety_rope)
        btn_layout.addWidget(self.calculate_rope_btn)

        self.import_txt_btn = QPushButton("Импорт из .txt заказа")
        self.import_txt_btn.clicked.connect(self.import_order_from_txt)
        btn_layout.addWidget(self.import_txt_btn)


        self.setLayout(main_layout)

    def _invalidate_order_calculation(self):
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.setToolTip("Заказ изменён — пересчитайте его перед подтверждением.")
        self._last_calc_result = None
        self._last_calc_requirements = None

    def import_order_from_txt(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите .txt файл заказа", "", "Text Files (*.txt)")
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                txt = f.read()
            items = self.parse_order_txt(txt)
            if not items:
                QMessageBox.warning(self, "Импорт заказа", "В файле не удалось найти позиции заказа!")
                return
            self.fill_order_table_from_txt(items)
            QMessageBox.information(self, "Импорт заказа", "Позиции заказа успешно импортированы!")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))

    def parse_order_txt(self, txt):
        """
        Находит в .txt такие строки:
        1. Изделие "Зигзаг" - 1 шт...
        Возвращает: список словарей [{"name": "...", "qty": ...}]
        """
        matches = re.findall(r'Изделие\s+"([^"]+)"\s*-\s*(\d+)\s*шт', txt)
        items = []
        for name, qty in matches:
            items.append({"name": name.strip(), "qty": int(qty)})
        return items

    def fill_order_table_from_txt(self, items):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM products")
        prod_map = {name: pid for pid, name in cursor.fetchall()}
        conn.close()

        self.clear_order()
        for item in items:
            prod_id = prod_map.get(item['name'])
            if not prod_id:
                QMessageBox.warning(self, "Не найдено изделие", f"В базе нет изделия: {item['name']}")
                continue
            rowcount = self.order_table.rowCount()
            self.order_table.insertRow(rowcount)
            type_item = QTableWidgetItem("Изделие")
            self.order_table.setItem(rowcount, 0, type_item)
            name_item = QTableWidgetItem(item['name'])
            name_item.setData(Qt.UserRole, prod_id)
            self.order_table.setItem(rowcount, 1, name_item)
            qty_item = QTableWidgetItem(str(item['qty']))
            self.order_table.setItem(rowcount, 2, qty_item)
            length_item = QTableWidgetItem("")
            self.order_table.setItem(rowcount, 3, length_item)
            cost_per_unit = self.get_product_cost(prod_id)
            total_cost = cost_per_unit * item['qty']
            cost_item = QTableWidgetItem(f"{total_cost:.2f}")
            self.order_table.setItem(rowcount, 4, cost_item)
            remove_btn = QPushButton("Удалить")
            remove_btn.clicked.connect(lambda _, r=rowcount: self.remove_from_order(r))
            self.order_table.setCellWidget(rowcount, 5, remove_btn)

        self._update_current_order()
        self.update_total_cost()

    def calculate_rope_materials(self, routes):
        """
        Исправленный расчет материалов страховочного троса.
        Теперь правильно работает с полными трассами, включая динамические этапы.
        """
        total_rope = 0.0
        total_clamps = 0

        for route in routes:
            if not route:  # Пустая трасса
                continue

            # Разбиваем трассу на сегменты (как в show_preview)
            segments = []
            current_segment = None

            for stage in route:
                stage_type = 'static' if stage['category'] == 'Статика' else 'dynamic'

                if current_segment is None or current_segment['type'] != stage_type:
                    # Начинаем новый сегмент
                    current_segment = {'type': stage_type, 'stages': [stage]}
                    segments.append(current_segment)
                else:
                    # Продолжаем текущий сегмент
                    current_segment['stages'].append(stage)

            # Рассчитываем трос только для статических сегментов
            for segment in segments:
                if segment['type'] == 'static':
                    N = len(segment['stages'])
                    L = sum(stage['length'] for stage in segment['stages'])
                    rope = 5 + 5 * N + L
                    clamps = 6 + 6 * N
                    total_rope += rope
                    total_clamps += clamps

        return total_rope, total_clamps

    def calculate_safety_rope(self):
        """Рассчитывает и добавляет страховочный трос в заказ"""
        # Получаем все этапы из заказа
        stages_in_order = []
        for row in range(self.order_table.rowCount()):
            if self.order_table.item(row, 0) and self.order_table.item(row, 0).text() == "Этап":
                stage_id = self.order_table.item(row, 1).data(Qt.UserRole) if self.order_table.item(row, 1) else None
                stage_name = self.order_table.item(row, 1).text() if self.order_table.item(row,
                                                                                           1) else "Неизвестный этап"
                length_text = self.order_table.item(row, 3).text() if self.order_table.item(row, 3) else "0"

                try:
                    length = float(length_text)
                except (ValueError, AttributeError):
                    length = 0.0

                if stage_id:
                    # Получаем категорию этапа
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.execute("SELECT category FROM stages WHERE id = ?", (stage_id,))
                    result = cursor.fetchone()
                    category = result[0] if result else "Статика"
                    conn.close()

                    stages_in_order.append({
                        'id': stage_id,
                        'name': stage_name,
                        'length': length,
                        'category': category
                    })

        if not stages_in_order:
            QMessageBox.warning(self, "Ошибка", "В заказе нет этапов для расчета страховочного троса")
            return

        # Проверяем, есть ли статические этапы
        static_stages = [s for s in stages_in_order if s['category'] == 'Статика']
        if not static_stages:
            QMessageBox.information(self, "Информация",
                                    f"В заказе только динамические/зип этапы ({len(stages_in_order)} шт.).\n"
                                    "Страховочный трос не требуется.")
            return

        dynamic_count = len(stages_in_order) - len(static_stages)
        info_msg = f"В заказе:\n• Статических этапов: {len(static_stages)}\n• Динамических/Зип: {dynamic_count}"

        # Открываем диалог планирования трасс
        dialog = RoutesPlanningDialog(stages_in_order, self)

        # Показываем информацию перед планированием
        QMessageBox.information(self, "Планирование трасс",
                                f"{info_msg}\n\nСейчас откроется окно планирования трасс.\n"
                                "Динамические этапы разрывают страховочный трос!")

        if dialog.exec_() == QDialog.Accepted:
            routes = dialog.get_routes()
            if routes:
                total_rope, total_clamps = self.calculate_rope_materials(routes)
                self.add_rope_to_order(total_rope, total_clamps)

                # Показываем детальный отчет
                routes_info = f"Создано трасс троса: {len(routes)}\n"
                for i, route in enumerate(routes, 1):
                    routes_info += f"Трасса {i}: {len(route)} этапов\n"

                QMessageBox.information(self, "Расчет завершен",
                                        f"{routes_info}\nДобавлено:\n"
                                        f"• Трос М12: {total_rope:.2f} м\n"
                                        f"• Зажимы М12: {total_clamps} шт")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось создать трассы для страховочного троса")

    def add_rope_to_order(self, rope_length, clamps_count):
        """Исправленный метод добавления материалов страховочного троса в заказ"""
        try:
            # Получаем ID материалов из БД
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT id, price FROM materials WHERE name = 'Трос М12'")
            rope_result = cursor.fetchone()
            cursor.execute("SELECT id, price FROM materials WHERE name = 'Зажим М12'")
            clamp_result = cursor.fetchone()
            conn.close()

            if not rope_result or not clamp_result:
                QMessageBox.warning(self, "Ошибка",
                                    "Материалы 'Трос М12' или 'Зажим М12' не найдены в базе данных.\n"
                                    "Добавьте эти материалы в раздел 'Материалы'")
                return

            rope_id, rope_price = rope_result
            clamp_id, clamp_price = clamp_result

            # Добавляем позиции в заказ
            for material_name, material_id, amount, price in [
                ("Трос М12", rope_id, rope_length, rope_price),
                ("Зажим М12", clamp_id, clamps_count, clamp_price),
            ]:
                row = self.order_table.rowCount()
                self.order_table.insertRow(row)

                # Тип позиции
                self.order_table.setItem(row, 0, QTableWidgetItem("Материал"))

                # Название с ID в данных
                item = QTableWidgetItem(material_name)
                item.setData(Qt.UserRole, material_id)
                self.order_table.setItem(row, 1, item)

                # Количество (округляем зажимы до целого числа)
                quantity_text = f"{amount:.2f}" if material_name.startswith("Трос") else str(int(amount))
                self.order_table.setItem(row, 2, QTableWidgetItem(quantity_text))

                # Длина (пустая для материалов)
                self.order_table.setItem(row, 3, QTableWidgetItem(""))

                # Стоимость
                total_cost = amount * price
                self.order_table.setItem(row, 4, QTableWidgetItem(f"{total_cost:.2f} руб"))

                # Кнопка удаления
                delete_btn = QPushButton("Удалить")
                delete_btn.clicked.connect(partial(self.remove_from_order, row))
                self.order_table.setCellWidget(row, 5, delete_btn)

            # Обновляем кнопки удаления для всех строк
            for r in range(self.order_table.rowCount()):
                widget = self.order_table.cellWidget(r, 5)
                if isinstance(widget, QPushButton):
                    widget.clicked.disconnect()
                    widget.clicked.connect(partial(self.remove_from_order, r))

            self.update_total_cost()

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при добавлении троса: {str(e)}")

    def on_item_type_changed(self, item_type):
        """Переключение между Изделием и Этапом с показом поля длины для этапа"""
        self.item_combo.clear()
        if item_type == "Изделие":
            self.length_spin.hide()
            self.quantity_spin.show()
            self.load_products()
        else:
            self.length_spin.show()
            self.quantity_spin.hide()
            self.load_stages()

    def load_products(self):
        """Загружает ВСЕ изделия (базовые + составные) для заказов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Загружаем все изделия с пометкой типа
        cursor.execute("""SELECT id, name, is_composite FROM products ORDER BY is_composite, name""")
        products = cursor.fetchall()
        conn.close()

        self.item_combo.clear()
        for prod_id, prod_name, is_composite in products:
            display_name = f"[Составное] {prod_name}" if is_composite else prod_name
            self.item_combo.addItem(display_name, prod_id)

    def get_product_cost(self, product_id):
        """Получает стоимость изделия (базового или составного)"""
        if product_id in self.product_cost_cache:
            return self.product_cost_cache[product_id]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT cost, is_composite FROM products WHERE id = ?", (product_id,))
        result = cursor.fetchone()
        conn.close()

        if result:
            cost, is_composite = result
            # Для составных изделий пересчитываем стоимость, если нужно
            if is_composite and cost == 0:
                cost = self.calculate_composite_product_cost(product_id)
                # Обновляем в БД
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("UPDATE products SET cost = ? WHERE id = ?", (cost, product_id))
                conn.commit()
                conn.close()

            self.product_cost_cache[product_id] = cost
            return cost
        return 0

    def calculate_composite_product_cost(self, composite_id):
        """Рассчитывает стоимость составного изделия через его компоненты"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT SUM(p.cost * cp.quantity)
            FROM composite_products cp
            JOIN products p ON cp.component_id = p.id
            WHERE cp.composite_id = ?
        """, (composite_id,))

        result = cursor.fetchone()
        conn.close()

        return result[0] if result[0] else 0.0

    def load_stages(self):
        """Загружает ТОЛЬКО этапы в выпадающий список"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM stages ORDER BY name")
        stages = cursor.fetchall()
        conn.close()

        # Очищаем и заполняем список этапами
        self.item_combo.clear()
        for stage_id, stage_name in stages:
            self.item_combo.addItem(stage_name, stage_id)

    def add_to_order(self):
        """Добавление позиции в заказ: для Этапа учитываем длину, для Изделия — количество"""
        item_id = self.item_combo.currentData()
        item_name = self.item_combo.currentText()
        item_type = self.item_type_combo.currentText()

        if not item_id:
            QMessageBox.warning(self, "Ошибка", f"Выберите {item_type.lower()}")
            return

        if item_type == "Изделие":
            quantity = self.quantity_spin.value()
            cost_per_unit = self._get_product_cost(item_id)

            row_count = self.order_table.rowCount()
            self.order_table.setRowCount(row_count + 1)

            self.order_table.setItem(row_count, 0, QTableWidgetItem(item_type))

            name_item = QTableWidgetItem(item_name)
            name_item.setData(Qt.UserRole, item_id)
            name_item.setData(Qt.UserRole + 1, item_type)
            self.order_table.setItem(row_count, 1, name_item)

            self.order_table.setItem(row_count, 2, QTableWidgetItem(str(quantity)))
            self.order_table.setItem(row_count, 3, QTableWidgetItem(""))  # длина пустая для изделия
            self.order_table.setItem(row_count, 4, QTableWidgetItem(f"{cost_per_unit * quantity:.2f} руб"))

            delete_btn = QPushButton("Удалить")
            delete_btn.clicked.connect(lambda: self.remove_from_order(row_count))
            self.order_table.setCellWidget(row_count, 5, delete_btn)

        else:  # Этап
            # ИСПРАВЛЕНО: НЕ округляем длину, сохраняем точное значение
            length_m = self.length_spin.value()  # Убрано round()

            if length_m <= 0:
                QMessageBox.warning(self, "Ошибка", "Длина этапа должна быть больше 0")
                return

            cost_total = self._compute_stage_cost(stage_id=item_id, length_m=length_m)

            row_count = self.order_table.rowCount()
            self.order_table.setRowCount(row_count + 1)

            self.order_table.setItem(row_count, 0, QTableWidgetItem(item_type))

            name_item = QTableWidgetItem(item_name)
            name_item.setData(Qt.UserRole, item_id)
            name_item.setData(Qt.UserRole + 1, item_type)
            name_item.setData(Qt.UserRole + 2, length_m)  # сохраним точную длину
            self.order_table.setItem(row_count, 1, name_item)

            self.order_table.setItem(row_count, 2, QTableWidgetItem("1"))  # количество строкой = 1 для этапа

            # ИСПРАВЛЕНО: показываем точную длину с 2 знаками после запятой
            self.order_table.setItem(row_count, 3, QTableWidgetItem(f"{length_m:.2f}"))
            self.order_table.setItem(row_count, 4, QTableWidgetItem(f"{cost_total:.2f} руб"))

            delete_btn = QPushButton("Удалить")
            delete_btn.clicked.connect(lambda: self.remove_from_order(row_count))
            self.order_table.setCellWidget(row_count, 5, delete_btn)

        self._update_current_order()
        self.update_total_cost()
        self._invalidate_order_calculation()

    def _get_product_cost(self, product_id):
        if product_id in self.product_cost_cache:
            return self.product_cost_cache[product_id]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT cost FROM products WHERE id = ?", (product_id,))
        cost = cursor.fetchone()[0]
        conn.close()

        self.product_cost_cache[product_id] = cost
        return cost

    def _get_stage_cost(self, stage_id):
        if stage_id in self.stage_cost_cache:
            return self.stage_cost_cache[stage_id]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT cost FROM stages WHERE id = ?", (stage_id,))
        cost = cursor.fetchone()[0]
        conn.close()

        self.stage_cost_cache[stage_id] = cost
        return cost

    def _update_current_order(self):
        self.current_order = []
        for row in range(self.order_table.rowCount()):
            item_type = self.order_table.item(row, 0).text()
            item_id = int(self.order_table.item(row, 1).data(Qt.UserRole))
            quantity = int(self.order_table.item(row, 2).text())
            self.current_order.append((item_type, item_id, quantity))

    def remove_from_order(self, row):
        """Безопасно удаляет строку и обновляет индексы кнопок."""
        if 0 <= row < self.order_table.rowCount():
            self.order_table.removeRow(row)
            # Перепривязываем все лямбды удаления с новыми индексами
            for r in range(self.order_table.rowCount()):
                widget = self.order_table.cellWidget(r, 5)
                if isinstance(widget, QPushButton):
                    widget.clicked.disconnect()
                    widget.clicked.connect(partial(self.remove_from_order, r))
            self.update_total_cost()
            self._invalidate_order_calculation()

    def on_cell_double_clicked(self, row, column):
        # Редактирование количества для изделия и длины (м) для этапа
        item_type = self.order_table.item(row, 0).text()
        item_id = int(self.order_table.item(row, 1).data(Qt.UserRole))

        if item_type == "Изделие" and column == 2:
            dialog = QDialog(self)
            dialog.setWindowTitle("Изменение количества")
            dialog.setFixedSize(300, 150)
            layout = QVBoxLayout()
            item_name = self.order_table.item(row, 1).text()
            layout.addWidget(QLabel(f"Позиция: {item_name}"))
            spin_box = QSpinBox()
            spin_box.setMinimum(1)
            spin_box.setMaximum(999)
            spin_box.setValue(int(self.order_table.item(row, 2).text()))
            layout.addWidget(QLabel("Новое количество:"))
            layout.addWidget(spin_box)
            btn_layout = QHBoxLayout()
            ok_btn = QPushButton("OK");
            cancel_btn = QPushButton("Отмена")
            ok_btn.clicked.connect(dialog.accept);
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(ok_btn);
            btn_layout.addWidget(cancel_btn)
            layout.addLayout(btn_layout)
            dialog.setLayout(layout)
            if dialog.exec_() == QDialog.Accepted:
                new_quantity = spin_box.value()
                self.order_table.item(row, 2).setText(str(new_quantity))
                cost_per_unit = self._get_product_cost(item_id)
                new_cost = cost_per_unit * new_quantity
                self.order_table.item(row, 4).setText(f"{new_cost:.2f} руб")
                self._update_current_order()
                self.update_total_cost()

        if item_type == "Этап" and column == 3:
            dialog = QDialog(self)
            dialog.setWindowTitle("Изменение длины (м)")
            dialog.setFixedSize(320, 160)
            layout = QVBoxLayout()
            item_name = self.order_table.item(row, 1).text()
            layout.addWidget(QLabel(f"Этап: {item_name}"))

            spin = QDoubleSpinBox()
            spin.setDecimals(2)  # ИСПРАВЛЕНО: 2 знака после запятой
            spin.setMinimum(0.01)
            spin.setMaximum(9999.0)
            spin.setSingleStep(0.01)  # ИСПРАВЛЕНО: шаг 0.01 вместо 0.10

            current_len_text = self.order_table.item(row, 3).text() or "0"
            try:
                current_len = float(current_len_text)
            except ValueError:
                current_len = 1.00
            spin.setValue(current_len if current_len > 0 else 1.00)

            layout.addWidget(QLabel("Новая длина (м):"))
            layout.addWidget(spin)
            btn_layout = QHBoxLayout()
            ok_btn = QPushButton("OK")
            cancel_btn = QPushButton("Отмена")
            ok_btn.clicked.connect(dialog.accept)
            cancel_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(ok_btn)
            btn_layout.addWidget(cancel_btn)
            layout.addLayout(btn_layout)
            dialog.setLayout(layout)

            if dialog.exec_() == QDialog.Accepted:
                # ИСПРАВЛЕНО: НЕ округляем новую длину
                new_len = spin.value()  # Убрано round()
                self.order_table.item(row, 3).setText(f"{new_len:.2f}")

                # пересчёт стоимости строки с точной длиной
                new_cost = self._compute_stage_cost(item_id, new_len)
                self.order_table.item(row, 4).setText(f"{new_cost:.2f} руб")

                # обновим сохранённую длину в UserRole+2 у названия
                name_item = self.order_table.item(row, 1)
                name_item.setData(Qt.UserRole + 2, new_len)  # Сохраняем точную длину

                self._update_current_order()
                self.update_total_cost()
        self._invalidate_order_calculation()
    def update_total_cost(self):
        total = 0.0
        for row in range(self.order_table.rowCount()):
            cost_text = self.order_table.item(row, 4).text().replace(' руб', '')
            total += float(cost_text or 0)
        self.total_cost_label.setText(f"Общая себестоимость: {total:.2f} руб")

    def clear_order(self):
        self.order_table.setRowCount(0)
        self.current_order = []
        self.instructions_text.clear()
        self.total_cost_label.setText("Общая себестоимость: 0.00 руб")
        self._invalidate_order_calculation()

    def calculate_order(self):
        if not self.current_order:
            QMessageBox.warning(self, "Ошибка", "Заказ пуст")
            return

        try:
            # Получаем требования и пересчитываем себестоимость по факту
            total_cost = 0.0
            requirements = defaultdict(int)  # суммируем целые количества и длины

            # Расширяем заказ в требования
            _, req_details = self._expand_order_to_requirements()

            # Суммируем требования
            for material, items in req_details.items():
                for qty, _ in items:
                    requirements[material] += qty

            # Подсчитываем себестоимость исходя из реальных требований
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            for material, total_qty in requirements.items():
                cursor.execute("SELECT price, type FROM materials WHERE name = ?", (material,))
                row = cursor.fetchone()
                if not row:
                    continue
                unit_price, mtype = row
                # для пиломатериалов cost за метр, для метизов cost за штуку
                total_cost += unit_price * total_qty
            conn.close()

            # Оптимизация резки
            stock_items = self._get_current_stock()
            optimizer = CuttingOptimizer()
            result = optimizer.optimize_cutting(req_details, stock_items, self.db_path)
            # сохранить результат расчёта, чтобы confirm мог использовать (не обязательно, но удобно)
            self._last_calc_result = result
            self._last_calc_requirements = req_details  # это то, что вы отдаёте в optimize_cutting

            if result.get('can_produce'):
                self.confirm_btn.setEnabled(True)
                self.confirm_btn.setToolTip("Материалов достаточно — можно подтверждать заказ.")
            else:
                self.confirm_btn.setEnabled(False)
                self.confirm_btn.setToolTip("Материалов недостаточно — подтвердить заказ нельзя.")

            # Формируем сообщение по материалам
            materials_message = "📦 Требуемые материалы:\n\n"
            # Получаем типы материалов из базы данных
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name, type FROM materials")
            material_types = {name: mtype for name, mtype in cursor.fetchall()}
            conn.close()

            for material, total_qty in requirements.items():
                material_type = material_types.get(material, "Метиз")  # По умолчанию считаем метизом
                unit = "м" if material_type == "Пиломатериал" else "шт"
                materials_message += f"• {material}: {total_qty:.2f} {unit}\n"

            # Проверка достаточности
            if result['can_produce']:
                availability = "\n✅ Материалов достаточно для производства"
            else:
                availability = "\n❌ Материалов недостаточно:\n"
                for err in result['missing']:
                    availability += f" - {err}\n"

            # Итоговые расчеты
            instructions = "📊 Расчет заказа:\n\n"
            instructions += f"💰 Себестоимость: {total_cost:.2f} руб\n"
            instructions += f"💰 Цена реализации: {total_cost * 4:.2f} руб\n\n"
            instructions += materials_message + availability

            self.instructions_text.setText(instructions)
            self.total_cost_label.setText(f"Общая себестоимость: {total_cost:.2f} руб")

        except Exception as e:
            QMessageBox.critical(self, "Критическая ошибка", f"Ошибка при расчете заказа: {e}")
            import traceback;
            print(traceback.format_exc())

    def _expand_order_to_requirements(self):
        """Расширяет заказ до требований материалов с правильной логикой для этапов"""
        total_cost = 0.0
        requirements = defaultdict(list)

        for row in range(self.order_table.rowCount()):
            item_type = self.order_table.item(row, 0).text()
            name_item = self.order_table.item(row, 1)
            item_id = int(name_item.data(Qt.UserRole))
            quantity = int(self.order_table.item(row, 2).text())

            if item_type == "Изделие":
                # Логика для изделий остается без изменений
                product_cost = self.get_product_cost(item_id)
                total_cost += product_cost * quantity

                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT name, is_composite FROM products WHERE id = ?", (item_id,))
                result = cursor.fetchone()
                product_name = result[0] if result else "Изделие"
                is_composite = result[1] if result else 0

                # ВАЖНО: source = реальное имя изделия
                source_label = product_name

                if is_composite:
                    self._expand_composite_product_requirements(cursor, item_id, quantity, requirements, source_label)
                else:
                    self._expand_basic_product_requirements(cursor, item_id, quantity, requirements, source_label)

                conn.close()

            else:  # Этап
                # ИСПРАВЛЕННАЯ ЛОГИКА ДЛЯ ЭТАПОВ
                length_m = float(name_item.data(Qt.UserRole + 2)) if name_item.data(Qt.UserRole + 2) else 1.0
                stage_cost = self._compute_stage_cost(item_id, length_m)  # Используем исправленную функцию
                total_cost += stage_cost

                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                cursor.execute("SELECT name FROM stages WHERE id = ?", (item_id,))
                stage_name = cursor.fetchone()[0]

                # Материалы, которые записаны прямо в этапе (не в составе изделий этапа) → должны подписываться именем этапа
                self._expand_stage_material_requirements(cursor, item_id, length_m, requirements, stage_name)

                # Материалы, которые приходят из изделий этапа → должны подписываться именем конкретного изделия
                self._expand_stage_product_requirements(cursor, item_id, length_m, requirements, stage_name)

                conn.close()

        return total_cost, requirements

    def _expand_composite_product_requirements(self, cursor, composite_id, quantity, requirements, source):
        """Разворачивает составное изделие в базовые изделия"""
        cursor.execute("""
            SELECT cp.component_id, cp.quantity
            FROM composite_products cp
            WHERE cp.composite_id = ?
        """, (composite_id,))

        components = cursor.fetchall()

        for component_id, component_qty in components:
            total_component_qty = component_qty * quantity

            # Проверяем, не является ли компонент тоже составным
            cursor.execute("SELECT is_composite FROM products WHERE id = ?", (component_id,))
            result = cursor.fetchone()
            is_composite = result[0] if result else 0

            if is_composite:
                # Рекурсивно разворачиваем составной компонент
                self._expand_composite_product_requirements(cursor, component_id, total_component_qty, requirements,
                                                            source)
            else:
                # Разворачиваем базовое изделие в материалы
                self._expand_basic_product_requirements(cursor, component_id, total_component_qty, requirements, source)

    def _expand_basic_product_requirements(self, cursor, product_id, quantity, requirements, source):
        """Разворачивает базовое изделие в материалы"""
        cursor.execute("""
            SELECT m.name, m.type, pc.quantity, pc.length
            FROM product_composition pc
            JOIN materials m ON pc.material_id = m.id
            WHERE pc.product_id = ?
        """, (product_id,))

        materials = cursor.fetchall()

        for material, mtype, mat_quantity, length in materials:
            total_qty = mat_quantity * quantity
            if mtype == "Пиломатериал" and length:
                for _ in range(int(total_qty)):
                    requirements[material].append((length, source))
            else:
                requirements[material].append((total_qty, source))

    def _expand_stage_material_requirements(self, cursor, stage_id, length_m, requirements, stage_name):
        """
        Правильное развертывание материалов этапа с учетом частей start/meter/end
        """
        cursor.execute("""
            SELECT m.name, m.type, sm.quantity, sm.length, sm.part, sm.merge_to_single
            FROM stage_materials sm
            JOIN materials m ON sm.material_id = m.id
            WHERE sm.stage_id = ?
        """, (stage_id,))

        stage_materials = cursor.fetchall()

        for material, m_type, quantity, length, part, merge_to_single in stage_materials:
            if part == "meter":
                if m_type == "Пиломатериал" and length:
                    if int(merge_to_single) == 1:
                        # ЦЕЛЬНЫЙ: один отрезок суммарной длины (без ceil)
                        total_length = float(quantity) * float(length_m) * float(length)
                        requirements[material].append((total_length, stage_name))
                        continue
                    else:
                        # КАК БЫЛО: N одинаковых кусков (ceil по количеству)
                        total_qty = math.ceil(quantity * length_m)
                else:
                    total_qty = math.ceil(quantity * length_m)
            else:
                total_qty = quantity

            # стандартное добавление (start/end и обычный meter)
            if m_type == "Пиломатериал" and length:
                for _ in range(int(total_qty)):
                    requirements[material].append((length, stage_name))
            else:
                requirements[material].append((total_qty, stage_name))

    def _expand_stage_product_requirements(self, cursor, stage_id, length_m, requirements, stage_name):

        """
        Правильное развертывание изделий этапа с учетом частей start/meter/end
        """
        cursor.execute("""
            SELECT sp.product_id, sp.quantity, sp.part, p.is_composite, p.name
            FROM stage_products sp
            JOIN products p ON sp.product_id = p.id
            WHERE sp.stage_id = ?

        """, (stage_id,))

        stage_products = cursor.fetchall()

        for product_id, quantity, part, is_composite, product_name in stage_products:

            if part == "meter":
                # Для meter части: количество умножаем на длину и округляем вверх
                total_qty = math.ceil(quantity * length_m)
            else:
                # Для start/end: количество как есть
                total_qty = quantity

            # Разворачиваем изделие в материалы
            if is_composite:
                # Разворачиваем составное изделие
                # source = конкретное изделие внутри этапа
                source_label = product_name if product_name else stage_name
                if total_qty and int(total_qty) > 1:
                    source_label = f"{source_label}({int(total_qty)}шт)"

                self._expand_composite_product_requirements(cursor, product_id, total_qty, requirements, source_label)
            else:
                # Разворачиваем базовое изделие
                # source = конкретное изделие внутри этапа
                source_label = product_name if product_name else stage_name
                if total_qty and int(total_qty) > 1:
                    source_label = f"{source_label}({int(total_qty)}шт)"
                self._expand_basic_product_requirements(cursor, product_id, total_qty, requirements, source_label)

    def _get_product_name(self, product_id: int) -> str:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT name FROM products WHERE id = ?", (product_id,))
        row = c.fetchone()
        conn.close()
        return row if row else f"Изделие #{product_id}"

    def _compute_stage_cost(self, stage_id: int, length_m: float) -> float:
        """
        Новый расчет стоимости этапа произвольной длины (с округлением позиций как в calculate_order)
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            total_cost = 0.0

            # ===== РАСЧЕТ СТОИМОСТИ ИЗДЕЛИЙ В ЭТАПЕ =====
            cursor.execute("""
                    SELECT sp.part, p.cost, sp.quantity, p.is_composite
                    FROM stage_products sp
                    JOIN products p ON sp.product_id = p.id
                    WHERE sp.stage_id = ?
                """, (stage_id,))

            for part, p_cost, qty, is_composite in cursor.fetchall():
                if part == "meter":
                    # Для meter части: количество умножаем на длину и округляем вверх
                    qty_total = math.ceil(qty * length_m)
                else:
                    # Для start/end: количество как есть
                    qty_total = qty

                total_cost += p_cost * qty_total

            # ===== РАСЧЕТ СТОИМОСТИ МАТЕРИАЛОВ В ЭТАПЕ =====
            cursor.execute("""
                    SELECT sm.part, m.type, m.price, sm.quantity, sm.length
                    FROM stage_materials sm
                    JOIN materials m ON sm.material_id = m.id
                    WHERE sm.stage_id = ?
                """, (stage_id,))

            for part, m_type, price, qty, length_val in cursor.fetchall():
                if part == "meter":
                    # Для meter части: количество умножаем на длину и округляем вверх
                    qty_total = math.ceil(qty * length_m)
                else:
                    # Для start/end: количество как есть
                    qty_total = qty

                # Рассчитываем стоимость материала
                if m_type == "Пиломатериал" and length_val:
                    total_cost += price * qty_total * length_val
                else:
                    total_cost += price * qty_total

            conn.close()
            return total_cost

        except Exception as e:
            print(f"Ошибка при расчете стоимости этапа {stage_id}: {e}")
            return 0.0

    def _get_row_length_for_stage(self, stage_id: int) -> float:
        # ищем строку в таблице заказа с этим stage_id и читаем колонку "Длина (м)"
        for row in range(self.order_table.rowCount()):
            if self.order_table.item(row, 0).text() == "Этап":
                name_item = self.order_table.item(row, 1)
                if int(name_item.data(Qt.UserRole)) == stage_id:
                    # сначала смотрим сохранённое значение
                    saved = name_item.data(Qt.UserRole + 2)
                    if saved is not None:
                        return float(saved)
                    # иначе читаем из ячейки
                    txt = self.order_table.item(row, 3).text() or "0"
                    try:
                        return float(txt)
                    except Exception:
                        return 0.0
        return 0.0

    def _get_stage_materials(self, stage_id, quantity):
        materials_summary = defaultdict(float)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Материалы из изделий в этапе
        cursor.execute("""
        SELECT m.name, m.type, pc.quantity, pc.length, sp.quantity as stage_qty
        FROM stage_products sp
        JOIN product_composition pc ON sp.product_id = pc.product_id
        JOIN materials m ON pc.material_id = m.id
        WHERE sp.stage_id = ?
        """, (stage_id,))

        for name, mtype, comp_quantity, length, stage_qty in cursor.fetchall():
            total_qty = comp_quantity * stage_qty * quantity
            if mtype == "Пиломатериал" and length:
                materials_summary[name] += total_qty * length
            else:
                materials_summary[name] += total_qty

        # Материалы напрямую в этапе
        cursor.execute("""
        SELECT m.name, m.type, sm.quantity, sm.length
        FROM stage_materials sm
        JOIN materials m ON sm.material_id = m.id
        WHERE sm.stage_id = ?
        """, (stage_id,))

        for name, mtype, sm_quantity, length in cursor.fetchall():
            total_qty = sm_quantity * quantity
            if mtype == "Пиломатериал" and length:
                materials_summary[name] += total_qty * length
            else:
                materials_summary[name] += total_qty

        conn.close()
        return materials_summary

    def _calculate_material_requirements(self):
        requirements = defaultdict(list)

        for item_type, item_id, quantity in self.current_order:
            if item_type == "Изделие":
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                cursor.execute("SELECT name FROM products WHERE id = ?", (item_id,))
                product_name = cursor.fetchone()[0]

                cursor.execute("""SELECT m.name, m.type, pc.quantity, pc.length
                FROM product_composition pc
                JOIN materials m ON pc.material_id = m.id
                WHERE pc.product_id = ?""", (item_id,))

                for material, mtype, comp_quantity, length in cursor.fetchall():
                    if mtype == "Пиломатериал" and length:
                        for _ in range(int(comp_quantity * quantity)):
                            requirements[material].append((length, product_name))
                    else:
                        requirements[material].append((comp_quantity * quantity, product_name))
                conn.close()

            else:  # Этап
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                cursor.execute("SELECT name FROM stages WHERE id = ?", (item_id,))
                stage_name = cursor.fetchone()[0]

                # Материалы из изделий в этапе
                cursor.execute("""
                SELECT m.name, m.type, pc.quantity, pc.length, sp.quantity as stage_qty, p.name as product_name
                FROM stage_products sp
                JOIN products p ON sp.product_id = p.id
                JOIN product_composition pc ON sp.product_id = pc.product_id
                JOIN materials m ON pc.material_id = m.id
                WHERE sp.stage_id = ?
                """, (item_id,))

                for material, mtype, comp_qty, length, stage_qty, product_name in cursor.fetchall():
                    total_qty = comp_qty * stage_qty * quantity
                    item_description = f"{stage_name}({product_name})"

                    if mtype == "Пиломатериал" and length:
                        for _ in range(int(total_qty)):
                            requirements[material].append((length, item_description))
                    else:
                        requirements[material].append((total_qty, item_description))

                # Материалы напрямую в этапе
                cursor.execute("""
                SELECT m.name, m.type, sm.quantity, sm.length
                FROM stage_materials sm
                JOIN materials m ON sm.material_id = m.id
                WHERE sm.stage_id = ?
                """, (item_id,))

                for material, mtype, sm_quantity, length in cursor.fetchall():
                    total_qty = sm_quantity * quantity
                    if mtype == "Пиломатериал" and length:
                        for _ in range(int(total_qty)):
                            requirements[material].append((length, stage_name))
                    else:
                        requirements[material].append((total_qty, stage_name))

                conn.close()

        return requirements

    def _get_current_stock(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT m.name, w.length, w.quantity FROM warehouse w JOIN materials m ON w.material_id = m.id')
            return cursor.fetchall()
        finally:
            if conn:
                conn.close()

    def confirm_order(self):
        """
        Подтверждение заказа с корректным сохранением длин этапов
        """
        try:
            if not self.current_order:
                QMessageBox.warning(self, "Ошибка", "Заказ пуст")
                return

            # Пересчёт требований + проверка склада прямо перед подтверждением
            _, req_details = self._expand_order_to_requirements()
            stock_items = self._get_current_stock()
            optimizer = CuttingOptimizer()
            result = optimizer.optimize_cutting(req_details, stock_items, self.db_path)

            if not result.get('can_produce'):
                self.confirm_btn.setEnabled(False)
                QMessageBox.warning(self, "Нельзя подтвердить",
                                    "Материалов на складе недостаточно.\nСначала пополните склад.")
                return

            # 1. Составляем order_details с правильными длинами
            # ВАЖНО: Используем индекс строки из current_order для получения правильной длины
            order_details = []
            for order_index, (item_type, item_id, quantity) in enumerate(self.current_order):
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                if item_type == "Изделие":
                    cursor.execute("SELECT name, cost FROM products WHERE id = ?", (item_id,))
                    name, cost = cursor.fetchone()
                    length_m = None
                else:  # Этап
                    cursor.execute("SELECT name FROM stages WHERE id = ?", (item_id,))
                    name = cursor.fetchone()[0]
                    # ИСПРАВЛЕНИЕ: берём длину из соответствующей строки таблицы заказа
                    length_m = self._get_stage_length_by_order_index(order_index)
                    cost = self._compute_stage_cost(item_id, length_m)
                conn.close()
                order_details.append((item_type.lower(), item_id, name, quantity, cost, length_m))

            # 2. Расширяем до требований и получаем total_cost
            total_cost, requirements = self._expand_order_to_requirements()

            # 3. Сохраняем заказ и получаем order_id
            order_id = self._save_order_to_db(total_cost, order_details, "")

            # 4. Генерируем инструкции
            instructions_text = self._generate_instructions_text(
                order_id, total_cost, order_details, requirements
            )

            # 5. Обновляем инструкции в БД
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE orders SET instructions = ? WHERE id = ?",
                (instructions_text, order_id)
            )
            conn.commit()
            conn.close()

            # 6. Создаём PDF
            self._generate_pdf(order_id, total_cost, order_details, requirements, instructions_text)
            self._update_warehouse(result.get('updated_warehouse', []))

            QMessageBox.information(self, "Успех", "Заказ успешно подтверждён!")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Произошла критическая ошибка: {e}")

    def _get_stage_length_by_order_index(self, order_index):
        """
        Получение длины этапа по индексу строки в таблице заказа.
        order_index должен соответствовать row в order_table.
        """
        try:
            if order_index < 0 or order_index >= self.order_table.rowCount():
                return 1.0

            if self.order_table.item(order_index, 0).text() != "Этап":
                return 1.0

            length_text = (self.order_table.item(order_index, 3).text() or "").strip()
            if not length_text:
                return 1.0

            length_val = float(length_text)
            return length_val if length_val > 0 else 1.0
        except Exception:
            return 1.0

    def _update_warehouse(self, updated_data):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM warehouse")
            for material, length, quantity in updated_data:
                cursor.execute("SELECT id FROM materials WHERE name = ?", (material,))
                result = cursor.fetchone()

                if result and quantity > 0:
                    mat_id = result[0]
                    cursor.execute("INSERT INTO warehouse (material_id, length, quantity) VALUES (?, ?, ?)",
                                   (mat_id, length, quantity))
            conn.commit()
        except sqlite3.Error as e:
            print(f"Ошибка при обновлении склада: {e}")
            conn.rollback()
        finally:
            conn.close()

    def _save_order_to_db(self, total_cost, order_details, instructions_text):
        """
        Сохранение заказа с корректными длинами этапов
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO orders (order_date, total_cost, instructions) VALUES (datetime('now'), ?, ?)",
                (total_cost, instructions_text)
            )
            order_id = cursor.lastrowid

            for item_type, item_id, name, quantity, cost, length_m in order_details:
                if item_type == 'изделие':
                    cursor.execute(
                        """
                        INSERT INTO order_items
                          (order_id, product_id, stage_id, quantity, length_meters, product_name, cost, item_type)
                        VALUES (?, ?, NULL, ?, NULL, ?, ?, ?)
                        """,
                        (order_id, item_id, quantity, name, cost, 'product')
                    )
                else:  # этап
                    cursor.execute(
                        """
                        INSERT INTO order_items
                          (order_id, product_id, stage_id, quantity, length_meters, product_name, cost, item_type)
                        VALUES (?, NULL, ?, 1, ?, ?, ?, ?)
                        """,
                        (order_id, item_id, length_m, name, cost, 'stage')
                    )

            conn.commit()
            return order_id
        except sqlite3.Error as e:
            conn.rollback()
            QMessageBox.critical(self, "Ошибка базы данных", f"Ошибка при сохранении заказа: {e}")
        finally:
            conn.close()

    def _generate_pdf(self, order_id, total_cost, order_details, requirements, instructions_text):
        """
        Генерирует PDF с корректными данными этапов и инструкциями.
        Для одноимённых этапов с разной длиной берём длину из базы.
        """
        try:
            # Путь к PDF
            if getattr(sys, 'frozen', False):
                pdf_dir = os.path.join(os.path.dirname(sys.executable), 'orders')
            else:
                pdf_dir = os.path.join(os.path.dirname(self.db_path), 'orders')

            if not os.path.exists(pdf_dir):
                os.makedirs(pdf_dir)

            pdf_filename = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_order.pdf"
            pdf_path = os.path.join(pdf_dir, pdf_filename)

            # Обновление имени файла в БД
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("UPDATE orders SET pdf_filename = ? WHERE id = ?", (pdf_filename, order_id))
            conn.commit()
            conn.close()

            # Формирование PDF
            doc = SimpleDocTemplate(pdf_path, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []

            # Стилизация (Arial, если доступен)
            if ARIAL_FONT_REGISTERED:
                from reportlab.lib.styles import ParagraphStyle
                title_style = ParagraphStyle('CustomTitle', parent=styles['Title'],
                                             fontName='Arial', fontSize=16, spaceAfter=12)
                heading_style = ParagraphStyle('CustomHeading', parent=styles['Heading2'],
                                               fontName='Arial', fontSize=14, spaceAfter=6)
                normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'],
                                              fontName='Arial', fontSize=12)
            else:
                title_style = styles['Title']
                heading_style = styles['Heading2']
                normal_style = styles['Normal']

            story.append(Paragraph(f"Заказ от {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", title_style))
            story.append(Spacer(1, 12))
            story.append(Paragraph(f"Себестоимость: {total_cost:.2f} руб", heading_style))
            sale_price = total_cost * 4
            story.append(Paragraph(f"Цена реализации: {sale_price:.2f} руб", heading_style))
            story.append(Spacer(1, 12))
            story.append(Paragraph("Состав заказа:", heading_style))

            # ВАЖНО: Берём каждый этап и его длину и ID прямо из БД!
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT product_name, quantity, cost, item_type, length_meters, stage_id
                FROM order_items
                WHERE order_id = ?
                ORDER BY id
                """, (order_id,))
            db_items = cursor.fetchall()
            conn.close()

            for name, qty, cost, item_type, length_m, stage_id in db_items:
                if item_type == 'stage':
                    length_m = length_m or 1.0
                    line = f"- {name} (Этап, ID:{stage_id}): 1 шт, длина {length_m:.2f} м → {cost:.2f} руб"
                else:
                    line = f"- {name} (Изделие): {qty} шт → {cost:.2f} руб"
                story.append(Paragraph(line, normal_style))
            story.append(Spacer(1, 12))

            # Инструкции (если есть)
            if instructions_text:
                import re
                from collections import defaultdict
                from reportlab.platypus import HRFlowable

                # ---------------------------------------------------------
                # 1) Парсим секцию "План распила материалов" из instructions_text
                #    plan[material] = [ { 'stock': float, 'cuts': [(len, dest), ...], 'tail': [str...] }, ... ]
                # ---------------------------------------------------------
                lines = instructions_text.splitlines()

                in_plan = False
                current_material = None
                current_block = None

                plan = defaultdict(list)
                all_dests = set()

                re_stock = re.compile(r"^Взять отрезок\s+([0-9]+(?:\.[0-9]+)?)м:\s*$", re.IGNORECASE)
                re_cut = re.compile(r"^\s*\d+\.\s*Отпилить\s+([0-9]+(?:\.[0-9]+)?)м\s+для\s+'([^']+)'\s*$",
                                    re.IGNORECASE)
                re_mat = re.compile(r"^(.+):\s*$")

                def _strip_tags(s: str) -> str:
                    return re.sub(r"<[^>]+>", "", s).strip()

                for raw in lines:
                    s = raw.rstrip()

                    if s.strip().lower().startswith("план распила материалов"):
                        in_plan = True
                        current_material = None
                        current_block = None
                        continue

                    if not in_plan:
                        continue

                    # пропускаем блок "Разбивка по изделиям" и строки вида "- '...': ..."
                    if s.strip().lower().startswith("разбивка по"):
                        continue
                    if s.strip().startswith("- "):
                        continue

                    # заголовок материала: "Доска террасная:"
                    m_mat = re_mat.match(_strip_tags(s.strip()))
                    if m_mat and "взять отрезок" not in s.lower() and "остаток:" not in s.lower() and "отпилить" not in s.lower():
                        current_material = m_mat.group(1).strip()
                        current_block = None
                        continue

                    # начало блока: "Взять отрезок 6.00м:"
                    m_stock = re_stock.match(_strip_tags(s.strip()))
                    if m_stock and current_material:
                        current_block = {"stock": float(m_stock.group(1)), "cuts": [], "tail": []}
                        plan[current_material].append(current_block)
                        continue

                    # строка распила: "1. Отпилить 0.35м для 'Блин'"
                    m_cut = re_cut.match(_strip_tags(s.strip()))
                    if m_cut and current_material and current_block:
                        cut_len = float(m_cut.group(1))
                        dest = m_cut.group(2).strip()
                        current_block["cuts"].append((cut_len, dest))
                        all_dests.add(dest)
                        continue

                    # хвосты блока (например "Остаток: ...") — привяжем к текущему блоку
                    if current_block and _strip_tags(s.strip()).lower().startswith("остаток:"):
                        current_block["tail"].append(_strip_tags(s.strip()))
                        continue

                # ---------------------------------------------------------
                # 2) Рендерим план ПО ЕДИНИЦАМ ЗАКАЗА (из order_items)
                #    Для этапа включаем также изделия внутри этапа (stage_products).
                # ---------------------------------------------------------
                # === ЗАТРАЧЕННЫЕ МАТЕРИАЛЫ (берём из instructions_text, без плана распила) ===
                def _extract_spent_materials(text):
                    lines = text.splitlines()
                    start = None
                    end = None

                    for i, ln in enumerate(lines):
                        if ln.strip().lower().startswith("затраченные материалы"):
                            start = i + 1
                            continue
                        if start is not None and ln.strip().lower().startswith("план распила материалов"):
                            end = i
                            break

                    if start is None:
                        return []

                    if end is None:
                        end = len(lines)

                    out = []
                    for ln in lines[start:end]:
                        ln = ln.strip()
                        if not ln:
                            continue
                        # на всякий случай отсекаем служебные заголовки
                        if ln.lower().startswith(""):
                            continue
                        out.append(ln)
                    return out

                def _build_spent_materials_from_requirements(reqs):
                    out = []
                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()

                    for material in sorted(reqs.keys()):
                        cursor.execute("SELECT type FROM materials WHERE name = ?", (material,))
                        row = cursor.fetchone()
                        mtype = row[0] if row else ""

                        total = 0.0
                        for qty, _src in reqs[material]:
                            total += float(qty)

                        if mtype == "Пиломатериал":
                            out.append(f"{material}: {total:.2f} м")
                        else:
                            out.append(f"{material}: {int(round(total))} шт")

                    conn.close()
                    return out

                spent_lines = _build_spent_materials_from_requirements(requirements)

                if spent_lines:
                    story.append(Paragraph("Затраченные материалы:", heading_style))
                    story.append(Spacer(1, 6))
                    for ln in spent_lines:
                        story.append(Paragraph(ln, normal_style))
                    story.append(Spacer(1, 12))

                story.append(Paragraph("План распила материалов:", heading_style))
                story.append(Spacer(1, 8))

                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()

                def _destinations_for_stage(stage_id, stage_name):
                    cursor.execute("""
                        SELECT p.name
                        FROM stage_products sp
                        JOIN products p ON sp.product_id = p.id
                        WHERE sp.stage_id = ?
                    """, (stage_id,))
                    base = [r[0] for r in cursor.fetchall()]

                    dests = {stage_name}
                    for bn in base:
                        # включаем точные совпадения и варианты вида "Имя(2шт)", если они реально встречаются
                        for d in all_dests:
                            if d == bn or d.startswith(bn + "("):
                                dests.add(d)
                    return dests

                # db_items ты уже получаешь выше в _generate_pdf (order_items ORDER BY id)
                # Перебираем их, чтобы заголовки совпадали с единицами заказа
                for name, qty, cost, item_type, length_m, stage_id in db_items:
                    if item_type == "stage":
                        length_val = 1.0 if (length_m is None or float(length_m) <= 0) else float(length_m)
                        unit_header = f'Этап "{name}": длина {length_val:.2f} м'
                        unit_dests = _destinations_for_stage(stage_id, name)
                    else:
                        unit_header = f'Изделие "{name}" - {int(qty)} шт'
                        # на всякий случай подтягиваем и варианты "(Nшт)" если такие когда-то попадут в текст
                        unit_dests = {name}
                        for d in all_dests:
                            if d.startswith(name + "("):
                                unit_dests.add(d)

                    # Заголовок единицы заказа (подчеркнутый)
                    story.append(Spacer(1, 10))
                    story.append(Paragraph(f"<b><u>{unit_header}</u></b>", heading_style))
                    story.append(Spacer(1, 4))

                    found_any = False

                    # Для каждой единицы заказа выводим только те распилы, чьё назначение входит в unit_dests
                    for material in sorted(plan.keys()):
                        blocks_for_unit = []
                        total_pieces = 0
                        total_len = 0.0

                        # фильтруем распилы по назначениям
                        for blk in plan[material]:
                            cuts = [(l, d) for (l, d) in blk["cuts"] if d in unit_dests]
                            if not cuts:
                                continue
                            blocks_for_unit.append({"stock": blk["stock"], "cuts": cuts, "tail": blk["tail"]})
                            total_pieces += len(cuts)
                            total_len += sum(l for l, _ in cuts)

                        if not blocks_for_unit:
                            continue

                        found_any = True

                        # Название материала (подчёркнуто) + линия-разделитель под ним (требование)
                        story.append(Paragraph(f"<b><u>{material}</u></b>", normal_style))
                        story.append(HRFlowable(width="100%", thickness=0.6, color=colors.lightgrey))
                        story.append(Spacer(1, 4))

                        # Сводка по материалу в рамках этой единицы заказа
                        story.append(
                            Paragraph(f"{material}: {total_pieces} отрезков, всего {total_len:.2f} м", normal_style))
                        story.append(Spacer(1, 4))

                        # Детализация по каждой заготовке
                        for blk in blocks_for_unit:
                            story.append(Paragraph(f"Взять отрезок {blk['stock']:.2f}м:", normal_style))
                            for i, (l, d) in enumerate(blk["cuts"], 1):
                                story.append(Paragraph(f"{i}. Отпилить {l:.2f}м для '{d}'", normal_style))
                            for t in blk["tail"]:
                                story.append(Paragraph(t, normal_style))
                            story.append(Spacer(1, 8))

                    if not found_any:
                        story.append(
                            Paragraph("(Распил пиломатериалов для этой единицы заказа не требуется)", normal_style))

                conn.close()

                # Если хочешь оставить “прочие инструкции” (метизы/сборка) — выводим весь текст ниже
                story.append(Spacer(1, 12))

            doc.build(story)
            QMessageBox.information(self, "Успех", f"PDF создан: {pdf_path}")

        except Exception as e:
            print(f"Ошибка создания PDF: {str(e)}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при создании PDF: {str(e)}")

    def _generate_instructions_text(self, order_id, total_cost, order_details, requirements):
        """
        Формирует текст инструкций с уникальными этапами (по stage_id и длине!)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT product_name, quantity, cost, item_type, length_meters, stage_id
            FROM order_items
            WHERE order_id = ?
            ORDER BY id
        """, (order_id,))
        items = cursor.fetchall()
        conn.close()

        lines = [f"Заказ №{order_id} - Общая стоимость: {total_cost:.2f} руб", ""]

        for name, qty, cost, item_type, length_m, stage_id in items:
            if item_type == 'stage':
                length_m = 1.0 if (length_m is None or length_m <= 0) else float(length_m)

                lines.append(f"Этап \"{name}\" (ID:{stage_id}): длина {length_m:.2f} м → {cost:.2f} руб")
            else:
                lines.append(f"Изделие \"{name}\": {qty} шт → {cost:.2f} руб")

        # Далее — требуемые материалы и ваш план распила (оставьте как есть)
        lines.append("\nТребуемые материалы:")
        cutting_instructions = self._generate_realistic_cutting_plan(requirements)
        lines.extend(cutting_instructions)

        return "\n".join(lines)

    def _generate_realistic_cutting_plan(self, requirements):
        """
        Формирует:
        1) Затраченные материалы (корректно: пиломатериал в метрах, метиз в штуках)
        2) План распила ТОЛЬКО для пиломатериалов (метизы исключаем)
        """
        from collections import defaultdict
        from cutting_optimizer import CuttingOptimizer

        # 0) Получаем типы материалов из БД (Пиломатериал/Метиз)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name, type FROM materials")
        material_types = {name: mtype for name, mtype in cursor.fetchall()}

        # Склад
        cursor.execute("""
            SELECT m.name, w.length, w.quantity
            FROM warehouse w
            JOIN materials m ON w.material_id = m.id
            WHERE w.quantity > 0
        """)
        stock_items = [(name, length, qty) for name, length, qty in cursor.fetchall()]
        conn.close()

        # 1) Затраченные материалы (как в расчёте: суммируем qty по требованиям)
        material_lines = []
        for material, reqs in requirements.items():
            mtype = material_types.get(material, "")

            # reqs = [(qty_or_length, source_name), ...]
            total = 0.0
            for qty, _src in reqs:
                total += float(qty)

            if mtype == "Пиломатериал":
                material_lines.append(f"{material}: {total:.2f} м")
            else:
                # метизы и прочее — штуки
                material_lines.append(f"{material}: {int(round(total))} шт")

        # 2) Готовим требования для оптимизатора: только пиломатериалы (и сразу исключаем тросы)
        optimizer_requirements = {}
        for material, reqs in requirements.items():
            if material in ("Трос М10", "Трос М12"):
                continue
            if material_types.get(material) != "Пиломатериал":
                continue
            optimizer_requirements[material] = reqs

        result = CuttingOptimizer.optimize_cutting(
            requirements=optimizer_requirements,
            stock_items=stock_items,
            db_path=self.db_path
        )
        cutting_instructions = result.get("cutting_instructions", {})  # как у тебя сейчас

        # 3) Итоговые строки + форматирование (пустая строка после заголовка)
        lines = ["Затраченные материалы:", ""]
        lines.extend(material_lines)

        # 4) План распила: только пиломатериалы, названия материалов подчёркнуты/выделены
        if cutting_instructions:
            lines.append("")
            lines.append("План распила материалов:")

            for material, instr_list in cutting_instructions.items():
                if not instr_list:
                    continue

                # подчёркивание/выделение имени пиломатериала (ReportLab Paragraph это переварит)
                lines.append("")
                lines.append(f"<u><b>{material}</b></u>:")

                # Доп. разделение “по изделиям” (чтобы визуально было легче)
                by_product = defaultdict(list)
                for qty, src in optimizer_requirements.get(material, []):
                    by_product[src].append(float(qty))

                if by_product:
                    lines.append("  Разбивка по изделиям:")
                    for prod in sorted(by_product.keys()):
                        pieces = by_product[prod]
                        lines.append(f"    - '{prod}': {len(pieces)} отрезков, всего {sum(pieces):.2f} м")
                    lines.append("")

                # Сами блоки распила
                for block in instr_list:
                    for l in block.strip().split("\n"):
                        lines.append(f"  {l}")
                    lines.append("")  # разделитель между “досками/блоками”

        return lines

    def _plan_lumber_cuts(self, cuts, available_stock):
        """ВСПОМОГАТЕЛЬНЫЙ МЕТОД: Планирует распил для конкретного материала"""
        lines = []
        sorted_cuts = sorted(cuts, key=lambda x: x[0], reverse=True)
        stock_copy = [item.copy() for item in available_stock]  # Копия для планирования

        cut_number = 1
        for cut_length, source in sorted_cuts:
            best_stock = None
            best_idx = None

            # Ищем наименьшую подходящую заготовку
            for idx, stock_item in enumerate(stock_copy):
                if stock_item['quantity'] > 0 and stock_item['length'] >= cut_length:
                    if best_stock is None or stock_item['length'] < best_stock['length']:
                        best_stock = stock_item
                        best_idx = idx

            if best_stock:
                lines.append(f"  {cut_number}. Взять заготовку {best_stock['length']:.2f}м со склада")
                lines.append(f"     Отпилить {cut_length:.2f}м для {source}")

                remaining = best_stock['length'] - cut_length
                if remaining >= 0.3:
                    lines.append(f"     Остаток: {remaining:.2f}м (вернуть на склад)")
                    # Добавляем остаток в доступные заготовки
                    stock_copy.append({'length': remaining, 'quantity': 1})
                elif remaining > 0:
                    lines.append(f"     Остаток: {remaining:.2f}м (отходы)")

                # Уменьшаем количество использованной заготовки
                best_stock['quantity'] -= 1
                cut_number += 1
            else:
                lines.append(f"  ❌ Не найдена заготовка для отрезка {cut_length:.2f}м ({source})")

        return lines

    def _generate_cut_plan(self, cuts_by_length, standard_lengths):
        """
        Генерирует оптимальный план распила пиломатериалов
        """
        cut_plan = {}

        # Сортируем отрезки по убыванию длины для лучшей оптимизации
        sorted_cuts = sorted(cuts_by_length.items(), key=lambda x: x[0], reverse=True)

        for cut_length, sources in sorted_cuts:
            placed = False

            # Пытаемся разместить в существующих заготовках
            for stock_length in cut_plan.keys():
                current_usage = sum(
                    length * len(sources_list)
                    for length, sources_list in cut_plan[stock_length].items()
                )
                if stock_length - current_usage >= cut_length:
                    if cut_length not in cut_plan[stock_length]:
                        cut_plan[stock_length][cut_length] = []
                    cut_plan[stock_length][cut_length].extend(sources)
                    placed = True
                    break

            if not placed:
                # Выбираем минимальную подходящую стандартную длину
                suitable_length = None
                for std_length in standard_lengths:
                    if std_length >= cut_length:
                        suitable_length = std_length
                        break

                if not suitable_length:
                    suitable_length = max(standard_lengths)  # берем максимальную, если отрезок очень длинный

                if suitable_length not in cut_plan:
                    cut_plan[suitable_length] = {}

                if cut_length not in cut_plan[suitable_length]:
                    cut_plan[suitable_length][cut_length] = []
                cut_plan[suitable_length][cut_length].extend(sources)

        return cut_plan

    def load_order_history(self):
        """Загружает историю заказов"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT o.id, 
                       datetime(o.order_date, 'localtime') as order_date,
                       o.total_cost,   
                       SUM(oi.quantity) as total_items  
                FROM orders o  
                JOIN order_items oi ON o.id = oi.order_id  
                GROUP BY o.id  
                ORDER BY o.order_date DESC
            """)
            orders = cursor.fetchall()

            self.history_table.setRowCount(len(orders))
            for row_idx, (order_id, date, total_cost, items_count) in enumerate(orders):
                self.history_table.setItem(row_idx, 0, QTableWidgetItem(str(order_id)))
                self.history_table.setItem(row_idx, 1, QTableWidgetItem(date))
                self.history_table.setItem(row_idx, 2, QTableWidgetItem(str(items_count)))
                self.history_table.setItem(row_idx, 3, QTableWidgetItem(f"{total_cost:.2f} руб"))

        except sqlite3.Error as e:
            QMessageBox.critical(self, "Ошибка базы данных", f"Ошибка загрузки истории: {str(e)}")
        finally:
            conn.close()

    def show_order_details(self, row, column):
        """Показывает детали заказа"""
        if row < 0 or not self.history_table.item(row, 0):
            return

        order_id = self.history_table.item(row, 0).text()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Получаем детали заказа
        cursor.execute("""
            SELECT product_name, quantity, cost, item_type, length_meters 
            FROM order_items 
            WHERE order_id = ?
        """, (order_id,))
        items = cursor.fetchall()

        # Получаем общую информацию о заказе
        cursor.execute("""
            SELECT order_date, total_cost, instructions 
            FROM orders 
            WHERE id = ?
        """, (order_id,))
        order_info = cursor.fetchone()
        conn.close()

        if not order_info:
            QMessageBox.warning(self, "Ошибка", "Заказ не найден")
            return

        order_date, total_cost, instructions = order_info

        # Создаем диалог с деталями
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Детали заказа №{order_id}")
        dialog.setMinimumSize(700, 500)

        layout = QVBoxLayout()

        # Основная информация
        info_text = f"Заказ от {order_date}\n"
        info_text += f"Общая стоимость: {total_cost:.2f} руб\n\n"
        info_text += "Состав заказа:\n"

        for name, quantity, cost, item_type, length_m in items:
            if item_type == 'stage':
                length_m = length_m or 1.0
                info_text += f"- {name} (Этап): длина {length_m:.2f} м → {cost:.2f} руб\n"
            else:
                info_text += f"- {name} (Изделие): {quantity} шт → {cost:.2f} руб\n"

        # Если есть подробные инструкции
        if instructions:
            info_text += f"\n{instructions}"

        # Создаем текстовое поле с прокруткой
        text_widget = QTextEdit()
        text_widget.setPlainText(info_text)
        text_widget.setReadOnly(True)
        layout.addWidget(text_widget)

        # Кнопка закрытия
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.setLayout(layout)
        dialog.exec_()

    # ИСПРАВЛЕНИЕ: Новые методы для работы с PDF
    def open_selected_pdf(self):
        """Открывает PDF для выбранного заказа в истории"""
        selected_row = self.history_table.currentRow()
        if selected_row == -1:
            QMessageBox.warning(self, "Выберите заказ",
                                "Пожалуйста, выберите заказ из списка истории")
            return

        # Получаем ID заказа из первой колонки
        order_id = int(self.history_table.item(selected_row, 0).text())

        # Вызываем метод открытия PDF
        self.open_pdf_file(order_id)

    def open_pdf_file(self, order_id):
        """Открывает PDF файл для указанного заказа"""
        try:
            # Получаем имя PDF файла из БД
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT pdf_filename FROM orders WHERE id = ?", (order_id,))
            result = cursor.fetchone()
            conn.close()

            if not result or not result[0]:
                QMessageBox.warning(self, "PDF не найден", "PDF файл для этого заказа не создан")
                return

            pdf_filename = result[0]

            # Определяем путь к PDF файлу
            if getattr(sys, 'frozen', False):
                pdf_dir = os.path.join(os.path.dirname(sys.executable), 'orders')
            else:
                pdf_dir = os.path.join(os.path.dirname(self.db_path), 'orders')

            pdf_path = os.path.join(pdf_dir, pdf_filename)

            if not os.path.exists(pdf_path):
                QMessageBox.warning(self, "Файл не найден",
                                    f"PDF файл не найден:\n{pdf_path}")
                return

            # Открываем PDF файл кроссплатформенно
            system = platform.system()
            if system == "Windows":
                os.startfile(pdf_path)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", pdf_path])
            else:  # Linux
                subprocess.run(["xdg-open", pdf_path])

            print(f"Открыт PDF файл: {pdf_path}")

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть PDF:\n{str(e)}")


# ИСПРАВЛЕННЫЙ ГЛАВНЫЙ КЛАСС
class MainWindow(QMainWindow):
    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path
        self.setWindowTitle("Учет деревообрабатывающего цеха - ИСПРАВЛЕНО")
        self.setGeometry(100, 100, 1200, 900)

        self.refresh_btn = QPushButton("Обновить все данные")
        self.refresh_btn.clicked.connect(self.reload_all_tabs)
        self.refresh_btn.setFixedSize(150, 30)
        self.refresh_btn.move(self.width() - 160, 0)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self.on_tab_changed)

        # Существующие вкладки
        self.materials_tab = MaterialsTab(db_path)
        self.materials_tab.main_window_ref = self
        self.tabs.addTab(self.materials_tab, "Материалы")

        self.warehouse_tab = WarehouseTab(db_path, self)
        self.tabs.addTab(self.warehouse_tab, "Склад")

        self.products_tab = ProductsTab(db_path, self)
        self.tabs.addTab(self.products_tab, "Изделия")

        # ИСПРАВЛЕННАЯ ВКЛАДКА ЭТАПОВ
        self.stages_tab = StagesTab(db_path, self)
        self.tabs.addTab(self.stages_tab, "Этапы")

        # ИСПРАВЛЕННАЯ ВКЛАДКА ЗАКАЗОВ
        self.orders_tab = OrdersTab(db_path, self)
        self.tabs.addTab(self.orders_tab, "Заказы")

        self.refresh_btn.setParent(self)
        self.refresh_btn.raise_()

        self.statusBar().showMessage("Готово - все ошибки исправлены!")

    def on_tab_changed(self, index):
        tab_name = self.tabs.tabText(index)

        if tab_name == "Склад":
            self.warehouse_tab.load_materials()
        elif tab_name == "Изделия":
            self.products_tab.load_materials()
        elif tab_name == "Этапы":
            self.stages_tab.load_products()
            self.stages_tab.load_materials()
        elif tab_name == "Заказы":
            # ИСПРАВЛЕНИЕ 3: Загружаем правильный тип по умолчанию
            current_type = self.orders_tab.item_type_combo.currentText()
            if current_type == "Изделие":
                self.orders_tab.load_products()
            else:
                self.orders_tab.load_stages()
            self.orders_tab.load_order_history()

    def update_all_comboboxes(self):
        """Обновляет все комбобоксы с учетом составных изделий"""
        self.warehouse_tab.load_materials()
        self.products_tab.load_products()  # Обновит и базовые, и составные
        self.stages_tab.load_products()  # Теперь загрузит все изделия
        self.stages_tab.load_materials()

        # Обновляем правильный список в заказах
        current_type = self.orders_tab.item_type_combo.currentText()
        if current_type == "Изделие":
            self.orders_tab.load_products()  # Загрузит все изделия
        else:
            self.orders_tab.load_stages()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_btn.move(self.width() - 160, 0)

    def reload_all_tabs(self):
        """Перезагружает данные во всех вкладках"""
        # Пересчитываем себестоимость всех изделий
        self.products_tab.recalculate_all_products_cost()
        self.stages_tab.recalculate_all_stages_cost()

        # Загружаем данные
        self.materials_tab.load_data()
        self.warehouse_tab.load_data()
        self.products_tab.load_products()  # Загрузит все изделия
        self.stages_tab.load_stages()
        self.orders_tab.load_order_history()

        # Правильное обновление списков в заказах
        current_type = self.orders_tab.item_type_combo.currentText()
        if current_type == "Изделие":
            self.orders_tab.load_products()
        else:
            self.orders_tab.load_stages()

        self.statusBar().showMessage("Данные обновлены", 3000)

    def force_close_all_db_connections(self):
        """Принудительно закрывает все соединения с БД во всех вкладках"""
        # Закрываем соединения в каждой вкладке, если у них есть такой метод
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            if hasattr(tab, 'force_close_db_connections'):
                tab.force_close_db_connections()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'database.db')
    window = MainWindow(db_path)
    window.show()
    sys.exit(app.exec_())