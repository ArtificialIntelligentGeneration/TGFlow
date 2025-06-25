import os
from app_paths import user_file

# Абсолютный путь к директории scripts внутри пользовательских данных
SCRIPTS_DIR = str(user_file("scripts"))

def ensure_dir():
    os.makedirs(SCRIPTS_DIR, exist_ok=True)


def list_scripts():
    ensure_dir()
    return [f for f in os.listdir(SCRIPTS_DIR) if f.endswith((".txt", ".html"))]


def load_script(name: str) -> str:
    ensure_dir()
    path = os.path.join(SCRIPTS_DIR, name)
    if not os.path.exists(path):
        raise FileNotFoundError(name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save_script(name: str, text: str):
    ensure_dir()
    if not name.endswith(".txt"):
        name += ".txt"
    path = os.path.join(SCRIPTS_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def delete_script(name: str):
    ensure_dir()
    path = os.path.join(SCRIPTS_DIR, name)
    if os.path.exists(path):
        os.remove(path) 