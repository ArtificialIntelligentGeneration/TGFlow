import os
import shutil
from pathlib import Path
from app_paths import user_file

# Базовая директория скриптов
SCRIPTS_ROOT = user_file("scripts")

def ensure_categories():
    """
    Создает структуру папок leads/chats и мигрирует старые скрипты в leads.
    """
    if not os.path.exists(SCRIPTS_ROOT):
        os.makedirs(SCRIPTS_ROOT)
        
    leads_dir = SCRIPTS_ROOT / "leads"
    chats_dir = SCRIPTS_ROOT / "chats"
    
    os.makedirs(leads_dir, exist_ok=True)
    os.makedirs(chats_dir, exist_ok=True)
    
    # Миграция: перемещаем файлы из корня в leads
    for item in os.listdir(SCRIPTS_ROOT):
        src = SCRIPTS_ROOT / item
        if os.path.isfile(src) and item.endswith((".txt", ".html")):
            dst = leads_dir / item
            try:
                shutil.move(str(src), str(dst))
                print(f"Migrated script {item} to leads/")
            except Exception as e:
                print(f"Failed to migrate {item}: {e}")

def get_dir(category: str) -> str:
    """Возвращает путь к подпапке категории."""
    ensure_categories()
    # Защита от выхода из директории
    category = category.replace("..", "").replace("/", "").replace("\\", "")
    path = SCRIPTS_ROOT / category
    os.makedirs(path, exist_ok=True)
    return str(path)

def list_scripts(category: str = "leads"):
    directory = get_dir(category)
    try:
        files = [f for f in os.listdir(directory) if f.endswith((".txt", ".html"))]
        return sorted(files)
    except Exception:
        return []

def load_script(name: str, category: str = "leads") -> str:
    directory = get_dir(category)
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Script {name} not found in {category}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def save_script(name: str, text: str, category: str = "leads"):
    directory = get_dir(category)
    if not name.endswith(".txt"):
        name += ".txt"
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def delete_script(name: str, category: str = "leads"):
    directory = get_dir(category)
    path = os.path.join(directory, name)
    if os.path.exists(path):
        os.remove(path)
