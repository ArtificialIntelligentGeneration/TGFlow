import sys
import os
import json
import time
import random
import logging
import asyncio
import re
import traceback
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, Dict, Set, Tuple

# Проверка версии Python для zoneinfo
if sys.version_info >= (3, 9):
    try:
        import zoneinfo  # Для работы с часовыми поясами (Python 3.9+)
        HAS_ZONEINFO = True
    except ImportError:
        zoneinfo = None
        HAS_ZONEINFO = False
else:
    zoneinfo = None
    HAS_ZONEINFO = False

try:
    import pytz  # Для обратной совместимости
except ImportError:
    pytz = None

# --- Crash Handling Setup ---
def log_uncaught_exception(exctype, value, tb):
    """Log uncaught exceptions to a file."""
    error_msg = "".join(traceback.format_exception(exctype, value, tb))
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    sys.stderr.write(f"\n[CRASH] {timestamp}\n{error_msg}\n")
    
    try:
        with open("crash_log.txt", "a", encoding="utf-8") as f:
            f.write(f"\n{'='*30}\n[CRASH] {timestamp}\n{error_msg}\n{'='*30}\n")
    except Exception:
        pass
        
    sys.__excepthook__(exctype, value, tb)

sys.excepthook = log_uncaught_exception
# ----------------------------

# Third-party
import nest_asyncio
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QTextEdit, QPlainTextEdit, QProgressBar, 
    QCheckBox, QMessageBox, QScrollArea, QFrame, QSpinBox, QDoubleSpinBox,
    QListWidget, QListWidgetItem, QDialog, QLineEdit, QToolButton, QComboBox,
    QFileDialog, QGroupBox, QDateEdit, QTimeEdit, QSizePolicy
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QMutex, QMutexLocker, QSize, QTimer, QDate, QTime, QDateTime
)
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette
from pyrogram import Client, errors
from pyrogram.enums import ParseMode, ChatType, ChatMemberStatus
from pyrogram.raw.functions.messages import GetDialogFilters
from bs4 import BeautifulSoup
from filelock import FileLock, Timeout

# App modules
import app_paths
from app_paths import USER_DATA_DIR, user_file
from broadcast_state import BroadcastState
from client_utils import normalize_recipient
from script_manager import list_scripts, load_script, save_script, delete_script
from PyQt6.QtWidgets import QInputDialog

# Initialize async
nest_asyncio.apply()

# --- Logging setup ---
logging.basicConfig(
    filename=user_file('mini_broadcast.log'),
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    encoding='utf-8'
)

# --- Copied Helpers from main.py ---
# Реализация вынесена в text_utils.py

from text_utils import html_to_telegram


def _log_debug(message: str, data: dict = None, location: str = "", hypothesis_id: str = ""):
    try:
        log_entry = {
            "sessionId": "debug-session",
            "runId": "repro-run-4",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000)
        }
        log_path = os.path.join(USER_DATA_DIR, "mini_debug.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"DEBUG LOG FAIL: {e} - {message}")

def open_client(session_name: str, api_id: Union[int, str], api_hash: str,
                retries: int = 5, start_client: bool = True, just_instance: bool = False) -> Client:
    _log_debug("open_client: start", {"session": session_name, "start_client": start_client, "just_instance": just_instance}, "open_client", "H1")
    lock_path = f"{session_name}.lock"
    for attempt in range(retries):
        lock = None
        cli = None
        try:
            lock = FileLock(lock_path)
            lock.acquire(timeout=10)
            
            cli = Client(session_name, int(api_id), api_hash)
            
            if just_instance:
                pass
            elif start_client:
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_running():
                         pass
                    else:
                        cli.start()
                except RuntimeError:
                    cli.start()
            else:
                cli.connect()

            cli._file_lock = lock
            return cli
        except Exception as exc:
            if cli:
                try:
                    if cli.is_connected:
                        cli.terminate() if hasattr(cli, 'terminate') else cli.disconnect()
                except:
                    pass
            if lock:
                try:
                    lock.release()
                except:
                    pass
            
            if isinstance(exc, Timeout):
                holder_pid = "unknown"
                try:
                    if os.path.exists(lock_path):
                        with open(lock_path, 'r') as f:
                            holder_pid = f.read().strip()
                except: pass
                
                if str(holder_pid) == str(os.getpid()):
                     raise RuntimeError(f"Deadlock: Session locked by current process ({holder_pid})")

            if "database is locked" in str(exc).lower():
                time.sleep(random.uniform(0.5, 1.5))
                continue
            raise

    raise RuntimeError("Failed to open client due to persistent database lock")

def _dbg(msg: str):
    try:
        log_path = Path.home() / 'Desktop' / 'tgflow_mini_debug.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('a', encoding='utf-8') as _f:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            _f.write(f"{ts} | {msg}\n")
    except Exception:
        pass

# --- Workers ---

class ChatListWorker(QThread):
    partial = pyqtSignal(list)
    success = pyqtSignal(list)
    folders_signal = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, account_data: dict, batch_size: int = 200):
        super().__init__()
        self.account_data = account_data
        self.batch_size = batch_size

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cli = None
        try:
            session_name = self.account_data['session_name']
            api_id = self.account_data['api_id']
            api_hash = self.account_data['api_hash']
            
            cli = open_client(session_name, api_id, api_hash, start_client=False)
            
            async def _collect_progressive():
                if not cli.is_connected:
                    await cli.start()
                me = await cli.get_me()

                try:
                    filters = await cli.invoke(GetDialogFilters())
                    folder_list = []
                    for f in filters:
                        if hasattr(f, 'title'):
                            folder_list.append({
                                'title': getattr(f, 'title', 'Untitled'),
                                'filter_obj': f
                            })
                    self.folders_signal.emit(folder_list)
                except Exception:
                    self.folders_signal.emit([])

                batch_dialogs = []
                async for d in cli.get_dialogs():
                    batch_dialogs.append(d)
                    if len(batch_dialogs) >= self.batch_size:
                        chats_partial = self._dialogs_to_chats(cli, me.id, batch_dialogs)
                        if chats_partial:
                            self.partial.emit(chats_partial)
                        batch_dialogs = []
                
                if batch_dialogs:
                    chats_partial = self._dialogs_to_chats(cli, me.id, batch_dialogs)
                    if chats_partial:
                        self.partial.emit(chats_partial)

            loop.run_until_complete(_collect_progressive())
            self.success.emit([])

        except Exception as e:
            self.error.emit(str(e))
        finally:
            if cli:
                try:
                    if cli.is_connected:
                         cli.stop()
                except Exception:
                    try: cli.disconnect() 
                    except: pass
                
                if hasattr(cli, "_file_lock"):
                    try: cli._file_lock.release()
                    except: pass

            try:
                loop.close()
            except: pass

    def _dialogs_to_chats(self, cli: Client, my_id: int, dialogs: list) -> list[dict]:
        chats = []
        for d in dialogs:
            try:
                ch = getattr(d, 'chat', None)
                if not ch: continue
                title = getattr(ch, 'title', None) or getattr(ch, 'first_name', None) or "Unknown"
                username = getattr(ch, 'username', "") or ""
                if username:
                    address = f"@{username}"
                else:
                    address = str(ch.id) 
                chats.append({
                    'id': ch.id,
                    'title': title,
                    'username': username,
                    'type': str(getattr(ch.type, 'name', 'UNKNOWN')),
                    'address': address
                })
            except Exception:
                continue
        return chats


class MiniBroadcastWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    finished_signal = pyqtSignal()

    def __init__(self, accounts_info: list[dict], message: str, 
                 delay_min: float = 30.0, delay_max: float = 60.0, disable_preview: bool = False,
                 media_files: Optional[list[str]] = None,
                 scheduled_time: Optional[datetime] = None):
        super().__init__()
        self.accounts_info = accounts_info
        self.message = html_to_telegram(message)
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.disable_preview = disable_preview
        self.media_files = media_files or []
        self.scheduled_time = scheduled_time
        self._stop_requested = False
        self.session_id = None
        self.broadcast_state = None
        self.sent_ok = 0
        self.sent_fail = 0
        self.failed_accounts = set()
        self.client_locks = {}
        self.active_clients = {}

    def stop(self):
        self._stop_requested = True

    def run(self):
        print("DEBUG: Thread started")
        self._broadcast_lock = None
        try:
            try:
                self._broadcast_lock = FileLock(str(USER_DATA_DIR / 'broadcast.lock'))
                self._broadcast_lock.acquire(timeout=1)
                print("DEBUG: Lock acquired")
            except Timeout:
                print("DEBUG: Lock timeout")
                self.log.emit("<span style='color:red'>❌ Рассылка уже запущена</span>")
                self.finished_signal.emit()
                return

            self.progress.emit(0, "Запуск...")
            
            # --- Server-Side Scheduling Init ---
            current_schedule_dt = self.scheduled_time
            # Приводим к UTC для проверки, если scheduled_time aware
            now_utc = datetime.now(timezone.utc)
            
            if current_schedule_dt:
                if current_schedule_dt <= now_utc:
                     current_schedule_dt = now_utc + timedelta(seconds=10)
            
            if current_schedule_dt:
                 self.log.emit(f"📅 <b>Режим планирования</b>: старт {current_schedule_dt.strftime('%d.%m.%Y %H:%M:%S')}")
            else:
                 self.log.emit("<b>🚀 Запуск рассылки по чатам...</b>")
            # -----------------------------------

            self._init_state()
            
            # Init locks for this run
            for acc in self.accounts_info:
                self.client_locks[acc['name']] = QMutex()

            eligible = [len(acc.get("recipients", [])) for acc in self.accounts_info]
            max_messages = max(eligible) if eligible else 0
            
            if max_messages == 0:
                self.log.emit("<span style='color:orange'>❗ Нет получателей</span>")
                self.finished_signal.emit()
                return

            print("DEBUG: Max messages:", max_messages)

            for wave_idx in range(max_messages):
                if self._stop_requested: break
                pct = int((wave_idx / max_messages) * 100)
                
                if current_schedule_dt:
                    self.progress.emit(pct, f"Планирование {wave_idx + 1}/{max_messages}")
                    self.log.emit(f"<b>📅 Планирование волны {wave_idx + 1}/{max_messages} на {current_schedule_dt.strftime('%H:%M:%S')}</b>")
                else:
                    self.progress.emit(pct, f"Волна {wave_idx + 1}/{max_messages}")
                    self.log.emit(f"<b>🌊 Волна {wave_idx + 1}/{max_messages}</b>")
                
                self._send_wave(wave_idx, schedule_dt=current_schedule_dt)
                
                # Calculate delays
                delay = random.uniform(self.delay_min, self.delay_max)
                
                if wave_idx < max_messages - 1:
                    if self.scheduled_time:
                         current_schedule_dt += timedelta(seconds=delay)
                         safe_wait = random.uniform(2.0, 4.0)
                         self.log.emit(f"⏳ Пауза {safe_wait:.1f}с перед планированием следующей...")
                         self._wait(safe_wait)
                    else:
                         self.log.emit(f"⏳ Ожидание {delay:.1f}с...")
                         self._wait(delay)

            self.progress.emit(100, "Завершено")
            self.log.emit("<b>✅ Рассылка завершена</b>")

        except Exception as e:
            self.log.emit(f"<span style='color:red'>Ошибка: {e}</span>")
            import traceback
            traceback.print_exc()
        finally:
            if self.broadcast_state:
                try: self.broadcast_state.save()
                except: pass
            self._cleanup_clients()
            if self._broadcast_lock:
                try: self._broadcast_lock.release()
                except: pass
            self.finished_signal.emit()

    def _init_state(self):
        import uuid
        self.session_id = str(uuid.uuid4())
        self.broadcast_state = BroadcastState(
            session_id=self.session_id,
            accounts_info=self.accounts_info,
            message=self.message
        )
        self.log.emit(f"Session ID: {self.session_id}")

    def _wait(self, seconds: float):
        steps = int(seconds * 10)
        for _ in range(steps):
            if self._stop_requested: break
            time.sleep(0.1)

    def _get_client(self, name: str, data: dict):
        mutex = self.client_locks.get(name)
        if not mutex: return None
        with QMutexLocker(mutex):
            if name in self.active_clients:
                return self.active_clients[name]
            time.sleep(random.uniform(0.1, 0.3))
            try:
                sess_path = Path(data['session_name'])
                sess_path.parent.mkdir(parents=True, exist_ok=True)
                cli = open_client(data['session_name'], data['api_id'], data['api_hash'])
                self.active_clients[name] = cli
                return cli
            except Exception as e:
                self.log.emit(f"<span style='color:red'>{name}: Не удалось открыть клиент: {e}</span>")
                self.failed_accounts.add(name)
                return None

    def _cleanup_clients(self):
        for name, cli in self.active_clients.items():
            try:
                if hasattr(cli, 'stop'): cli.stop()
                elif hasattr(cli, 'disconnect'): cli.disconnect()
                if hasattr(cli, '_file_lock'):
                    cli._file_lock.release()
            except: pass
        self.active_clients.clear()

    def _send_wave(self, wave_idx, schedule_dt=None):
        active_list = []
        for acc in self.accounts_info:
            if acc['name'] not in self.failed_accounts:
                if len(acc['recipients']) > wave_idx:
                    active_list.append(acc)
        if not active_list: return

        for i, acc in enumerate(active_list):
            if self._stop_requested: break
            name = acc['name']
            recipient = acc['recipients'][wave_idx]
            self._send_single(name, acc, recipient, wave_idx, schedule_dt=schedule_dt)
            if i < len(active_list) - 1:
                time.sleep(3.0)

    def _humanize_error(self, error_text: str) -> str:
        # Simplified for brevity
        return str(error_text)

    def _send_single(self, name, acc_data, recipient, wave_idx, schedule_dt=None):
        try:
            chat_id = recipient
            if isinstance(chat_id, str):
                if chat_id.lstrip('-').isdigit():
                     chat_id = int(chat_id)
            client = self._get_client(name, acc_data)
            if not client: return
            
            try:
                if not client.get_me():
                    raise Exception("Not authorized")
            except Exception as e:
                self.log.emit(f"<span style='color:red'>{name}: Ошибка авторизации: {e}</span>")
                self.failed_accounts.add(name)
                return

            # Отправка медиа (если выбрано)
            media_sent_count = 0
            caption_too_long = len(self.message) > 1024
            
            if self.media_files:
                for i, path in enumerate(self.media_files):
                    try:
                        # Подпись добавляем только к первому файлу и если она помещается
                        current_caption = None
                        if i == 0 and not caption_too_long:
                            current_caption = self.message

                        ext = os.path.splitext(path)[1].lower()
                        if ext in ('.jpg', '.jpeg', '.png', '.webp'):
                            client.send_photo(chat_id=chat_id, photo=path, caption=current_caption, parse_mode=ParseMode.HTML, schedule_date=schedule_dt)
                        elif ext in ('.mp4', '.mov', '.mkv'):
                            client.send_video(chat_id=chat_id, video=path, caption=current_caption, parse_mode=ParseMode.HTML, schedule_date=schedule_dt)
                        else:
                            client.send_document(chat_id=chat_id, document=path, caption=current_caption, parse_mode=ParseMode.HTML, schedule_date=schedule_dt)
                        
                        media_sent_count += 1
                        
                        # Короткая пауза между файлами, если их несколько
                        if len(self.media_files) > 1:
                            time.sleep(0.5)

                    except Exception as m_err:
                        self.log.emit(f"<span style='color:orange'>{name} -> медиа {os.path.basename(path)}: {m_err}</span>")

                # Если подпись была слишком длинной, отправляем текст отдельным сообщением
                if caption_too_long and self.message.strip():
                    client.send_message(
                        chat_id=chat_id, 
                        text=self.message, 
                        parse_mode=ParseMode.HTML, 
                        disable_web_page_preview=self.disable_preview,
                        schedule_date=schedule_dt
                    )
                    status_prefix = "✅ Текст (отдельно)" if not schedule_dt else f"✅ Текст запланирован ({schedule_dt.strftime('%H:%M')})"
                    self.log.emit(f"{name} -> {recipient}: {status_prefix}")
                    self.sent_ok += 1
                elif media_sent_count > 0:
                    # Если медиа отправлены и текст был в подписи (или его не было)
                    status_prefix = "✅ Медиа отправлено" if not schedule_dt else f"✅ Медиа запланировано ({schedule_dt.strftime('%H:%M')})"
                    self.log.emit(f"{name} -> {recipient}: {status_prefix}")
                    self.sent_ok += 1
                elif media_sent_count == 0 and self.message.strip():
                     # Если медиа были, но не отправились, пробуем отправить текст
                    client.send_message(
                        chat_id=chat_id,
                        text=self.message,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=self.disable_preview,
                        schedule_date=schedule_dt
                    )
                    status_msg = "✅ Отправлено (текст)"
                    if schedule_dt:
                        status_msg = f"✅ Запланировано ({schedule_dt.strftime('%H:%M')})"
                    self.log.emit(f"{name} -> {recipient}: {status_msg}")
                    self.sent_ok += 1

                if self.broadcast_state:
                    self.broadcast_state.mark_message_sent(name, str(recipient), wave_idx)

            # Если медиа файлов не было вообще, отправляем просто текст
            elif self.message.strip():
                client.send_message(
                    chat_id=chat_id,
                    text=self.message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=self.disable_preview,
                    schedule_date=schedule_dt
                )
                
                status_msg = "✅ Отправлено"
                if schedule_dt:
                    status_msg = f"✅ Запланировано ({schedule_dt.strftime('%H:%M')})"
                    
                self.log.emit(f"{name} -> {recipient}: {status_msg}")
                self.sent_ok += 1
                if self.broadcast_state:
                    self.broadcast_state.mark_message_sent(name, str(recipient), wave_idx)

        except errors.FloodWait as e:
            self.log.emit(f"<span style='color:orange'>{name}: ⏳ FloodWait {e.value}s</span>")
            if e.value < 60:
                time.sleep(e.value)
                try:
                    client.send_message(chat_id=chat_id, text=self.message, parse_mode=ParseMode.HTML, disable_web_page_preview=self.disable_preview)
                    self.log.emit(f"{name} -> {recipient}: ✅ Отправлено (после ожидания)")
                except Exception:
                    self.log.emit(f"<span style='color:red'>{name} -> {recipient}: ❌ Ошибка после ожидания</span>")
            else:
                self.failed_accounts.add(name)
        except Exception as e:
            self.log.emit(f"<span style='color:red'>{name} -> {recipient}: {e}</span>")


