# cutting_optimizer.py
import json
import sqlite3
from collections import defaultdict

class CuttingOptimizer:
    MIN_LENGTH = 0.3  # Минимальный полезный остаток

    @staticmethod
    def optimize_cutting(requirements, stock_items, db_path):
        """
        Оптимизирует раскрой материалов для заданных требований.

        :param requirements: Список требований по материалам
        :param stock_items: Доступные материалы на складе
        :param db_path: Путь к базе данных
        :return: Результат проверки и оптимизации
        """
        print(f"[DEBUG] Требования: {dict(requirements)}")
        print(f"[DEBUG] Склад: {stock_items}")

        # Создаем копию склада для работы
        warehouse = defaultdict(list)
        for item in stock_items:
            material_name = item[0]
            # Пропускаем материалы с нулевым количеством
            if item[2] <= 0:
                continue
            warehouse[material_name].append({
                'length': item[1],
                'quantity': item[2],
                'original_length': item[1]
            })

        # Словари для результатов
        cutting_instructions = defaultdict(list)
        updated_warehouse = []
        missing_materials = []
        can_produce = True

        # Получаем типы материалов из БД
        material_types = CuttingOptimizer._get_material_types(db_path)

        # Проверяем наличие всех требуемых материалов
        for material in requirements.keys():
            # Если материала нет на складе или его количество равно 0
            if material not in warehouse or not warehouse[material]:
                # Получаем общее количество этого материала на складе (включая нулевые)
                total_available = sum(item[2] for item in stock_items if item[0] == material)

                # Рассчитываем общее требуемое количество
                total_required = sum(req[0] for req in requirements[material])

                if total_available < total_required:
                    missing_materials.append(f"{material}: требуется {total_required}, доступно {total_available}")
                    can_produce = False
                # Если материал есть, но количество равно 0
                elif total_available == 0:
                    missing_materials.append(f"{material}: отсутствует на складе")
                    can_produce = False

        # Обрабатываем каждый материал
        for material, req_list in requirements.items():
            print(f"[DEBUG] Обрабатываем материал: {material}, требования: {req_list}")

            # Пропускаем материалы, которых нет на складе
            if material not in warehouse or not warehouse[material]:
                continue

            if material_types.get(material) == "Метиз":
                # Обработка метизов
                result = CuttingOptimizer._process_fastener(
                    material, req_list, warehouse[material])
                cutting_instructions[material] = result['instructions']
                if not result['success']:
                    can_produce = False
                    missing_materials.append(result['message'])
                updated_warehouse.extend(result['updated'])
            else:
                # Обработка пиломатериалов
                result = CuttingOptimizer._process_lumber(
                    material, req_list, warehouse[material])
                print(f"[DEBUG] Результат обработки пиломатериала {material}: {result}")

                if not result['success']:
                    can_produce = False
                    missing_materials.extend(result['missing'])
                cutting_instructions[material] = result['instructions']
                updated_warehouse.extend(result['updated'])

        # Добавляем материалы, не участвовавшие в заказе
        processed_materials = set(requirements.keys())
        for mat, length, qty in stock_items:
            if mat not in processed_materials and qty > 0:
                updated_warehouse.append([mat, length, qty])

        # Округление всех длин до 2 знаков
        updated_warehouse = [[mat, round(len_val, 2), qty] for mat, len_val, qty in updated_warehouse]

        # Сортировка по названию материала и длине (от большего к меньшему)
        updated_warehouse.sort(key=lambda x: (x[0], -x[1]))

        return {
            'can_produce': can_produce,
            'missing': missing_materials,
            'updated_warehouse': updated_warehouse,
            'cutting_instructions': dict(cutting_instructions)
        }

    @staticmethod
    def _get_material_types(db_path):
        """Возвращает типы материалов из БД"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name, type FROM materials")
        material_types = {}
        for name, mtype in cursor.fetchall():
            material_types[name] = mtype
        conn.close()
        return material_types

    @staticmethod
    def _process_lumber(material, requirements, stock):
        """Обработка пиломатериалов с оптимизацией раскроя и повторным использованием остатков"""
        # Фильтруем требования: теперь храним (длина, изделие)
        requirements = [req for req in requirements if req[0] > 0]

        if not requirements:
            return {
                'success': True,
                'instructions': [],
                'updated': [],
                'missing': []
            }

        # Сортируем требования по убыванию длины
        requirements.sort(key=lambda x: x[0], reverse=True)
        instructions = []
        updated = []
        missing_dict = defaultdict(float)  # Для сбора общей недостающей длины по изделиям

        # Создаем список доступных досок
        boards = []
        for item in stock:
            for _ in range(item['quantity']):
                boards.append({
                    'original_length': item['length'],
                    'current_length': item['length'],
                    'cuts': []  # История распилов для этой доски
                })

        # Сортируем доски по убыванию длины (для минимизации отходов)
        boards.sort(key=lambda x: x['current_length'], reverse=True)

        # Обрабатываем каждое требование
        for req_length, product in requirements:
            board_found = False

            # Ищем доску с минимальным подходящим остатком
            best_index = -1
            best_remaining = float('inf')

            for i, board in enumerate(boards):
                if board['current_length'] >= req_length:
                    remaining = board['current_length'] - req_length
                    if remaining < best_remaining:
                        best_remaining = remaining
                        best_index = i

            if best_index != -1:
                board = boards[best_index]
                board['current_length'] = round(board['current_length'] - req_length, 2)
                board['cuts'].append({
                    'length': req_length,
                    'product': product
                })
                board_found = True

            if not board_found:
                # Собираем общую недостающую длину по изделиям
                missing_dict[product] += req_length

        # Формируем инструкции и остатки
        for board in boards:
            if board['cuts']:
                instruction = f"Взять отрезок {board['original_length']:.2f}м:\n"
                for i, cut in enumerate(board['cuts'], 1):
                    instruction += f"  {i}. Отпилить {cut['length']:.2f}м для '{cut['product']}'\n"

                if board['current_length'] >= CuttingOptimizer.MIN_LENGTH:
                    instruction += f"  Остаток: {round(board['current_length'], 2):.2f}м\n"
                else:
                    instruction += f"  Остаток: {round(board['current_length'], 2):.2f}м (не используется)\n"

                instructions.append(instruction)

            if board['current_length'] >= CuttingOptimizer.MIN_LENGTH:
                current_length_rounded = round(board['current_length'], 2)
                # Группируем одинаковые остатки
                found = False
                for item in updated:
                    if item[0] == material and abs(item[1] - current_length_rounded) < 0.01:
                        item[2] += 1
                        found = True
                        break

                if not found:
                    updated.append([material, current_length_rounded, 1])

        # Формируем сообщения о недостающих материалах с общей длиной
        missing = []
        if missing_dict:
            total_missing = sum(missing_dict.values())
            products_list = ", ".join([f"'{prod}'" for prod in missing_dict.keys()])
            missing.append(f"{material}: не хватает {total_missing:.2f}м для изделий {products_list}")

        return {
            'success': len(missing) == 0,
            'instructions': instructions,
            'updated': updated,
            'missing': missing
        }


    @staticmethod
    def _process_fastener(material, requirements, stock):
        """Обработка метизов с улучшенными инструкциями"""
        # Извлекаем только количества из требований
        quantities = [req[0] for req in requirements]
        total_required = sum(quantities)

        total_available = sum(item['quantity'] for item in stock)

        if total_available < total_required:
            return {
                'success': False,
                'message': f"{material}: требуется {total_required}, доступно {total_available}",
                'updated': [],
                'instructions': []
            }

        # Обновляем остатки
        updated = []
        remaining = total_required
        instructions = []

        # Формируем инструкции с указанием изделий
        for req in requirements:
            qty, product = req
            instructions.append(f"Использовано {qty} шт для '{product}'")

        # Обновляем складские остатки
        if total_available - total_required > 0:
            # Для метизов используем длину 0
            updated.append([material, 0.0, total_available - total_required])  # Изменено на list

        return {
            'success': True,
            'updated': updated,
            'message': "",
            'instructions': instructions
        }