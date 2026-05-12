import sys
import os
import json
import asyncio
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                            QHBoxLayout, QPushButton, QLabel, QLineEdit, QDateEdit, QTimeEdit, QToolButton,
                            QTextEdit, QMessageBox, QTabWidget, QDialog, QListWidget, QListWidgetItem, QInputDialog, QComboBox, QScrollArea, QCheckBox, QProgressBar, QFormLayout)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QMutex, QMutexLocker, QTimer, QEventLoop, QDate, QTime, QEvent, QObject
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QAbstractSpinBox, QSizePolicy
import nest_asyncio
from pyrogram import Client, errors
from pyrogram.enums import ParseMode, ChatType, ChatMemberStatus
import logging
from PyQt6 import sip, QtCore
from script_manager import list_scripts, load_script, save_script, delete_script
import random
import time
import sqlite3  # Для обработки ошибок «database is locked»
import datetime, pathlib
import configparser
import re
from bs4 import BeautifulSoup
from pathlib import Path
import app_paths  # ensure USER_DATA_DIR is resolved early
from app_paths import USER_DATA_DIR, user_file
from filelock import FileLock, Timeout
from typing import Optional, Dict, Union

from broadcast_state import BroadcastState
from client_utils import normalize_recipient
# Проверка версии Python для zoneinfo
import sys
if sys.version_info >= (3, 9):
    try:
        import zoneinfo  # Для работы с часовыми поясами (Python 3.9+)
        HAS_ZONEINFO = True
    except ImportError:
        zoneinfo = None
        HAS_ZONEINFO = False
else:
    print("Внимание: Рекомендуется Python 3.9+ для полной поддержки часовых поясов")
    zoneinfo = None
    HAS_ZONEINFO = False

try:
    import pytz  # Для обратной совместимости
except ImportError:
    if not HAS_ZONEINFO:
        print("Ошибка: Требуется pytz для Python < 3.9. Установите: pip install pytz")
        sys.exit(1)
    else:
        print("Предупреждение: pytz не установлен, но zoneinfo доступен")
    pytz = None

nest_asyncio.apply()

# ─── Настройка рабочей директории ────────────────────────────────────────────
# Все файлы, которые приложение создаёт (auth.log, accounts.json, sessions …)
# теперь хранятся в каталоге `~/Library/Application Support/TGFlow` (macOS)
# или аналогичном для других ОС. Переключаем `cwd`, чтобы существующий код
# с относительными путями продолжал работать без больших изменений.
os.chdir(USER_DATA_DIR)

# Настраиваем логирование
logging.basicConfig(
    filename=user_file('auth.log'),
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    encoding='utf-8'
)

# -------- Markdown converter ---------
# Преобразует упрощённый HTML (b/i/a/br,p) в Telegram HTML.
# Реализация вынесена в text_utils.py
# -------------------------------------

from text_utils import html_to_telegram


# ─── Определение наличия ссылки в тексте ──────────────────────────────────────
# Используется для автоотключения превью ссылок при отправке сообщений.
URL_RE = re.compile(r'(https?://\S+|www\.\S+|t\.me/\S+|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\S*)', re.IGNORECASE)

def contains_url(text: str) -> bool:
    """Возвращает True, если в тексте обнаружена ссылка."""
    if not text:
        return False
    return bool(URL_RE.search(text))

# ─── Утилита безопасного открытия Pyrogram-клиента ─────────────────────────────
# Иногда при повторных подключениях к одному .session-файлу SQLite ещё держит
# блокировку и Pyrogram выбрасывает «database is locked».  Ниже — вспомогательная
# функция, которая делает несколько повторов с короткой задержкой, тем самым
# надёжно устраняя временный конфликт.

def open_client(session_name: str, api_id: Union[int, str], api_hash: str,
                retries: int = 3, delay: float = 0.3, start_client: bool = True) -> Client:
    """Возвращает *подключённый* Pyrogram-клиент.

    Если при открытии возникает sqlite3.OperationalError «database is locked»,
    делает до *retries* попыток с экспоненциальной paузой.
    """
    lock_path = f"{session_name}.lock"
    for attempt in range(retries):
        lock = None
        cli = None
        try:
            # Эксклюзивная блокировка на файл-сессию
            lock = FileLock(lock_path)
            # Даём короткий таймаут, чтобы предыдущая операция успела освободить lock
            lock.acquire(timeout=5)

            cli = Client(session_name, int(api_id), api_hash)
            if start_client:
                # start() гарантирует инициализацию client.me (is_premium и пр.)
                # Это устраняет внутреннюю ошибку Pyrogram: 'NoneType' object has no attribute 'is_premium'
                cli.start()
            else:
                # Для сценариев авторизации (send_code/sign_in) достаточно connect(),
                # чтобы избежать зависаний при интерактивном вводе внутри start().
                cli.connect()

            # Сохраняем lock внутри клиента, чтобы потом освободить
            cli._file_lock = lock
            return cli
        except Exception as exc:
            # Если что-то пошло не так – корректно освобождаем ресурсы перед ретраем/выходом
            try:
                if cli is not None:
                    try:
                        cli.stop()
                    except Exception:
                        try:
                            cli.disconnect()
                        except Exception:
                            pass
                if lock is not None:
                    try:
                        lock.release()
                    except Exception:
                        pass
            except Exception:
                pass

            # Если lock уже кем-то захвачен – делаем несколько повторов перед ошибкой
            if isinstance(exc, Timeout):
                # Если lock завис – пробуем мягко удалить явно старый или сломанный lock-файл
                try:
                    import os, time as _t
                    if os.path.exists(lock_path):
                        age = _t.time() - os.path.getmtime(lock_path)
                        if age > 300:  # 5 минут
                            os.remove(lock_path)
                            _t.sleep(0.2)
                            continue
                except Exception:
                    pass
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))
                    continue
                raise RuntimeError("Сессия уже используется другим процессом. Закройте другие окна авторизации или дождитесь завершения предыдущей операции.")

            if "database is locked" in str(exc).lower() and attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
                continue
            raise

    # Не должно дойти: если дошло — пробрасываем последнюю ошибку
    raise RuntimeError("Failed to open client due to persistent database lock")

class AuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подтверждение кода")
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        
        # Поле для кода
        code_layout = QHBoxLayout()
        code_label = QLabel("Код подтверждения:")
        self.code_input = QLineEdit()
        code_layout.addWidget(code_label)
        code_layout.addWidget(self.code_input)
        layout.addLayout(code_layout)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.setProperty("role", "primary")
        cancel_button = QPushButton("Отмена")
        cancel_button.setProperty("role", "secondary")
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(ok_button)
        buttons_layout.addWidget(cancel_button)
        layout.addLayout(buttons_layout)

class PasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Введите пароль 2FA")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        label = QLabel("Пароль 2FA:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(label)
        layout.addWidget(self.password_input)
        buttons_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        ok_button.setProperty("role", "primary")
        cancel_button = QPushButton("Отмена")
        cancel_button.setProperty("role", "secondary")
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(ok_button)
        buttons_layout.addWidget(cancel_button)
        layout.addLayout(buttons_layout)

class TelegramWorker(QThread):
    finished = pyqtSignal(bool, str, dict)
    
    def __init__(self, session_name, api_id, api_hash, phone, phone_code=None, phone_code_hash=None, password=None):
        super().__init__()
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.phone_code = phone_code
        self.phone_code_hash = phone_code_hash
        self.password = password
        self.extra = {}
    
    def run(self):
        try:
            app_client = None
            # Убедимся, что родительская директория для .session-файла присутствует
            Path(self.session_name).parent.mkdir(parents=True, exist_ok=True)
            _dbg(f'TelegramWorker: open session {self.session_name}')
            app_client = open_client(self.session_name, self.api_id, self.api_hash, start_client=False)
            
            if self.phone_code is None:
                # Первый этап - запрос кода
                logging.debug(f"[AuthWorker] send_code to {self.phone}")
                try:
                    sent_code = app_client.send_code(self.phone)
                except errors.FloodWait as fw:
                    app_client.disconnect()
                    self.finished.emit(False, f'FLOOD_WAIT_{fw.value}', {})
                    return
                self.extra = {'phone_code_hash': sent_code.phone_code_hash}
                logging.debug(f"[AuthWorker] phone_code_hash={sent_code.phone_code_hash}")
                app_client.disconnect()
                self.finished.emit(True, 'NEED_CODE', self.extra)
                return
                
            try:
                # Второй этап - ввод кода
                if self.phone_code_hash is None:
                    app_client.disconnect()
                    self.finished.emit(False, 'MISSING_HASH', self.extra)
                    return
                app_client.sign_in(
                    phone_number=self.phone,
                    phone_code_hash=self.phone_code_hash,
                    phone_code=self.phone_code
                )
            except errors.PhoneCodeExpired:
                # Код истёк или введён неверно – сообщаем GUI, чтобы инициировать новый запрос
                app_client.disconnect()
                self.finished.emit(False, 'PHONE_CODE_EXPIRED', {})
                return
            except errors.SessionPasswordNeeded:
                # Третий этап - ввод пароля 2FA
                if self.password:
                    try:
                        app_client.check_password(self.password)
                    except Exception as e:
                        app_client.disconnect()
                        self.finished.emit(False, str(e), self.extra)
                        return
                else:
                    app_client.disconnect()
                    self.finished.emit(True, 'NEED_PASSWORD', self.extra)
                    return
            except errors.PhoneCodeInvalid:
                app_client.disconnect()
                self.finished.emit(False, 'PHONE_CODE_INVALID', self.extra)
                return
                
            app_client.disconnect()
            # Снимаем файловый lock
            try:
                if hasattr(app_client, "_file_lock"):
                    app_client._file_lock.release()
            except Exception:
                pass
            # Дополнительно закрываем SQLite-соединение и собираем GC, чтобы гарантировать снятие блокировки
            try:
                del app_client
                import gc; gc.collect()
            except Exception:
                pass
            self.finished.emit(True, 'SUCCESS', self.extra)
        except Exception as e:
            self.finished.emit(False, str(e), self.extra)
        finally:
            try:
                if app_client is not None:
                    try:
                        app_client.disconnect()
                    except Exception:
                        pass
                    try:
                        if hasattr(app_client, "_file_lock"):
                            app_client._file_lock.release()
                    except Exception:
                        pass
                    try:
                        del app_client
                        import gc; gc.collect()
                    except Exception:
                        pass
            except Exception:
                pass

class TelegramAuthWorker(QThread):
    """Поток, который ведёт авторизацию полностью (send_code → sign_in → check_password).\n
    • send_code вызывается один раз при запуске.\n    • Поток остаётся работать и ждёт, пока GUI пришлёт код или пароль через сигналы.\n    • Клиент НЕ отключается между шагами, поэтому hash не устаревает."""

    finished = pyqtSignal(bool, str, dict)             # success, message, extra
    submit_code = pyqtSignal(str)                      # принимает введённый код из GUI
    submit_password = pyqtSignal(str)                  # принимает пароль 2FA из GUI
    progress = pyqtSignal(int, str)                    # progress_value, status_text
    
    def __init__(self, session_name: str, api_id: int, api_hash: str, phone: str):
        super().__init__()
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone

        # Данные, которые пополняет GUI
        self.phone_code: Optional[str] = None
        self.phone_code_hash: Optional[str] = None
        self.password: Optional[str] = None

        # служебные флаги
        self._signed_in = False
        self._cancel_requested = False

        # Соединяем внутренние слоты
        self.submit_code.connect(self._on_code)
        self.submit_password.connect(self._on_password)

    def cancel(self):
        """Запрашивает отмену процесса авторизации."""
        self._cancel_requested = True

    @pyqtSlot(str)
    def _on_code(self, code: str):
        self.phone_code = code.strip()

    @pyqtSlot(str)
    def _on_password(self, pwd: str):
        self.password = pwd
    
    def run(self):
        try:
            # Прогресс: Начало авторизации (0%)
            self.progress.emit(0, "Подключение к Telegram...")

            # Убедимся, что родительская директория для .session-файла присутствует
            Path(self.session_name).parent.mkdir(parents=True, exist_ok=True)
            _dbg(f'TelegramAuthWorker: open session {self.session_name}')

            # Прогресс: Подключение (20%)
            self.progress.emit(20, "Установка соединения...")
            client = open_client(self.session_name, self.api_id, self.api_hash, start_client=False)

            # 1. Отправляем код всегда один раз (40%)
            self.progress.emit(40, "Отправка кода подтверждения...")
            try:
                sent = client.send_code(self.phone)
            except errors.FloodWait as fw:
                client.disconnect()
                self.progress.emit(100, f"FloodWait {fw.value} сек")
                self.finished.emit(False, f"FLOOD_WAIT_{fw.value}", {})
                return
            except errors.PhoneNumberInvalid:
                try:
                    client.disconnect()
                except Exception:
                    pass
                self.progress.emit(100, "Неверный номер телефона")
                self.finished.emit(False, "PHONE_NUMBER_INVALID", {})
                return
            except errors.ApiIdInvalid:
                try:
                    client.disconnect()
                except Exception:
                    pass
                self.progress.emit(100, "Неверный API ID")
                self.finished.emit(False, "API_ID_INVALID", {})
                return
            except errors.ApiHashInvalid:
                try:
                    client.disconnect()
                except Exception:
                    pass
                self.progress.emit(100, "Неверный API Hash")
                self.finished.emit(False, "API_HASH_INVALID", {})
                return

            self.phone_code_hash = sent.phone_code_hash
            self.progress.emit(60, "Ожидание кода подтверждения...")
            self.finished.emit(True, "NEED_CODE", {"phone_code_hash": self.phone_code_hash})

            # Основной цикл ожидания ввода пользователя
            while not self._signed_in:
                self.msleep(200)  # 0.2 секунды – нагрузка минимальна

                # Отмена пользователем
                if self._cancel_requested:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                    try:
                        if hasattr(client, "_file_lock"):
                            client._file_lock.release()
                    except Exception:
                        pass
                    try:
                        del client
                        import gc; gc.collect()
                    except Exception:
                        pass
                    self.progress.emit(100, "Авторизация отменена")
                    self.finished.emit(False, "CANCELLED", {})
                    return

                # --- Ввод кода ---
                if self.phone_code and not self._signed_in:
                    self.progress.emit(80, "Проверка кода подтверждения...")
                    try:
                        client.sign_in(
                            phone_number=self.phone,
                            phone_code_hash=self.phone_code_hash,
                            phone_code=self.phone_code,
                        )
                        self._signed_in = True
                        self.progress.emit(100, "Авторизация успешна")
                    except errors.PhoneCodeInvalid:
                        self.phone_code = None
                        self.progress.emit(60, "Неверный код, повторите")
                        self.finished.emit(False, "PHONE_CODE_INVALID", {})
                    except errors.PhoneCodeExpired:
                        sent = client.send_code(self.phone)
                        self.phone_code_hash = sent.phone_code_hash
                        self.phone_code = None
                        self.progress.emit(40, "Код истек, отправлен новый")
                        self.finished.emit(False, "PHONE_CODE_EXPIRED", {"phone_code_hash": self.phone_code_hash})
                    except errors.FloodWait as fw:
                        self.phone_code = None
                        try:
                            client.disconnect()
                        except Exception:
                            pass
                        self.progress.emit(100, f"FloodWait {fw.value} сек")
                        self.finished.emit(False, f"FLOOD_WAIT_{fw.value}", {})
                        return
                    except errors.SessionPasswordNeeded:
                        # Требуется пароль 2FA – ждём ввода
                        self.phone_code = None
                        self.progress.emit(90, "Требуется пароль 2FA")
                        self.finished.emit(True, "NEED_PASSWORD", {})

                # --- Ввод пароля 2FA ---
                if self.password and not self._signed_in:
                    self.progress.emit(95, "Проверка пароля 2FA...")
                    try:
                        client.check_password(self.password)
                        self._signed_in = True
                        self.progress.emit(100, "Авторизация успешна")
                    except errors.PasswordHashInvalid:
                        self.password = None
                        self.progress.emit(90, "Неверный пароль 2FA")
                        self.finished.emit(False, "PASSWORD_INVALID", {})

            # Успех
            self.progress.emit(100, "Завершение авторизации...")
            try:
                client.disconnect()
            except Exception:
                pass
            # Снимаем файловый lock
            try:
                if hasattr(client, "_file_lock"):
                    client._file_lock.release()
            except Exception:
                pass
            # Дополнительно закрываем SQLite-соединение и собираем GC, чтобы гарантировать снятие блокировки
            try:
                del client
                import gc; gc.collect()
            except Exception:
                pass
            self.progress.emit(100, "Авторизация завершена")
            self.finished.emit(True, "SUCCESS", {})

        except Exception as e:
            self.progress.emit(100, f"Ошибка: {str(e)[:30]}...")
            self.finished.emit(False, str(e), {})
        finally:
            try:
                if 'client' in locals() and client is not None:
                    try:
                        client.disconnect()
                    except Exception:
                        pass
                    try:
                        if hasattr(client, "_file_lock"):
                            client._file_lock.release()
                    except Exception:
                        pass
                    try:
                        del client
                        import gc; gc.collect()
                    except Exception:
                        pass
            except Exception:
                pass

