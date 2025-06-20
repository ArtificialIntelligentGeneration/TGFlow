import sys
import os
import json
import asyncio
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                            QTextEdit, QMessageBox, QTabWidget, QDialog, QListWidget, QListWidgetItem, QInputDialog, QComboBox, QScrollArea, QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QIcon
import nest_asyncio
from pyrogram import Client, errors
from pyrogram.enums import ParseMode
import logging
from script_manager import list_scripts, load_script, save_script, delete_script
import random
import time
import datetime, pathlib
import configparser
import re

nest_asyncio.apply()

# Настраиваем логирование
logging.basicConfig(
    filename='auth.log',
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    encoding='utf-8'
)

class AuthDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подтверждение кода")
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
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
        cancel_button = QPushButton("Отмена")
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
        label = QLabel("Пароль 2FA:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(label)
        layout.addWidget(self.password_input)
        buttons_layout = QHBoxLayout()
        ok_button = QPushButton("OK")
        cancel_button = QPushButton("Отмена")
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
            app_client = Client(self.session_name, self.api_id, self.api_hash)
            app_client.connect()
            
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
            self.finished.emit(True, 'SUCCESS', self.extra)
        except Exception as e:
            self.finished.emit(False, str(e), self.extra)

class TelegramAuthWorker(QThread):
    """Поток, который ведёт авторизацию полностью (send_code → sign_in → check_password).\n
    • send_code вызывается один раз при запуске.\n    • Поток остаётся работать и ждёт, пока GUI пришлёт код или пароль через сигналы.\n    • Клиент НЕ отключается между шагами, поэтому hash не устаревает."""

    finished = pyqtSignal(bool, str, dict)             # success, message, extra
    submit_code = pyqtSignal(str)                      # принимает введённый код из GUI
    submit_password = pyqtSignal(str)                  # принимает пароль 2FA из GUI
    
    def __init__(self, session_name: str, api_id: int, api_hash: str, phone: str):
        super().__init__()
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone

        # Данные, которые пополняет GUI
        self.phone_code: str | None = None
        self.phone_code_hash: str | None = None
        self.password: str | None = None

        # служебные флаги
        self._signed_in = False

        # Соединяем внутренние слоты
        self.submit_code.connect(self._on_code)
        self.submit_password.connect(self._on_password)

    @pyqtSlot(str)
    def _on_code(self, code: str):
        self.phone_code = code.strip()

    @pyqtSlot(str)
    def _on_password(self, pwd: str):
        self.password = pwd
    
    def run(self):
        try:
            client = Client(self.session_name, self.api_id, self.api_hash)
            client.connect()
            
            # 1. Отправляем код всегда один раз
            try:
                sent = client.send_code(self.phone)
            except errors.FloodWait as fw:
                client.disconnect()
                self.finished.emit(False, f"FLOOD_WAIT_{fw.value}", {})
                return
            
            self.phone_code_hash = sent.phone_code_hash
            self.finished.emit(True, "NEED_CODE", {"phone_code_hash": self.phone_code_hash})

            # Основной цикл ожидания ввода пользователя
            while not self._signed_in:
                self.msleep(200)  # 0.2 с – минимальная нагрузка

                # --- Ввод кода ---
                if self.phone_code and not self._signed_in:
                    try:
                        client.sign_in(
                            phone_number=self.phone,
                            phone_code_hash=self.phone_code_hash,
                            phone_code=self.phone_code
                        )
                        self._signed_in = True
                    except errors.PhoneCodeInvalid:
                        self.phone_code = None
                        self.finished.emit(False, "PHONE_CODE_INVALID", {})
                    except errors.PhoneCodeExpired:
                        sent = client.send_code(self.phone)
                        self.phone_code_hash = sent.phone_code_hash
                        self.phone_code = None
                        self.finished.emit(False, "PHONE_CODE_EXPIRED", {"phone_code_hash": self.phone_code_hash})
                    except errors.SessionPasswordNeeded:
                        # Требуется пароль 2FA – ждём ввода
                        self.phone_code = None
                        self.finished.emit(True, "NEED_PASSWORD", {})

                # --- Ввод пароля 2FA ---
                if self.password and not self._signed_in:
                    try:
                        client.check_password(self.password)
                        self._signed_in = True
                    except errors.PasswordHashInvalid:
                        self.password = None
                        self.finished.emit(False, "PASSWORD_INVALID", {})

            # Успех
            client.disconnect()
            self.finished.emit(True, "SUCCESS", {})

        except Exception as e:
            self.finished.emit(False, str(e), {})

class BroadcastWorker(QThread):
    """Отдельный поток, который рассылает сообщения для выбранных аккаунтов.

    parameters:
        accounts_info – список словарей, каждый содержит:
            session_name, api_id, api_hash, name, recipients(list[str])
        message – текст сообщения (HTML)
        min_delay, max_delay – задержка между отправками в секундах
    """

    log = pyqtSignal(str)

    def __init__(self, accounts_info: list[dict], message: str, min_delay: float, max_delay: float):
        super().__init__()
        self.accounts_info = accounts_info
        self.message = self._sanitize_html(message)
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._stop_requested = False

        # Статистика
        self.total_leads: int = 0
        self.sent_ok: int = 0
        self.sent_fail: int = 0
        self.error_reasons: list[str] = []

    def stop(self):
        self._stop_requested = True

    def run(self):
        for acc in self.accounts_info:
            if self._stop_requested:
                break
            name = acc["name"]
            try:
                self.log.emit(f"<b>{name}</b>: подключение…")
                client = Client(acc["session_name"], int(acc["api_id"]), acc["api_hash"])
                client.connect()
            except Exception as e:
                self.log.emit(f"<span style='color:red'>{name}: ошибка подключения – {e}</span>")
                continue

            for i, recipient in enumerate(acc["recipients"], 1):
                self.total_leads += 1
                if self._stop_requested:
                    break
                try:
                    def norm(r:str):
                        r=r.strip().replace('https://t.me/','').replace('http://t.me/','').replace('t.me/','')
                        if r.startswith('@'):
                            r=r[1:]
                        return r
                    client.send_message(norm(recipient), self.message, parse_mode=ParseMode.HTML)
                    self.sent_ok += 1
                    self.log.emit(f"{name}: ✅ {recipient}")
                except errors.FloodWait as fw:
                    # Пропускаем оставшиеся лиды для данного аккаунта
                    self.error_reasons.append(f"{name}: FLOOD_WAIT {fw.value}s – аккаунт пропущен")
                    self.log.emit(f"<span style='color:red'>{name}: FLOOD_WAIT {fw.value}s – пропуск аккаунта</span>")
                    break  # выходим из цикла по лидам
                except Exception as e:
                    self.sent_fail += 1
                    err_msg = str(e)
                    self.error_reasons.append(f"{name}/{recipient}: {err_msg}")
                    self.log.emit(f"{name}: ❌ {recipient} – {e}")

                # Случайная задержка
                if i != len(acc["recipients"]):
                    delay = random.uniform(self.min_delay, self.max_delay)
                    self.log.emit(f"{name}: пауза {delay:.1f} с…")
                    # Проверяем флаг остановки каждую секунду во время паузы
                    slept = 0.0
                    while slept < delay and not self._stop_requested:
                        chunk = min(1.0, delay - slept)
                        time.sleep(chunk)
                        slept += chunk

            client.disconnect()
            self.log.emit(f"{name}: завершено")

        # Итоговый отчёт
        report_lines = [
            "<hr>",
            f"<b>Всего лидов:</b> {self.total_leads}",
            f"<b>Успешно отправлено:</b> {self.sent_ok}",
            f"<b>Ошибок:</b> {self.sent_fail}",
        ]
        if self.error_reasons:
            report_lines.append("<b>Список ошибок:</b><br>" + "<br>".join(self.error_reasons))

        self.log.emit("<br>".join(report_lines))
        self.log.emit("<b>Рассылка остановлена</b>" if self._stop_requested else "<b>Все аккаунты обработаны</b>")

    @staticmethod
    def _sanitize_html(html: str) -> str:
        """Приводит HTML из QTextEdit к формату, совместимому с Telegram."""
        # Удаляем head/style
        body_start = html.find('<body')
        if body_start != -1:
            body_start = html.find('>', body_start) + 1
            body_end = html.find('</body>', body_start)
            html = html[body_start:body_end]

        # <span style="font-weight:600;"> → <b>
        html = re.sub(r'<span[^>]*font-weight:[^>]*>(.*?)</span>', r'<b>\1</b>', html, flags=re.S)
        # <span style="font-style:italic;"> → <i>
        html = re.sub(r'<span[^>]*font-style:\s*italic[^>]*>(.*?)</span>', r'<i>\1</i>', html, flags=re.S)
        # Убираем остальные span
        html = re.sub(r'<span[^>]*>(.*?)</span>', r'\1', html, flags=re.S)
        # <p> → ''   </p> → <br>
        html = re.sub(r'<p[^>]*>', '', html)
        html = re.sub(r'</p>', '<br>', html)
        # Убираем стилевые атрибуты
        html = re.sub(r' style="[^"]*"', '', html)
        return html.strip()

class TelegramApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Sender")
        self.setMinimumSize(800, 600)
        
        # Создаем центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Основной layout
        main_layout = QVBoxLayout(central_widget)
        
        # Создаем вкладки
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # 1. Вкладка «Рассылка» (пока заглушка)
        self.broadcast_tab = QWidget()
        self.tabs.addTab(self.broadcast_tab, "Рассылка")
        
        # 2. «Аккаунты»
        self.accounts_tab = QWidget()
        self.tabs.addTab(self.accounts_tab, "Аккаунты")
        
        # 3. «Скрипты» (заглушка)
        self.scripts_tab = QWidget()
        self.tabs.addTab(self.scripts_tab, "Скрипты")
        
        # 4. «История» (заглушка)
        self.history_tab = QWidget()
        self.tabs.addTab(self.history_tab, "История")
        
        # 5. «О программе»
        self.about_tab = QWidget()
        self.tabs.addTab(self.about_tab, "О программе")
        
        # Настройка вкладок
        self.setup_broadcast_tab()
        self.setup_accounts_tab()
        self.setup_scripts_tab()
        self.setup_history_tab()
        self.setup_about_tab()
        
        # Загружаем сохраненные аккаунты
        self.load_accounts()
        self.load_broadcast_accounts()
        
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
        add_button.clicked.connect(self.add_account)
        form_layout.addWidget(add_button)
        
        layout.addLayout(form_layout)
        
        # Список аккаунтов
        self.accounts_list = QListWidget()
        layout.addWidget(self.accounts_list, 1)

        btn_acc_bar = QHBoxLayout()
        rename_acc_btn = QPushButton("Переименовать")
        del_acc_btn = QPushButton("Удалить")
        btn_acc_bar.addWidget(rename_acc_btn)
        btn_acc_bar.addWidget(del_acc_btn)
        btn_acc_bar.addStretch()
        layout.addLayout(btn_acc_bar)

        def refresh_accounts_list():
            self.accounts_list.clear()
            try:
                if os.path.exists('accounts.json'):
                    with open('accounts.json', 'r') as f:
                        accs = json.load(f)
                else:
                    accs = []
            except Exception:
                accs = []
            for acc in accs:
                self.accounts_list.addItem(f"{acc['name']} ({acc['phone']})")

        self.refresh_accounts_list = refresh_accounts_list
        refresh_accounts_list()

        def parse_selected_phone():
            item = self.accounts_list.currentItem()
            if not item:
                return None
            text = item.text()
            if '(' in text and text.endswith(')'):
                return text.split('(')[-1][:-1]
            return None

        def rename_account():
            phone = parse_selected_phone()
            if not phone:
                return
            new_name, ok = QInputDialog.getText(self, "Переименовать", "Новое имя:")
            if ok and new_name.strip():
                try:
                    with open('accounts.json', 'r') as f:
                        accs = json.load(f)
                    for acc in accs:
                        if acc['phone'] == phone:
                            acc['name'] = new_name.strip()
                            break
                    with open('accounts.json', 'w') as f:
                        json.dump(accs, f, ensure_ascii=False, indent=2)
                    refresh_accounts_list()
                    self.load_broadcast_accounts()
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка", str(e))

        def delete_account():
            phone = parse_selected_phone()
            if not phone:
                return
            if QMessageBox.question(self, "Удалить", f"Удалить аккаунт {phone}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            try:
                with open('accounts.json', 'r') as f:
                    accs = json.load(f)
                accs = [a for a in accs if a['phone'] != phone]
                with open('accounts.json', 'w') as f:
                    json.dump(accs, f, ensure_ascii=False, indent=2)
                refresh_accounts_list()
                self.load_broadcast_accounts()
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))

        rename_acc_btn.clicked.connect(rename_account)
        del_acc_btn.clicked.connect(delete_account)

    def setup_broadcast_tab(self):
        layout = QVBoxLayout(self.broadcast_tab)

        # Выбор скрипта
        script_layout = QHBoxLayout()
        script_layout.addWidget(QLabel("Скрипт:"))
        self.script_combo = QComboBox()
        script_layout.addWidget(self.script_combo, 1)

        reload_scripts_btn = QPushButton("↻")
        reload_scripts_btn.setToolTip("Обновить список скриптов")
        script_layout.addWidget(reload_scripts_btn)

        reload_accounts_btn = QPushButton("👥")
        reload_accounts_btn.setToolTip("Обновить список аккаунтов")
        script_layout.addWidget(reload_accounts_btn)

        layout.addLayout(script_layout)

        self.script_preview = QTextEdit()
        self.script_preview.setReadOnly(True)
        self.script_preview.setFixedHeight(120)
        layout.addWidget(self.script_preview)

        # Задержка
        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("Задержка от (сек):"))
        config = self.load_config()
        self.min_delay_input = QLineEdit(config.get('delays','min',fallback='1'))
        self.min_delay_input.setFixedWidth(60)
        delay_layout.addWidget(self.min_delay_input)
        delay_layout.addWidget(QLabel("до:"))
        self.max_delay_input = QLineEdit(config.get('delays','max',fallback='3'))
        self.max_delay_input.setFixedWidth(60)
        delay_layout.addWidget(self.max_delay_input)
        delay_layout.addStretch()
        layout.addLayout(delay_layout)

        # Список аккаунтов с лидами
        self.broadcast_accounts_area = QWidget()
        self.broadcast_accounts_layout = QVBoxLayout(self.broadcast_accounts_area)
        self.broadcast_accounts_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.broadcast_accounts_area)
        layout.addWidget(QLabel("Аккаунты:"))
        layout.addWidget(scroll, 1)

        # Кнопка запуска
        self.start_broadcast_btn = QPushButton("Запустить рассылку")
        layout.addWidget(self.start_broadcast_btn)

        # Внутренние связи
        reload_scripts_btn.clicked.connect(self.reload_scripts_list)
        self.script_combo.currentTextChanged.connect(self.update_script_preview)
        self.start_broadcast_btn.clicked.connect(self.start_broadcast)
        reload_accounts_btn.clicked.connect(self.reload_accounts)

        self.reload_scripts_list()
        self.load_broadcast_accounts()

    def reload_scripts_list(self):
        current = self.script_combo.currentText()
        self.script_combo.clear()
        self.script_combo.addItems(list_scripts())
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
            txt = load_script(name)
        except FileNotFoundError:
            txt = ""
        self.script_preview.setHtml(txt)

    def load_broadcast_accounts(self):
        # Очищаем
        while self.broadcast_accounts_layout.count():
            w = self.broadcast_accounts_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.broadcast_items = []
        try:
            if os.path.exists('accounts.json'):
                with open('accounts.json', 'r') as f:
                    accounts = json.load(f)
            else:
                accounts = []
        except Exception:
            accounts = []
        for acc in accounts:
            box = QCheckBox(f"{acc['name']} ({acc['phone']})")
            txt = QTextEdit()
            txt.setPlaceholderText("Лиды: по одному на строку")
            txt.setReadOnly(True)
            # Переключаем режим редактирования по галочке (s – int)
            box.stateChanged.connect(lambda s, w=txt: w.setReadOnly(s != Qt.CheckState.Checked.value))
            self.broadcast_accounts_layout.addWidget(box)
            self.broadcast_accounts_layout.addWidget(txt)
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
            min_d = float(self.min_delay_input.text())
            max_d = float(self.max_delay_input.text())
            if min_d < 0 or max_d < min_d:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Неверно заданы задержки")
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
                accounts_info.append({
                    "session_name": f"sessions/{acc['phone'].replace('+','').replace(' ','')}",
                    "api_id": acc['api_id'],
                    "api_hash": acc['api_hash'],
                    "name": acc['name'],
                    "recipients": recs
                })
        if not accounts_info:
            QMessageBox.warning(self, "Ошибка", "Не выбран ни один аккаунт")
            return
        # Сохраняем задержки в конфиг
        cfg = self.load_config()
        if not cfg.has_section('delays'):
            cfg.add_section('delays')
        cfg.set('delays','min',str(min_d))
        cfg.set('delays','max',str(max_d))
        with open('settings.ini','w') as f:
            cfg.write(f)

        # Диалог логов
        dlg = QDialog(self)
        dlg.setWindowTitle("Логи рассылки")
        dlg_layout = QVBoxLayout(dlg)
        log_view = QTextEdit()
        log_view.setReadOnly(True)
        dlg_layout.addWidget(log_view)

        btn_bar = QHBoxLayout()
        stop_btn = QPushButton("Остановить")
        close_btn = QPushButton("Закрыть")
        close_btn.setEnabled(False)
        btn_bar.addStretch()
        btn_bar.addWidget(stop_btn)
        btn_bar.addWidget(close_btn)
        dlg_layout.addLayout(btn_bar)

        start_dt = datetime.datetime.now()
        worker = BroadcastWorker(accounts_info, message, min_d, max_d)
        worker.log.connect(lambda line: log_view.append(line))
        def done():
            log_view.append("<b>Завершено</b>")
            close_btn.setEnabled(True)
            stop_btn.setEnabled(False)
            # Сохраняем лог
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
        close_btn.clicked.connect(dlg.accept)
        stop_btn.clicked.connect(worker.stop)
        worker.start()
        dlg.exec()

    def setup_scripts_tab(self):
        layout = QVBoxLayout(self.scripts_tab)

        self.scripts_list = QListWidget()
        layout.addWidget(self.scripts_list, 1)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Добавить")
        edit_btn = QPushButton("Редактировать")
        del_btn = QPushButton("Удалить")
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
                cancel_btn = QPushButton("Отмена")
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
                raw = self.editor.toHtml()
                # Используем ту же функцию очистки, что и в BroadcastWorker
                return BroadcastWorker._sanitize_html(raw)

        def add_script():
            name, ok = QInputDialog.getText(self, "Новый скрипт", "Имя файла (без расширения):")
            if not (ok and name.strip()):
                return
            dlg = ScriptEditorDialog(self, "Текст скрипта")
            if dlg.exec() == QDialog.DialogCode.Accepted:
                save_script(name.strip(), dlg.html())
                reload_list()

        def edit_script():
            item = self.scripts_list.currentItem()
            if not item:
                QMessageBox.warning(self, "Скрипты", "Выберите файл")
                return
            fname = item.text()
            try:
                text = load_script(fname)
            except FileNotFoundError:
                QMessageBox.warning(self, "Скрипты", "Файл не найден")
                reload_list()
                return
            dlg = ScriptEditorDialog(self, f"Редактировать {fname}", text)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                save_script(fname, dlg.html())

        def del_script():
            item = self.scripts_list.currentItem()
            if not item:
                return
            fname = item.text()
            if QMessageBox.question(self, "Удалить", f"Удалить {fname}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                delete_script(fname)
                reload_list()

        add_btn.clicked.connect(add_script)
        edit_btn.clicked.connect(edit_script)
        del_btn.clicked.connect(del_script)

    def setup_history_tab(self):
        layout = QVBoxLayout(self.history_tab)
        self.history_list = QListWidget()
        layout.addWidget(self.history_list, 1)

        open_btn = QPushButton("Открыть")
        refresh_btn = QPushButton("↻")
        hbar = QHBoxLayout()
        hbar.addWidget(open_btn)
        hbar.addWidget(refresh_btn)
        hbar.addStretch()
        layout.addLayout(hbar)

        def reload():
            self.history_list.clear()
            if not os.path.exists('broadcast_logs'):
                return
            for fname in sorted(os.listdir('broadcast_logs')):
                self.history_list.addItem(fname)

        self.reload_history = reload
        reload()

        def open_log():
            item = self.history_list.currentItem()
            if not item:
                return
            path = os.path.join('broadcast_logs', item.text())
            if not os.path.exists(path):
                QMessageBox.warning(self, "Ошибка", "Файл не найден")
                reload()
                return
            dlg = QDialog(self)
            dlg.setWindowTitle(item.text())
            v = QVBoxLayout(dlg)
            view = QTextEdit()
            view.setReadOnly(True)
            with open(path, 'r', encoding='utf-8') as f:
                view.setHtml(f.read())
            v.addWidget(view)
            btn = QPushButton("Закрыть")
            btn.clicked.connect(dlg.accept)
            v.addWidget(btn)
            dlg.resize(600, 400)
            dlg.exec()

        open_btn.clicked.connect(open_log)
        refresh_btn.clicked.connect(reload)

    def setup_about_tab(self):
        layout = QVBoxLayout(self.about_tab)
        lbl = QLabel('<h3>SLAVA AiG</h3>')
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        link_edit = QLineEdit('https://t.me/HermannSaliter')
        link_edit.setReadOnly(True)
        copy_btn = QPushButton('Копировать ссылку')
        def copy_link():
            QApplication.clipboard().setText(link_edit.text())
            QMessageBox.information(self,'Скопировано','Ссылка скопирована в буфер обмена')
        copy_btn.clicked.connect(copy_link)

        h = QHBoxLayout()
        h.addWidget(QLabel('TG:'))
        h.addWidget(link_edit,1)
        h.addWidget(copy_btn)
        layout.addLayout(h)

        copyright = QLabel('© 2025')
        copyright.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(copyright)

        font = QFont(); font.setPointSize(14)
        lbl.setFont(font)
        
    def load_accounts(self):
        try:
            if os.path.exists('accounts.json'):
                with open('accounts.json', 'r') as f:
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
                with open('accounts.json', 'r') as f:
                    accounts = json.load(f)
            
            # Проверяем, существует ли уже такой аккаунт
            for i, acc in enumerate(accounts):
                if acc['phone'] == account_data['phone']:
                    accounts[i] = account_data
                    break
            else:
                accounts.append(account_data)
            
            with open('accounts.json', 'w') as f:
                json.dump(accounts, f, ensure_ascii=False, indent=2)
                
            self.load_accounts()
            # Также обновим вкладку «Рассылка», если она есть
            if hasattr(self, "broadcast_accounts_layout"):
                self.load_broadcast_accounts()
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сохранить аккаунт: {str(e)}")
    
    def add_account(self):
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
        session_name = f"sessions/{phone.replace('+', '').replace(' ', '')}"
        os.makedirs('sessions', exist_ok=True)
        self.account_data = {
            'api_id': str(api_id),
            'api_hash': api_hash,
            'phone': phone,
            'name': name
        }
        self.worker = TelegramAuthWorker(session_name, api_id, api_hash, phone)
        self.worker.finished.connect(self.handle_auth_response)
        self.worker.start()
    
    def handle_auth_response(self, success, msg, extra):
        if not success:
            if msg == 'PHONE_CODE_EXPIRED':
                QMessageBox.information(self, "Код истёк", "Запрошен новый код. Проверьте Telegram/SMS и введите новый код.")
                return
            elif msg.startswith('FLOOD_WAIT_'):
                seconds = msg.split('_')[-1]
                QMessageBox.warning(self, "FloodWait", f"Telegram просит подождать {seconds} секунд перед повторной отправкой кода. Попробуйте позже.")
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
            return
        if msg == 'NEED_CODE':
            dialog = AuthDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                code = dialog.code_input.text().strip()
                if not code.isdigit():
                    QMessageBox.warning(self, "Ошибка", "Код должен содержать только цифры")
                    return
                self.worker.submit_code.emit(code)
        elif msg == 'NEED_PASSWORD':
            dialog = PasswordDialog(self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                password = dialog.password_input.text()
                if not password:
                    QMessageBox.warning(self, "Ошибка", "Введите пароль 2FA")
                    return
                self.worker.submit_password.emit(password)
        elif msg == 'SUCCESS':
            self.save_account(self.account_data)
            QMessageBox.information(self, "Успех", "Аккаунт успешно добавлен")
    
    def send_messages(self):
        message = self.message_input.toPlainText()
        recipients = self.recipients_input.toPlainText().split('\n')
        
        if not message or not recipients:
            QMessageBox.warning(self, "Ошибка", "Заполните сообщение и список получателей")
            return
            
        try:
            if not os.path.exists('accounts.json'):
                QMessageBox.warning(self, "Ошибка", "Нет добавленных аккаунтов")
                return
                
            with open('accounts.json', 'r') as f:
                accounts = json.load(f)
                
            errors_list = []
            for acc in accounts:
                session_name = f"sessions/{acc['phone'].replace('+', '').replace(' ', '')}"
                try:
                    app_client = Client(session_name, int(acc['api_id']), acc['api_hash'])
                    app_client.connect()
                    
                    def norm(r:str):
                        r=r.strip().replace('https://t.me/','').replace('http://t.me/','').replace('t.me/','')
                        if r.startswith('@'):
                            r=r[1:]
                        return r
                    for recipient in recipients:
                        if recipient.strip():
                            try:
                                app_client.send_message(norm(recipient), message)
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

    def load_config(self):
        config = configparser.ConfigParser()
        config.read('settings.ini')
        return config

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TelegramApp()
    window.show()
    sys.exit(app.exec()) 