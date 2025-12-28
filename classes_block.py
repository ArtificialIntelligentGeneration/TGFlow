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


class PrecheckWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    done = pyqtSignal(int, int)

    def __init__(self, accounts_info: list[dict]):
        super().__init__()
        self.accounts_info = accounts_info
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total_ok = 0
        total_fail = 0
        try:
            self.progress.emit(0, "Предпроверка получателей...")
            # Iterate accounts
            for acc_idx, acc in enumerate(self.accounts_info):
                if self._stop:
                    break
                name = acc.get('name', 'account')
                self.log.emit(f"<b>👤 {name}</b>")
                try:
                    cli = open_client(acc['session_name'], acc['api_id'], acc['api_hash'])
                    me = cli.get_me()
                except Exception as e:
                    self.log.emit(f"<span style='color:red'>❌ Не удалось открыть сессию: {e}</span>")
                    total_fail += len(acc.get('recipients', []))
                    continue

                recs = acc.get('recipients', [])
                for i, r in enumerate(recs, start=1):
                    if self._stop:
                        break
                    nr = normalize_recipient(r)
                    target = nr[1:] if nr.startswith('@') else nr
                    try:
                        chat = cli.get_chat(target)
                        # Determine permission
                        can_write = True
                        hint = None
                        try:
                            member = cli.get_chat_member(chat.id, me.id)
                            status = getattr(member, 'status', None)
                            from pyrogram.enums import ChatType as _CT, ChatMemberStatus as _CMS
                            if chat.type == _CT.CHANNEL:
                                can_write = status in (_CMS.ADMINISTRATOR, _CMS.OWNER)
                                if not can_write:
                                    hint = "нет прав публикации"
                            else:
                                if status == _CMS.BANNED:
                                    can_write = False
                                    hint = "бан"
                                elif status == _CMS.RESTRICTED:
                                    perms = getattr(member, 'permissions', None)
                                    allowed = getattr(perms, 'can_send_messages', True) if perms is not None else False
                                    can_write = bool(allowed)
                                    if not can_write:
                                        hint = "ограничение на отправку"
                        except Exception:
                            # If check failed — unknown, but chat exists
                            can_write = True

                        if can_write:
                            total_ok += 1
                            self.log.emit(f"✅ {nr} — OK")
                        else:
                            total_fail += 1
                            self.log.emit(f"<span style='color:orange'>⚠️ {nr} — нет прав ({hint})</span>")
                    except Exception as e:
                        total_fail += 1
                        self.log.emit(f"<span style='color:red'>❌ {nr} — недоступен ({e})</span>")

                # Disconnect client
                try:
                    cli.stop()
                except Exception:
                    try:
                        cli.disconnect()
                    except Exception:
                        pass

                self.progress.emit(int(((acc_idx + 1) / max(1, len(self.accounts_info))) * 100), "...")

        except Exception as e:
            self.log.emit(f"<span style='color:red'>❌ Ошибка предпроверки: {e}</span>")
        finally:
            self.done.emit(total_ok, total_fail)

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