class OptimizedBroadcastWorker(QThread):
    """Оптимизированный поток рассылки с волновой отправкой.

    Логика:
    - Волна 1: Аккаунт1 -> Сообщение1, через 3с Аккаунт2 -> Сообщение1, ..., через 3с АккаунтN -> Сообщение1
    - Через 60с Волна 2: Аккаунт1 -> Сообщение2, через 3с Аккаунт2 -> Сообщение2, ...
    - И так далее для всех сообщений

    parameters:
        accounts_info – список словарей, каждый содержит:
            session_name, api_id, api_hash, name, recipients(list[str])
        message – текст сообщения (HTML)
        media_files – список путей к медиа файлам
        inter_wave_delay – задержка между волнами (60 сек)
    """

    log = pyqtSignal(str)
    progress = pyqtSignal(int, str)  # progress_value, status_text

    def __init__(self, accounts_info: list[dict], message: str, media_files: list[str] = None,
                 inter_wave_delay_min: float = 30.0, inter_wave_delay_max: float = 60.0, scheduled_params: dict = None,
                 floodwait_auto_wait: bool = False, floodwait_max_wait: int = 60,
                 floodwait_exclude_threshold: int = 300,
                 dry_run: bool = False):
        super().__init__()
        self.accounts_info = accounts_info
        # Конвертируем HTML из скрипта сразу в Markdown V2
        self.message = html_to_telegram(message)
        self.media_files = media_files or []  # Список путей к медиа файлам
        self.inter_wave_delay_min = inter_wave_delay_min        # Минимальная задержка между волнами
        self.inter_wave_delay_max = inter_wave_delay_max        # Максимальная задержка между волнами
        self.scheduled_params = scheduled_params                 # Параметры отложенной отправки
        self.floodwait_auto_wait = floodwait_auto_wait          # Автоожидание FloodWait
        self.floodwait_max_wait = floodwait_max_wait            # Макс. время ожидания FloodWait
        self.floodwait_exclude_threshold = floodwait_exclude_threshold  # Порог исключения аккаунта
        self.broadcast_state = None                             # Broadcast state for resume functionality
        self.session_id = None                                  # Session ID for state management
        self._stop_requested = False
        self.dry_run = dry_run

        # Инициализируем состояние рассылки
        self._init_broadcast_state()

        # Статистика
        self.total_leads: int = 0
        self.sent_ok: int = 0
        self.sent_fail: int = 0
        self.error_reasons: list[str] = []
        self.schedule_corrected: int = 0  # Количество скорректированных планирований

        # Механизм синхронизации для предотвращения race condition
        self.client_locks = {}  # QMutex для каждого аккаунта
        self.failed_accounts = set()

        # Храним активные клиенты в течение всей рассылки, чтобы не переоткрывать сессию
        self.active_clients = {}
        self.max_concurrent_clients = len(accounts_info)  # Открываем на все аккаунты

    def stop(self):
        self._stop_requested = True

    def run(self):
        """Основная логика волновой отправки."""
        try:
            # Глобальный межпроцессный lock: только одна рассылка одновременно
            try:
                from filelock import Timeout
                self._broadcast_lock = FileLock(str(Path(USER_DATA_DIR) / 'broadcast.lock'))
                self._broadcast_lock.acquire(timeout=1)
            except Timeout:
                self.log.emit("<span style='color:red'>❌ Уже выполняется другая рассылка в другом окне приложения</span>")
                self.progress.emit(100, "Рассылка занята")
                return
            except Exception:
                # Не блокируем из-за ошибок lock, просто продолжаем
                self._broadcast_lock = None
            # Прогресс: Начало (0%)
            self.progress.emit(0, "Подготовка рассылки...")

            if self.scheduled_params:
                self.log.emit("<b>🚀 Начинаем отложенную рассылку</b>")
                self.log.emit(f"Аккаунтов: {len(self.accounts_info)} | Начало: {self.scheduled_params['start_datetime_local'].strftime('%d.%m.%Y %H:%M')} ({self.scheduled_params['timezone_name']}) | Задержка между сообщениями: {self.scheduled_params['message_delay_minutes']} мин")
            else:
                self.log.emit("<b>🚀 Начинаем оптимизированную рассылку</b>")
                self.log.emit(f"Аккаунтов: {len(self.accounts_info)} | Задержка между аккаунтами: 3.0с | Задержка между волнами: {self.inter_wave_delay_min:.1f}-{self.inter_wave_delay_max:.1f}с")

            # Шаг 1: Инициализируем механизм синхронизации (5%)
            self.progress.emit(5, "Инициализация синхронизации...")
            self._initialize_sync()

            # Проверяем наличие аккаунтов
            if not self.accounts_info:
                self.log.emit("<span style='color:red'>❌ Нет аккаунтов для рассылки</span>")
                self.progress.emit(100, "Рассылка завершена")
                return

            # Шаг 2: Определяем максимальное количество сообщений (волн) (10%)
            self.progress.emit(10, "Расчет параметров отправки...")
            eligible = [len(acc.get("recipients", [])) for acc in self.accounts_info if acc.get("name") not in self.failed_accounts]
            max_messages = max(eligible) if eligible else 0
            if max_messages == 0:
                self.log.emit("<span style='color:orange'>❗ Нет получателей для рассылки</span>")
                self.progress.emit(100, "Рассылка завершена")
                return

            self.log.emit(f"Максимум сообщений на аккаунт: {max_messages}")
            mode = "DRY-RUN (без отправки)" if self.dry_run else "волновую отправку"
            self.log.emit(f"<b>📤 Начинаем {mode}...</b>")

            # Шаг 3: Волновая отправка (10-90%)
            for wave_idx in range(max_messages):
                if self._stop_requested:
                    break
                
                # Обновляем прогресс для каждой волны
                progress_value = 10 + int((wave_idx / max_messages) * 80)
                self.progress.emit(progress_value, f"Волна {wave_idx + 1}/{max_messages}")

                self.log.emit(f"<b>🌊 Волна {wave_idx + 1}/{max_messages}</b>")

                # Отправка волны всеми аккаунтами с задержкой
                self._send_wave(wave_idx)

                # Задержка между волнами (кроме последней)
                # Для отложенной отправки соблюдаем интервалы, чтобы избежать одновременной отправки всех волн
                if wave_idx < max_messages - 1:
                    actual_wave_delay = random.uniform(self.inter_wave_delay_min, self.inter_wave_delay_max)
                    if self.scheduled_params:
                        self.log.emit(f"⏳ Отложенная отправка: ожидание {actual_wave_delay:.1f}с до следующей волны...")
                    else:
                        self.log.emit(f"⏳ Ожидание {actual_wave_delay:.1f}с до следующей волны...")
                    self._wait_with_check(actual_wave_delay)

            # Итоговый отчёт (100%)
            self.progress.emit(100, "Формирование отчета...")
            self._generate_report()

            self.progress.emit(100, "Рассылка завершена")

        except Exception as e:
            self.log.emit(f"<span style='color:red'>❌ Критическая ошибка: {str(e)}</span>")
            self.progress.emit(100, "Ошибка выполнения")
            return
        finally:
            # Сохраняем состояние рассылки для возможности возобновления
            if self.broadcast_state:
                try:
                    self.broadcast_state.save()
                    self.log.emit(f"📊 Состояние рассылки сохранено (сессия: {self.session_id})")
                except Exception as state_err:
                    self.log.emit(f"<span style='color:orange'>⚠️ Ошибка сохранения состояния: {str(state_err)}</span>")

            try:
                self._cleanup_clients()
            except Exception as cleanup_err:
                _dbg(f"Cleanup error: {cleanup_err}")
            # Снимаем глобальный lock
            try:
                if hasattr(self, '_broadcast_lock') and self._broadcast_lock and getattr(self._broadcast_lock, 'is_locked', False):
                    self._broadcast_lock.release()
            except Exception:
                pass

    def _initialize_sync(self):
        """Инициализирует механизм синхронизации для всех аккаунтов."""
        self.log.emit("<b>🔒 Инициализируем синхронизацию...</b>")

        for acc in self.accounts_info:
            name = acc["name"]
            # Создаем mutex для каждого аккаунта для предотвращения race condition
            self.client_locks[name] = QMutex()
            _dbg(f'Initialized mutex for account: {name}')

        self.log.emit(f"✅ Синхронизация инициализирована для {len(self.client_locks)} аккаунтов")

    def _init_broadcast_state(self):
        """Initialize broadcast state for resume functionality."""
        import uuid
        self.session_id = str(uuid.uuid4())

        # Create new broadcast state
        self.broadcast_state = BroadcastState(
            session_id=self.session_id,
            accounts_info=self.accounts_info,
            message=self.message
        )

        self.log.emit(f"📊 Создана сессия рассылки: {self.session_id}")

    def _get_client(self, account_name: str, account_data: dict):
        """Получает или создает клиент для аккаунта с синхронизацией."""
        mutex = self.client_locks.get(account_name)
        if not mutex:
            raise RuntimeError(f"Mutex not found for account: {account_name}")

        with QMutexLocker(mutex):  # Автоматическая блокировка/разблокировка
            # Проверяем, есть ли уже активный клиент
            if account_name in self.active_clients:
                return self.active_clients[account_name]

            # Ограничиваем количество одновременных клиентов для экономии памяти
            while len(self.active_clients) >= self.max_concurrent_clients:
                if self._stop_requested:
                    return None
                time.sleep(0.1)  # Ждем освобождения клиента

            try:
                # Гарантируем, что каталог для .session-файла существует
                sess_path = Path(account_data['session_name'])
                sess_path.parent.mkdir(parents=True, exist_ok=True)

                _dbg(f'Creating client for account: {account_name}')
                # Если клиент уже создан ранее (между волнами) — переиспользуем
                if account_name in self.active_clients:
                    return self.active_clients[account_name]

                # Добавим небольшую случайную задержку, чтобы избежать одновременного захвата sqlite/lock
                time.sleep(random.uniform(0.05, 0.2))
                client = open_client(account_data['session_name'], account_data['api_id'], account_data['api_hash'])
                self.active_clients[account_name] = client
                return client

            except Exception as e:
                # Не помечаем аккаунт как проваленный при временной блокировке сессии.
                # Такие ошибки транзиентны и должны повторно пытаться на следующих волнах.
                err_msg = str(e)
                if (
                    "Сессия уже используется" in err_msg
                    or "database is locked" in err_msg.lower()
                    or "persistent database lock" in err_msg.lower()
                ):
                    # Пробрасываем исключение, чтобы зафиксировать в логах причину,
                    # но НЕ исключаем аккаунт из дальнейших волн.
                    raise e
                # Для прочих ошибок исключаем аккаунт, как фатальный случай
                self.failed_accounts.add(account_name)
                if self.broadcast_state:
                    self.broadcast_state.mark_account_failed(account_name)
                raise e

    def _release_client(self, account_name: str):
        """Освобождает клиент и снимает блокировку."""
        mutex = self.client_locks.get(account_name)
        if not mutex:
            return

        with QMutexLocker(mutex):
            if account_name in self.active_clients:
                client = None
                try:
                    client = self.active_clients[account_name]
                    # Корректно останавливаем Pyrogram-клиент, чтобы закрыть event loop и sqlite
                    try:
                        client.stop()
                    except Exception:
                        try:
                            client.disconnect()
                        except Exception:
                            pass
                    # Снимаем файловый lock
                    if hasattr(client, "_file_lock"):
                        try:
                            client._file_lock.release()
                        except Exception:
                            pass
                except Exception as e:
                    _dbg(f'Error disconnecting client {account_name}: {e}')
                finally:
                    # Гарантированно удаляем из активных клиентов
                    if account_name in self.active_clients:
                        del self.active_clients[account_name]
                    
                    # Дополнительная очистка памяти
                    if client:
                        try:
                            # Освобождаем SQLite соединения
                            import gc
                            del client
                            gc.collect()
                        except Exception:
                            pass

    def _send_wave(self, wave_idx: int):
        """Отправляет волну сообщений (одно сообщение всеми аккаунтами)."""
        active_accounts = []
        for acc in self.accounts_info:
            name = acc["name"]
            if name in self.failed_accounts:
                continue
            if len(acc.get("recipients", [])) > wave_idx:
                active_accounts.append((name, acc))

        if not active_accounts:
            return

        if self.scheduled_params:
            self.log.emit(f"Планирование отправки {len(active_accounts)} аккаунтами...")
        else:
            self.log.emit(f"Отправка {len(active_accounts)} аккаунтами...")

        # Отправка каждым аккаунтом
        for i, (name, acc) in enumerate(active_accounts):
            if self._stop_requested:
                break

            # Проверяем, не находится ли аккаунт в паузе


            recipient = acc["recipients"][wave_idx]
            success = self._send_single_message(name, acc, recipient, wave_idx + 1)
            
            # Клиента не закрываем до конца рассылки, чтобы не терять файловый lock

            # Задержка между аккаунтами (кроме последнего) - фиксированная 3с
            if i < len(active_accounts) - 1 and not self.scheduled_params:
                actual_delay = 3.0
                self.log.emit(f"⏱️  Задержка {actual_delay:.1f}с перед следующим аккаунтом...")
                self._wait_with_check(actual_delay)

    def _send_single_message(self, account_name: str, account_data: dict, recipient: str, message_num: int, retry_count: int = 0):
        """Отправляет одно сообщение от конкретного аккаунта."""
        try:
            def norm(r: str):
                r = r.strip().replace('https://t.me/', '').replace('http://t.me/', '').replace('t.me/', '')
                if r.startswith('@'):
                    r = r[1:]
                return r

            normalized_recipient = norm(recipient)
            # DRY-RUN: ничего не отправляем, только логируем успешную 'проверку'
            if self.dry_run:
                self.log.emit(f"{account_name}: 🧪 DRY-RUN #{message_num} → {recipient}")
                self.sent_ok += 1
                if self.broadcast_state:
                    wave_idx = message_num - 1
                    self.broadcast_state.mark_message_sent(account_name, recipient, wave_idx)
                return True

            # Получаем или создаем клиента с синхронизацией
            client = self._get_client(account_name, account_data)
            if not client:
                return False

            _dbg(f'optimized_send: {account_name} -> {normalized_recipient} (msg #{message_num})')

            # Перед отправкой проверяем, что клиент авторизован и инициализирован.
            # Это устраняет редкую ошибку внутри Pyrogram: `'NoneType' object has no attribute 'is_premium'`,
            # возникающую, когда `client.me` ещё не инициализирован или сессия невалидна.
            try:
                me = client.get_me()
                if me is None:
                    raise errors.Unauthorized("Client is not authorized")
            except Exception as auth_exc:
                self.sent_fail += 1
                self.error_reasons.append(f"{account_name}: аккаунт не авторизован – {str(auth_exc)[:100]}")
                self.log.emit("<span style='color:red'>%s: ❌ Аккаунт не авторизован или сессия повреждена. Перезайдите во вкладке «Аккаунты».</span>" % account_name)
                logging.error(f"ACCOUNT_UNAUTHORIZED: {account_name}: {auth_exc}")
                self.failed_accounts.add(account_name)
                if self.broadcast_state:
                    self.broadcast_state.mark_account_failed(account_name)
                return False

            # Определяем время отправки для отложенной отправки
            schedule_date = None
            schedule_valid = True
            if self.scheduled_params:
                # Расчет времени отправки: start_datetime_utc + (message_num - 1) * message_delay_minutes
                message_delay_seconds = (message_num - 1) * self.scheduled_params['message_delay_minutes'] * 60
                schedule_datetime_utc = self.scheduled_params['start_datetime_utc'] + datetime.timedelta(seconds=message_delay_seconds)

                # Проверяем корректность времени планирования
                current_time = datetime.datetime.now(datetime.timezone.utc)
                max_future_time = current_time + datetime.timedelta(days=365)  # Telegram ограничивает планирование до 1 года

                if schedule_datetime_utc <= current_time:
                    # Время уже прошло - отправляем немедленно
                    self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Время планирования #{message_num} уже прошло - отправка немедленно</span>")
                    schedule_date = None
                    schedule_valid = False
                    self.schedule_corrected += 1
                elif schedule_datetime_utc > max_future_time:
                    # Слишком далеко в будущем
                    self.log.emit(f"<span style='color:red'>{account_name}: ❌ Время планирования #{message_num} слишком далеко в будущем (макс. 1 год)</span>")
                    schedule_date = None
                    schedule_valid = False
                    self.schedule_corrected += 1
                else:
                    schedule_date = schedule_datetime_utc

                # Показываем время в локальном часовом поясе пользователя для удобства
                local_schedule_time = schedule_datetime_utc.astimezone(self.scheduled_params['start_datetime_local'].tzinfo)
                if schedule_valid:
                    self.log.emit(f"{account_name}: 📅 Отложенная отправка #{message_num} на {local_schedule_time.strftime('%d.%m.%Y %H:%M')} ({self.scheduled_params['timezone_name']})")
                else:
                    self.log.emit(f"{account_name}: 📅 Планирование #{message_num} на {local_schedule_time.strftime('%d.%m.%Y %H:%M')} ({self.scheduled_params['timezone_name']}) - скорректировано")

            # Отправляем медиа файлы, если они есть
            media_sent = False
            if self.media_files:
                # Отправляем каждое изображение с текстом как подписью
                for media_file in self.media_files:
                    try:
                        # Проверяем, существует ли файл
                        if not os.path.exists(media_file):
                            self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Файл не найден: {os.path.basename(media_file)}</span>")
                            continue

                        # Проверяем размер файла
                        file_size = os.path.getsize(media_file)
                        max_photo_size = 10 * 1024 * 1024  # 10MB для фото в Telegram
                        max_document_size = 2 * 1024 * 1024 * 1024  # 2GB для документов в Telegram

                        if file_size > max_document_size:
                            self.log.emit(f"<span style='color:red'>{account_name}: ❌ Файл слишком большой для Telegram (макс 2GB): {os.path.basename(media_file)} ({file_size / (1024*1024*1024):.1f}GB)</span>")
                            continue

                        # Определяем тип файла по расширению
                        import mimetypes
                        mime_type, _ = mimetypes.guess_type(media_file)

                        # Проверяем, удалось ли определить MIME-тип
                        if mime_type is None:
                            self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Не удалось определить тип файла: {os.path.basename(media_file)} - отправка как документ</span>")
                            mime_type = 'application/octet-stream'  # fallback тип

                        # Определяем caption (текст только к первому файлу)
                        caption = self.message if media_file == self.media_files[0] else None
                        # Telegram ограничивает длину подписи 1024 символами
                        send_text_separately_after_media = False
                        caption_to_send = caption
                        if caption and len(caption) > 1024:
                            self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Подпись длиннее 1024 символов – отправим текст отдельным сообщением</span>")
                            caption_to_send = None
                            send_text_separately_after_media = True

                        if mime_type == 'image/gif':
                            # Специальная обработка для GIF файлов
                            try:
                                client.send_document(
                                    chat_id=normalized_recipient,
                                    document=media_file,
                                    caption=caption_to_send,
                                    parse_mode=ParseMode.HTML,
                                    schedule_date=schedule_date
                                )
                                schedule_status = "запланирован" if schedule_date else "отправлен"
                                self.log.emit(f"{account_name}: 📎 GIF {os.path.basename(media_file)} {'с текстом' if caption else ''} {schedule_status}")
                            except Exception as schedule_error:
                                # Если планирование не удалось, пробуем отправить без schedule_date
                                schedule_error_str = str(schedule_error).lower()
                                is_schedule_error = (
                                    "schedule" in schedule_error_str or
                                    "too old" in schedule_error_str or
                                    "too many" in schedule_error_str or
                                    "invalid schedule" in schedule_error_str
                                )
                                if schedule_date and is_schedule_error:
                                    self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование GIF не удалось: {schedule_error} - отправка немедленно</span>")
                                    client.send_document(
                                        chat_id=normalized_recipient,
                                        document=media_file,
                                    caption=caption_to_send,
                                        parse_mode=ParseMode.HTML
                                )
                                self.log.emit(f"{account_name}: 📎 GIF {os.path.basename(media_file)} {'с текстом' if caption else ''} отправлен немедленно")
                                self.schedule_corrected += 1
                            else:
                                raise schedule_error
                        elif mime_type and mime_type.startswith('video/'):
                            # Отправляем как видео
                            try:
                                client.send_video(
                                    chat_id=normalized_recipient,
                                    video=media_file,
                                    caption=caption_to_send,
                                    parse_mode=ParseMode.HTML,
                                    schedule_date=schedule_date
                                )
                                schedule_status = "запланировано" if schedule_date else "отправлено"
                                self.log.emit(f"{account_name}: 🎬 Видео {os.path.basename(media_file)} {'с текстом' if caption else ''} {schedule_status}")
                            except Exception as schedule_error:
                                schedule_error_str = str(schedule_error).lower()
                                is_schedule_error = (
                                    "schedule" in schedule_error_str or
                                    "too old" in schedule_error_str or
                                    "too many" in schedule_error_str or
                                    "invalid schedule" in schedule_error_str
                                )
                                if schedule_date and is_schedule_error:
                                    self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование видео не удалось: {schedule_error} - отправка немедленно</span>")
                                    client.send_video(
                                        chat_id=normalized_recipient,
                                        video=media_file,
                                        caption=caption_to_send,
                                        parse_mode=ParseMode.HTML
                                    )
                                    self.log.emit(f"{account_name}: 🎬 Видео {os.path.basename(media_file)} {'с текстом' if caption else ''} отправлено немедленно")
                                    self.schedule_corrected += 1
                                else:
                                    raise schedule_error
                        elif mime_type and mime_type.startswith('audio/'):
                            # Отправляем как аудио
                            try:
                                client.send_audio(
                                    chat_id=normalized_recipient,
                                    audio=media_file,
                                    caption=caption_to_send,
                                    parse_mode=ParseMode.HTML,
                                    schedule_date=schedule_date
                                )
                                schedule_status = "запланировано" if schedule_date else "отправлено"
                                self.log.emit(f"{account_name}: 🎵 Аудио {os.path.basename(media_file)} {'с текстом' if caption else ''} {schedule_status}")
                            except Exception as schedule_error:
                                schedule_error_str = str(schedule_error).lower()
                                is_schedule_error = (
                                    "schedule" in schedule_error_str or
                                    "too old" in schedule_error_str or
                                    "too many" in schedule_error_str or
                                    "invalid schedule" in schedule_error_str
                                )
                                if schedule_date and is_schedule_error:
                                    self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование аудио не удалось: {schedule_error} - отправка немедленно</span>")
                                    client.send_audio(
                                        chat_id=normalized_recipient,
                                        audio=media_file,
                                        caption=caption_to_send,
                                        parse_mode=ParseMode.HTML
                                    )
                                    self.log.emit(f"{account_name}: 🎵 Аудио {os.path.basename(media_file)} {'с текстом' if caption else ''} отправлено немедленно")
                                    self.schedule_corrected += 1
                                else:
                                    # Невозможно запланировать и отправить – пробуем как документ без планирования
                                    self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Отправка GIF как документ не удалась: {schedule_error}</span>")
                                    raise schedule_error
                        elif mime_type and mime_type.startswith('image/'):
                            # Фото принимаются как фото только для JPEG/PNG. Остальные форматы отправляем как документ.
                            allowed_photo_types = {'image/jpeg', 'image/png'}
                            if mime_type not in allowed_photo_types:
                                self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Формат изображения не поддерживается как фото ({mime_type}), отправляем как документ: {os.path.basename(media_file)}</span>")
                                try:
                                    client.send_document(
                                        chat_id=normalized_recipient,
                                        document=media_file,
                                        caption=caption_to_send,
                                        parse_mode=ParseMode.HTML,
                                        schedule_date=schedule_date
                                    )
                                    schedule_status = "запланирован" if schedule_date else "отправлен"
                                    self.log.emit(f"{account_name}: 📎 Документ {os.path.basename(media_file)} {'с текстом' if caption else ''} {schedule_status}")
                                except Exception as schedule_error:
                                    schedule_error_str = str(schedule_error).lower()
                                    is_schedule_error = (
                                        "schedule" in schedule_error_str or
                                        "too old" in schedule_error_str or
                                        "too many" in schedule_error_str or
                                        "invalid schedule" in schedule_error_str
                                    )
                                    if schedule_date and is_schedule_error:
                                        self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование документа не удалось: {schedule_error} - отправка немедленно</span>")
                                        client.send_document(
                                            chat_id=normalized_recipient,
                                            document=media_file,
                                            caption=caption_to_send,
                                            parse_mode=ParseMode.HTML
                                        )
                                        self.log.emit(f"{account_name}: 📎 Документ {os.path.basename(media_file)} {'с текстом' if caption else ''} отправлен немедленно")
                                        self.schedule_corrected += 1
                                    else:
                                        raise schedule_error
                            elif file_size > max_photo_size:
                                self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Изображение больше 10MB, отправляем как документ: {os.path.basename(media_file)} ({file_size / (1024*1024):.1f}MB)</span>")
                                # Отправляем как документ
                                try:
                                    client.send_document(
                                        chat_id=normalized_recipient,
                                        document=media_file,
                                        caption=caption_to_send,
                                        parse_mode=ParseMode.HTML,
                                        schedule_date=schedule_date
                                    )
                                    schedule_status = "запланирован" if schedule_date else "отправлен"
                                    self.log.emit(f"{account_name}: 📎 Документ {os.path.basename(media_file)} {'с текстом' if caption else ''} {schedule_status}")
                                except Exception as schedule_error:
                                    # Если планирование не удалось, пробуем отправить без schedule_date
                                    schedule_error_str = str(schedule_error).lower()
                                    is_schedule_error = (
                                        "schedule" in schedule_error_str or
                                        "too old" in schedule_error_str or
                                        "too many" in schedule_error_str or
                                        "invalid schedule" in schedule_error_str
                                    )
                                    if schedule_date and is_schedule_error:
                                        self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование документа не удалось: {schedule_error} - отправка немедленно</span>")
                                        client.send_document(
                                            chat_id=normalized_recipient,
                                            document=media_file,
                                            caption=caption_to_send,
                                            parse_mode=ParseMode.HTML
                                        )
                                        self.log.emit(f"{account_name}: 📎 Документ {os.path.basename(media_file)} {'с текстом' if caption else ''} отправлен немедленно")
                                        self.schedule_corrected += 1
                                    else:
                                        # Если это не ошибка планирования, пробуем отправить как документ
                                        try:
                                            client.send_document(
                                                chat_id=normalized_recipient,
                                                document=media_file,
                                                caption=caption_to_send,
                                                parse_mode=ParseMode.HTML,
                                                schedule_date=schedule_date
                                            )
                                            schedule_status = "запланирован" if schedule_date else "отправлен"
                                            self.log.emit(f"{account_name}: 📎 Документ (fallback от фото) {os.path.basename(media_file)} {schedule_status}")
                                        except Exception as doc_error:
                                            self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Fallback фото→документ не удался: {doc_error}</span>")
                                            logging.error(f"MEDIA_ERROR_FALLBACK_PHOTO_DOC: {account_name} -> {os.path.basename(media_file)}: {doc_error}")
                                            raise schedule_error
                            else:
                                # Отправляем как изображение (JPEG/PNG <= 10MB)
                                try:
                                    with open(media_file, 'rb') as photo_fp:
                                        client.send_photo(
                                        chat_id=normalized_recipient,
                                            photo=photo_fp,
                                        caption=caption_to_send,
                                        parse_mode=ParseMode.HTML,
                                        schedule_date=schedule_date
                                    )
                                    schedule_status = "запланировано" if schedule_date else "отправлено"
                                    self.log.emit(f"{account_name}: 📎 Фото {os.path.basename(media_file)} {'с текстом' if caption else ''} {schedule_status}")
                                except Exception as schedule_error:
                                    # Если планирование не удалось, пробуем отправить без schedule_date
                                    schedule_error_str = str(schedule_error).lower()
                                    is_schedule_error = (
                                        "schedule" in schedule_error_str or
                                        "too old" in schedule_error_str or
                                        "too many" in schedule_error_str or
                                        "invalid schedule" in schedule_error_str
                                    )
                                    if schedule_date and is_schedule_error:
                                        self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование фото не удалось: {schedule_error} - отправка немедленно</span>")
                                        with open(media_file, 'rb') as photo_fp:
                                            client.send_photo(
                                            chat_id=normalized_recipient,
                                                photo=photo_fp,
                                            caption=caption_to_send,
                                            parse_mode=ParseMode.HTML
                                        )
                                        self.log.emit(f"{account_name}: 📎 Фото {os.path.basename(media_file)} {'с текстом' if caption else ''} отправлено немедленно")
                                        self.schedule_corrected += 1
                                    else:
                                        # Если это не ошибка планирования, пробуем отправить как документ
                                        try:
                                            client.send_document(
                                                chat_id=normalized_recipient,
                                                document=media_file,
                                                caption=caption_to_send,
                                                parse_mode=ParseMode.HTML,
                                                schedule_date=schedule_date
                                            )
                                            schedule_status = "запланирован" if schedule_date else "отправлен"
                                            self.log.emit(f"{account_name}: 📎 Документ (fallback от фото) {os.path.basename(media_file)} {schedule_status}")
                                        except Exception as doc_error:
                                            self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Fallback фото→документ не удался: {doc_error}</span>")
                                            logging.error(f"MEDIA_ERROR_FALLBACK_PHOTO_DOC: {account_name} -> {os.path.basename(media_file)}: {doc_error}")
                                            raise schedule_error
                        else:
                            # Для других типов файлов отправляем как документ
                            try:
                                client.send_document(
                                    chat_id=normalized_recipient,
                                    document=media_file,
                                    caption=caption_to_send,
                                    parse_mode=ParseMode.HTML,
                                    schedule_date=schedule_date
                                )
                                schedule_status = "запланирован" if schedule_date else "отправлен"
                                self.log.emit(f"{account_name}: 📎 Документ {os.path.basename(media_file)} {'с текстом' if caption else ''} {schedule_status}")
                            except Exception as schedule_error:
                                # Если планирование не удалось, пробуем отправить без schedule_date
                                schedule_error_str = str(schedule_error).lower()
                                is_schedule_error = (
                                    "schedule" in schedule_error_str or
                                    "too old" in schedule_error_str or
                                    "too many" in schedule_error_str or
                                    "invalid schedule" in schedule_error_str
                                )
                                if schedule_date and is_schedule_error:
                                    self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование документа не удалось: {schedule_error} - отправка немедленно</span>")
                                    client.send_document(
                                        chat_id=normalized_recipient,
                                        document=media_file,
                                        caption=caption_to_send,
                                        parse_mode=ParseMode.HTML
                                    )
                                    self.log.emit(f"{account_name}: 📎 Документ {os.path.basename(media_file)} {'с текстом' if caption else ''} отправлен немедленно")
                                    self.schedule_corrected += 1
                                else:
                                    # Невозможно запланировать и отправить – пробуем как документ без планирования (повтор)
                                    self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Отправка документа не удалась: {schedule_error}</span>")
                                    raise schedule_error

                        media_sent = True

                        # Если подпись была слишком длинной, отправляем текст отдельным сообщением (только один раз)
                        if send_text_separately_after_media and caption and media_file == self.media_files[0]:
                            try:
                                client.send_message(
                                    normalized_recipient,
                                    self.message,
                                    parse_mode=ParseMode.HTML,
                                    disable_web_page_preview=contains_url(self.message),
                                    schedule_date=schedule_date
                                )
                                schedule_status = "запланировано" if schedule_date else "отправлено"
                                self.log.emit(f"{account_name}: 💬 Текст {schedule_status} отдельно (подпись слишком длинная)")
                            except Exception as schedule_error:
                                schedule_error_str = str(schedule_error).lower()
                                is_schedule_error = (
                                    "schedule" in schedule_error_str or
                                    "too old" in schedule_error_str or
                                    "too many" in schedule_error_str or
                                    "invalid schedule" in schedule_error_str
                                )
                                if schedule_date and is_schedule_error:
                                    self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование текста не удалось: {schedule_error} - отправка немедленно</span>")
                                    client.send_message(
                                        normalized_recipient,
                                        self.message,
                                        parse_mode=ParseMode.HTML,
                                        disable_web_page_preview=contains_url(self.message)
                                    )
                                    self.log.emit(f"{account_name}: 💬 Текст отправлен немедленно отдельно (подпись слишком длинная)")
                                    self.schedule_corrected += 1
                                else:
                                    raise schedule_error

                        # Небольшая задержка между отправкой файлов
                        if len(self.media_files) > 1:
                            time.sleep(0.5)

                    except Exception as media_error:
                        media_error_msg = str(media_error)
                        self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Ошибка отправки файла {os.path.basename(media_file)}: {media_error_msg}</span>")
                        # Логируем ошибку в auth.log для диагностики
                        logging.error(f"MEDIA_ERROR: {account_name} -> {os.path.basename(media_file)}: {media_error_msg}")
                        continue

                # Если не удалось отправить ни одного медиа файла, отправляем текстовое сообщение
                if not media_sent and self.message.strip():
                    try:
                        client.send_message(
                            normalized_recipient,
                            self.message,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=contains_url(self.message),
                            schedule_date=schedule_date
                        )
                        schedule_status = "запланировано" if schedule_date else "отправлено"
                        self.log.emit(f"{account_name}: 💬 Текстовое сообщение {schedule_status} (медиа файлы недоступны)")
                    except Exception as schedule_error:
                        # Если планирование не удалось, пробуем отправить без schedule_date
                        schedule_error_str = str(schedule_error).lower()
                        is_schedule_error = (
                            "schedule" in schedule_error_str or
                            "too old" in schedule_error_str or
                            "too many" in schedule_error_str or
                            "invalid schedule" in schedule_error_str
                        )
                        if schedule_date and is_schedule_error:
                            self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование текста не удалось: {schedule_error} - отправка немедленно</span>")
                            client.send_message(
                                normalized_recipient,
                                self.message,
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=contains_url(self.message)
                            )
                            self.log.emit(f"{account_name}: 💬 Текстовое сообщение отправлено немедленно (медиа файлы недоступны)")
                            self.schedule_corrected += 1
                        else:
                            raise schedule_error
            else:
                # Отправляем обычное текстовое сообщение
                try:
                    client.send_message(
                        normalized_recipient,
                        self.message,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=contains_url(self.message),
                        schedule_date=schedule_date
                    )
                    schedule_status = "запланировано" if schedule_date else "отправлено"
                    self.log.emit(f"{account_name}: 💬 Текстовое сообщение {schedule_status}")
                except Exception as schedule_error:
                    # Если планирование не удалось, пробуем отправить без schedule_date
                    schedule_error_str = str(schedule_error).lower()
                    is_schedule_error = (
                        "schedule" in schedule_error_str or
                        "too old" in schedule_error_str or
                        "too many" in schedule_error_str or
                        "invalid schedule" in schedule_error_str
                    )
                    if schedule_date and is_schedule_error:
                        self.log.emit(f"<span style='color:orange'>{account_name}: ⚠️ Планирование текста не удалось: {schedule_error} - отправка немедленно</span>")
                        client.send_message(
                            normalized_recipient,
                            self.message,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=contains_url(self.message)
                        )
                        self.log.emit(f"{account_name}: 💬 Текстовое сообщение отправлено немедленно")
                        self.schedule_corrected += 1
                    else:
                        raise schedule_error

            # Статистика по результату отправки текущего сообщения (получателя)
            self.sent_ok += 1
            media_info = " + медиа" if (self.media_files and media_sent) else ""

            # Определяем статус отправки для логов
            if self.scheduled_params:
                if schedule_valid:
                    schedule_info = f" (запланировано на {local_schedule_time.strftime('%H:%M')})"
                else:
                    schedule_info = " (отправлено немедленно - время скорректировано)"
            else:
                schedule_info = ""

            self.log.emit(f"{account_name}: ✅ #{message_num} → {recipient}{media_info}{schedule_info}")

            # Сбрасываем FloodWait множитель при успешной отправке


            # Отмечаем сообщение как отправленное в состоянии рассылки
            if self.broadcast_state:
                wave_idx = message_num - 1  # Convert to 0-based
                self.broadcast_state.mark_message_sent(account_name, recipient, wave_idx)

            return True

        except errors.FloodWait as fw:
            wait_seconds = fw.value

            if wait_seconds > self.floodwait_exclude_threshold:
                # FloodWait слишком большой - исключаем аккаунт без ожидания
                self.sent_fail += 1
                self.error_reasons.append(f"{account_name}: FLOOD_WAIT {wait_seconds}s (> {self.floodwait_exclude_threshold}s) – аккаунт исключен")
                self.log.emit(f"<span style='color:red'>{account_name}: ❌ FLOOD_WAIT {wait_seconds}s – превышен порог {self.floodwait_exclude_threshold}s, аккаунт исключен</span>")
                logging.error(f"FLOOD_WAIT_EXCLUDED_THRESHOLD: {account_name} -> {recipient}: {wait_seconds}s > {self.floodwait_exclude_threshold}s")
                self.failed_accounts.append(account_name)
                return False
            elif self.floodwait_auto_wait and wait_seconds <= self.floodwait_max_wait:
                adapted_wait, explanation = wait_seconds, f"базовая пауза {wait_seconds}s"

                self.log.emit(f"<span style='color:orange'>{account_name}: ⏳ FloodWait {wait_seconds}s – {explanation}...</span>")
                logging.warning(f"FLOOD_WAIT_ADAPTIVE: {account_name} -> {recipient}: {wait_seconds}s -> {adapted_wait}s ({explanation})")

                # Ожидаем адаптированное время
                self._wait_with_check(adapted_wait)

                # Повторяем попытку отправки (реальный ретрай)
                self.log.emit(f"<span style='color:blue'>{account_name}: 🔄 Повторная попытка после FloodWait (#{retry_count+1})</span>")
                # Ограничение на количество повторов, чтобы избежать бесконечных циклов
                if retry_count < 2 and not self._stop_requested:
                    return self._send_single_message(account_name, account_data, recipient, message_num, retry_count=retry_count+1)
                else:
                    # Если лимит повторов исчерпан — помечаем как неуспешную отправку
                    self.sent_fail += 1
                    self.error_reasons.append(f"{account_name}: FLOOD_WAIT {wait_seconds}s — лимит повторов исчерпан")
                    return False
            else:
                # FloodWait в пределах порога, но автоожидание отключено или превышен max_wait
                self.sent_fail += 1
                self.error_reasons.append(f"{account_name}: FLOOD_WAIT {wait_seconds}s – аккаунт исключен")
                self.log.emit(f"<span style='color:red'>{account_name}: ❌ FLOOD_WAIT {wait_seconds}s – аккаунт исключен</span>")
                logging.error(f"FLOOD_WAIT_EXCLUDED: {account_name} -> {recipient}: {wait_seconds}s")
                self.failed_accounts.add(account_name)
                if self.broadcast_state:
                    self.broadcast_state.mark_account_failed(account_name)
                return False

        except errors.PeerFlood:
            self.sent_fail += 1
            self.error_reasons.append(f"{account_name}: PEER_FLOOD")
            return False

        except errors.UserIsBlocked:
            self.sent_fail += 1
            self.error_reasons.append(f"{account_name}: Пользователь заблокировал бота")
            self.log.emit(f"<span style='color:orange'>{account_name}: ❌ #{message_num} → {recipient} – Пользователь заблокировал бота</span>")
            logging.error(f"USER_BLOCKED: {account_name} -> {recipient}")
            return False

        except errors.PeerIdInvalid:
            self.sent_fail += 1
            self.error_reasons.append(f"{account_name}: Неверный ID получателя")
            self.log.emit(f"<span style='color:orange'>{account_name}: ❌ #{message_num} → {recipient} – Неверный ID получателя</span>")
            logging.error(f"PEER_INVALID: {account_name} -> {recipient}")
            return False

        except errors.UsernameNotOccupied:
            self.sent_fail += 1
            self.error_reasons.append(f"{account_name}: Пользователь/канал не существует")
            self.log.emit(f"<span style='color:orange'>{account_name}: ❌ #{message_num} → {recipient} – Пользователь/канал не существует</span>")
            logging.error(f"USERNAME_NOT_OCCUPIED: {account_name} -> {recipient}")
            return False

        except errors.ChatWriteForbidden:
            self.sent_fail += 1
            self.error_reasons.append(f"{account_name}: Запрещено писать в чат")
            self.log.emit(f"<span style='color:orange'>{account_name}: ❌ #{message_num} → {recipient} – Запрещено писать в чат</span>")
            logging.error(f"CHAT_WRITE_FORBIDDEN: {account_name} -> {recipient}")
            return False

        except errors.ChannelPrivate:
            self.sent_fail += 1
            self.error_reasons.append(f"{account_name}: Канал приватный")
            self.log.emit(f"<span style='color:orange'>{account_name}: ❌ #{message_num} → {recipient} – Канал приватный</span>")
            logging.error(f"CHANNEL_PRIVATE: {account_name} -> {recipient}")
            return False

        except errors.SlowmodeWait as sw:
            # Логируем секунды, пропускаем без ожидания (для массовой рассылки рациональнее)
            self.sent_fail += 1
            self.error_reasons.append(f"{account_name}: Slowmode {sw.value}s – пропущен")
            self.log.emit(f"<span style='color:orange'>{account_name}: ❌ #{message_num} → {recipient} – Slowmode {sw.value}s (пропущен без ожидания)</span>")
            logging.warning(f"SLOWMODE_SKIP: {account_name} -> {recipient}: {sw.value}s (пропущен для эффективности рассылки)")
            return False

        except errors.MessageTooLong:
            self.sent_fail += 1
            self.error_reasons.append(f"{account_name}: Сообщение слишком длинное")
            self.log.emit(f"<span style='color:orange'>{account_name}: ❌ #{message_num} → {recipient} – Сообщение слишком длинное</span>")
            logging.error(f"MESSAGE_TOO_LONG: {account_name} -> {recipient}")
            return False

        # Прочие не фатальные исключения - лог и продолжить; аккаунт не исключаем
        except (errors.ChatAdminRequired, errors.ChatRestricted, errors.UserRestricted,
                errors.UserDeactivated, errors.UserNotMutualContact, errors.InviteHashExpired,
                errors.MediaInvalid, errors.FileReferenceExpired, errors.StickerInvalid) as e:
            error_type = type(e).__name__
            self.sent_fail += 1
            self.error_reasons.append(f"{account_name}: {error_type} – {str(e)[:100]}")
            self.log.emit(f"<span style='color:orange'>{account_name}: ❌ #{message_num} → {recipient} – {error_type}: {str(e)[:50]}...</span>")
            logging.warning(f"NON_FATAL_ERROR: {account_name} -> {recipient}: {error_type} - {str(e)}")
            return False

        except Exception as e:
            self.sent_fail += 1
            err_msg = str(e)
            self.error_reasons.append(f"{account_name}/#{message_num} → {recipient}: {err_msg}")
            self.log.emit(f"{account_name}: ❌ #{message_num} → {recipient} – {e}")
            # Логируем ошибку в auth.log
            logging.error(f"SEND_ERROR: {account_name} -> {recipient}: {err_msg}")
            return False

    def _wait_with_check(self, delay: float):
        """Ожидание в рабочем потоке без использования Qt-таймеров."""
        if delay <= 0:
            return

        remaining = delay
        while remaining > 0 and not self._stop_requested:
            chunk = min(0.1, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _cleanup_clients(self):
        """Закрывает все активные соединения и снимает блокировки."""
        self.log.emit("<b>🔌 Отключаем аккаунты...</b>")

        # Закрываем все активные клиенты
        for name in list(self.active_clients.keys()):
            self._release_client(name)

        # Очищаем mutex'ы
        self.client_locks.clear()

        self.log.emit("✅ Все соединения закрыты")
        import gc
        gc.collect()

    def _generate_report(self):
        """Генерирует итоговый отчет."""
        report_lines = [
            "<hr>",
            f"<b>📊 СТАТИСТИКА РАССЫЛКИ</b>",
            f"<b>Всего лидов:</b> {self.total_leads}",
        ]

        if self.scheduled_params:
            # Проверяем, были ли скорректированы времена
            current_utc = datetime.datetime.now(datetime.timezone.utc)
            start_utc = self.scheduled_params['start_datetime_utc']

            if start_utc < current_utc:
                schedule_status = "⚠️ Время скорректировано (начало в прошлом)"
            elif self.schedule_corrected > 0:
                schedule_status = f"⚠️ {self.schedule_corrected} планирований скорректировано"
            else:
                schedule_status = "✅ Планирование выполнено"

            report_lines.extend([
                f"<b>Запланировано к отправке:</b> {self.sent_ok}",
                f"<b>Ошибок планирования:</b> {self.sent_fail}",
                f"<b>Скорректировано планирований:</b> {self.schedule_corrected}",
                f"<b>Начало отправки:</b> {self.scheduled_params['start_datetime_local'].strftime('%d.%m.%Y %H:%M')} ({self.scheduled_params['timezone_name']})",
                f"<b>Интервал между сообщениями:</b> {self.scheduled_params['message_delay_minutes']} мин",
                f"<b>Статус планирования:</b> {schedule_status}",
            ])
        else:
            report_lines.extend([
            f"<b>Успешно отправлено:</b> {self.sent_ok}",
            f"<b>Ошибок:</b> {self.sent_fail}",
            ])

        if self.error_reasons:
            report_lines.append("<b>❌ Список ошибок:</b><br>" + "<br>".join(self.error_reasons))

        self.log.emit("<br>".join(report_lines))

        if self.scheduled_params:
            completion_msg = "<b>🏁 Планирование завершено! Сообщения будут отправлены Telegram в указанное время</b>"
        else:
            completion_msg = "<b>🏁 Рассылка завершена!</b>"

        self.log.emit(completion_msg if not self._stop_requested else "<b>⏹️  Рассылка остановлена</b>")

class ChatListWorker(QThread):
    partial = pyqtSignal(list)
    success = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, account_data: dict, batch_size: int = 200, max_items: Optional[int] = None):
        super().__init__()
        self.account_data = account_data
        self.batch_size = max(10, int(batch_size))
        self.max_items = max_items if (isinstance(max_items, int) and max_items > 0) else None

    def run(self):
        cli = None
        try:
            session_name = self.account_data['session_name']
            api_id = self.account_data['api_id']
            api_hash = self.account_data['api_hash']
            cli = open_client(session_name, api_id, api_hash)
            me = cli.get_me()

            # Сбор диалогов с прогрессивной выдачей
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def _collect_progressive():
                    collected = 0
                    batch_dialogs = []
                    async for d in cli.get_dialogs():
                        batch_dialogs.append(d)
                        collected += 1
                        if self.max_items and collected >= self.max_items:
                            break
                        if len(batch_dialogs) >= self.batch_size:
                            chats_partial = self._dialogs_to_chats(cli, me.id, batch_dialogs)
                            if chats_partial:
                                self.partial.emit(chats_partial)
                            batch_dialogs = []
                    # остаток
                    if batch_dialogs:
                        chats_partial = self._dialogs_to_chats(cli, me.id, batch_dialogs)
                        if chats_partial:
                            self.partial.emit(chats_partial)

                loop.run_until_complete(_collect_progressive())
            except Exception as e:
                self.error.emit(f"Ошибка загрузки чатов: {e}")
                return

            # Завершение: сигнализируем, что прогрузка закончена
            self.success.emit([])
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                if cli is not None:
                    try:
                        cli.stop()
                    except Exception:
                        try:
                            cli.disconnect()
                        except Exception:
                            pass
                    if hasattr(cli, "_file_lock"):
                        try:
                            cli._file_lock.release()
                        except Exception:
                            pass
            except Exception:
                pass

    def _dialogs_to_chats(self, cli: Client, my_id: int, dialogs: list) -> list[dict]:
        chats: list[dict] = []
        for d in dialogs:
            ch = getattr(d, 'chat', None)
            if not ch:
                continue
            if ch.type not in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
                continue
            username = getattr(ch, 'username', None)
            address = f"@{username}" if username else str(ch.id)
            # недавняя активность
            recent_ts = 0
            try:
                msg = getattr(d, 'top_message', None)
                dt = getattr(msg, 'date', None)
                if dt:
                    recent_ts = int(dt.timestamp()) if hasattr(dt, 'timestamp') else 0
            except Exception:
                recent_ts = 0

            can_write = None
            hint = None
            try:
                member = cli.get_chat_member(ch.id, my_id)
                status = getattr(member, 'status', None)
                if ch.type == ChatType.CHANNEL:
                    can_write = status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
                    if not can_write:
                        hint = "Нет прав на публикацию в канале"
                else:
                    if status == ChatMemberStatus.BANNED:
                        can_write = False
                        hint = "Пользователь забанен в чате"
                    elif status == ChatMemberStatus.RESTRICTED:
                        perms = getattr(member, 'permissions', None)
                        allowed = getattr(perms, 'can_send_messages', True) if perms is not None else False
                        can_write = bool(allowed)
                        if not can_write:
                            hint = "Ограничение на отправку сообщений"
                    else:
                        can_write = True
            except Exception:
                can_write = None
                hint = "Права не определены"

            chats.append({
                'id': ch.id,
                'title': ch.title or ch.first_name or str(ch.id),
                'username': username,
                'type': ch.type.name,
                'address': address,
                'can_write': can_write,
                'hint': hint,
                'recent_ts': recent_ts,
            })

        # Сортировка: недавние сверху, затем A→Z
        chats.sort(key=lambda c: (-int(c.get('recent_ts') or 0), (c['title'] or '').lower()))
        return chats


