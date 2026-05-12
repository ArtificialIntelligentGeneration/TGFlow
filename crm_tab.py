import asyncio
import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QAbstractTableModel, QDate, QModelIndex, QPoint, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from pyrogram import Client

from app_paths import user_file
from database_manager import (
    LEAD_STATUS_ARCHIVED,
    LEAD_STATUS_ERROR,
    LEAD_STATUS_IN_PROGRESS,
    LEAD_STATUS_NEW,
    LEAD_STATUS_SENT,
    DatabaseManager,
)
from parsing_engine import ParsingEngine, ParsingEngineError


class ParsingWorker(QThread):
    progress = pyqtSignal(int, int, str)  # scanned, added, message
    finished = pyqtSignal(int, str)  # added_count, error_message

    def __init__(self, db_manager: DatabaseManager, account_data: dict, target: str, mode: str, config: dict):
        super().__init__()
        self.db_manager = db_manager
        self.account_data = account_data
        self.target = target
        self.mode = mode
        self.config = config

        self._engine: Optional[ParsingEngine] = None
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        if self._engine:
            self._engine.stop()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            added, error = loop.run_until_complete(self._run_async())
            self.finished.emit(added, error)
        except Exception as e:
            self.finished.emit(0, str(e))
        finally:
            try:
                loop.close()
            except Exception as loop_err:
                logging.getLogger('CRMTab').debug(f'Failed to close parsing event loop: {loop_err}')

    async def _run_async(self) -> Tuple[int, str]:
        def cb(scanned: int, added: int, text: str):
            self.progress.emit(scanned, added, text)

        session_name = self.account_data.get('session_name')
        api_id = self.account_data.get('api_id')
        api_hash = self.account_data.get('api_hash')

        if not session_name or not api_id or not api_hash:
            return 0, 'Неполные данные аккаунта для парсинга'

        session_path = Path(str(session_name))
        session_path.parent.mkdir(parents=True, exist_ok=True)

        client = Client(str(session_path), int(api_id), str(api_hash))

        try:
            await client.start()
            self._engine = ParsingEngine(client, self.db_manager)

            if self._stop_requested:
                return 0, ''

            if self.mode == 'deep':
                days = int(self.config.get('days_limit', 7) or 7)
                added = await self._engine.deep_parsing(
                    self.target,
                    days,
                    self.config,
                    progress_callback=cb,
                )
            else:
                added = await self._engine.get_chat_members_basic(
                    self.target,
                    self.config,
                    progress_callback=cb,
                )

            return added, ''

        except ParsingEngineError as e:
            logging.getLogger('CRMTab').warning(f'Parsing ended with engine error: {e}')
            return int(getattr(e, 'partial_count', 0) or 0), str(e)
        except Exception as e:
            logging.getLogger('CRMTab').error(f'Parsing worker error: {e}')
            return 0, str(e)
        finally:
            self._engine = None
            try:
                await client.stop()
            except Exception as stop_err:
                logging.getLogger('CRMTab').debug(f'Parsing worker stop() failed: {stop_err}')
                try:
                    await client.disconnect()
                except Exception as disconnect_err:
                    logging.getLogger('CRMTab').debug(f'Parsing worker disconnect() fallback failed: {disconnect_err}')


class LeadsTableModel(QAbstractTableModel):
    def __init__(self, leads_data: List[dict], parent=None):
        super().__init__(parent)
        self._data = leads_data
        self._headers = [
            'ID',
            'Юзернейм',
            'Имя',
            'Статус',
            'Источник',
            'Был онлайн',
            'Отправлено',
        ]

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._headers)

    @staticmethod
    def _safe_display_value(value: Any) -> str:
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        try:
            return str(value)
        except Exception:
            return ''

    def _safe_ts_display(self, value: Any) -> str:
        text = self._safe_display_value(value)
        if not text:
            return ''
        # UI-only trimming of microseconds in ISO-like timestamp
        return text.split('.')[0]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self._data):
            return None
        if col < 0 or col >= len(self._headers):
            return None

        row_data = self._data[row]
        if not isinstance(row_data, dict):
            return None

        if col == 0:
            return self._safe_display_value(row_data.get('user_id', ''))
        if col == 1:
            return self._safe_display_value(row_data.get('username'))
        if col == 2:
            return self._safe_display_value(row_data.get('full_name'))
        if col == 3:
            return self._safe_display_value(row_data.get('status'))
        if col == 4:
            return self._safe_display_value(row_data.get('source_chat'))
        if col == 5:
            return self._safe_ts_display(row_data.get('last_online'))
        if col == 6:
            return self._safe_ts_display(row_data.get('sent_at'))

        return None

    def headerData(self, section, orientation, role):
        if (
            role == Qt.ItemDataRole.DisplayRole
            and orientation == Qt.Orientation.Horizontal
            and 0 <= section < len(self._headers)
        ):
            return self._headers[section]
        return None