# --- Dialogs ---

class ChatPickerDialog(QDialog):
    def __init__(self, parent, account_name: str, chats: list[dict], folders: list[dict] = None, initial_ids: set = None):
        super().__init__(parent)
        self.setWindowTitle(f"Чаты — {account_name}")
        self.resize(600, 700)
        self.chats = chats
        self.folders = folders or []
        self.selected_chats = []
        self.selected_ids = set(initial_ids) if initial_ids else set()
        
        layout = QVBoxLayout(self)
        
        if self.folders:
            folder_layout = QHBoxLayout()
            folder_layout.addWidget(QLabel("📂 Папка:"))
            self.folder_combo = QComboBox()
            self.folder_combo.addItem("Все чаты", None)
            for f in self.folders:
                self.folder_combo.addItem(f['title'], f) 
            self.folder_combo.currentIndexChanged.connect(self.on_folder_changed)
            folder_layout.addWidget(self.folder_combo, 1)
            layout.addLayout(folder_layout)
        
        type_layout = QHBoxLayout()
        self.filter_channels = QCheckBox("Исключить каналы")
        self.filter_channels.setChecked(True) 
        self.filter_channels.stateChanged.connect(lambda: self.filter_list(self.search_input.text()))
        type_layout.addWidget(self.filter_channels)
        
        self.filter_groups = QCheckBox("Группы")
        self.filter_groups.setChecked(True)
        self.filter_groups.stateChanged.connect(lambda: self.filter_list(self.search_input.text()))
        type_layout.addWidget(self.filter_groups)
        
        self.filter_users = QCheckBox("Пользователи")
        self.filter_users.setChecked(True)
        self.filter_users.stateChanged.connect(lambda: self.filter_list(self.search_input.text()))
        type_layout.addWidget(self.filter_users)
        
        type_layout.addStretch()
        layout.addLayout(type_layout)

        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("🔍 Поиск:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Название или @username")
        self.search_input.textChanged.connect(self.filter_list)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(self.list_widget)
        
        sel_layout = QHBoxLayout()
        btn_all = QPushButton("Выбрать все видимые")
        btn_all.clicked.connect(self.select_all_visible)
        btn_none = QPushButton("Снять выделение")
        btn_none.clicked.connect(self.clear_selection)
        sel_layout.addWidget(btn_all)
        sel_layout.addWidget(btn_none)
        sel_layout.addStretch()
        self.count_lbl = QLabel("0 чатов")
        sel_layout.addWidget(self.count_lbl)
        layout.addLayout(sel_layout)
        
        self.current_chats_view = self.chats
        self.filter_list("")
        
        btns = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def save_selection(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if not data: continue
            cid = data['id']
            if item.isSelected():
                self.selected_ids.add(cid)
            else:
                self.selected_ids.discard(cid)

    def on_folder_changed(self):
        idx = self.folder_combo.currentIndex()
        folder_data = self.folder_combo.currentData()
        self.save_selection()
        
        if not folder_data:
            self.current_chats_view = self.chats
        else:
            f_obj = folder_data.get('filter_obj')
            if not f_obj:
                self.current_chats_view = self.chats
            else:
                filtered = []
                inc_contacts = getattr(f_obj, 'include_contacts', False)
                inc_non_contacts = getattr(f_obj, 'include_non_contacts', False)
                inc_groups = getattr(f_obj, 'include_groups', False)
                inc_channels = getattr(f_obj, 'include_broadcasts', False)
                inc_bots = getattr(f_obj, 'include_bots', False)
                
                include_ids = set()
                exclude_ids = set()
                
                for p in getattr(f_obj, 'include_peers', []) or []:
                    if hasattr(p, 'user_id'): include_ids.add(p.user_id)
                    elif hasattr(p, 'chat_id'): include_ids.add(-int(p.chat_id))
                    elif hasattr(p, 'channel_id'): include_ids.add(int(f"-100{p.channel_id}"))
                
                for p in getattr(f_obj, 'exclude_peers', []) or []:
                    if hasattr(p, 'user_id'): exclude_ids.add(p.user_id)
                    elif hasattr(p, 'chat_id'): exclude_ids.add(-int(p.chat_id))
                    elif hasattr(p, 'channel_id'): exclude_ids.add(int(f"-100{p.channel_id}"))

                for c in self.chats:
                    cid = c['id']
                    ctype = c['type'] 
                    if cid in exclude_ids: continue
                    if cid in include_ids:
                        filtered.append(c)
                        continue
                        
                    match = False
                    if ctype == 'private':
                        if inc_non_contacts: match = True
                        if inc_contacts: match = True 
                        if getattr(c, 'is_bot', False) and inc_bots: match = True
                    elif ctype in ('group', 'supergroup') and inc_groups:
                        match = True
                    elif ctype == 'channel' and inc_channels:
                        match = True
                    if match:
                        filtered.append(c)
                self.current_chats_view = filtered
        self.filter_list(self.search_input.text())

    def filter_list(self, text):
        self.save_selection()
        text = text.lower()
        exclude_chan = self.filter_channels.isChecked()
        show_groups = self.filter_groups.isChecked()
        show_users = self.filter_users.isChecked()
        
        final_list = []
        for c in self.current_chats_view:
            if text and (text not in c['title'].lower() and text not in c['address'].lower()):
                continue
            t = c['type']
            if t == 'channel' and exclude_chan: continue
            if t in ('group', 'supergroup') and not show_groups: continue
            if t == 'private' and not show_users: continue
            final_list.append(c)
        self.populate(final_list)

    def populate(self, items):
        self.list_widget.clear()
        for c in items:
            item = QListWidgetItem(f"{c['title']} ({c['address']})")
            item.setData(Qt.ItemDataRole.UserRole, c)
            if c['id'] in self.selected_ids:
                item.setSelected(True)
            self.list_widget.addItem(item)
        self.count_lbl.setText(f"Видимых чатов: {len(items)}")

    def select_all_visible(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setSelected(True)
        self.save_selection()

    def clear_selection(self):
        self.list_widget.clearSelection()
        self.save_selection()

    def accept(self):
        self.save_selection()
        self.selected_chats = []
        for c in self.chats:
            if c['id'] in self.selected_ids:
                self.selected_chats.append(c)
        super().accept()


# --- Main Widget ---

class MiniBroadcastWidget(QWidget):
    def __init__(self):
        super().__init__()
        # self.setWindowTitle("Рассылка по чатам (Mini Broadcast)")
        # self.resize(700, 800)
        # Style embedded manually or via parent
        
        self.accounts_data = []
        self.account_chats_cache = {} 
        self.account_folders_cache = {} 
        self.selected_recipients_map = {} 
        self.worker = None
        self.chat_worker = None
        self.selected_media_files: list[str] = []
        
        self.init_ui()
        self.load_accounts()

    def init_ui(self):
        # --- Main Layout (Root) ---
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- Global Scroll Area ---
        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        # --- Content Container ---
        content_widget = QWidget()
        main_layout = QVBoxLayout(content_widget) # Using main_layout name to minimize diff, but this is now inner layout
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)
        
        main_scroll.setWidget(content_widget)
        root_layout.addWidget(main_scroll)

        # =============================================
        # 1. Group: Получатели (Receivers)
        # =============================================
        receivers_group = QGroupBox("1. Получатели")
        receivers_layout = QVBoxLayout(receivers_group)
        receivers_layout.setContentsMargins(10, 10, 10, 10)
        receivers_layout.setSpacing(5)

        receivers_layout.addWidget(QLabel("ВЫБЕРИТЕ АККАУНТЫ И ЧАТЫ:"))
        
        self.accounts_area = QScrollArea()
        self.accounts_area.setWidgetResizable(True)
        self.accounts_area.setFrameShape(QFrame.Shape.NoFrame) # Clean look inside group
        
        self.accounts_container = QWidget()
        self.accounts_layout = QVBoxLayout(self.accounts_container)
        self.accounts_layout.setContentsMargins(0, 0, 0, 0)
        
        self.accounts_area.setWidget(self.accounts_container)
        self.accounts_area.setMinimumHeight(120)
        
        receivers_layout.addWidget(self.accounts_area)
        
        # Add to main
        main_layout.addWidget(receivers_group, 2) # Flex factor 2
        
        # =============================================
        # 2. Group: Сообщение (Message)
        # =============================================
        message_group = QGroupBox("2. Сообщение")
        message_layout = QVBoxLayout(message_group)
        message_layout.setContentsMargins(10, 10, 10, 10)
        message_layout.setSpacing(8)

        # --- Scripts Row ---
        scripts_layout = QHBoxLayout()
        scripts_layout.addWidget(QLabel("📜 Скрипт:"))
        
        self.script_combo = QComboBox()
        self.script_combo.addItem("Без скрипта", "")
        self.script_combo.currentTextChanged.connect(self.on_script_changed)
        scripts_layout.addWidget(self.script_combo, 1)
        
        # Script Buttons
        add_script_btn = QToolButton()
        add_script_btn.setText("+")
        add_script_btn.setToolTip("Создать скрипт")
        add_script_btn.clicked.connect(self.add_script)
        
        edit_script_btn = QToolButton()
        edit_script_btn.setText("✎")
        edit_script_btn.setToolTip("Редактировать")
        edit_script_btn.clicked.connect(self.edit_script)
        
        del_script_btn = QToolButton()
        del_script_btn.setText("🗑")
        del_script_btn.setToolTip("Удалить")
        del_script_btn.clicked.connect(self.del_script)
        
        scripts_layout.addWidget(add_script_btn)
        scripts_layout.addWidget(edit_script_btn)
        scripts_layout.addWidget(del_script_btn)
        
        message_layout.addLayout(scripts_layout, 0) # Stretch 0

        # --- Message Input ---
        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("Введите текст сообщения... <b>bold</b>, <i>italic</i>")
        self.message_input.setMinimumHeight(120) 
        self.message_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        message_layout.addWidget(self.message_input, 10) # Stretch 10 (Main Content)

        # --- Media Row (Wrapped in Widget to prevent overlap) ---
        media_container = QWidget()
        media_layout = QHBoxLayout(media_container)
        media_layout.setContentsMargins(0, 0, 0, 0)
        
        media_layout.addWidget(QLabel("📎 Медиа:"))
        
        self.media_list = QListWidget()
        self.media_list.setMaximumHeight(60) 
        media_layout.addWidget(self.media_list, 1)

        media_btns = QVBoxLayout()
        media_btns.setSpacing(2)
        add_media_btn = QPushButton("Добавить")
        # add_media_btn.setProperty("role", "secondary") 
        add_media_btn.setFixedSize(80, 24)
        add_media_btn.clicked.connect(self.add_media)
        
        clear_media_btn = QPushButton("Очистить")
        # clear_media_btn.setProperty("role", "danger")
        clear_media_btn.setFixedSize(80, 24)
        clear_media_btn.clicked.connect(self.clear_media)
        
        media_btns.addWidget(add_media_btn)
        media_btns.addWidget(clear_media_btn)
        media_btns.addStretch()
        
        media_layout.addLayout(media_btns)
        
        # Add container to main layout
        message_layout.addWidget(media_container, 0) # Stretch 0
        
        # --- Preview Checkbox ---
        self.disable_preview_checkbox = QCheckBox("Отключить превью ссылок")
        self.disable_preview_checkbox.setChecked(True)
        message_layout.addWidget(self.disable_preview_checkbox, 0)

        # Add to main
        main_layout.addWidget(message_group, 10) # Flex factor 10 (Main Group)
        
        # =============================================
        # 3. Group: Отложенная отправка (Scheduled Sending)
        # =============================================
        schedule_group = QGroupBox("3. Отложенная отправка")
        schedule_layout = QVBoxLayout(schedule_group)
        schedule_layout.setContentsMargins(10, 10, 10, 10)
        
        self.enable_schedule_cb = QCheckBox("Включить отложенную отправку")
        schedule_layout.addWidget(self.enable_schedule_cb)
        
        sch_params_layout = QHBoxLayout()
        sch_params_layout.addWidget(QLabel("Дата:"))
        self.sch_date = QDateEdit()
        self.sch_date.setDate(QDate.currentDate())
        self.sch_date.setCalendarPopup(True)
        self.sch_date.setStyleSheet("background-color: #3A3A3A; color: #E0E0E0; border: 1px solid #555; border-radius: 4px; selection-background-color: #555;")
        sch_params_layout.addWidget(self.sch_date)
        
        sch_params_layout.addWidget(QLabel("Время:"))
        self.sch_time = QTimeEdit()
        self.sch_time.setDisplayFormat("HH:mm")
        self.sch_time.setTime(QTime.currentTime())
        self.sch_time.setStyleSheet("background-color: #3A3A3A; color: #E0E0E0; border: 1px solid #555; border-radius: 4px; selection-background-color: #555;")
        sch_params_layout.addWidget(self.sch_time)
        
        self.sch_timezone = QComboBox()
        self.sch_timezone.addItems(["Europe/Moscow", "UTC", "Europe/London", "America/New_York"])
        sch_params_layout.addWidget(self.sch_timezone)
        
        sch_params_layout.addStretch()
        schedule_layout.addLayout(sch_params_layout)
        
        main_layout.addWidget(schedule_group, 0)

        # =============================================
        # 4. Group: Настройки и Управление (Settings)
        # =============================================
        settings_group = QGroupBox("4. Настройки")
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setContentsMargins(10, 10, 10, 10)
        settings_layout.setSpacing(5)
        
        # Delays
        h_layout = QHBoxLayout()
        h_layout.addWidget(QLabel("Задержка волны (сек):"))
        self.delay_min = QDoubleSpinBox()
        self.delay_min.setRange(0, 3600)
        self.delay_min.setValue(30)
        self.delay_max = QDoubleSpinBox()
        self.delay_max.setRange(0, 3600)
        self.delay_max.setValue(60)
        h_layout.addWidget(QLabel("Мин:"))
        h_layout.addWidget(self.delay_min)
        h_layout.addWidget(QLabel("Макс:"))
        h_layout.addWidget(self.delay_max)
        h_layout.addStretch()
        settings_layout.addLayout(h_layout)
        
        # Controls (Start/Stop)
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("ЗАПУСТИТЬ РАССЫЛКУ")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(self.start_broadcast)
        
        self.stop_btn = QPushButton("СТОП")
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setProperty("role", "stop")
        self.stop_btn.clicked.connect(self.stop_broadcast)
        self.stop_btn.setEnabled(False)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        settings_layout.addLayout(btn_layout)
        
        # Add to main
        main_layout.addWidget(settings_group, 0) # Fixed size

        # =============================================
        # 5. Logs
        # =============================================
        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.progress_bar)
        
        # Log View
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(120)
        main_layout.addWidget(self.log_view)

        # Initialize scripts
        self.reload_scripts_list()

    def reload_scripts_list(self):
        current = self.script_combo.currentText()
        self.script_combo.clear()
        self.script_combo.addItem("Без скрипта", "")
        self.script_combo.addItems(list_scripts(category="chats"))
        idx = self.script_combo.findText(current)
        if idx >= 0:
            self.script_combo.setCurrentIndex(idx)
        else:
            self.script_combo.setCurrentIndex(0)
        self.on_script_changed(self.script_combo.currentText())

    def on_script_changed(self, name):
        if not name or name == "Без скрипта":
            return
        try:
            text = load_script(name, category="chats")
            self.message_input.setHtml(text)
        except Exception:
            pass

    def add_script(self):
        name, ok = QInputDialog.getText(self, "Новый скрипт", "Имя файла:")
        if ok and name:
            if not name.endswith(".txt"):
                name += ".txt"
            try:
                # Пустая болванка + немедленное открытие в редакторе
                save_script(name, "", category="chats")
                self.reload_scripts_list()
                idx = self.script_combo.findText(name)
                if idx >= 0:
                    self.script_combo.setCurrentIndex(idx)
                self.edit_script()  # сразу открываем полноценный редактор
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось создать скрипт: {e}")

    def edit_script(self):
        name = self.script_combo.currentText()
        if not name or name == "Без скрипта":
            QMessageBox.warning(self, "Ошибка", "Выберите скрипт для редактирования")
            return
        
        try:
            content = load_script(name, category="chats")
            
            # Используем тот же визуальный редактор, что и во вкладке "Скрипты" (упрощённая копия)
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Редактор: {name}")
            dlg.resize(640, 520)
            lay = QVBoxLayout(dlg)

            toolbar = QHBoxLayout()
            b_btn = QPushButton("B"); b_btn.setToolTip("Жирный")
            i_btn = QPushButton("I"); i_btn.setToolTip("Курсив")
            link_btn = QPushButton("🔗"); link_btn.setToolTip("Вставить ссылку")
            clear_btn = QPushButton("Tx"); clear_btn.setToolTip("Очистить форматирование")
            for btn in (b_btn, i_btn, link_btn, clear_btn):
                btn.setFixedHeight(24)
            toolbar.addWidget(b_btn)
            toolbar.addWidget(i_btn)
            toolbar.addWidget(link_btn)
            toolbar.addWidget(clear_btn)
            toolbar.addStretch()
            lay.addLayout(toolbar)

            editor = QTextEdit()
            editor.setAcceptRichText(True)
            editor.setHtml(content)
            editor.setMinimumHeight(320)
            lay.addWidget(editor, 1)

            btn_box = QHBoxLayout()
            save_btn = QPushButton("Сохранить")
            save_btn.setProperty("role", "primary")
            close_btn = QPushButton("Отмена")
            btn_box.addStretch()
            btn_box.addWidget(save_btn)
            btn_box.addWidget(close_btn)
            lay.addLayout(btn_box)

            def make_bold():
                cursor = editor.textCursor()
                fmt = cursor.charFormat()
                fmt.setFontWeight(QFont.Weight.Bold)
                cursor.mergeCharFormat(fmt)

            def make_italic():
                cursor = editor.textCursor()
                fmt = cursor.charFormat()
                fmt.setFontItalic(True)
                cursor.mergeCharFormat(fmt)

            def insert_link():
                url, ok = QInputDialog.getText(dlg, "Ссылка", "URL:")
                if ok and url:
                    cursor = editor.textCursor()
                    text = cursor.selectedText() or url
                    html = f'<a href="{url}">{text}</a>'
                    cursor.insertHtml(html)

            def clear_format():
                cursor = editor.textCursor()
                plain = editor.toPlainText()
                editor.setPlainText(plain)

            b_btn.clicked.connect(make_bold)
            i_btn.clicked.connect(make_italic)
            link_btn.clicked.connect(insert_link)
            clear_btn.clicked.connect(clear_format)
            
            def save():
                try:
                    save_script(name, editor.toHtml(), category="chats")
                    self.message_input.setHtml(editor.toHtml())
                    dlg.accept()
                except Exception as e:
                    QMessageBox.warning(dlg, "Ошибка", f"Не удалось сохранить: {e}")
            
            save_btn.clicked.connect(save)
            close_btn.clicked.connect(dlg.reject)
            
            dlg.exec()
            
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть скрипт: {e}")

    def del_script(self):
        name = self.script_combo.currentText()
        if not name or name == "Без скрипта":
            return
        if QMessageBox.question(self, "Удаление", f"Удалить скрипт {name}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            try:
                delete_script(name, category="chats")
                self.reload_scripts_list()
                self.message_input.clear()
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", f"Не удалось удалить скрипт: {e}")

    def load_accounts(self):
        try:
            acc_path = USER_DATA_DIR / 'accounts.json'
            if not acc_path.exists():
                self.log("Файл accounts.json не найден.")
                return
                
            with open(acc_path, 'r', encoding='utf-8') as f:
                self.accounts_data = json.load(f)
            
            while self.accounts_layout.count():
                child = self.accounts_layout.takeAt(0)
                if child.widget(): child.widget().deleteLater()

            for acc in self.accounts_data:
                self.add_account_row(acc)
                
            self.accounts_layout.addStretch()
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить аккаунты: {e}")

    def add_account_row(self, acc):
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(5) # Reduce spacing
        
        # Checkbox with less stretch/padding
        cb = QCheckBox(f"{acc.get('name', 'Unknown')} ({acc.get('phone', '')})")
        cb.setChecked(False) 
        cb.account_data = acc
        row_layout.addWidget(cb, stretch=1)
        
        status_lbl = QLabel("")
        status_lbl.setStyleSheet("color: orange; margin-right: 5px;")
        row_layout.addWidget(status_lbl)

        chat_btn = QPushButton("Выбрать чаты")
        chat_btn.setProperty("role", "secondary")
        chat_btn.setFixedSize(100, 24) # Smaller button
        chat_btn.setStyleSheet("padding: 2px 5px; font-size: 11px;")
        
        cb.chat_btn = chat_btn
        cb.status_lbl = status_lbl
        
        chat_btn.clicked.connect(lambda: self.open_chat_picker(acc, cb))
        
        row_layout.addWidget(chat_btn)
        self.accounts_layout.addWidget(row_widget)

    def open_chat_picker(self, acc, cb_widget):
        session_name = acc.get('session_name')
        if not session_name:
            clean_phone = acc['phone'].replace('+', '').replace(' ', '')
            session_name = str(user_file('sessions', clean_phone))
            acc['session_name'] = session_name
            
        if session_name in self.account_chats_cache:
            self.show_picker(acc, self.account_chats_cache[session_name], self.account_folders_cache.get(session_name), cb_widget)
        else:
            cb_widget.status_lbl.setText("Загрузка чатов...")
            cb_widget.chat_btn.setEnabled(False)
            
            self.chat_worker = ChatListWorker(acc)
            self.chat_worker.partial.connect(lambda chats: self.cache_chats(session_name, chats))
            self.chat_worker.folders_signal.connect(lambda folders: self.cache_folders(session_name, folders))
            self.chat_worker.success.connect(lambda _: self.on_chats_loaded(acc, session_name, cb_widget))
            self.chat_worker.error.connect(lambda err: self.on_chats_error(err, cb_widget))
            self.chat_worker.start()

    def cache_chats(self, session_name, chats):
        if session_name not in self.account_chats_cache:
            self.account_chats_cache[session_name] = []
        self.account_chats_cache[session_name].extend(chats)

    def cache_folders(self, session_name, folders):
        self.account_folders_cache[session_name] = folders

    def on_chats_loaded(self, acc, session_name, cb_widget):
        cb_widget.status_lbl.setText("")
        cb_widget.chat_btn.setEnabled(True)
        chats = self.account_chats_cache.get(session_name, [])
        folders = self.account_folders_cache.get(session_name, [])
        self.show_picker(acc, chats, folders, cb_widget)

    def on_chats_error(self, err, cb_widget):
        cb_widget.status_lbl.setText("Ошибка!")
        cb_widget.chat_btn.setEnabled(True)
        QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить чаты: {err}")

    def show_picker(self, acc, chats, folders, cb_widget):
        saved_recipients = self.selected_recipients_map.get(acc['name'], [])
        initial_ids = set()
        if saved_recipients:
            for c in chats:
                if c['address'] in saved_recipients:
                    initial_ids.add(c['id'])
        
        dlg = ChatPickerDialog(self, acc['name'], chats, folders, initial_ids=initial_ids)
        if dlg.exec():
            selected = dlg.selected_chats
            recipients = [c['address'] for c in selected] 
            self.selected_recipients_map[acc['name']] = recipients
            
            count = len(recipients)
            if count > 0:
                cb_widget.status_lbl.setText(f"Выбрано: {count}")
                cb_widget.status_lbl.setStyleSheet("color: #2ea44f;")
                cb_widget.setChecked(True)
            else:
                cb_widget.status_lbl.setText("Не выбрано")
                cb_widget.status_lbl.setStyleSheet("color: orange;")
                cb_widget.setChecked(False)

    def log(self, msg):
        self.log_view.append(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def add_media(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Выберите медиа",
            str(USER_DATA_DIR),
            "Медиа и файлы (*.*)"
        )
        if not files:
            return
        for f in files:
            if f not in self.selected_media_files:
                self.selected_media_files.append(f)
                self.media_list.addItem(f)

    def clear_media(self):
        self.selected_media_files = []
        self.media_list.clear()

    def start_broadcast(self):
        message = self.message_input.toHtml()
        plain_text = self.message_input.toPlainText().strip()
        if not plain_text and not self.selected_media_files:
            QMessageBox.warning(self, "Ошибка", "Введите сообщение или выберите медиа!")
            return
            
        # Collect accounts
        accounts_info = []
        for i in range(self.accounts_layout.count()):
            w = self.accounts_layout.itemAt(i).widget()
            if not w: continue
            cb = w.findChild(QCheckBox)
            if cb and cb.isChecked():
                acc = cb.account_data
                recipients = self.selected_recipients_map.get(acc['name'], [])
                if recipients:
                    acc['recipients'] = recipients
                    accounts_info.append(acc)
                    
        if not accounts_info:
            QMessageBox.warning(self, "Ошибка", "Выберите аккаунты и укажите получателей!")
            return
            
        # Params
        d_min = self.delay_min.value()
        d_max = self.delay_max.value()
        disable_preview = self.disable_preview_checkbox.isChecked()
        print("DEBUG: Params collected")
        
        # --- Scheduling Logic ---
        scheduled_time = None
        if self.enable_schedule_cb.isChecked():
            print("DEBUG: Scheduling enabled")
            try:
                date = self.sch_date.date()
                time_ = self.sch_time.time()
                tz_name = self.sch_timezone.currentText()
                print(f"DEBUG: Date/Time: {date} {time_}")
                
                 # Создаем datetime начала в выбранном часовом поясе
                start_datetime_naive = datetime.combine(
                    datetime(date.year(), date.month(), date.day()).date(),
                    datetime(2000, 1, 1, time_.hour(), time_.minute()).time()
                )

                # Разная логика для разных библиотек часовых поясов
                start_datetime_local = None
                try:
                    if HAS_ZONEINFO:
                        user_timezone = zoneinfo.ZoneInfo(tz_name)
                        start_datetime_local = start_datetime_naive.replace(tzinfo=user_timezone)
                    elif pytz:
                        user_timezone = pytz.timezone(tz_name)
                        start_datetime_local = user_timezone.localize(start_datetime_naive)
                    else:
                        # Fallback if no timezone lib (should not happen based on imports)
                        start_datetime_local = start_datetime_naive
                except Exception as tz_err:
                     print(f"DEBUG: Timezone error: {tz_err}")
                     QMessageBox.warning(self, "Ошибка", f"Ошибка часового пояса: {tz_err}")
                     return

                # Convert to UTC for internal logic
                # Note: We pass UTC to the worker, but we can also pass local for logging if needed
                if start_datetime_local.tzinfo:
                     start_datetime_utc = start_datetime_local.astimezone(timezone.utc)
                     scheduled_time = start_datetime_utc
                     print(f"DEBUG: Local DT: {start_datetime_local} -> UTC: {start_datetime_utc}")
                else:
                     # Fallback for naive
                     scheduled_time = start_datetime_local
                     print(f"DEBUG: Naive DT (fallback): {scheduled_time}")
                
                # If datetime is in past?
                # Check against current UTC time if we have UTC, or local vs local
                now_check = datetime.now(timezone.utc) if start_datetime_local.tzinfo else datetime.now()
                
                if scheduled_time <= now_check:
                    QMessageBox.warning(self, "Ошибка", "Время отложенной отправки должно быть в будущем!")
                    return
                print("DEBUG: Schedule time valid")
                    
            except Exception as e:
                print(f"DEBUG: Schedule error: {e}")
                QMessageBox.warning(self, "Ошибка", f"Некорректная дата/время: {e}")
                return
        # ------------------------

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log_view.clear()
        print("DEBUG: UI Updated, initializing worker")
        
        self.worker = MiniBroadcastWorker(
            accounts_info, message, 
            delay_min=d_min, delay_max=d_max, 
            disable_preview=disable_preview,
            media_files=self.selected_media_files,
            scheduled_time=scheduled_time # Pass it
        )
        print("DEBUG: Worker initialized")
        self.worker.log.connect(self.log)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished_signal.connect(self.on_finished)
        print("DEBUG: Signals connected, starting worker")
        self.worker.start()
        print("DEBUG: Worker started")

    def update_progress(self, val, txt):
        self.progress_bar.setValue(val)
        self.progress_bar.setFormat(f"{txt} %p%")

    def stop_broadcast(self):
        if self.worker:
            self.worker.stop()
            self.log("Остановка...")
            self.stop_btn.setEnabled(False)

    def on_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log("--- Завершено ---")
        self.worker = None

# Wrapper for standalone run
class MiniBroadcastApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Рассылка по чатам (Mini Broadcast)")
        self.resize(700, 800)
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #1e1f24; color: #e6e6e6; font-family: sans-serif; }
            QLineEdit, QTextEdit, QPlainTextEdit, QListWidget { background-color: #14161c; border: 1px solid #3b3f46; border-radius: 6px; padding: 6px; color: white; }
            QPushButton { background-color: #2d79c7; color: white; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold; }
            QPushButton:hover { background-color: #3a86d4; }
            QPushButton:disabled { background-color: #2a2e36; color: #888; }
            QPushButton[role="stop"] { background-color: #d94040; }
            QPushButton[role="secondary"] { background-color: #3b3f46; }
            QLabel { color: #aaa; font-size: 12px; }
            QProgressBar { border: 1px solid #3b3f46; border-radius: 6px; text-align: center; }
            QProgressBar::chunk { background-color: #2ea44f; }
        """)
        
        self.widget = MiniBroadcastWidget()
        self.setCentralWidget(self.widget)

def main():
    try:
        try:
            os.chdir(USER_DATA_DIR)
        except Exception as e:
            pass

        app = QApplication(sys.argv)
        window = MiniBroadcastApp()
        window.show()
        
        sys.exit(app.exec())
    except Exception as e:
        with open("crash.log", "w") as f:
            f.write(str(e))
        raise e

if __name__ == "__main__":
    main()