class LeadsEditorDialog(QDialog):
    def __init__(self, parent, text: str):
        super().__init__(parent)
        self.setWindowTitle("Редактирование лидов")
        self.resize(500, 600)
        self.layout = QVBoxLayout(self)
        
        self.editor = QTextEdit()
        self.editor.setPlainText(text)
        self.layout.addWidget(self.editor)
        
        self.info_label = QLabel("По одному получателю на строку")
        self.layout.addWidget(self.info_label)
        
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self.accept)
        save_btn.setProperty("role", "primary")
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        self.layout.addLayout(btn_layout)
        
        self.editor.textChanged.connect(self.update_count)
        self.update_count()
        
    def update_count(self):
        lines = [l for l in self.editor.toPlainText().split('\n') if l.strip()]
        self.info_label.setText(f"Лидов: {len(lines)}")
        
    def get_text(self):
        return self.editor.toPlainText()

class ChatPickerDialog(QDialog):
    def __init__(self, parent, account_name: str, chats: list[dict], on_refresh=None):
        super().__init__(parent)
        self.setWindowTitle(f"Чаты — {account_name}")
        self.setModal(True)
        self._all_chats = chats or []  # list of {id, title, username, type, address, can_write, hint}
        self._filtered = list(self._all_chats)
        self._on_refresh = on_refresh

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Top: search + refresh
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Поиск:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Название или @username")
        top_row.addWidget(self.search_input, 1)
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.setProperty("role", "secondary")
        top_row.addWidget(self.refresh_btn)
        layout.addLayout(top_row)

        # Loading / status
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#c97a7a;")
        layout.addWidget(self.status_label)

        # List and selection controls
        controls = QHBoxLayout()
        select_all_btn = QPushButton("Выбрать все")
        clear_sel_btn = QPushButton("Снять выделение")
        select_all_btn.setProperty("role", "secondary")
        clear_sel_btn.setProperty("role", "secondary")
        controls.addWidget(select_all_btn)
        controls.addWidget(clear_sel_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.list, 1)

        # Buttons
        btns = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setProperty("role", "primary")
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setProperty("role", "secondary")
        btns.addStretch()
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

        # Handlers
        def populate(items: list[dict]):
            self.list.clear()
            for ch in items:
                disp_username = f" (@{ch['username']})" if ch.get('username') else ""
                prefix = ""
                if ch.get('can_write') is False:
                    prefix = "🚫 "
                item = QListWidgetItem(f"{prefix}{ch['title']}{disp_username}\n{ch['address']}")
                item.setData(Qt.ItemDataRole.UserRole, ch['address'])
                if ch.get('hint'):
                    item.setToolTip(ch['hint'])
                self.list.addItem(item)

        self._populate = populate
        populate(self._filtered)

        # Debounce поиска
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(350)

        def apply_filter_now():
            t = (self.search_input.text() or "").strip().lower()
            if not t:
                self._filtered = list(self._all_chats)
            else:
                self._filtered = [c for c in self._all_chats if t in (c['title'] or '').lower() or (c.get('username') or '').lower().startswith(t.lstrip('@')) or t in c['address']]
            populate(self._filtered)

        self._debounce_timer.timeout.connect(apply_filter_now)
        def on_search_changed(_):
            self._debounce_timer.start()
        self.search_input.textChanged.connect(on_search_changed)

        def select_all():
            for i in range(self.list.count()):
                it = self.list.item(i)
                it.setSelected(True)

        def clear_selection():
            self.list.clearSelection()

        select_all_btn.clicked.connect(select_all)
        clear_sel_btn.clicked.connect(clear_selection)
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        self.refresh_btn.clicked.connect(lambda: self._on_refresh and self._on_refresh(True, self))

        # Счётчик выбранных
        self.selection_label = QLabel("")
        layout.addWidget(self.selection_label)
        def update_count():
            self.selection_label.setText(f"Выбрано: {len(self.list.selectedItems())}")
        self.list.itemSelectionChanged.connect(update_count)
        update_count()

    def selected_addresses(self) -> list[str]:
        addrs: list[str] = []
        for it in self.list.selectedItems():
            addr = it.data(Qt.ItemDataRole.UserRole)
            if addr:
                addrs.append(addr)
        return addrs

    def set_loading(self, is_loading: bool, text: str = ""):
        try:
            self.progress.setVisible(is_loading)
            self.status_label.setText(text or ("Загрузка..." if is_loading else ""))
        except Exception:
            pass

    def show_error(self, text: str):
        try:
            self.status_label.setText(text or "")
        except Exception:
            pass

    def refresh_with(self, chats: list[dict]):
        self._all_chats = chats or []
        self._filtered = list(self._all_chats)
        self._populate(self._filtered)

class TelegramApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TGFlow")
        # Флаг, предотвращающий конкурентные попытки авторизации
        self.is_auth_in_progress = False

        # Устанавливаем иконку с проверкой существования файла
        self._set_application_icon()

        self.setMinimumSize(800, 600)




        # Создаем центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Основной layout
        main_layout = QVBoxLayout(central_widget)
        
        # Создаем вкладки
        self.tabs = QTabWidget()
        self.tabs.setMovable(True)  # Разрешаем перемещать вкладки drag-and-drop
        main_layout.addWidget(self.tabs)
        
        # 1. Вкладка «Рассылка»
        self.broadcast_tab = QWidget()
        self.tabs.addTab(self.broadcast_tab, "Рассылка")
        
        # 2. «Чат-рассылка»
        self.chats_broadcast_tab = QWidget()
        self.tabs.addTab(self.chats_broadcast_tab, "Чат-рассылка")

        # 3. «Скрипты»
        self.scripts_tab = QWidget()
        self.tabs.addTab(self.scripts_tab, "Скрипты")

        # 4. «Аккаунты»
        self.accounts_tab = QWidget()
        self.tabs.addTab(self.accounts_tab, "Аккаунты")

        # 5. «История»
        self.history_tab = QWidget()
        self.tabs.addTab(self.history_tab, "История")
        
        # 6. «О программе»
        self.about_tab = QWidget()
        self.tabs.addTab(self.about_tab, "О программе")
        
        # Настройка вкладок
        self.setup_broadcast_tab()
        self.setup_accounts_tab()
        self.setup_chats_broadcast_tab()
        self.setup_scripts_tab()
        self.setup_history_tab()
        self.setup_about_tab()
        
        # Подключаем обработчик переключения вкладок (один раз при инициализации)
        self.tabs.currentChanged.connect(self._handle_tab_changed)
        
        # Загружаем сохраненные аккаунты
        self.load_accounts()
        self.load_broadcast_accounts()
        
    def _set_application_icon(self):
        """Устанавливает иконку приложения с проверкой существования файла."""
        import os
        from pathlib import Path
        
        # Попробуем тему системы (редко срабатывает, но не мешает)
        try:
            themed = QIcon.fromTheme('applications-graphics')
            if not themed.isNull():
                self.setWindowIcon(themed)
        except Exception:
            pass
        
        # Возможные относительные пути к иконке (в порядке приоритета)
        icon_paths = [
            "icon.icns",
            "28538791-c5e2-4ec8-9091-498b7e3e2ebd-_1_.ico",
            "resources/icon.icns",
            "resources/icon.ico",
            "resources/icon.png",
            "icon.ico",
            "icon.png",
        ]
        
        # Также проверяем пути относительно исходной директории проекта
        # на случай, если текущий каталог переключён на USER_DATA_DIR
        project_root = Path(__file__).parent
        candidate_paths: list[Path] = []
        for p in icon_paths:
            candidate_paths.append(Path(p))
            candidate_paths.append(project_root / p)
        
        for icon_path in candidate_paths:
            try:
                if icon_path.exists():
                    self.setWindowIcon(QIcon(str(icon_path)))
                    print(f"Иконка загружена из: {icon_path}")
                    return
            except Exception as e:
                print(f"Ошибка загрузки иконки из {icon_path}: {e}")
                continue
        
        print("Предупреждение: иконка не найдена, приложение будет без иконки")

    def _handle_tab_changed(self, index: int):
        """Обработчик переключения вкладок.
        
        Автоматически обновляет список скриптов при переходе на вкладку «Рассылка».
        """
        try:
            if self.tabs.widget(index) is self.broadcast_tab:
                self.reload_scripts_list()
        except Exception:
            pass

    def setup_accounts_tab(self):
        layout = QVBoxLayout(self.accounts_tab)
        
        # Форма добавления аккаунта
        form_layout = QVBoxLayout()
        
        # API ID
        api_id_layout = QHBoxLayout()
        api_id_label = QLabel("API ID:")
        self.api_id_input = QLineEdit()
        api_id_layout.addWidget(api_id_label)
        api_id_layout.addWidget(self.api_id_input)
        form_layout.addLayout(api_id_layout)
        
        # API Hash
        api_hash_layout = QHBoxLayout()
        api_hash_label = QLabel("API Hash:")
        self.api_hash_input = QLineEdit()
        api_hash_layout.addWidget(api_hash_label)
        api_hash_layout.addWidget(self.api_hash_input)
        form_layout.addLayout(api_hash_layout)
        
        # Телефон
        phone_layout = QHBoxLayout()
        phone_label = QLabel("Телефон:")
        self.phone_input = QLineEdit()
        phone_layout.addWidget(phone_label)
        phone_layout.addWidget(self.phone_input)
        form_layout.addLayout(phone_layout)
        
        # Имя аккаунта
        name_layout = QHBoxLayout()
        name_label = QLabel("Имя аккаунта:")
        self.name_input = QLineEdit()
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        form_layout.addLayout(name_layout)
        
        # Кнопка добавления
        add_button = QPushButton("Добавить аккаунт")
        add_button.setProperty("role", "success")
        add_button.clicked.connect(self.add_account)
        self.add_account_button = add_button
        form_layout.addWidget(add_button)
        
        layout.addLayout(form_layout)
        
        # Список аккаунтов
        self.accounts_list = QListWidget()
        layout.addWidget(self.accounts_list, 1)
        # Игнорируем клики по пустому месту, чтобы не вызывать странное поведение
        class _IgnoreEmptyClickFilter(QtCore.QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.MouseButtonPress:
                    item = obj.itemAt(event.pos())
                    if item is None:
                        return True
                return QtCore.QObject.eventFilter(self, obj, event)
        try:
            self._ignore_click_filter = _IgnoreEmptyClickFilter()
            self.accounts_list.installEventFilter(self._ignore_click_filter)
        except Exception:
            pass

        btn_acc_bar = QHBoxLayout()
        rename_acc_btn = QPushButton("Переименовать")
        del_acc_btn = QPushButton("Удалить")
        rename_acc_btn.setProperty("role", "secondary")
        del_acc_btn.setProperty("role", "danger")
        btn_acc_bar.addWidget(rename_acc_btn)
        btn_acc_bar.addWidget(del_acc_btn)
        btn_acc_bar.addStretch()
        layout.addLayout(btn_acc_bar)

        def refresh_accounts_list():
            self.accounts_list.clear()
            try:
                if os.path.exists('accounts.json'):
                    with open('accounts.json', 'r', encoding='utf-8') as f:
                        accs = json.load(f)
                else:
                    accs = []
            except Exception:
                accs = []
            for acc in accs:
                self.accounts_list.addItem(f"{acc['name']} ({acc['phone']})")

        self.refresh_accounts_list = refresh_accounts_list
        refresh_accounts_list()

        def selected_index() -> int:
            """Возвращает индекс выделенной строки в QListWidget либо -1."""
            row = self.accounts_list.currentRow()
            return row if row >= 0 else -1

        def rename_account():
            idx = selected_index()
            if idx < 0:
                return
            new_name, ok = QInputDialog.getText(self, "Переименовать", "Новое имя:")
            if ok and new_name.strip():
                try:
                    with open('accounts.json', 'r', encoding='utf-8') as f:
                        accs = json.load(f)
                    if idx < len(accs):
                        import re as _re
                        accs[idx]['name'] = _re.sub(r'\s+', ' ', new_name.strip())
                    with open('accounts.json', 'w', encoding='utf-8') as f:
                        json.dump(accs, f, ensure_ascii=False, indent=2)
                    refresh_accounts_list()
                    self.load_broadcast_accounts()
                    # Инвалидация кэша чатов по всем сессиям (имя менялось)
                    try:
                        if hasattr(self, '_chat_cache'):
                            self._chat_cache.clear()
                    except Exception:
                        pass
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка", str(e))

        def delete_account():
            idx = selected_index()
            if idx < 0:
                return
            if QMessageBox.question(self, "Удалить", "Удалить выбранный аккаунт?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            try:
                with open('accounts.json', 'r', encoding='utf-8') as f:
                    accs = json.load(f)
                if idx < len(accs):
                    removed = accs.pop(idx)
                with open('accounts.json', 'w', encoding='utf-8') as f:
                    json.dump(accs, f, ensure_ascii=False, indent=2)
                refresh_accounts_list()
                self.load_broadcast_accounts()
                # Инвалидируем кэш чатов по удаленной сессии
                try:
                    if hasattr(self, '_chat_cache') and isinstance(removed, dict):
                        sess = removed.get('session_name') or removed.get('phone')
                        if sess:
                            self._chat_cache.pop(sess, None)
                except Exception:
                    pass
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))

        rename_acc_btn.clicked.connect(rename_account)
        del_acc_btn.clicked.connect(delete_account)

    def _check_resume_possibility(self) -> Optional[Dict]:
        """Check if there are any resumable broadcast sessions.

        Returns:
            Session info dict or None if no resumable sessions found
        """
        from broadcast_state import BroadcastState
        candidates = BroadcastState.find_resume_candidates()
        return candidates[0] if candidates else None

    def _resume_broadcast(self, session_id: str):
        """Resume a broadcast session.

        Args:
            session_id: Session ID to resume
        """
        from broadcast_state import BroadcastState

        # Load broadcast state
        state = BroadcastState.load(session_id)
        if not state:
            QMessageBox.warning(self, "Ошибка", "Не удалось загрузить состояние рассылки")
            return

        # Show resume info
        stats = state.get_stats()
        QMessageBox.information(
            self, "Возобновление рассылки",
            f"Возобновляем рассылку:\n"
            f"• Отправлено: {stats['total_sent']}\n"
            f"• Активных аккаунтов: {stats['active_accounts']}\n"
            f"• Начало: {stats['start_time']}\n"
            f"• Сессия: {session_id[:8]}..."
        )

        # Start broadcast with loaded state
        self.start_broadcast_with_state(state)

    def start_broadcast_with_state(self, broadcast_state):
        """Start broadcast with pre-loaded state for resume functionality.

        Args:
            broadcast_state: BroadcastState instance with resume data
        """
        # This is a simplified version - in practice would need more integration
        # For now, just show that resume is not fully implemented
        QMessageBox.information(
            self, "Возобновление",
            "Функция возобновления рассылки находится в разработке.\n"
            "Пока что начнется новая рассылка."
        )

    def setup_broadcast_tab(self):
        outer_layout = QVBoxLayout(self.broadcast_tab)
        scroll_container = QScrollArea()
        scroll_container.setWidgetResizable(True)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_container.setWidget(scroll_content)
        outer_layout.addWidget(scroll_container, 1)

        # Выбор скрипта
        script_layout = QHBoxLayout()
        script_layout.addWidget(QLabel("Скрипт:"))
        self.script_combo = QComboBox()
        script_layout.addWidget(self.script_combo, 1)

        # Убираем ручную кнопку обновления списка скриптов — теперь автообновление при входе во вкладку

        # Кнопка массового сброса выбора аккаунтов/обновления не используется — удалена

        content_layout.addLayout(script_layout)

        self.script_preview = QTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setFixedHeight(120)
        content_layout.addWidget(self.script_preview)

        # Dry‑Run и Предпроверка
        precheck_bar = QHBoxLayout()
        self.dry_run_checkbox = QCheckBox("Пробный запуск (без отправки)")
        self.dry_run_checkbox.setToolTip("Ничего не отправляется — только логируется")
        precheck_bar.addWidget(self.dry_run_checkbox)
        precheck_bar.addStretch()
        content_layout.addLayout(precheck_bar)


        # Кнопка раскрытия расширенных настроек
        advanced_toggle = QToolButton()
        advanced_toggle.setText("Настроить")
        advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        advanced_toggle.setCheckable(True)
        advanced_toggle.setChecked(False)
        advanced_toggle.setProperty("role", "primary")  # Сделаем заметней
        content_layout.addWidget(advanced_toggle)

        # Контейнер расширенных настроек (скрываемый)
        advanced_container = QWidget()
        advanced_container_layout = QVBoxLayout(advanced_container)
        advanced_container_layout.setContentsMargins(0,0,0,0)
        content_layout.addWidget(advanced_container)

        def update_advanced_visible(checked: bool):
            advanced_container.setVisible(checked)
        advanced_toggle.toggled.connect(update_advanced_visible)
        advanced_container.setVisible(False)

        # Задержки
        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("Задержка между волнами (сек):"))
        config = self.load_config()
        wave_delay_layout = QHBoxLayout()
        self.wave_delay_min_input = QLineEdit(config.get('delays','wave_delay_min',fallback='30'))
        self.wave_delay_min_input.setFixedWidth(50)
        self.wave_delay_min_input.setToolTip("Минимальная задержка между волнами")
        wave_delay_layout.addWidget(self.wave_delay_min_input)

        wave_delay_layout.addWidget(QLabel("-"))

        self.wave_delay_max_input = QLineEdit(config.get('delays','wave_delay_max',fallback='60'))
        self.wave_delay_max_input.setFixedWidth(50)
        self.wave_delay_max_input.setToolTip("Максимальная задержка между волнами")
        wave_delay_layout.addWidget(self.wave_delay_max_input)
        delay_layout.addLayout(wave_delay_layout)

        # Задержка между аккаунтами (фиксированная)
        account_delay_layout = QHBoxLayout()
        account_delay_layout.addWidget(QLabel("Задержка между аккаунтами (сек):"))
        fixed_account_delay_label = QLabel("3.0")
        fixed_account_delay_label.setToolTip("Фиксированная задержка между аккаунтами")
        account_delay_layout.addWidget(fixed_account_delay_label)
        delay_layout.addLayout(account_delay_layout)

        delay_layout.addStretch()
        advanced_container_layout.addLayout(delay_layout)

        # Настройки FloodWait
        flood_layout = QHBoxLayout()
        self.floodwait_auto_checkbox = QCheckBox("Автоожидание FloodWait")
        self.floodwait_auto_checkbox.setToolTip("Автоматически ожидать при FloodWait до указанного времени")
        self.floodwait_auto_checkbox.setChecked(config.getboolean('floodwait', 'auto_wait', fallback=False))
        flood_layout.addWidget(self.floodwait_auto_checkbox)

        flood_layout.addWidget(QLabel("Макс. время ожидания (сек):"))
        self.floodwait_max_wait_input = QLineEdit(config.get('floodwait', 'max_wait_seconds', fallback='60'))
        self.floodwait_max_wait_input.setFixedWidth(50)
        self.floodwait_max_wait_input.setToolTip("Максимальное время ожидания FloodWait в секундах")
        self.floodwait_max_wait_input.setEnabled(self.floodwait_auto_checkbox.isChecked())
        flood_layout.addWidget(self.floodwait_max_wait_input)

        flood_layout.addWidget(QLabel("Порог исключения аккаунта (сек):"))
        self.floodwait_exclude_threshold_input = QLineEdit(config.get('floodwait', 'exclude_threshold_seconds', fallback='300'))
        self.floodwait_exclude_threshold_input.setFixedWidth(50)
        self.floodwait_exclude_threshold_input.setToolTip("Если FloodWait > этого порога, аккаунт будет исключен без ожидания")
        self.floodwait_exclude_threshold_input.setEnabled(self.floodwait_auto_checkbox.isChecked())
        flood_layout.addWidget(self.floodwait_exclude_threshold_input)

        flood_layout.addStretch()
        advanced_container_layout.addLayout(flood_layout)

        # Подключаем обработчик изменения чекбокса
        self.floodwait_auto_checkbox.stateChanged.connect(
            lambda: (
                self.floodwait_max_wait_input.setEnabled(self.floodwait_auto_checkbox.isChecked()),
                self.floodwait_exclude_threshold_input.setEnabled(self.floodwait_auto_checkbox.isChecked())
            ))

        # Настройки антиспама

        # Отложенная отправка
        scheduled_layout = QVBoxLayout()
        scheduled_header = QHBoxLayout()

        # Чекбокс для включения отложенной отправки
        self.enable_scheduled_checkbox = QCheckBox("Включить отложенную отправку")
        self.enable_scheduled_checkbox.setToolTip("Сообщения будут поставлены в очередь Telegram для отправки в указанное время")
        scheduled_header.addWidget(self.enable_scheduled_checkbox)

        scheduled_header.addStretch()
        scheduled_layout.addLayout(scheduled_header)

        # Параметры отложенной отправки
        scheduled_params_layout = QHBoxLayout()

        # Дата и время начала
        start_time_layout = QVBoxLayout()
        start_time_layout.addWidget(QLabel("Время начала:"))
        self.start_time_input = QTimeEdit()
        self.start_time_input.setDisplayFormat("HH:mm")
        # Buttons enabled by default, line removed
        self.start_time_input.setFixedWidth(80)
        self.start_time_input.setStyleSheet("background-color: #3A3A3A; color: #E0E0E0; border: 1px solid #555; border-radius: 4px; selection-background-color: #555;")
        start_time_layout.addWidget(self.start_time_input)
        scheduled_params_layout.addLayout(start_time_layout)

        # Дата начала
        start_date_layout = QVBoxLayout()
        start_date_layout.addWidget(QLabel("Дата начала:"))
        self.start_date_input = QDateEdit()
        self.start_date_input.setDisplayFormat("dd.MM.yyyy")
        self.start_date_input.setCalendarPopup(True)
        self.start_date_input.setDate(QDate.currentDate())
        self.start_date_input.setFixedWidth(120)
        self.start_date_input.setStyleSheet("background-color: #3A3A3A; color: #E0E0E0; border: 1px solid #555; border-radius: 4px; selection-background-color: #555;")
        start_date_layout.addWidget(self.start_date_input)
        scheduled_params_layout.addLayout(start_date_layout)

        # Часовой пояс
        timezone_layout = QVBoxLayout()
        timezone_layout.addWidget(QLabel("Часовой пояс:"))
        self.timezone_combo = QComboBox()
        self.timezone_combo.setFixedWidth(120)
        self.timezone_combo.setToolTip("Часовой пояс для времени отправки")

        # Добавляем популярные часовые пояса с проверкой доступности
        timezone_candidates = [
            ("Europe/Moscow", "МСК (UTC+3)"),
            ("UTC", "UTC"),
            ("Europe/London", "Лондон (UTC+0/+1)"),
            ("Europe/Berlin", "Берлин (UTC+1/+2)"),
            ("Europe/Paris", "Париж (UTC+1/+2)"),
            ("America/New_York", "Нью-Йорк (UTC-5/-4)"),
            ("Asia/Tokyo", "Токио (UTC+9)"),
            ("Asia/Shanghai", "Шанхай (UTC+8)"),
            ("Australia/Sydney", "Сидней (UTC+10/+11)"),
        ]

        available_timezones = []
        for tz_name, tz_display in timezone_candidates:
            try:
                # Проверяем доступность часового пояса
                if HAS_ZONEINFO:
                    zoneinfo.ZoneInfo(tz_name)
                elif pytz:
                    pytz.timezone(tz_name)
                available_timezones.append((tz_name, tz_display))
            except Exception:
                # Пропускаем недоступные зоны
                continue

        # Если нет доступных зон, добавляем UTC как fallback
        if not available_timezones:
            available_timezones = [("UTC", "UTC")]

        for tz_name, tz_display in available_timezones:
            self.timezone_combo.addItem(tz_display, tz_name)

        # Устанавливаем МСК по умолчанию
        msk_index = self.timezone_combo.findData("Europe/Moscow")
        if msk_index >= 0:
            self.timezone_combo.setCurrentIndex(msk_index)

        timezone_layout.addWidget(self.timezone_combo)
        scheduled_params_layout.addLayout(timezone_layout)

        # Задержка между сообщениями
        message_delay_layout = QVBoxLayout()
        message_delay_layout.addWidget(QLabel("Задержка между сообщениями (мин):"))
        self.message_delay_input = QLineEdit("1")
        self.message_delay_input.setFixedWidth(60)
        self.message_delay_input.setToolTip("Задержка между отправкой каждого следующего сообщения в минутах")
        message_delay_layout.addWidget(self.message_delay_input)
        scheduled_params_layout.addLayout(message_delay_layout)

        scheduled_params_layout.addStretch()
        scheduled_layout.addLayout(scheduled_params_layout)

        # Информационная метка
        scheduled_info = QLabel("ℹ️ Все аккаунты будут отправлять сообщения синхронно в указанное время")
        scheduled_info.setStyleSheet("color: #666; font-size: 11px;")
        scheduled_layout.addWidget(scheduled_info)

        advanced_container_layout.addLayout(scheduled_layout)

        # Подключаем обработчик изменения чекбокса
        self.enable_scheduled_checkbox.stateChanged.connect(self.toggle_scheduled_inputs)

        # Медиа файлы
        media_layout = QVBoxLayout()
        media_header = QHBoxLayout()
        media_header.addWidget(QLabel("📎 Медиа файлы:"))

        self.select_media_btn = QPushButton("Добавить медиа")
        self.select_media_btn.setProperty("role", "primary")
        self.select_media_btn.clicked.connect(self.select_media_files)
        media_header.addWidget(self.select_media_btn)

        self.preview_media_btn = QPushButton("👁️ Предпросмотр")
        self.preview_media_btn.setProperty("role", "success")
        self.preview_media_btn.clicked.connect(self.preview_media_files)
        media_header.addWidget(self.preview_media_btn)

        self.clear_media_btn = QPushButton("Очистить")
        self.clear_media_btn.setProperty("role", "danger")
        self.clear_media_btn.clicked.connect(self.clear_media_files)
        media_header.addWidget(self.clear_media_btn)

        # Оптимизация медиа
        self.optimize_media_checkbox = QCheckBox("Оптимизировать медиа (фото ≤1280px, JPEG≈80)")
        self.optimize_media_checkbox.setToolTip("Перед отправкой уменьшать изображения и сжимать JPEG")
        media_header.addWidget(self.optimize_media_checkbox)

        media_header.addStretch()
        media_layout.addLayout(media_header)

        # Список выбранных медиа файлов
        self.media_list = QListWidget()
        self.media_list.setMaximumHeight(100)
        media_layout.addWidget(self.media_list)
        content_layout.addLayout(media_layout)

        # Инициализация списка медиа файлов
        self.selected_media_files = []

        # Информационная подсказка о лимитах Telegram
        limits_label = QLabel("ℹ️ Лимиты Telegram: фото до 10MB, документы до 2GB")
        limits_label.setStyleSheet("color: #666; font-size: 11px; margin-top: 5px;")
        content_layout.addWidget(limits_label)

        # Список аккаунтов с лидами
        self.broadcast_accounts_area = QWidget()
        self.broadcast_accounts_layout = QVBoxLayout(self.broadcast_accounts_area)
        self.broadcast_accounts_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        content_layout.addWidget(QLabel("Аккаунты:"))
        content_layout.addWidget(self.broadcast_accounts_area)

        # Кнопка запуска
        self.start_broadcast_btn = QPushButton("Запустить рассылку")
        self.start_broadcast_btn.setProperty("role", "primary")
        outer_layout.addWidget(self.start_broadcast_btn)

        # Внутренние связи
        self.script_combo.currentTextChanged.connect(self.update_script_preview)
        self.start_broadcast_btn.clicked.connect(self.start_broadcast)

        self.reload_scripts_list()
        self.load_broadcast_accounts()

        # Инициализация состояния полей отложенной отправки
        self.toggle_scheduled_inputs()

    def toggle_scheduled_inputs(self):
        """Включает/отключает поля ввода параметров отложенной отправки."""
        enabled = self.enable_scheduled_checkbox.isChecked()
        self.start_time_input.setEnabled(enabled)
        self.start_date_input.setEnabled(enabled)
        self.timezone_combo.setEnabled(enabled)
        self.message_delay_input.setEnabled(enabled)

    def reload_scripts_list(self):
        current = self.script_combo.currentText()
        self.script_combo.clear()
        self.script_combo.addItems(list_scripts(category="leads"))
        idx = self.script_combo.findText(current)
        if idx >= 0:
            self.script_combo.setCurrentIndex(idx)
        self.update_script_preview()

    def update_script_preview(self):
        name = self.script_combo.currentText()
        if not name:
            self.script_preview.clear()
            return
        try:
            txt = load_script(name, category="leads")
        except FileNotFoundError:
            txt = ""
        self.script_preview.setHtml(txt)

    def load_broadcast_accounts(self):
        # Helper to clear layout recursively
        def clear_layout(layout):
            if layout is not None:
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
                    else:
                        sub_layout = item.layout()
                        if sub_layout:
                            clear_layout(sub_layout)

        clear_layout(self.broadcast_accounts_layout)
        self.broadcast_items = []
        try:
            if os.path.exists('accounts.json'):
                with open('accounts.json', 'r', encoding='utf-8') as f:
                    accounts = json.load(f)
            else:
                accounts = []
        except Exception:
            accounts = []

        # Верхняя панель: выбрать все / снять все
        if accounts:
            select_bar = QHBoxLayout()
            select_bar.setContentsMargins(0, 0, 0, 0)
            select_all_checkbox = QCheckBox("Выбрать все")
            select_all_checkbox.setProperty("role", "primary")
            def on_select_all(checked: bool):
                for b, _t, _a in self.broadcast_items:
                    b.setChecked(checked)
            select_all_checkbox.toggled.connect(on_select_all)
            select_bar.addWidget(select_all_checkbox)

            # Кнопка очистки всех полей лидов
            clear_all_btn = QPushButton("Очистить")
            clear_all_btn.setProperty("role", "danger")
            clear_all_btn.setFixedSize(80, 24)
            
            def _clear_all_leads():
                try:
                    for _b, _txt, _acc in getattr(self, 'broadcast_items', []):
                        try:
                            if _txt is not None:
                                _txt.clear()
                        except Exception:
                            pass
                except Exception:
                    pass
            
            clear_all_btn.clicked.connect(_clear_all_leads)
            select_bar.addWidget(clear_all_btn)
            select_bar.addStretch()
            self.broadcast_accounts_layout.addLayout(select_bar)
            
            # Spacer
            self.broadcast_accounts_layout.addSpacing(10)

        for acc in accounts:
            row = QHBoxLayout()
            row.setContentsMargins(0,0,0,0)
            row.setSpacing(10)

            # Безопасный и компактный вывод имени
            _name_full = acc.get('name', '')
            _name_disp = _name_full
            try:
                if len(_name_disp) > 32:
                    _name_disp = _name_disp[:31] + '…'
            except Exception:
                pass
            
            box = QCheckBox(f"{_name_disp} ({acc['phone']})")
            try:
                box.setToolTip(f"{_name_full} ({acc['phone']})")
            except Exception:
                pass
            row.addWidget(box)

            # Кнопка редактирования лидов
            edit_leads_btn = QPushButton("Лиды")
            edit_leads_btn.setProperty("role", "secondary")
            edit_leads_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            edit_leads_btn.setFixedSize(60, 24)
            row.addWidget(edit_leads_btn)

            # Статус (количество)
            count_label = QLabel("0 шт.")
            count_label.setStyleSheet("color: #888; margin-left: 5px;")
            row.addWidget(count_label)
            
            # Скрытое поле для хранения текста
            txt = QTextEdit(self.broadcast_accounts_area)
            txt.setVisible(False)
            
            # Растяжка
            row.addStretch()

            self.broadcast_accounts_layout.addLayout(row)

            # Fix closure: pass current txt and count_label as default args
            def update_count_label(_txt=txt, _lbl=count_label):
                lines = [l for l in _txt.toPlainText().split('\n') if l.strip()]
                _lbl.setText(f"{len(lines)} шт.")

            # Connect textChanged to update label
            txt.textChanged.connect(update_count_label)

            def on_leads_click(_=None, _txt=txt):
                dlg = LeadsEditorDialog(self, _txt.toPlainText())
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    _txt.setPlainText(dlg.get_text())
            
            edit_leads_btn.clicked.connect(on_leads_click)
            
            self.broadcast_items.append((box, txt, acc))
            
        self.broadcast_accounts_layout.addStretch()

    def start_broadcast(self):
        script_name = self.script_combo.currentText()
        if not script_name:
            QMessageBox.warning(self, "Скрипты", "Выберите скрипт")
            return
        # Берём именно HTML-код, чтобы сохранить форматирование
        message = self.script_preview.toHtml()
        if not message.strip():
            QMessageBox.warning(self, "Скрипты", "Выбранный скрипт пуст")
            return
        try:
            wave_delay_min = float(self.wave_delay_min_input.text())
            wave_delay_max = float(self.wave_delay_max_input.text())

            # Валидация параметров
            if wave_delay_min < 0 or wave_delay_max < 0:
                raise ValueError("Задержки между волнами должны быть >= 0")
            if wave_delay_min > wave_delay_max:
                raise ValueError("Минимальная задержка не может быть больше максимальной")

        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", f"Неверно заданы задержки: {str(e)}")
            return
        accounts_info = []
        for box, txt, acc in self.broadcast_items:
            if box.isChecked():
                def norm(r:str):
                    r=r.strip().replace('https://t.me/','').replace('http://t.me/','').replace('t.me/','')
                    if r.startswith('@'):
                        r=r[1:]
                    return r
                recs = [norm(l) for l in txt.toPlainText().split('\n') if l.strip()]
                if not recs:
                    QMessageBox.warning(self, "Ошибка", f"Не указаны получатели для {acc['name']}")
                    return
                # Используем сохранённое имя сессии, если есть, иначе дефолт по номеру
                session_name = acc.get('session_name') or str(user_file('sessions', acc['phone'].replace('+', '').replace(' ', '')))
                accounts_info.append({
                    "session_name": session_name,
                    "api_id": acc['api_id'],
                    "api_hash": acc['api_hash'],
                    "name": acc['name'],
                    "recipients": recs
                })
        if not accounts_info:
            QMessageBox.warning(self, "Ошибка", "Не выбран ни один аккаунт")
            return

        # Обработка параметров отложенной отправки
        scheduled_params = None
        if self.enable_scheduled_checkbox.isChecked():
            try:
                # Берем дату/время напрямую из виджетов
                qd: QDate = self.start_date_input.date()
                qt: QTime = self.start_time_input.time()
                start_date = datetime.date(qd.year(), qd.month(), qd.day())
                start_time = datetime.time(qt.hour(), qt.minute())

                # Получаем выбранный часовой пояс
                timezone_name = self.timezone_combo.currentData()
                try:
                    if HAS_ZONEINFO:
                        # Используем zoneinfo (Python 3.9+)
                        user_timezone = zoneinfo.ZoneInfo(timezone_name)
                    elif pytz:
                        # Fallback на pytz для совместимости
                        user_timezone = pytz.timezone(timezone_name)
                    else:
                        raise ImportError("zoneinfo не поддерживается и pytz не установлен")
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка", f"Ошибка загрузки часового пояса: {e}")
                    return

                # Создаем datetime начала в выбранном часовом поясе
                start_datetime_naive = datetime.datetime.combine(start_date, start_time)

                # Разная логика для разных библиотек часовых поясов
                if HAS_ZONEINFO:
                    start_datetime_local = start_datetime_naive.replace(tzinfo=user_timezone)
                else:  # pytz
                    start_datetime_local = user_timezone.localize(start_datetime_naive)

                # Конвертируем в UTC для Telegram API
                start_datetime_utc = start_datetime_local.astimezone(datetime.timezone.utc)

                # Проверяем, что время начала не в прошлом
                current_utc = datetime.datetime.now(datetime.timezone.utc)
                if start_datetime_utc < current_utc:
                    # Предупреждаем пользователя, но позволяем продолжить
                    time_diff = current_utc - start_datetime_utc
                    hours_passed = time_diff.total_seconds() / 3600
                    warning_msg = f"Время начала уже прошло ({hours_passed:.1f} часов назад).\n\nСообщения будут отправлены немедленно.\n\nПродолжить?"
                    reply = QMessageBox.question(self, "Время в прошлом", warning_msg,
                                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                               QMessageBox.StandardButton.No)
                    if reply == QMessageBox.StandardButton.No:
                        return

                # Парсим задержку между сообщениями
                message_delay_minutes = int(self.message_delay_input.text())
                if message_delay_minutes <= 0:
                    raise ValueError

                scheduled_params = {
                    'start_datetime_utc': start_datetime_utc,
                    'start_datetime_local': start_datetime_local,
                    'timezone_name': timezone_name,
                    'message_delay_minutes': message_delay_minutes
                }

            except ValueError:
                QMessageBox.warning(self, "Ошибка", "Неверно задана задержка между сообщениями")
                return

        # Сохраняем задержки в конфиг
        cfg = self.load_config()
        if not cfg.has_section('delays'):
            cfg.add_section('delays')
        cfg.set('delays','wave_delay_min',str(wave_delay_min))
        cfg.set('delays','wave_delay_max',str(wave_delay_max))

        # Сохраняем настройки FloodWait
        if not cfg.has_section('floodwait'):
            cfg.add_section('floodwait')
        cfg.set('floodwait','auto_wait',str(self.floodwait_auto_checkbox.isChecked()))
        cfg.set('floodwait','max_wait_seconds',self.floodwait_max_wait_input.text())
        cfg.set('floodwait','exclude_threshold_seconds',self.floodwait_exclude_threshold_input.text())

        # Сохраняем настройки антиспама

        with open('settings.ini','w', encoding='utf-8') as f:
            cfg.write(f)

        # Подсчёт запланированных сообщений для резервирования квоты
        planned_messages = sum(len(acc["recipients"]) for acc in accounts_info)

        # Резервирование квоты лицензии
        reservation_id = None


        # Диалог логов
        dlg = QDialog(self)
        dlg.setWindowTitle("Логи рассылки")
        dlg.setMinimumSize(640, 420)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setContentsMargins(14, 14, 14, 14)
        dlg_layout.setSpacing(10)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(22)
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Подготовка... %p%")
        dlg_layout.addWidget(self.progress_bar)

        log_view = QTextEdit()
        log_view.setReadOnly(True)
        dlg_layout.addWidget(log_view)

        btn_bar = QHBoxLayout()
        action_btn = QPushButton("Остановить")
        action_btn.setProperty("role", "danger")
        btn_bar.addStretch()
        btn_bar.addWidget(action_btn)
        dlg_layout.addLayout(btn_bar)

        start_dt = datetime.datetime.now()
        # Используем оптимизированный воркер с настраиваемыми задержками
        inter_wave_delay_min = wave_delay_min
        inter_wave_delay_max = wave_delay_max

        # Получаем настройки FloodWait
        floodwait_auto_wait = self.floodwait_auto_checkbox.isChecked()
        floodwait_max_wait = int(self.floodwait_max_wait_input.text()) if floodwait_auto_wait else 60
        floodwait_exclude_threshold = int(self.floodwait_exclude_threshold_input.text()) if floodwait_auto_wait else 300

        # Получаем список выбранных медиа файлов
        media_files = getattr(self, 'selected_media_files', [])
        if self.optimize_media_checkbox.isChecked() and media_files:
            try:
                optimized = []
                import importlib
                ImageModule = importlib.import_module('PIL.Image')
                for path in media_files:
                    try:
                        if not os.path.exists(path):
                            continue
                        ext = os.path.splitext(path)[1].lower()
                        if ext in ('.jpg', '.jpeg', '.png'):
                            im = ImageModule.open(path)
                            im_format = 'JPEG' if ext in ('.jpg', '.jpeg') else 'PNG'
                            # resize if larger than 1280 in either dimension
                            max_side = 1280
                            w, h = im.size
                            if max(w, h) > max_side:
                                scale = max_side / float(max(w, h))
                                new_size = (int(w * scale), int(h * scale))
                                im = im.resize(new_size)
                            # save to temp file
                            tmp_dir = user_file('tmp')
                            os.makedirs(tmp_dir, exist_ok=True)
                            base = os.path.basename(path)
                            out_path = os.path.join(tmp_dir, f"optimized_{base}")
                            if im_format == 'JPEG':
                                im = im.convert('RGB')
                                im.save(out_path, format='JPEG', quality=80, optimize=True)
                            else:
                                im.save(out_path, format='PNG', optimize=True)
                            optimized.append(out_path)
                        else:
                            optimized.append(path)
                    except Exception:
                        optimized.append(path)
                media_files = optimized
            except Exception as e:
                QMessageBox.warning(self, "Медиа", f"Оптимизация медиа: {e}")
        worker = OptimizedBroadcastWorker(accounts_info, message, media_files,
                                        inter_wave_delay_min=inter_wave_delay_min,
                                        inter_wave_delay_max=inter_wave_delay_max,
                                        scheduled_params=scheduled_params,
                                        floodwait_auto_wait=floodwait_auto_wait,
                                        floodwait_max_wait=floodwait_max_wait,
                                        floodwait_exclude_threshold=floodwait_exclude_threshold,
                                        dry_run=self.dry_run_checkbox.isChecked())
        worker.log.connect(lambda line: log_view.append(line))

        # Подключаем сигнал прогресса к progress bar
        def update_progress(value, text):
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat(f"{text} %p%")

        worker.progress.connect(update_progress)

        # Состояние кнопки действия: False — рассылка идёт; True — завершено/остановлено
        is_finished = False

        def done():
            nonlocal is_finished
            log_view.append("<b>Завершено</b>")
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Завершено %p%")
            is_finished = True
            action_btn.setEnabled(True)
            action_btn.setText("Закрыть")
            action_btn.setProperty("role", "secondary")
            # Обновляем стиль после смены role
            try:
                action_btn.style().unpolish(action_btn)
                action_btn.style().polish(action_btn)
                action_btn.update()
            except Exception:
                pass

            # Завершение резерва квоты (commit/rollback)
            end_dt = datetime.datetime.now()
            fname = f"Рассылка_{start_dt.strftime('%d.%m.%Y')}_{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}.html"
            pathlib.Path('broadcast_logs').mkdir(exist_ok=True)
            with open(os.path.join('broadcast_logs', fname), 'w', encoding='utf-8') as f:
                f.write(log_view.toHtml())
            # Обновим историю
            try:
                self.reload_history()
            except Exception:
                pass
        worker.finished.connect(done)

        def on_action_click():
            nonlocal is_finished
            if not is_finished:
                # Останавливаем рассылку
                action_btn.setEnabled(False)
                action_btn.setText("Остановка...")
                try:
                    action_btn.style().unpolish(action_btn)
                    action_btn.style().polish(action_btn)
                    action_btn.update()
                except Exception:
                    pass
                worker.stop()
            else:
                # Закрываем диалог
                dlg.accept()

        action_btn.clicked.connect(on_action_click)
        worker.start()
        dlg.exec()

    def setup_chats_broadcast_tab(self):
        try:
            # Layout initialization done in init
            layout = QVBoxLayout(self.chats_broadcast_tab)
            layout.setContentsMargins(0, 0, 0, 0)
            
            # Import widget dynamically to avoid circular issues
            from mini_broadcast import MiniBroadcastWidget
            
            self.mini_broadcast_widget = MiniBroadcastWidget()
            layout.addWidget(self.mini_broadcast_widget)
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Error setting up chats broadcast tab: {e}")
            layout.addWidget(QLabel(f"Ошибка загрузки модуля: {e}"))

    def setup_scripts_tab(self):
        layout = QVBoxLayout(self.scripts_tab)

        self.scripts_list = QListWidget()
        layout.addWidget(self.scripts_list, 1)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Добавить")
        edit_btn = QPushButton("Редактировать")
        del_btn = QPushButton("Удалить")
        add_btn.setProperty("role", "success")
        edit_btn.setProperty("role", "secondary")
        del_btn.setProperty("role", "danger")
        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        def reload_list():
            self.scripts_list.clear()
            for fname in list_scripts():
                self.scripts_list.addItem(QListWidgetItem(fname))

        reload_list()

        # --- Расширенный редактор скриптов ---
        class ScriptEditorDialog(QDialog):
            """Простой визуальный редактор с кнопками форматирования под HTML."""

            def __init__(self, parent: QWidget, title: str, initial_html: str = ""):
                super().__init__(parent)
                self.setWindowTitle(title)
                lay = QVBoxLayout(self)

                # Панель инструментов
                toolbar = QHBoxLayout()
                b_btn = QPushButton("B")
                b_btn.setToolTip("Жирный")
                i_btn = QPushButton("I")
                i_btn.setToolTip("Курсив")
                link_btn = QPushButton("🔗")
                link_btn.setToolTip("Вставить ссылку")
                clear_btn = QPushButton("Tx")
                clear_btn.setToolTip("Очистить форматирование")

                toolbar.addWidget(b_btn)
                toolbar.addWidget(i_btn)
                toolbar.addWidget(link_btn)
                toolbar.addWidget(clear_btn)
                toolbar.addStretch()
                lay.addLayout(toolbar)

                # Редактор
                self.editor = QTextEdit()
                self.editor.setAcceptRichText(True)
                self.editor.setHtml(initial_html)
                lay.addWidget(self.editor, 1)

                # Кнопки OK/Cancel
                btn_box = QHBoxLayout()
                ok_btn = QPushButton("OK")
                ok_btn.setProperty("role", "primary")
                cancel_btn = QPushButton("Отмена")
                cancel_btn.setProperty("role", "secondary")
                btn_box.addStretch()
                btn_box.addWidget(ok_btn)
                btn_box.addWidget(cancel_btn)
                lay.addLayout(btn_box)

                ok_btn.clicked.connect(self.accept)
                cancel_btn.clicked.connect(self.reject)

                # Форматирование
                def make_bold():
                    cursor = self.editor.textCursor()
                    fmt = cursor.charFormat()
                    fmt.setFontWeight(QFont.Weight.Bold)
                    cursor.mergeCharFormat(fmt)

                def make_italic():
                    cursor = self.editor.textCursor()
                    fmt = cursor.charFormat()
                    fmt.setFontItalic(True)
                    cursor.mergeCharFormat(fmt)

                def insert_link():
                    url, ok = QInputDialog.getText(self, "Ссылка", "URL:")
                    if ok and url:
                        cursor = self.editor.textCursor()
                        text = cursor.selectedText() or url
                        html = f'<a href="{url}">{text}</a>'
                        cursor.insertHtml(html)

                def clear_format():
                    cursor = self.editor.textCursor()
                    if cursor.hasSelection():
                        txt = cursor.selectedText()
                        cursor.removeSelectedText()
                        cursor.insertText(txt)
                    else:
                        # Без выделения – убираем формат всего текста
                        plain = self.editor.toPlainText()
                        self.editor.clear()
                        self.editor.insertPlainText(plain)

                b_btn.clicked.connect(make_bold)
                i_btn.clicked.connect(make_italic)
                link_btn.clicked.connect(insert_link)
                clear_btn.clicked.connect(clear_format)

            def html(self):
                return self.editor.toHtml()

        def add_script():
            name, ok = QInputDialog.getText(self, "Новый скрипт", "Имя файла (без расширения):")
            if not (ok and name.strip()):
                return
            dlg = ScriptEditorDialog(self, "Текст скрипта")
            if dlg.exec() == QDialog.DialogCode.Accepted:
                save_script(name.strip(), dlg.html(), category="leads")
                reload_list()

        def edit_script():
            item = self.scripts_list.currentItem()
            if not item:
                QMessageBox.warning(self, "Скрипты", "Выберите файл")
                return
            fname = item.text()
            try:
                text = load_script(fname, category="leads")
            except FileNotFoundError:
                QMessageBox.warning(self, "Скрипты", "Файл не найден")
                reload_list()
                return
            dlg = ScriptEditorDialog(self, f"Редактировать {fname}", text)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                save_script(fname, dlg.html(), category="leads")

        def del_script():
            item = self.scripts_list.currentItem()
            if not item:
                return
            fname = item.text()
            if QMessageBox.question(self, "Удалить", f"Удалить {fname}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                delete_script(fname, category="leads")
                reload_list()

        add_btn.clicked.connect(add_script)
        edit_btn.clicked.connect(edit_script)
        del_btn.clicked.connect(del_script)

    def setup_history_tab(self):
        layout = QVBoxLayout(self.history_tab)
        
        # Кнопка обновления
        top_bar = QHBoxLayout()
        refresh_btn = QPushButton("Обновить")
        refresh_btn.setProperty("role", "secondary")
        refresh_btn.clicked.connect(self.reload_history)
        top_bar.addStretch()
        top_bar.addWidget(refresh_btn)
        layout.addLayout(top_bar)
        
        # Список логов
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self.open_history_log)
        layout.addWidget(self.history_list)
        
        # Загружаем историю
        self.reload_history()
        
    def reload_history(self):
        self.history_list.clear()
        if not os.path.exists('broadcast_logs'):
            return
            
        try:
            files = [f for f in os.listdir('broadcast_logs') if f.endswith('.html')]
            # Сортируем по дате изменения (новые сверху)
            files.sort(key=lambda x: os.path.getmtime(os.path.join('broadcast_logs', x)), reverse=True)
            
            for f in files:
                self.history_list.addItem(f)
        except Exception:
            pass
            
    def open_history_log(self, item):
        fname = item.text()
        path = os.path.join('broadcast_logs', fname)
        if not os.path.exists(path):
            QMessageBox.warning(self, "Ошибка", "Файл лога не найден")
            return
            
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Лог: {fname}")
            dlg.resize(800, 600)
            lay = QVBoxLayout(dlg)
            
            view = QTextEdit()
            view.setReadOnly(True)
            view.setHtml(content)
            lay.addWidget(view)
            
            btn = QPushButton("Закрыть")
            btn.clicked.connect(dlg.accept)
            lay.addWidget(btn)
            
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть лог: {e}")
        
    def setup_about_tab(self):
        import platform
        
        layout = QVBoxLayout(self.about_tab)
        layout.setSpacing(15)
        layout.setContentsMargins(40, 40, 40, 40)
        
        # Logo / Header
        title_lbl = QLabel("TGFlow")
        title_font = QFont()
        title_font.setPointSize(28)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet("color: #4A90E2;")
        layout.addWidget(title_lbl)
        
        version_lbl = QLabel("v2.1.0 Pro")
        version_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_lbl.setStyleSheet("color: #888; margin-bottom: 20px;")
        layout.addWidget(version_lbl)
        
        # Description
        desc_lbl = QLabel("Мощный инструмент для автоматизации рассылок в Telegram.\n"
                          "Управляйте аккаунтами, создавайте сценарии и анализируйте результаты.")
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 14px; line-height: 1.4;")
        layout.addWidget(desc_lbl)
        
        layout.addSpacing(20)
        
        # Developer Card
        dev_frame = QWidget()
        dev_frame.setStyleSheet("""
            background-color: #2b2b2b; 
            border-radius: 10px; 
            padding: 15px;
        """)
        dev_layout = QVBoxLayout(dev_frame)
        
        dev_title = QLabel("Разработчик / Поддержка")
        dev_title.setStyleSheet("color: #aaa; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;")
        dev_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dev_layout.addWidget(dev_title)
        
        dev_link = QPushButton("@HermannSaliter")
        dev_link.setCursor(Qt.CursorShape.PointingHandCursor)
        dev_link.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #4A90E2;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #5AA0F2;
                text-decoration: underline;
            }
        """)
        def open_tg_dev():
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl("https://t.me/HermannSaliter"))
            
        dev_link.clicked.connect(open_tg_dev)
        dev_layout.addWidget(dev_link)
        
        layout.addWidget(dev_frame)
        
        layout.addSpacing(10)
        
        # Buttons Grid
        btns_layout = QHBoxLayout()
        btns_layout.setSpacing(15)
        
        # Open Data Folder
        data_btn = QPushButton("📂 Папка данных")
        data_btn.setMinimumHeight(40)
        def open_data_dir():
             from PyQt6.QtGui import QDesktopServices
             from PyQt6.QtCore import QUrl
             QDesktopServices.openUrl(QUrl.fromLocalFile(str(USER_DATA_DIR)))
        data_btn.clicked.connect(open_data_dir)
        btns_layout.addWidget(data_btn)

        # Check Updates
        update_btn = QPushButton("🔄 Проверить обновления")
        update_btn.setMinimumHeight(40)
        def check_updates():
            QMessageBox.information(self, "Обновление", "У вас установлена последняя версия TGFlow!")
        update_btn.clicked.connect(check_updates)
        btns_layout.addWidget(update_btn)
        
        layout.addLayout(btns_layout)
        
        layout.addStretch()
        
        # System Info Footer
        sys_info = f"Python {sys.version.split()[0]} | {platform.system()} {platform.release()}"
        footer = QLabel(f"© 2026 AiGen Inc.\n{sys_info}")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("color: #555; font-size: 10px;")
        layout.addWidget(footer)
        
    def load_accounts(self):
        try:
            if os.path.exists('accounts.json'):
                with open('accounts.json', 'r', encoding='utf-8') as f:
                    accounts = json.load(f)
                self.accounts_list.clear()
                for acc in accounts:
                    self.accounts_list.addItem(f"{acc['name']} ({acc['phone']})")
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить аккаунты: {str(e)}")
    
    def save_account(self, account_data):
        try:
            accounts = []
            if os.path.exists('accounts.json'):
                with open('accounts.json', 'r', encoding='utf-8') as f:
                    accounts = json.load(f)
            
            # Добавляем *новый* аккаунт даже если номер уже есть –
            # это позволяет хранить несколько сессий на один телефон.
            accounts.append(account_data)
            
            with open('accounts.json', 'w', encoding='utf-8') as f:
                json.dump(accounts, f, ensure_ascii=False, indent=2)
                
            self.load_accounts()
            # Также обновим вкладку «Рассылка», если она есть
            if hasattr(self, "broadcast_accounts_layout"):
                self.load_broadcast_accounts()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить аккаунт: {str(e)}")
    
    def add_account(self):
        # Предотвращаем одновременные попытки авторизации
        if getattr(self, 'is_auth_in_progress', False):
            QMessageBox.information(self, "Авторизация", "Процесс авторизации уже запущен. Дождитесь завершения или отмените текущую попытку.")
            return
        api_id = self.api_id_input.text()
        api_hash = self.api_hash_input.text()
        phone = self.phone_input.text()
        name = self.name_input.text()
        if not all([api_id, api_hash, phone]):
            QMessageBox.warning(self, "Ошибка", "Заполните все поля")
            return
        try:
            api_id = int(api_id)
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "API ID должен быть числом")
            return
        # Нормализуем пробелы в имени, чтобы избежать проблем форматирования/отображения
        try:
            import re as _re
            name = _re.sub(r'\s+', ' ', (name or '').strip())
        except Exception:
            name = (name or '').strip()
        # Генерируем уникальное имя сессии, чтобы один номер мог иметь несколько сессий
        sessions_dir = user_file('sessions')
        try:
            sessions_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        phone_base = phone.replace('+', '').replace(' ', '')
        unique_base = phone_base
        try:
            # Собираем уже занятые имена сессий из accounts.json
            existing_session_names = set()
            if os.path.exists('accounts.json'):
                with open('accounts.json', 'r', encoding='utf-8') as f:
                    for _acc in json.load(f):
                        if isinstance(_acc, dict) and 'session_name' in _acc:
                            existing_session_names.add(_acc['session_name'])
        except Exception:
            existing_session_names = set()
        # Также учитываем реально существующие файлы сессий/локи, чтобы не конфликтовать с активными клиентами
        existing_session_files = set()
        try:
            for fname in os.listdir(sessions_dir):
                if fname.endswith('.session') or fname.endswith('.lock'):
                    base = fname.replace('.session','').replace('.lock','')
                    existing_session_files.add(str(user_file('sessions', base)))
        except Exception:
            pass
        idx = 1
        while True:
            candidate = str(user_file('sessions', unique_base))
            if candidate not in existing_session_names and candidate not in existing_session_files:
                session_name = candidate
                break
            idx += 1
            unique_base = f"{phone_base}-{idx}"
        self.account_data = {
            'api_id': str(api_id),
            'api_hash': api_hash,
            'phone': phone,
            'name': name,
            'session_name': session_name
        }

        # Создаем диалог авторизации с progress bar
        self.auth_dialog = QDialog(self)
        self.auth_dialog.setWindowTitle("Авторизация аккаунта")
        self.auth_dialog.setModal(True)
        self.auth_dialog.setMinimumWidth(420)
        auth_layout = QVBoxLayout(self.auth_dialog)
        auth_layout.setContentsMargins(14, 14, 14, 14)
        auth_layout.setSpacing(10)

        # Progress bar для авторизации
        self.auth_progress_bar = QProgressBar()
        self.auth_progress_bar.setMinimumHeight(22)
        self.auth_progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.auth_progress_bar.setRange(0, 100)
        self.auth_progress_bar.setValue(0)
        self.auth_progress_bar.setFormat("Подготовка... %p%")
        auth_layout.addWidget(self.auth_progress_bar)

        # Метка статуса
        self.auth_status_label = QLabel("Начинаем авторизацию...")
        auth_layout.addWidget(self.auth_status_label)

        # Кнопка отмены
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setProperty("role", "secondary")
        def on_cancel():
            try:
                if hasattr(self, 'worker') and self.worker is not None:
                    self.worker.cancel()
            except Exception:
                pass
            try:
                if self.auth_dialog.isVisible():
                    self.auth_dialog.reject()
            except Exception:
                pass
        cancel_btn.clicked.connect(on_cancel)
        auth_layout.addWidget(cancel_btn)

        # Если предыдущий worker ещё существует – просим его отмениться
        try:
            if hasattr(self, 'worker') and self.worker is not None and self.worker.isRunning():
                self.worker.cancel()
        except Exception:
            pass
        # Отмечаем старт авторизации и дизейблим кнопку добавления
        self.is_auth_in_progress = True
        try:
            if hasattr(self, 'add_account_button'):
                self.add_account_button.setEnabled(False)
        except Exception:
            pass

        self.worker = TelegramAuthWorker(session_name, api_id, api_hash, phone)
        self.worker.finished.connect(self.handle_auth_response)

        # Подключаем сигнал прогресса
        def update_auth_progress(value, text):
            self.auth_progress_bar.setValue(value)
            self.auth_progress_bar.setFormat(f"{text} %p%")
            self.auth_status_label.setText(text)

        self.worker.progress.connect(update_auth_progress)
        self.worker.start()

        # Показываем диалог
        # Только пользовательная отмена (reject) должна отменять worker и разблокировать кнопку.
        def on_dialog_rejected():
            try:
                if hasattr(self, 'worker') and self.worker is not None and self.worker.isRunning():
                    self.worker.cancel()
            except Exception:
                pass
            self.is_auth_in_progress = False
            try:
                if hasattr(self, 'add_account_button'):
                    self.add_account_button.setEnabled(True)
            except Exception:
                pass

        self.auth_dialog.rejected.connect(on_dialog_rejected)
        self.auth_dialog.exec()
    
    def handle_auth_response(self, success, msg, extra):
        # Не сбрасываем флаги для промежуточных шагов (NEED_CODE / NEED_PASSWORD).
        # Флаги и кнопки сбрасываются только при финальном результате или явной отмене.
        if not success:
            # Закрываем диалог авторизации при ошибке
            if hasattr(self, 'auth_dialog') and self.auth_dialog.isVisible():
                self.auth_dialog.accept()

            if msg == 'PHONE_CODE_EXPIRED':
                QMessageBox.information(self, "Код истёк", "Запрошен новый код. Проверьте Telegram/SMS и введите новый код.")
                # Сразу запрашиваем новый код
                dialog = AuthDialog(self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    code = dialog.code_input.text().strip()
                    if not code.isdigit():
                        QMessageBox.warning(self, "Ошибка", "Код должен содержать только цифры")
                        return
                    self.worker.submit_code.emit(code)
                return
            elif msg.startswith('FLOOD_WAIT_'):
                seconds = msg.split('_')[-1]
                QMessageBox.warning(self, "FloodWait", f"Telegram просит подождать {seconds} секунд перед повторной отправкой кода. Попробуйте позже.")
                # Финальный фейл — разблокируем
                self.is_auth_in_progress = False
                try:
                    if hasattr(self, 'add_account_button'):
                        self.add_account_button.setEnabled(True)
                except Exception:
                    pass
            elif msg == 'PHONE_NUMBER_INVALID':
                QMessageBox.warning(self, "Номер", "Неверный номер телефона. Проверьте формат, например +7XXXXXXXXXX")
                self.is_auth_in_progress = False
                try:
                    if hasattr(self, 'add_account_button'):
                        self.add_account_button.setEnabled(True)
                except Exception:
                    pass
                return
            elif msg == 'API_ID_INVALID':
                QMessageBox.warning(self, "API ID", "Неверный API ID. Проверьте значение")
                self.is_auth_in_progress = False
                try:
                    if hasattr(self, 'add_account_button'):
                        self.add_account_button.setEnabled(True)
                except Exception:
                    pass
                return
            elif msg == 'API_HASH_INVALID':
                QMessageBox.warning(self, "API Hash", "Неверный API Hash. Проверьте значение")
                self.is_auth_in_progress = False
                try:
                    if hasattr(self, 'add_account_button'):
                        self.add_account_button.setEnabled(True)
                except Exception:
                    pass
                return
            elif msg == 'PHONE_CODE_INVALID':
                # Неверный код – просим ещё раз
                QMessageBox.warning(self, "Неверный код", "Введён неверный код. Попробуйте ещё раз.")
                dialog = AuthDialog(self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    code = dialog.code_input.text().strip()
                    if not code.isdigit():
                        QMessageBox.warning(self, "Ошибка", "Код должен содержать только цифры")
                        return
                    self.worker.submit_code.emit(code)
                return
            elif msg == 'PASSWORD_INVALID':
                QMessageBox.warning(self, "Пароль", "Неверный пароль 2FA. Попробуйте ещё раз.")
                dialog = PasswordDialog(self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    pwd = dialog.password_input.text()
                    if not pwd:
                        QMessageBox.warning(self, "Ошибка", "Введите пароль 2FA")
                        return
                    self.worker.submit_password.emit(pwd)
                return
            else:
                QMessageBox.warning(self, "Ошибка", f"Ошибка авторизации: {msg}")
                # Финальный фейл — разблокируем
                self.is_auth_in_progress = False
                try:
                    if hasattr(self, 'add_account_button'):
                        self.add_account_button.setEnabled(True)
                except Exception:
                    pass
            return

        if msg == 'NEED_CODE':
            # Закрываем диалог авторизации и показываем диалог для ввода кода
            if hasattr(self, 'auth_dialog') and self.auth_dialog.isVisible():
                self.auth_dialog.accept()

            dialog = AuthDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                code = dialog.code_input.text().strip()
                if not code.isdigit():
                    QMessageBox.warning(self, "Ошибка", "Код должен содержать только цифры")
                    return
                self.worker.submit_code.emit(code)
            else:
                # Пользователь отменил ввод кода – прекращаем авторизацию
                try:
                    if hasattr(self, 'worker') and self.worker is not None and self.worker.isRunning():
                        self.worker.cancel()
                except Exception:
                    pass
                self.is_auth_in_progress = False
                try:
                    if hasattr(self, 'add_account_button'):
                        self.add_account_button.setEnabled(True)
                except Exception:
                    pass
        elif msg == 'NEED_PASSWORD':
            # Закрываем диалог авторизации и показываем диалог для ввода пароля
            if hasattr(self, 'auth_dialog') and self.auth_dialog.isVisible():
                self.auth_dialog.accept()

            dialog = PasswordDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                password = dialog.password_input.text()
                if not password:
                    QMessageBox.warning(self, "Ошибка", "Введите пароль 2FA")
                    return
                self.worker.submit_password.emit(password)
            else:
                # Пользователь отменил ввод пароля – прекращаем авторизацию
                try:
                    if hasattr(self, 'worker') and self.worker is not None and self.worker.isRunning():
                        self.worker.cancel()
                except Exception:
                    pass
                self.is_auth_in_progress = False
                try:
                    if hasattr(self, 'add_account_button'):
                        self.add_account_button.setEnabled(True)
                except Exception:
                    pass
        elif msg == 'SUCCESS':
            # Закрываем диалог авторизации при успехе
            if hasattr(self, 'auth_dialog') and self.auth_dialog.isVisible():
                self.auth_dialog.accept()

            self.save_account(self.account_data)
            QMessageBox.information(self, "Успех", "Аккаунт успешно добавлен")
            # Финальный успех — разблокируем
            self.is_auth_in_progress = False
            try:
                if hasattr(self, 'add_account_button'):
                    self.add_account_button.setEnabled(True)
            except Exception:
                pass
    
    def send_messages(self):
        """
        LEGACY METHOD - Не использовать в основном потоке!
        Старый метод отправки сообщений без волновой архитектуры.
        Сохранен для совместимости, но рекомендуется использовать start_broadcast().
        """
        QMessageBox.warning(self, "Устаревший метод",
                          "Этот метод устарел! Используйте вкладку 'Рассылка' с волновой архитектурой.")
        return

        # Код ниже отключен - не выполнять
        message = self.message_input.toPlainText()  # Устаревший элемент UI
        recipients = self.recipients_input.toPlainText().split('\n')  # Устаревший элемент UI
        
        if not message or not recipients:
            QMessageBox.warning(self, "Ошибка", "Заполните сообщение и список получателей")
            return
            
        try:
            if not os.path.exists('accounts.json'):
                QMessageBox.warning(self, "Ошибка", "Нет добавленных аккаунтов")
                return
                
            with open('accounts.json', 'r', encoding='utf-8') as f:
                accounts = json.load(f)
                
            errors_list = []
            for acc in accounts:
                session_name = acc.get('session_name') or str(user_file('sessions', acc['phone'].replace('+', '').replace(' ', '')))
                try:
                    app_client = open_client(session_name, acc['api_id'], acc['api_hash'])
                    
                    def norm(r:str):
                        r=r.strip().replace('https://t.me/','').replace('http://t.me/','').replace('t.me/','')
                        if r.startswith('@'):
                            r=r[1:]
                        return r
                    for recipient in recipients:
                        if recipient.strip():
                            try:
                                app_client.send_message(norm(recipient), message, disable_web_page_preview=contains_url(message))
                            except Exception as e:
                                errors_list.append(f"{acc['name']}: {recipient}: {str(e)}")
                                
                    app_client.disconnect()
                except Exception as e:
                    errors_list.append(f"{acc['name']}: {str(e)}")
                    
            if errors_list:
                QMessageBox.warning(self, "Ошибки", "\n".join(errors_list))
            else:
                QMessageBox.information(self, "Успех", "Сообщения отправлены")
                
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Ошибка при отправке: {str(e)}")

    # Публичный псевдоним для кнопки обновления
    def reload_accounts(self):
        self.load_broadcast_accounts()

    def select_media_files(self):
        """Открывает диалог выбора изображений."""
        from PyQt6.QtWidgets import QFileDialog
        file_dialog = QFileDialog(self)
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        file_dialog.setNameFilter("Медиа (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.mp4 *.mov *.mkv *.avi *.mp3 *.wav *.m4a *.pdf *.doc *.docx *.xls *.xlsx *.zip *.rar)")
        file_dialog.setViewMode(QFileDialog.ViewMode.List)

        if file_dialog.exec() == QFileDialog.DialogCode.Accepted:
            selected_files = file_dialog.selectedFiles()

            # Создаем progress dialog для обработки файлов
            from PyQt6.QtWidgets import QProgressDialog
            progress_dialog = QProgressDialog("Обработка файлов...", "Отмена", 0, len(selected_files), self)
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setAutoReset(False)
            progress_dialog.setAutoClose(False)

            added_files = 0
            skipped_files = 0
            large_files = []

            for i, file_path in enumerate(selected_files):
                # Обновляем progress dialog
                progress_dialog.setValue(i)
                progress_dialog.setLabelText(f"Обработка: {os.path.basename(file_path)}")
                QApplication.processEvents()  # Обрабатываем события GUI

                if progress_dialog.wasCanceled():
                    break

                if file_path not in self.selected_media_files:
                    # Принимаем любые файлы, проверка лимитов будет на этапе отправки
                    file_size = os.path.getsize(file_path)
                    self.selected_media_files.append(file_path)
                    added_files += 1

                    # Добавляем в список с кнопкой удаления
                    from PyQt6.QtWidgets import QListWidgetItem, QPushButton, QHBoxLayout, QWidget
                    item_widget = QWidget()
                    item_layout = QHBoxLayout(item_widget)
                    item_layout.setContentsMargins(5, 2, 5, 2)

                    # Название файла с размером
                    file_name = os.path.basename(file_path)
                    file_size_mb = file_size / (1024 * 1024)

                    size_text = f"{file_size_mb:.1f} MB"
                    display_name = f"{file_name} ({size_text})"
                    name_label = QLabel(display_name)
                    name_label.setToolTip(f"{file_path}\nРазмер: {size_text}")
                    item_layout.addWidget(name_label)

                    # Кнопка удаления
                    remove_btn = QPushButton("❌")
                    remove_btn.setFixedSize(30, 25)
                    remove_btn.setProperty("role", "danger")
                    remove_btn.setToolTip("Удалить файл")
                    remove_btn.clicked.connect(lambda checked, path=file_path: self.remove_media_file(path))
                    item_layout.addWidget(remove_btn)

                    item = QListWidgetItem()
                    item.setSizeHint(item_widget.sizeHint())
                    self.media_list.addItem(item)
                    self.media_list.setItemWidget(item, item_widget)

            # Завершаем progress dialog
            progress_dialog.setValue(len(selected_files))
            progress_dialog.close()

            # Показываем отчет о добавленных файлах
            if added_files > 0:
                self.log_to_status(f"✅ Добавлено файлов: {added_files}")

            # Убираем предупреждение об ограничениях выбора: лимиты учитываются при отправке

    def remove_media_file(self, file_path):
        """Удаляет медиа файл из списка."""
        if file_path in self.selected_media_files:
            self.selected_media_files.remove(file_path)

        # Обновляем список виджетов
        self.update_media_list_display()

    def clear_media_files(self):
        """Очищает все выбранные медиа файлы."""
        self.selected_media_files.clear()
        self.media_list.clear()

    def preview_media_files(self):
        """Показывает диалог с предпросмотром выбранных медиа файлов."""
        if not self.selected_media_files:
            QMessageBox.information(self, "Предпросмотр", "Нет выбранных файлов для предпросмотра.")
            return

        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QWidget, QLabel, QProgressDialog
        from PyQt6.QtGui import QPixmap, QImage
        from PyQt6.QtCore import Qt

        # Создаем progress dialog для загрузки изображений
        progress_dialog = QProgressDialog("Загрузка изображений...", "Отмена", 0, len(self.selected_media_files), self)
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.setAutoReset(False)
        progress_dialog.setAutoClose(False)

        dialog = QDialog(self)
        dialog.setWindowTitle("Предпросмотр медиа файлов")
        dialog.setMinimumSize(600, 400)

        layout = QVBoxLayout(dialog)

        # Создаем область прокрутки для изображений
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        for i, file_path in enumerate(self.selected_media_files):
            # Обновляем progress dialog
            progress_dialog.setValue(i)
            progress_dialog.setLabelText(f"Загрузка: {os.path.basename(file_path)}")
            QApplication.processEvents()  # Обрабатываем события GUI

            if progress_dialog.wasCanceled():
                return

            # Создаем контейнер для каждого файла
            file_container = QWidget()
            file_layout = QVBoxLayout(file_container)
            file_layout.setContentsMargins(10, 10, 10, 10)

            # Название файла
            file_name = os.path.basename(file_path)
            name_label = QLabel(file_name)
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_label.setStyleSheet("font-weight: bold; margin-bottom: 5px;")
            file_layout.addWidget(name_label)

            # Пытаемся загрузить и показать изображение
            try:
                pixmap = QPixmap(file_path)
                if not pixmap.isNull():
                    # Масштабируем изображение для предпросмотра
                    scaled_pixmap = pixmap.scaledToWidth(300, Qt.TransformationMode.SmoothTransformation)
                    if scaled_pixmap.height() > 200:
                        scaled_pixmap = pixmap.scaled(300, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

                    image_label = QLabel()
                    image_label.setPixmap(scaled_pixmap)
                    image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    image_label.setStyleSheet("border: 1px solid #ccc; padding: 5px;")
                    file_layout.addWidget(image_label)
                else:
                    # Если не удалось загрузить как изображение
                    error_label = QLabel("⚠️ Не удалось загрузить изображение")
                    error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    error_label.setStyleSheet("color: #ff6b6b; padding: 20px;")
                    file_layout.addWidget(error_label)
            except Exception as e:
                error_label = QLabel(f"⚠️ Ошибка загрузки: {str(e)}")
                error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                error_label.setStyleSheet("color: #ff6b6b; padding: 20px;")
                file_layout.addWidget(error_label)

            scroll_layout.addWidget(file_container)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)

        # Кнопка закрытия
        close_btn = QPushButton("Закрыть")
        close_btn.setProperty("role", "secondary")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        # Завершаем progress dialog
        progress_dialog.setValue(len(self.selected_media_files))
        progress_dialog.close()

        dialog.exec()

    def log_to_status(self, message):
        """Показывает сообщение в статусной строке."""
        if hasattr(self, 'statusBar'):
            self.statusBar().showMessage(message, 5000)  # Показывать 5 секунд
        else:
            # Если статусной строки нет, показываем в QMessageBox
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Информация", message)

    def update_media_list_display(self):
        """Обновляет отображение списка медиа файлов."""
        self.media_list.clear()
        for file_path in self.selected_media_files:
            from PyQt6.QtWidgets import QListWidgetItem, QPushButton, QHBoxLayout, QWidget
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 2, 5, 2)

            # Название файла с размером
            file_name = os.path.basename(file_path)
            try:
                file_size = os.path.getsize(file_path)
                file_size_mb = file_size / (1024 * 1024)

                size_text = f"{file_size_mb:.1f} MB"
                display_name = f"{file_name} ({size_text})"
                tooltip_text = f"{file_path}\nРазмер: {size_text}"
            except OSError:
                display_name = f"{file_name} (размер неизвестен)"
                tooltip_text = f"{file_path}\nНе удалось определить размер файла"

            name_label = QLabel(display_name)
            name_label.setToolTip(tooltip_text)
            item_layout.addWidget(name_label)

            # Кнопка удаления
            remove_btn = QPushButton("❌")
            remove_btn.setFixedSize(30, 25)
            remove_btn.setProperty("role", "danger")
            remove_btn.setToolTip("Удалить файл")
            remove_btn.clicked.connect(lambda checked, path=file_path: self.remove_media_file(path))
            item_layout.addWidget(remove_btn)

            item = QListWidgetItem()
            item.setSizeHint(item_widget.sizeHint())
            self.media_list.addItem(item)
            self.media_list.setItemWidget(item, item_widget)

    def load_config(self):
        config = configparser.ConfigParser()
        config.read('settings.ini', encoding='utf-8')
        return config

# --- Utility functions ---

def cleanup_temp_files():
    """Очистка временных файлов сессий и мусора."""
    import shutil
    try:
        user_data_dir = USER_DATA_DIR

        # Очищаем старые файлы сессий (старше 30 дней)
        sessions_dir = os.path.join(user_data_dir, 'sessions')
        if os.path.exists(sessions_dir):
            for filename in os.listdir(sessions_dir):
                if filename.endswith('.session'):
                    filepath = os.path.join(sessions_dir, filename)
                    try:
                        # Проверяем возраст файла
                        file_age_days = (time.time() - os.path.getmtime(filepath)) / (24 * 3600)
                        if file_age_days > 30:
                            os.remove(filepath)
                            _dbg(f"Удален старый файл сессии: {filename}")
                    except Exception as e:
                        _dbg(f"Ошибка при удалении {filename}: {e}")

        # Очищаем старые логи рассылки (старше 90 дней)
        logs_dir = os.path.join(user_data_dir, 'broadcast_logs')
        if os.path.exists(logs_dir):
            for filename in os.listdir(logs_dir):
                if filename.endswith('.html'):
                    filepath = os.path.join(logs_dir, filename)
                    try:
                        file_age_days = (time.time() - os.path.getmtime(filepath)) / (24 * 3600)
                        if file_age_days > 90:
                            os.remove(filepath)
                            _dbg(f"Удален старый лог рассылки: {filename}")
                    except Exception as e:
                        _dbg(f"Ошибка при удалении {filename}: {e}")

    except Exception as e:
        _dbg(f"Ошибка при очистке временных файлов: {e}")

# --- Debug helper ---
def _dbg(msg: str):
    """Append diagnostic line to ~/Desktop/tgflow_debug.log (best-effort)."""
    try:
        log_path = pathlib.Path.home() / 'Desktop' / 'tgflow_debug.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8') as _f:
            ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            _f.write(f"{ts} | {msg}\n")
    except Exception:
        pass

def apply_global_theme(app):
    qss = """
    /* Base */
    QWidget { font-family: -apple-system, "Segoe UI", Roboto, "Noto Sans", "Helvetica Neue", Arial; font-size: 13px; color: #e6e6e6; background: #1e1f24; }
    QToolTip { color: #e6e6e6; background: #2a2e36; border: 1px solid #3b3f46; padding: 6px; border-radius: 6px; }

    /* Inputs */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget, QTreeWidget, QTableWidget { 
        background: #14161c; color: #e6e6e6; border: 1px solid #3b3f46; border-radius: 8px; padding: 6px; selection-background-color: #2d79c7; selection-color: #ffffff; }
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QListWidget:focus, QTreeWidget:focus, QTableWidget:focus { border: 1px solid #2d79c7; }
    QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled { color: #9aa1ab; background: #1a1c22; border-color: #2a2d34; }

    /* Buttons */
    QPushButton { background: #2a2e36; color: #e6e6e6; border: 1px solid #3b3f46; border-radius: 10px; padding: 6px 12px; }
    QPushButton:hover { background: #323844; }
    QPushButton:pressed { background: #262b33; }
    QPushButton:disabled { color: #8f96a1; background: #232730; border-color: #2f343d; }
    QPushButton:focus { border: 2px solid #2d79c7; }

    /* Role variants */
    QPushButton[role="primary"] { background: #2d79c7; border-color: #2d79c7; color: #ffffff; }
    QPushButton[role="primary"]:hover { background: #3a86d4; border-color: #3a86d4; }
    QPushButton[role="primary"]:pressed { background: #2567ac; border-color: #2567ac; }
    QPushButton[role="primary"]:focus { border: 2px solid #9dc6f2; }

    QPushButton[role="success"] { background: #2ea44f; border-color: #2ea44f; color: #ffffff; }
    QPushButton[role="success"]:hover { background: #33b357; border-color: #33b357; }
    QPushButton[role="success"]:pressed { background: #278d43; border-color: #278d43; }
    QPushButton[role="success"]:focus { border: 2px solid #83d299; }

    QPushButton[role="danger"] { background: #d14b4b; border-color: #d14b4b; color: #ffffff; }
    QPushButton[role="danger"]:hover { background: #dc5c5c; border-color: #dc5c5c; }
    QPushButton[role="danger"]:pressed { background: #b84040; border-color: #b84040; }
    QPushButton[role="danger"]:focus { border: 2px solid #f29b9b; }

    QPushButton[role="secondary"] { background: #2a2e36; color: #e6e6e6; border: 1px solid #4a4f59; }
    QPushButton[role="secondary"]:hover { background: #323844; }
    QPushButton[role="secondary"]:pressed { background: #262b33; }
    QPushButton[role="secondary"]:focus { border: 2px solid #5b93c7; }

    /* Tabs */
    QTabWidget::pane { border: 1px solid #3b3f46; border-radius: 8px; top: -1px; }
    QTabBar::tab { background: #2a2e36; color: #e6e6e6; border: 1px solid #3b3f46; padding: 6px 12px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
    QTabBar::tab:selected { background: #323844; border-bottom-color: #323844; }
    QTabBar::tab:hover { background: #363c48; }

    /* Dialogs */
    QDialog { background: #23262d; }

    /* Scrollbars (minimal) */
    QScrollBar:vertical { background: #1e1f24; width: 10px; margin: 0; }
    QScrollBar::handle:vertical { background: #3b3f46; border-radius: 5px; }
    QScrollBar::handle:vertical:hover { background: #4a4f59; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

    QScrollBar:horizontal { background: #1e1f24; height: 10px; margin: 0; }
    QScrollBar::handle:horizontal { background: #3b3f46; border-radius: 5px; }
    QScrollBar::handle:horizontal:hover { background: #4a4f59; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

    /* Progress */
    QProgressBar { border: 1px solid #3b3f46; border-radius: 6px; background: #14161c; text-align: center; color: #e6e6e6; }
    QProgressBar::chunk { background-color: #2d79c7; border-radius: 6px; }

    /* Checkboxes */
    QCheckBox { spacing: 8px; color: #e6e6e6; }
    QCheckBox::indicator { width: 18px; height: 18px; border: 2px solid #5b626b; border-radius: 4px; background: #1a1c22; }
    QCheckBox::indicator:unchecked:hover { border-color: #798291; background: #23262d; }
    QCheckBox::indicator:checked { background: #2d79c7; border-color: #2d79c7; }
    QCheckBox::indicator:checked:hover { background: #3a86d4; border-color: #3a86d4; }
    """.strip()
    app.setStyleSheet(qss)

if __name__ == '__main__':
    # Очищаем временные файлы при запуске
    cleanup_temp_files()

    app = QApplication(sys.argv)
    try:
        apply_global_theme(app)
    except Exception as _e:
        _dbg(f"Theme apply failed: {_e}")

    # Устанавливаем иконку на уровне приложения (Dock/таскбар)
    try:
        from pathlib import Path as _P
        _proj = _P(__file__).parent
        _cands = [
            _P('icon.icns'),
            _P('28538791-c5e2-4ec8-9091-498b7e3e2ebd-_1_.ico'),
            _P('resources/icon.icns'),
            _P('resources/icon.ico'),
            _P('resources/icon.png'),
            _P('icon.ico'),
            _P('icon.png'),
        ]
        _abs = []
        for _p in _cands:
            _abs.append(_p)
            _abs.append(_proj / _p)
        for _p in _abs:
            if _p.exists():
                app.setWindowIcon(QIcon(str(_p)))
                break
    except Exception as _e:
        _dbg(f"App icon set failed: {_e}")
    window = TelegramApp()
    window.show()
    # Попытка принудительно вывести окно на передний план (актуально для macOS)
    try:
        window.raise_()
        window.activateWindow()
    except Exception:
        pass
    sys.exit(app.exec()) 