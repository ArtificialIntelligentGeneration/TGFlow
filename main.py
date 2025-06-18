import sys
import os
import json
import asyncio
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                            QTextEdit, QMessageBox, QTabWidget, QDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QIcon
import nest_asyncio
from pyrogram import Client, errors
import logging

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
                self.msleep(200)  # 0.2 секунды – нагрузка минимальна

                # Если код введён, пытаемся войти
                if self.phone_code and not self._signed_in:
                    try:
                        client.sign_in(
                            phone_number=self.phone,
                            phone_code_hash=self.phone_code_hash,
                            phone_code=self.phone_code,
                        )
                        self._signed_in = True
                    except errors.PhoneCodeInvalid:
                        self.phone_code = None  # ждём новый ввод
                        self.finished.emit(False, "PHONE_CODE_INVALID", {})
                    except errors.PhoneCodeExpired:
                        # Запрашиваем новый код автоматически
                        sent = client.send_code(self.phone)
                        self.phone_code_hash = sent.phone_code_hash
                        self.phone_code = None
                        self.finished.emit(False, "PHONE_CODE_EXPIRED", {"phone_code_hash": self.phone_code_hash})
                    except errors.SessionPasswordNeeded:
                        # Требуется пароль 2FA – останавливаем дальнейшие sign_in пока не получим пароль
                        self.phone_code = None  # блокируем повторные sign_in
                        self.finished.emit(True, "NEED_PASSWORD", {})

                # Если пароль введён и мы ещё не прошли check_password
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
        
        # Вкладка аккаунтов
        self.accounts_tab = QWidget()
        self.tabs.addTab(self.accounts_tab, "Аккаунты")
        
        # Вкладка отправки сообщений
        self.messages_tab = QWidget()
        self.tabs.addTab(self.messages_tab, "Отправка сообщений")
        
        self.setup_accounts_tab()
        self.setup_messages_tab()
        
        # Загружаем сохраненные аккаунты
        self.load_accounts()
        
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
        self.accounts_list = QTextEdit()
        self.accounts_list.setReadOnly(True)
        layout.addWidget(self.accounts_list)
        
    def setup_messages_tab(self):
        layout = QVBoxLayout(self.messages_tab)
        
        # Поле для сообщения
        message_label = QLabel("Сообщение:")
        self.message_input = QTextEdit()
        layout.addWidget(message_label)
        layout.addWidget(self.message_input)
        
        # Поле для списка получателей
        recipients_label = QLabel("Список получателей (по одному на строку):")
        self.recipients_input = QTextEdit()
        layout.addWidget(recipients_label)
        layout.addWidget(self.recipients_input)
        
        # Кнопка отправки
        send_button = QPushButton("Отправить сообщения")
        send_button.clicked.connect(self.send_messages)
        layout.addWidget(send_button)
        
    def load_accounts(self):
        try:
            if os.path.exists('accounts.json'):
                with open('accounts.json', 'r') as f:
                    accounts = json.load(f)
                self.accounts_list.setText('\n'.join([f"{acc['name']} ({acc['phone']})" for acc in accounts]))
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
                    
                    for recipient in recipients:
                        if recipient.strip():
                            try:
                                app_client.send_message(recipient.strip(), message)
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

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TelegramApp()
    window.show()
    sys.exit(app.exec()) 