class BroadcastAccountsDialog(QDialog):
    def __init__(self, accounts: List[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle('Аккаунты для рассылки')
        self.resize(460, 380)
        self._selected_sessions: List[str] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Выберите аккаунты, которые будут использоваться для рассылки:'))

        self.list_accounts = QListWidget()
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            session_name = str(acc.get('session_name') or '').strip()
            if not session_name:
                continue
            name = str(acc.get('name') or 'Без имени').strip()
            phone = str(acc.get('phone') or '').strip()
            title = f'{name} ({phone})' if phone else name
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, session_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list_accounts.addItem(item)
        layout.addWidget(self.list_accounts, 1)

        controls = QHBoxLayout()
        btn_select_all = QPushButton('Выбрать все')
        btn_clear_all = QPushButton('Снять выбор')
        controls.addWidget(btn_select_all)
        controls.addWidget(btn_clear_all)
        controls.addStretch()
        layout.addLayout(controls)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(buttons)

        btn_select_all.clicked.connect(self._select_all)
        btn_clear_all.clicked.connect(self._clear_all)
        buttons.accepted.connect(self._accept_with_validation)
        buttons.rejected.connect(self.reject)

    def _select_all(self):
        for i in range(self.list_accounts.count()):
            item = self.list_accounts.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _clear_all(self):
        for i in range(self.list_accounts.count()):
            item = self.list_accounts.item(i)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _accept_with_validation(self):
        selected: List[str] = []
        for i in range(self.list_accounts.count()):
            item = self.list_accounts.item(i)
            if not item or item.checkState() != Qt.CheckState.Checked:
                continue
            session = str(item.data(Qt.ItemDataRole.UserRole) or '').strip()
            if session:
                selected.append(session)
        if not selected:
            QMessageBox.warning(self, 'Аккаунты не выбраны', 'Отметьте минимум один аккаунт.')
            return
        self._selected_sessions = selected
        self.accept()

    def selected_sessions(self) -> List[str]:
        return list(self._selected_sessions)


class CRMTab(QWidget):
    def __init__(
        self,
        parent_app=None,
        db_manager: Optional[DatabaseManager] = None,
        broadcast_callback: Optional[Callable[..., Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.parent_app = parent_app
        self.db_manager = db_manager or DatabaseManager()
        self.broadcast_callback = broadcast_callback

        self.accounts_data: List[dict] = []
        self.worker: Optional[ParsingWorker] = None
        self.table_model: Optional[LeadsTableModel] = None
        self._last_mode: Optional[str] = None
        self._adaptive_buttons: List[QPushButton] = []
        self._button_full_texts: Dict[QPushButton, str] = {}
        self._button_base_tooltips: Dict[QPushButton, str] = {}
        self._db_selector_refreshing = False
        self._db_feedback_timer = QTimer(self)
        self._db_feedback_timer.setSingleShot(True)
        self._db_feedback_timer.timeout.connect(self._clear_db_feedback)

        self.init_ui()
        self.reload_accounts()
        self.refresh_table()
        self.refresh_db_info()
        QTimer.singleShot(0, self.refresh_database_list)

    def init_ui(self):
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        grp_account = QGroupBox('Аккаунт для парсинга')
        account_layout = QHBoxLayout()
        self.combo_account = QComboBox()
        self.btn_reload_accounts = QPushButton('Обновить')
        account_layout.addWidget(self.combo_account)
        account_layout.addWidget(self.btn_reload_accounts)
        grp_account.setLayout(account_layout)

        grp_target = QGroupBox('Источник парсинга')
        form_layout = QFormLayout()
        self.input_target = QLineEdit()
        self.input_target.setPlaceholderText(
            '@username, https://t.me/username, https://t.me/c/123/456, https://t.me/joinchat/ABC'
        )
        form_layout.addRow('Чат публичный/приватный:', self.input_target)
        grp_target.setLayout(form_layout)

        grp_settings = QGroupBox('Настройки фильтрации')
        settings_layout = QVBoxLayout()
        self.chk_deep = QCheckBox('Глубокий сбор (скрытые участники)')
        self.chk_deep.setToolTip('Сканирует историю сообщений и добавляет реальных авторов')

        self.combo_period = QComboBox()
        self.combo_period.addItem('1 день', ('preset_days', 1))
        self.combo_period.addItem('3 дня', ('preset_days', 3))
        self.combo_period.addItem('7 дней (1 неделя)', ('preset_days', 7))
        self.combo_period.addItem('14 дней (2 недели)', ('preset_days', 14))
        self.combo_period.addItem('30 дней (1 месяц)', ('preset_days', 30))
        self.combo_period.addItem('90 дней (3 месяца)', ('preset_days', 90))
        self.combo_period.addItem('Гибкий период: свои дни', ('custom_days', None))
        self.combo_period.addItem('Гибкий период: диапазон дат', ('date_range', None))

        period_row = QHBoxLayout()
        period_row.addWidget(QLabel('Период глубокой выборки:'))
        period_row.addWidget(self.combo_period)
        self.spin_custom_days = QSpinBox()
        self.spin_custom_days.setRange(1, 3650)
        self.spin_custom_days.setValue(30)
        self.spin_custom_days.setSuffix(' дн.')
        self.spin_custom_days.setVisible(False)
        period_row.addWidget(self.spin_custom_days)

        date_range_row = QHBoxLayout()
        self.lbl_date_from = QLabel('С даты:')
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDisplayFormat('dd.MM.yyyy')
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.lbl_date_to = QLabel('По дату:')
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDisplayFormat('dd.MM.yyyy')
        self.date_to.setDate(QDate.currentDate())
        self.lbl_date_from.setVisible(False)
        self.lbl_date_to.setVisible(False)
        self.date_from.setVisible(False)
        self.date_to.setVisible(False)
        date_range_row.addWidget(self.lbl_date_from)
        date_range_row.addWidget(self.date_from)
        date_range_row.addWidget(self.lbl_date_to)
        date_range_row.addWidget(self.date_to)
        date_range_row.addStretch()

        self.chk_online = QCheckBox('Только активные (недавно онлайн)')
        self.chk_online.setChecked(True)

        self.chk_no_bots = QCheckBox('Исключить ботов')
        self.chk_no_bots.setChecked(True)

        self.chk_no_admins = QCheckBox('Исключить админов')
        self.chk_no_admins.setChecked(True)

        settings_layout.addWidget(self.chk_deep)
        settings_layout.addLayout(period_row)
        settings_layout.addLayout(date_range_row)
        settings_layout.addWidget(self.chk_online)
        settings_layout.addWidget(self.chk_no_bots)
        settings_layout.addWidget(self.chk_no_admins)
        grp_settings.setLayout(settings_layout)

        grp_progress = QGroupBox('Прогресс')
        progress_layout = QVBoxLayout()
        self.lbl_status = QLabel('Ожидание...')
        self.progress_bar = QProgressBar()
        self.btn_start = QPushButton('Начать сбор')
        self.btn_stop = QPushButton('Остановить')
        self.btn_stop.setEnabled(False)

        progress_layout.addWidget(self.lbl_status)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.btn_start)
        progress_layout.addWidget(self.btn_stop)
        grp_progress.setLayout(progress_layout)

        left_layout.addWidget(grp_account)
        left_layout.addWidget(grp_target)
        left_layout.addWidget(grp_settings)
        left_layout.addWidget(grp_progress)
        left_layout.addStretch()

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        db_layout = QVBoxLayout()
        db_top_row = QHBoxLayout()
        db_bottom_row = QHBoxLayout()
        self.lbl_db_info = QLabel('База: -')
        self.combo_db_selector = QComboBox()
        self.btn_new_db = QPushButton('Новая')
        self.btn_clone_db = QPushButton('Сохранить как')
        self.btn_refresh_db_list = QPushButton('Обновить список')
        self.input_db_tag = QLineEdit()
        self.input_db_tag.setPlaceholderText('Тег базы (например, февраль_2026)')
        self.btn_apply_db_tag = QPushButton('Сохранить тег')
        self.lbl_db_feedback = QLabel('')
        self.lbl_db_feedback.setVisible(False)

        db_top_row.addWidget(self.lbl_db_info, 1)
        db_top_row.addWidget(self.combo_db_selector, 2)
        db_top_row.addWidget(self.btn_new_db)
        db_top_row.addWidget(self.btn_clone_db)
        db_top_row.addWidget(self.btn_refresh_db_list)

        db_bottom_row.addWidget(QLabel('Тег базы:'))
        db_bottom_row.addWidget(self.input_db_tag, 1)
        db_bottom_row.addWidget(self.btn_apply_db_tag)
        db_bottom_row.addWidget(self.lbl_db_feedback)

        db_layout.addLayout(db_top_row)
        db_layout.addLayout(db_bottom_row)

        filter_layout = QHBoxLayout()
        self.combo_status_filter = QComboBox()
        self.combo_status_filter.addItem('Все статусы', None)
        self.combo_status_filter.addItem('Новые', LEAD_STATUS_NEW)
        self.combo_status_filter.addItem('В работе', LEAD_STATUS_IN_PROGRESS)
        self.combo_status_filter.addItem('Отправлено', LEAD_STATUS_SENT)
        self.combo_status_filter.addItem('Ошибка', LEAD_STATUS_ERROR)
        self.combo_status_filter.addItem('В архиве', LEAD_STATUS_ARCHIVED)
        self.btn_refresh = QPushButton('Обновить')
        self.btn_columns = QPushButton('Столбцы')
        self.btn_export_csv = QPushButton('В CSV')
        self.btn_export_xlsx = QPushButton('В Excel')
        self.btn_broadcast = QPushButton('В рассылку')
        self.btn_clear_db = QPushButton('Очистить базу')
        self.btn_clear_db.setStyleSheet('color: red;')

        filter_layout.addWidget(QLabel('Статус:'))
        filter_layout.addWidget(self.combo_status_filter)
        filter_layout.addWidget(self.btn_refresh)
        filter_layout.addWidget(self.btn_columns)
        filter_layout.addWidget(self.btn_export_csv)
        filter_layout.addWidget(self.btn_export_xlsx)
        filter_layout.addWidget(self.btn_broadcast)
        filter_layout.addStretch()
        filter_layout.addWidget(self.btn_clear_db)

        self.table_view = QTableView()
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.MultiSelection)
        self.table_view.setSortingEnabled(True)
        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionsMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_columns_menu)

        self.lbl_stats = QLabel('Всего контактов: 0')

        right_layout.addLayout(db_layout)
        right_layout.addLayout(filter_layout)
        right_layout.addWidget(self.table_view)
        right_layout.addWidget(self.lbl_stats)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)

        self.btn_reload_accounts.clicked.connect(self.reload_accounts)
        self.combo_period.currentIndexChanged.connect(self._on_period_mode_changed)
        self.btn_start.clicked.connect(self.start_parsing)
        self.btn_stop.clicked.connect(self.stop_parsing)
        self.combo_db_selector.currentIndexChanged.connect(self._on_db_selector_changed)
        self.btn_new_db.clicked.connect(self.create_new_database)
        self.btn_clone_db.clicked.connect(self.save_database_as_new)
        self.btn_refresh_db_list.clicked.connect(self.refresh_database_list)
        self.btn_apply_db_tag.clicked.connect(self.save_database_tag)
        self.btn_refresh.clicked.connect(self.refresh_table)
        self.btn_columns.clicked.connect(self.show_columns_menu)
        self.combo_status_filter.currentTextChanged.connect(self.refresh_table)
        self.btn_export_csv.clicked.connect(self.export_to_csv)
        self.btn_export_xlsx.clicked.connect(self.export_to_excel)
        self.btn_broadcast.clicked.connect(self.broadcast_selected)
        self.btn_clear_db.clicked.connect(self.clear_database)

        self._register_adaptive_buttons([
            self.btn_reload_accounts,
            self.btn_start,
            self.btn_stop,
            self.btn_refresh,
            self.btn_columns,
            self.btn_export_csv,
            self.btn_export_xlsx,
            self.btn_broadcast,
            self.btn_clear_db,
            self.btn_new_db,
            self.btn_clone_db,
            self.btn_refresh_db_list,
            self.btn_apply_db_tag,
        ])
        self._on_period_mode_changed(self.combo_period.currentIndex())
        QTimer.singleShot(0, self._update_adaptive_button_texts)

    def _accounts_path(self) -> Path:
        return user_file('accounts.json')

    def reload_accounts(self):
        self.accounts_data = []
        self.combo_account.clear()
        self.combo_account.addItem('Выберите аккаунт...', None)

        acc_path = self._accounts_path()
        if not acc_path.exists():
            return

        try:
            with acc_path.open('r', encoding='utf-8') as f:
                raw = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, 'Ошибка', f'Не удалось прочитать accounts.json: {e}')
            return

        if not isinstance(raw, list):
            return

        for acc in raw:
            if not isinstance(acc, dict):
                continue
            session_name = acc.get('session_name')
            api_id = acc.get('api_id')
            api_hash = acc.get('api_hash')
            name = acc.get('name') or 'Без имени'
            phone = acc.get('phone') or ''

            if not session_name or not api_id or not api_hash:
                continue

            display = f'{name} ({phone})' if phone else name
            self.accounts_data.append(acc)
            self.combo_account.addItem(display, acc)

    def _selected_account(self) -> Optional[dict]:
        data = self.combo_account.currentData()
        return data if isinstance(data, dict) else None

    def _register_adaptive_buttons(self, buttons: List[QPushButton]):
        for btn in buttons:
            if not isinstance(btn, QPushButton):
                continue
            full_text = btn.text()
            base_tooltip = btn.toolTip()
            self._adaptive_buttons.append(btn)
            self._button_full_texts[btn] = full_text
            self._button_base_tooltips[btn] = base_tooltip
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setProperty('fullText', full_text)

    def _update_adaptive_button_texts(self):
        for btn in self._adaptive_buttons:
            if not btn:
                continue
            full_text = self._button_full_texts.get(btn) or str(btn.property('fullText') or '')
            if not full_text:
                continue
            max_width = max(24, btn.width() - 12)
            elided = btn.fontMetrics().elidedText(full_text, Qt.TextElideMode.ElideRight, max_width)
            btn.setText(elided)
            base_tip = self._button_base_tooltips.get(btn, '')
            if elided != full_text:
                tip = f'{full_text}\n{base_tip}'.strip()
                btn.setToolTip(tip)
            else:
                btn.setToolTip(base_tip)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_adaptive_button_texts()

    def _on_period_mode_changed(self, _index: int):
        mode_data = self.combo_period.currentData()
        mode = mode_data[0] if isinstance(mode_data, tuple) and mode_data else 'preset_days'
        is_custom_days = mode == 'custom_days'
        is_date_range = mode == 'date_range'
        self.spin_custom_days.setVisible(is_custom_days)
        self.lbl_date_from.setVisible(is_date_range)
        self.lbl_date_to.setVisible(is_date_range)
        self.date_from.setVisible(is_date_range)
        self.date_to.setVisible(is_date_range)

    def _current_period_days(self) -> Tuple[int, Optional[str], Optional[str], str]:
        data = self.combo_period.currentData()
        if isinstance(data, tuple) and len(data) >= 2:
            mode, raw_value = data
        else:
            mode, raw_value = 'preset_days', 7

        if mode == 'custom_days':
            days = int(self.spin_custom_days.value())
            if days <= 0:
                raise ValueError('Количество дней должно быть больше нуля.')
            return days, None, None, f'{days} дней'

        if mode == 'date_range':
            start_date = self.date_from.date().toPyDate()
            end_date = self.date_to.date().toPyDate()
            if start_date > end_date:
                raise ValueError('Дата "С даты" не может быть позже даты "По дату".')
            days = (end_date - start_date).days + 1
            return days, start_date.isoformat(), end_date.isoformat(), f'{start_date.isoformat()} .. {end_date.isoformat()}'

        days = int(raw_value or 7)
        if days <= 0:
            days = 7
        return days, None, None, f'{days} дней'

    @staticmethod
    def _normalize_target_input(target_value: str) -> str:
        # Keep UI normalization exactly aligned with engine behavior.
        return ParsingEngine._normalize_target_input(target_value)

    def start_parsing(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, 'Парсинг', 'Парсинг уже выполняется. Дождитесь завершения или нажмите "Остановить".')
            return

        raw_target = self.input_target.text().strip()
        target = self._normalize_target_input(raw_target)
        if not target:
            QMessageBox.warning(self, 'Ошибка', 'Введите ссылку или юзернейм чата')
            return
        self.input_target.setText(target)

        account = self._selected_account()
        if not account:
            QMessageBox.warning(self, 'Ошибка', 'Выберите аккаунт для парсинга')
            return

        try:
            days_limit, date_from_iso, date_to_iso, period_label = self._current_period_days()
        except ValueError as period_error:
            QMessageBox.warning(self, 'Ошибка периода', str(period_error))
            return

        config = {
            'only_active': self.chk_online.isChecked(),
            'exclude_bots': self.chk_no_bots.isChecked(),
            'exclude_admins': self.chk_no_admins.isChecked(),
            'days_limit': days_limit,
            'active_within_days': days_limit,
        }
        if date_from_iso and date_to_iso:
            config['date_from_iso'] = date_from_iso
            config['date_to_iso'] = date_to_iso
            config['absolute_date_range'] = True

        mode = 'deep' if self.chk_deep.isChecked() else 'basic'
        self._last_mode = mode

        self.worker = ParsingWorker(
            db_manager=self.db_manager,
            account_data=account,
            target=target,
            mode=mode,
            config=config,
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        mode_label = 'глубокого' if mode == 'deep' else 'базового'
        period_suffix = f' | Период: {period_label}' if mode == 'deep' else ''
        self.lbl_status.setText(f'Запуск {mode_label} парсинга...{period_suffix}')

        self.worker.start()

    def stop_parsing(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.lbl_status.setText('Остановка...')

    def on_progress(self, scanned: int, added: int, text: str):
        self.lbl_status.setText(f'Сканировано: {scanned} | Добавлено: {added} | {text}')

    def on_finished(self, total: int, error_message: str):
        finished_worker = self.sender()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        if error_message:
            if total > 0:
                self.lbl_status.setText(f'Частично: добавлено {total}. Ошибка: {error_message}')
                QMessageBox.warning(
                    self,
                    'Парсинг завершён с ошибкой',
                    f'{error_message}\n\nУспешно добавлено контактов: {total}',
                )
            else:
                self.lbl_status.setText(f'Ошибка: {error_message}')
                QMessageBox.warning(self, 'Парсинг завершён с ошибкой', error_message)
        else:
            self.lbl_status.setText(f'Готово. Добавлено: {total}')
            if total == 0:
                hints = [
                    'Новых контактов не найдено.',
                    'Проверьте фильтры: "Только активные", "Исключить ботов", "Исключить админов".',
                    'Если контакты уже есть в базе, счетчик новых будет 0.',
                ]
                if self._last_mode == 'basic':
                    hints.append('Для чатов со скрытыми участниками включите "Глубокий сбор".')
                QMessageBox.information(self, 'Парсинг завершен', '\n'.join(hints))
            else:
                QMessageBox.information(
                    self,
                    'Успех',
                    f'Парсинг завершен.\nСобрано новых контактов: {total}',
                )

        self.refresh_table()

        if isinstance(finished_worker, QThread):
            try:
                finished_worker.deleteLater()
            except Exception as delete_err:
                logging.getLogger('CRMTab').debug(f'Failed to delete finished worker: {delete_err}')
        self.worker = None

    def shutdown(self, timeout_ms: int = 15000):
        if self.worker is None:
            return

        if self.worker.isRunning():
            logging.getLogger('CRMTab').info('Stopping parsing worker on shutdown')
            self.worker.stop()
            if not self.worker.wait(timeout_ms):
                logging.getLogger('CRMTab').warning(f'Parsing worker did not stop within {timeout_ms} ms')

        try:
            self.worker.deleteLater()
        except Exception as delete_err:
            logging.getLogger('CRMTab').debug(f'Failed to delete parsing worker on shutdown: {delete_err}')
        self.worker = None

    def closeEvent(self, event):
        self.shutdown(timeout_ms=15000)
        super().closeEvent(event)

    @staticmethod
    def _same_db_path(first: Path, second: Path) -> bool:
        try:
            return Path(first).resolve() == Path(second).resolve()
        except Exception:
            return str(Path(first)) == str(Path(second))

    @staticmethod
    def _database_entry_label(entry: Dict[str, Any]) -> str:
        name = str(entry.get('display_name') or 'База')
        tag = str(entry.get('tag') or '').strip()
        contacts = int(entry.get('contacts_total') or 0)
        if tag:
            return f'{name} [{tag}] • {contacts}'
        return f'{name} • {contacts}'

    def _clear_db_feedback(self):
        self.lbl_db_feedback.setVisible(False)
        self.lbl_db_feedback.setText('')

    def _show_db_feedback(self, text: str, success: bool = True, timeout_ms: int = 2600):
        prefix = '✓' if success else '⚠'
        color = '#2e7d32' if success else '#a06500'
        self.lbl_db_feedback.setText(f'{prefix} {text}')
        self.lbl_db_feedback.setStyleSheet(f'color: {color};')
        self.lbl_db_feedback.setVisible(True)
        self._db_feedback_timer.start(timeout_ms)

    def refresh_db_info(self):
        db_path = getattr(self.db_manager, 'db_path', None)
        db_label = self.db_manager.display_name_for_path(Path(db_path)) if db_path else '-'
        try:
            tag = self.db_manager.get_database_tag()
        except Exception:
            tag = ''
        tag_text = f' | Тег: {tag}' if tag else ''
        self.lbl_db_info.setText(f'Активная база: {db_label}{tag_text}')
        if self.input_db_tag.text().strip() != tag:
            self.input_db_tag.setText(tag)

    def refresh_database_list(self):
        # macOS Qt/Cocoa can crash if model updates happen while popup selection is active.
        if self.combo_db_selector.view().isVisible():
            QTimer.singleShot(150, self.refresh_database_list)
            return

        current_path = Path(getattr(self.db_manager, 'db_path', Path('')))
        entries = self.db_manager.list_internal_databases()

        self._db_selector_refreshing = True
        self.combo_db_selector.blockSignals(True)
        try:
            self.combo_db_selector.clear()

            selected_index = 0
            if not entries:
                self.combo_db_selector.addItem('Нет доступных баз', '')
            else:
                for idx, entry in enumerate(entries):
                    path_text = str(entry.get('path') or '')
                    self.combo_db_selector.addItem(self._database_entry_label(entry), path_text)
                    if path_text and self._same_db_path(Path(path_text), current_path):
                        selected_index = idx

            if self.combo_db_selector.count() > 0:
                safe_index = min(max(selected_index, 0), self.combo_db_selector.count() - 1)
                self.combo_db_selector.setCurrentIndex(safe_index)
        finally:
            self.combo_db_selector.blockSignals(False)
            self._db_selector_refreshing = False

    def _switch_database_by_path(
        self,
        selected_path: Path,
        *,
        show_feedback: bool = True,
        refresh_selector: bool = True,
    ):
        if self._same_db_path(selected_path, Path(self.db_manager.db_path)):
            self.refresh_db_info()
            if show_feedback:
                self._show_db_feedback('Эта база уже активна', success=True)
            return

        self.db_manager.switch_database(selected_path)
        self.refresh_table()
        self.refresh_db_info()
        if refresh_selector:
            self.refresh_database_list()
        if show_feedback:
            self._show_db_feedback(
                f'Открыта: {self.db_manager.display_name_for_path(selected_path)}',
                success=True,
            )

    def _on_db_selector_changed(self, _index: int):
        if self._db_selector_refreshing:
            return

        selected_path = str(self.combo_db_selector.currentData() or '').strip()
        if not selected_path:
            return

        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, 'Парсинг выполняется', 'Остановите парсинг перед переключением базы.')
            return

        try:
            self._switch_database_by_path(
                Path(selected_path),
                show_feedback=True,
                refresh_selector=False,
            )
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Не удалось открыть базу: {e}')

    def _ask_database_name(self, title: str, label: str, default_text: str = '') -> Optional[str]:
        text, ok = QInputDialog.getText(self, title, label, text=default_text)
        if not ok:
            return None
        name = str(text or '').strip()
        if not name:
            QMessageBox.warning(self, 'Название базы', 'Введите название базы.')
            return None
        return name

    def save_database_tag(self):
        tag = self.input_db_tag.text().strip()
        try:
            self.db_manager.set_database_tag(tag)
            self.refresh_db_info()
            self.refresh_database_list()
            self._show_db_feedback('Тег базы сохранён', success=True)
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Не удалось сохранить тег базы: {e}')

    def create_new_database(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, 'Парсинг выполняется', 'Остановите парсинг перед созданием новой базы.')
            return

        default_name = f'База {datetime.now().strftime("%d.%m.%Y %H:%M")}'
        db_name = self._ask_database_name('Новая база', 'Название новой базы:', default_text=default_name)
        if not db_name:
            return

        tag = self.input_db_tag.text().strip() or None
        try:
            new_path = self.db_manager.create_empty_internal_database(db_name, tag=tag)
            self._switch_database_by_path(new_path, show_feedback=False)
            self._show_db_feedback(f'Создана новая база: {db_name}', success=True)
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Не удалось создать новую базу: {e}')

    def save_database_as_new(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, 'Парсинг выполняется', 'Остановите парсинг перед сохранением копии базы.')
            return

        current_name = self.db_manager.display_name_for_path(Path(self.db_manager.db_path))
        default_name = f'{current_name} копия'
        db_name = self._ask_database_name('Сохранить как', 'Название новой базы-копии:', default_text=default_name)
        if not db_name:
            return

        tag = self.input_db_tag.text().strip() or None
        try:
            cloned_path = self.db_manager.duplicate_to_internal_database(db_name, tag=tag)
            self._switch_database_by_path(cloned_path, show_feedback=False)
            self._show_db_feedback(f'Сохранена копия: {db_name}', success=True)
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Не удалось сохранить копию базы: {e}')

    def _toggle_column_visible(self, column: int, visible: bool):
        model = self.table_view.model()
        if model is None:
            return
        if not visible:
            visible_columns = sum(1 for i in range(model.columnCount()) if not self.table_view.isColumnHidden(i))
            if visible_columns <= 1:
                QMessageBox.warning(self, 'Столбцы', 'Нельзя скрыть все столбцы.')
                return
        self.table_view.setColumnHidden(column, not visible)

    def show_columns_menu(self, pos=None):
        model = self.table_view.model()
        if model is None:
            return

        menu = QMenu(self)
        for col in range(model.columnCount()):
            header_value = model.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            title = str(header_value or f'Колонка {col + 1}')
            action = menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(not self.table_view.isColumnHidden(col))
            action.triggered.connect(lambda checked, c=col: self._toggle_column_visible(c, checked))

        if isinstance(pos, QPoint):
            global_pos = self.table_view.horizontalHeader().mapToGlobal(pos)
        else:
            global_pos = self.btn_columns.mapToGlobal(self.btn_columns.rect().bottomLeft())
        menu.exec(global_pos)

    def refresh_table(self):
        status_data = self.combo_status_filter.currentData()
        status = str(status_data) if isinstance(status_data, str) and status_data else None

        header = self.table_view.horizontalHeader()
        header_state = header.saveState()
        hidden_columns: List[bool] = []
        model_before = self.table_view.model()
        if model_before is not None:
            for idx in range(model_before.columnCount()):
                hidden_columns.append(self.table_view.isColumnHidden(idx))

        data = self.db_manager.get_leads(status_filter=status, limit=2000)
        self.table_model = LeadsTableModel(data, parent=self.table_view)
        self.table_view.setModel(self.table_model)
        if header_state:
            header.restoreState(header_state)
        for idx, hidden in enumerate(hidden_columns):
            if idx < self.table_model.columnCount():
                self.table_view.setColumnHidden(idx, hidden)

        stats = self.db_manager.get_stats()
        total = stats.get('TOTAL', 0)
        status_labels = {
            LEAD_STATUS_NEW: 'Новые',
            LEAD_STATUS_IN_PROGRESS: 'В работе',
            LEAD_STATUS_SENT: 'Отправлено',
            LEAD_STATUS_ERROR: 'Ошибка',
            LEAD_STATUS_ARCHIVED: 'В архиве',
        }
        detail_parts = []
        for key in [LEAD_STATUS_NEW, LEAD_STATUS_IN_PROGRESS, LEAD_STATUS_SENT, LEAD_STATUS_ERROR, LEAD_STATUS_ARCHIVED]:
            if key in stats:
                detail_parts.append(f'{status_labels.get(key, key)}: {stats[key]}')

        details = ', '.join(detail_parts)
        self.lbl_stats.setText(f'Всего: {total}' + (f' ({details})' if details else ''))
        self.refresh_db_info()

    def clear_database(self):
        reply = QMessageBox.question(
            self,
            'Подтверждение',
            'Вы уверены? Это удалит всю базу контактов и историю статусов.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db_manager.clear_database()
            self.refresh_table()

    def _get_filtered_data_for_export(self) -> List[Dict[str, Any]]:
        status_data = self.combo_status_filter.currentData()
        status = str(status_data) if isinstance(status_data, str) and status_data else None
        return self.db_manager.get_leads(status_filter=status, limit=100000)

    def export_to_csv(self):
        data = self._get_filtered_data_for_export()
        if not data:
            QMessageBox.warning(self, 'Ошибка', 'Нет данных для экспорта')
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            'Сохранить CSV',
            'leads_export.csv',
            'CSV (*.csv)',
        )
        if not path:
            return

        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=list(data[0].keys()))
                writer.writeheader()
                writer.writerows(data)
            QMessageBox.information(self, 'Успех', f'Экспортировано {len(data)} контактов в {path}')
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Не удалось сохранить CSV: {e}')

    def export_to_excel(self):
        data = self._get_filtered_data_for_export()
        if not data:
            QMessageBox.warning(self, 'Ошибка', 'Нет данных для экспорта')
            return

        try:
            from openpyxl import Workbook
        except Exception:
            QMessageBox.critical(
                self,
                'Ошибка',
                'Для экспорта Excel требуется openpyxl. Установите зависимость и повторите.',
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            'Сохранить Excel',
            'leads_export.xlsx',
            'Excel (*.xlsx)',
        )
        if not path:
            return
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'

        try:
            wb = Workbook()
            ws = wb.active
            ws.title = 'Контакты'

            headers = list(data[0].keys())
            ws.append(headers)
            for row in data:
                ws.append([row.get(h) for h in headers])

            wb.save(path)
            QMessageBox.information(self, 'Успех', f'Экспортировано {len(data)} контактов в {path}')
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Не удалось сохранить Excel: {e}')

    def _choose_accounts_for_broadcast(self) -> Optional[List[str]]:
        if not self.accounts_data:
            self.reload_accounts()
        dialog = BroadcastAccountsDialog(self.accounts_data, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        sessions = dialog.selected_sessions()
        if not sessions:
            QMessageBox.warning(self, 'Аккаунты не выбраны', 'Отметьте минимум один аккаунт для рассылки.')
            return None
        return sessions

    def broadcast_selected(self):
        model = self.table_view.model()
        if model is None:
            QMessageBox.warning(self, 'Ошибка', 'Таблица пуста')
            return

        selection_model = self.table_view.selectionModel()
        if selection_model is None:
            QMessageBox.warning(self, 'Ошибка', 'Не удалось получить выделение таблицы')
            return

        indexes = selection_model.selectedRows()
        if not indexes:
            QMessageBox.warning(self, 'Ошибка', 'Выберите контакты для рассылки')
            return

        selected_rows: List[Tuple[int, str, str]] = []  # user_id, username, status
        for idx in indexes:
            user_id = model.data(model.index(idx.row(), 0))
            username = model.data(model.index(idx.row(), 1))
            status = model.data(model.index(idx.row(), 3))

            if not user_id:
                continue

            try:
                uid = int(user_id)
            except (TypeError, ValueError):
                logging.getLogger('CRMTab').warning(f'Invalid user_id in table model: {user_id!r}')
                continue
            uname = (username or '').strip()
            st = (status or '').strip()
            selected_rows.append((uid, uname, st))

        if not selected_rows:
            QMessageBox.warning(self, 'Ошибка', 'Не удалось прочитать выбранные строки')
            return

        selected_ids = [uid for uid, _u, _s in selected_rows]
        sendable_ids, blocked_map = self.db_manager.filter_sendable_leads(selected_ids)
        sendable_id_set = set(sendable_ids)

        sendable_pairs: List[Tuple[str, int]] = []
        for uid, uname, _st in selected_rows:
            if uid not in sendable_id_set:
                continue
            if uname:
                sendable_pairs.append((uname, uid))

        sendable_usernames = [username for username, _uid in sendable_pairs]
        ordered_sendable_ids = [uid for _username, uid in sendable_pairs]

        if not sendable_usernames:
            if blocked_map:
                blocked_info = ', '.join(f'{uid}:{status}' for uid, status in blocked_map.items())
                QMessageBox.warning(self, 'Недоступно для отправки', f'Все выбранные лиды заблокированы по статусу ({blocked_info})')
            else:
                QMessageBox.warning(self, 'Ошибка', 'У выбранных лидов отсутствует юзернейм')
            return

        selected_sessions = self._choose_accounts_for_broadcast()
        if selected_sessions is None:
            return

        if not self.broadcast_callback:
            from PyQt6.QtGui import QGuiApplication

            clipboard = QGuiApplication.clipboard()
            clipboard.setText('\n'.join(sendable_usernames))
            QMessageBox.information(
                self,
                'Ручной режим',
                f'Скопировано {len(sendable_usernames)} юзернеймов в буфер обмена.\n'
                'Подключите обработчик рассылки для автоматического режима.',
            )
            return

        try:
            try:
                callback_result = self.broadcast_callback(sendable_usernames, ordered_sendable_ids, selected_sessions)
            except TypeError:
                callback_result = self.broadcast_callback(sendable_usernames, ordered_sendable_ids)
        except Exception as e:
            logging.getLogger('CRMTab').exception(f'Broadcast callback crashed: {e}')
            QMessageBox.warning(self, 'Рассылка не запущена', f'Ошибка модуля рассылки: {e}')
            return
        success = False
        info_message = ''

        if isinstance(callback_result, tuple):
            success = bool(callback_result[0])
            info_message = str(callback_result[1]) if len(callback_result) > 1 else ''
        else:
            success = bool(callback_result)

        if not success:
            QMessageBox.warning(self, 'Рассылка не запущена', info_message or 'Не удалось передать лиды в модуль рассылки')
            return

        self.refresh_table()

        blocked_count = len(blocked_map)
        extra = f'\nПропущено (SENT/IN_PROGRESS/ARCHIVED): {blocked_count}' if blocked_count else ''
        QMessageBox.information(
            self,
            'Успех',
            f'Передано в рассылку: {len(ordered_sendable_ids)} контактов.{extra}',
        )
