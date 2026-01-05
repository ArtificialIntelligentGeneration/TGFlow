#!/usr/bin/env python3
"""
Скрипт для извлечения и подготовки иконки из скриншота
"""
from PIL import Image
import sys

# Загрузить исходное изображение
source_path = "/Users/a1/.gemini/antigravity/brain/f52ca7e5-1d61-4b38-ac4b-f57c496ae434/uploaded_image_1767493977087.png"
output_path = "/Users/a1/Documents/AiGen/TGFlow_Dev/TGFlow/user_icon_extracted.png"

img = Image.open(source_path)
print(f"Размер исходного изображения: {img.size}")

# Скриншот содержит несколько иконок
# Нужно извлечь Telegram иконку (синяя, справа)
# Примерно на позиции x: 370-465, y: 8-95
# Каждая иконка примерно 60x60 с отступами

# Извлекаем правую иконку Telegram (синяя)
# x: примерно от 370 до 465 (95 пикселей)
# y: примерно от 8 до 95 (87 пикселей)
icon_box = (370, 8, 465, 95)  # left, top, right, bottom
icon = img.crop(icon_box)

print(f"Размер извлеченной иконки: {icon.size}")

# Теперь нужно сделать квадратной и убрать лишнее
# Найдём размер для квадрата
width, height = icon.size
size = max(width, height)

# Создадим новое квадратное изображение с прозрачным фоном
square_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))

# Вставим иконку по центру
x_offset = (size - width) // 2
y_offset = (size - height) // 2
square_img.paste(icon, (x_offset, y_offset))

# Изменим размер до 1024x1024 для лучшего качества
final_img = square_img.resize((1024, 1024), Image.LANCZOS)

# Сохраним
final_img.save(output_path, 'PNG')
print(f"Иконка сохранена: {output_path}")
print(f"Финальный размер: {final_img.size}")
