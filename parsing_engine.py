import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Set
from urllib.parse import urlparse

from pyrogram import Client, enums
from pyrogram.errors import RPCError
from pyrogram.types import User

from database_manager import DatabaseManager


class ParsingEngineError(RuntimeError):
    def __init__(self, message: str, partial_count: int = 0):
        super().__init__(message)
        self.partial_count = partial_count


class ParsingEngine:
    def __init__(self, client: Client, db_manager: DatabaseManager):
        self.client = client
        self.db = db_manager
        self.logger = logging.getLogger('ParsingEngine')
        self._stop_flag = False

    def stop(self):
        """Signal to stop the current parsing operation."""
        self._stop_flag = True

    @staticmethod
    def _normalize_target_url(url_value: str) -> str:
        parsed = urlparse(url_value.strip())
        host = parsed.netloc.lower()
        if host.startswith('www.'):
            host = host[4:]
        if host not in ('t.me', 'telegram.me'):
            return url_value.strip()

        path = parsed.path.strip('/')
        if not path:
            return url_value.strip()

        if path.startswith('c/'):
            parts = path.split('/')
            if len(parts) >= 2 and parts[1].isdigit():
                return f'-100{parts[1]}'

        if path.startswith('joinchat/') or path.startswith('+'):
            invite_path = path
            if parsed.query:
                invite_path = f'{invite_path}?{parsed.query}'
            return f'https://t.me/{invite_path}'

        username = path.split('/')[0]
        if username:
            return f"@{username.lstrip('@')}"
        return url_value.strip()

    @classmethod
    def _normalize_target_input(cls, target_link: str) -> str:
        target = target_link.strip()
        if not target:
            return ''

        lower = target.lower()
        if lower.startswith('https://') or lower.startswith('http://'):
            return cls._normalize_target_url(target)

        if (
            lower.startswith('t.me/')
            or lower.startswith('telegram.me/')
            or lower.startswith('www.t.me/')
            or lower.startswith('www.telegram.me/')
        ):
            return cls._normalize_target_url(f'https://{target}')

        if target.startswith('@'):
            return target

        if target.startswith('-100') and target[4:].isdigit():
            return target

        if target.isdigit():
            return f'-100{target}'

        return f'@{target.lstrip("@")}'

    async def _resolve_chat(self, target_link: str):
        normalized = self._normalize_target_input(target_link)
        if not normalized:
            raise ParsingEngineError('Пустая ссылка/идентификатор чата', partial_count=0)

        # For invite links we may need to join first.
        if normalized.startswith('https://t.me/joinchat/') or normalized.startswith('https://t.me/+'):
            try:
                join_result = await self.client.join_chat(normalized)
                return join_result, normalized
            except Exception as join_err:
                self.logger.warning(f'join_chat failed for invite {normalized}: {join_err}')
                chat = await self.client.get_chat(normalized)
                return chat, normalized

        chat = await self.client.get_chat(normalized)
        return chat, normalized

    @staticmethod
    def _parse_date_bounds(filter_config: Dict[str, Any]) -> tuple[Optional[datetime], Optional[datetime]]:
        raw_from = str(filter_config.get('date_from_iso') or '').strip()
        raw_to = str(filter_config.get('date_to_iso') or '').strip()
        if not raw_from or not raw_to:
            return None, None

        date_from = datetime.fromisoformat(raw_from).replace(hour=0, minute=0, second=0, microsecond=0)
        date_to = datetime.fromisoformat(raw_to).replace(hour=23, minute=59, second=59, microsecond=999999)
        return date_from, date_to

    @staticmethod
    def _match_boundary_timezone(boundary: datetime, message_date: datetime) -> datetime:
        if message_date.tzinfo is None:
            if boundary.tzinfo is not None:
                return boundary.astimezone(boundary.tzinfo).replace(tzinfo=None)
            return boundary.replace(tzinfo=None)
        if boundary.tzinfo is None:
            return boundary.replace(tzinfo=message_date.tzinfo)
        return boundary.astimezone(message_date.tzinfo)

    async def get_chat_members_basic(
        self,
        target_link: str,
        filter_config: Dict[str, Any],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> int:
        """Basic parsing: iterate over visible chat members."""
        self._stop_flag = False
        active_within_days = int(filter_config.get('active_within_days', 7) or 7)

        try:
            chat, source_target = await self._resolve_chat(target_link)
            self.logger.info(f'Starting basic parsing for: {getattr(chat, "title", source_target)} ({chat.id})')
        except RPCError as e:
            self.logger.error(f'Error getting chat {target_link}: {e}')
            if progress_callback:
                progress_callback(0, 0, f'Ошибка чата: {e}')
            raise ParsingEngineError(f'Не удалось открыть чат {target_link}: {e}', partial_count=0) from e

        scanned = 0
        added = 0

        try:
            async for member in self.client.get_chat_members(chat.id):
                if self._stop_flag:
                    self.logger.info('Basic parsing stopped by user')
                    break

                scanned += 1
                if progress_callback and scanned % 20 == 0:
                    progress_callback(scanned, added, f'Проверено {scanned} участников')

                user = member.user
                if not user:
                    continue

                if self._skip_user(user, filter_config, active_within_days):
                    continue

                if filter_config.get('exclude_admins', False):
                    if member.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
                        continue

                if self._upsert_user(user, source_chat=source_target):
                    added += 1

            self.db.log_parsing_session(source_target, added)
            return added

        except Exception as e:
            self.logger.error(f'Error in basic parsing: {e}')
            if progress_callback:
                progress_callback(scanned, added, f'Ошибка: {e}')
            hint = ''
            err_l = str(e).lower()
            if 'admin' in err_l or 'participant' in err_l or 'forbidden' in err_l:
                hint = ' Для чатов со скрытыми участниками используйте "Глубокий парсинг".'
            raise ParsingEngineError(f'Базовый парсинг прерван: {e}.{hint}', partial_count=added) from e

    async def deep_parsing(
        self,
        target_link: str,
        days_limit: int,
        filter_config: Dict[str, Any],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> int:
        """Deep parsing: scans chat history and extracts active speakers."""
        self._stop_flag = False
        active_within_days = int(filter_config.get('active_within_days', days_limit) or days_limit or 7)

        try:
            chat, source_target = await self._resolve_chat(target_link)
            self.logger.info(f'Starting deep parsing for: {getattr(chat, "title", source_target)} ({chat.id})')
        except RPCError as e:
            self.logger.error(f'Error getting chat {target_link}: {e}')
            if progress_callback:
                progress_callback(0, 0, f'Ошибка чата: {e}')
            raise ParsingEngineError(f'Не удалось открыть чат {target_link}: {e}', partial_count=0) from e

        try:
            date_from_bound, date_to_bound = self._parse_date_bounds(filter_config)
        except Exception as date_err:
            raise ParsingEngineError(f'Неверный формат диапазона дат: {date_err}', partial_count=0) from date_err

        admin_ids: Set[int] = set()
        if filter_config.get('exclude_admins', False):
            admin_ids = await self._get_admin_ids(chat.id)

        scanned_msgs = 0
        added_users = 0
        seen_ids: Set[int] = set()
        skipped_no_user = 0
        skipped_filtered = 0

        try:
            async for message in self.client.get_chat_history(chat.id):
                if self._stop_flag:
                    self.logger.info('Deep parsing stopped by user')
                    break

                scanned_msgs += 1
                if progress_callback and scanned_msgs % 50 == 0:
                    progress_callback(scanned_msgs, added_users, f'Сканирую сообщения: {scanned_msgs}')

                message_date = message.date
                if message_date and date_to_bound is not None:
                    if message_date > self._match_boundary_timezone(date_to_bound, message_date):
                        continue
                if message_date and date_from_bound is not None:
                    if message_date < self._match_boundary_timezone(date_from_bound, message_date):
                        self.logger.info('Reached lower date boundary in deep parsing')
                        break
                elif self._is_message_older_than_limit(message_date, days_limit):
                    self.logger.info('Reached date limit in deep parsing')
                    break

                user = message.from_user
                if not user:
                    skipped_no_user += 1
                    continue

                if user.id in seen_ids:
                    continue
                seen_ids.add(user.id)

                if user.id in admin_ids:
                    continue

                if self._skip_user(
                    user,
                    filter_config,
                    active_within_days,
                    message_date=message_date,
                    message_window_days=days_limit,
                ):
                    skipped_filtered += 1
                    continue

                if self._upsert_user(user, source_chat=source_target):
                    added_users += 1

            if progress_callback and added_users == 0:
                progress_callback(
                    scanned_msgs,
                    added_users,
                    f'0 добавлено: без автора={skipped_no_user}, отфильтровано={skipped_filtered}',
                )
            self.db.log_parsing_session(source_target, added_users)
            return added_users

        except Exception as e:
            self.logger.error(f'Deep parsing error: {e}')
            if progress_callback:
                progress_callback(scanned_msgs, added_users, f'Ошибка: {e}')
            raise ParsingEngineError(f'Глубокий парсинг прерван: {e}', partial_count=added_users) from e

    async def _get_admin_ids(self, chat_id: int) -> Set[int]:
        admin_ids: Set[int] = set()
        try:
            chat_members_filter = getattr(enums, 'ChatMembersFilter', None)
            administrators_filter = getattr(chat_members_filter, 'ADMINISTRATORS', None) if chat_members_filter else None

            if administrators_filter is None:
                self.logger.warning('ChatMembersFilter.ADMINISTRATORS is unavailable in this Pyrogram version')
                return admin_ids

            async for member in self.client.get_chat_members(chat_id, filter=administrators_filter):
                if member.user:
                    admin_ids.add(member.user.id)

            self.logger.info(f'Deep parsing admin exclusion loaded: {len(admin_ids)} admins')
        except Exception as e:
            self.logger.warning(f'Could not fetch admin list for deep parsing: {e}')

        return admin_ids

    @staticmethod
    def _is_message_older_than_limit(message_date: Optional[datetime], days_limit: int) -> bool:
        if not message_date:
            return False
        if message_date.tzinfo is not None:
            cutoff = datetime.now(message_date.tzinfo) - timedelta(days=days_limit)
        else:
            cutoff = datetime.now() - timedelta(days=days_limit)
        return message_date < cutoff

    def _skip_user(
        self,
        user: User,
        filter_config: Dict[str, Any],
        active_within_days: int,
        message_date: Optional[datetime] = None,
        message_window_days: Optional[int] = None,
    ) -> bool:
        if not user:
            return True

        if filter_config.get('exclude_bots', True) and getattr(user, 'is_bot', False):
            return True

        # Exclude deleted accounts from CRM quality baseline
        if getattr(user, 'is_deleted', False):
            return True

        if filter_config.get('only_active', True):
            # Для deep parsing сам факт сообщения в пределах окна already означает "активен".
            if message_date is not None and filter_config.get('absolute_date_range', False):
                pass
            elif message_date is not None and message_window_days and not self._is_message_older_than_limit(message_date, message_window_days):
                pass
            elif not self._is_user_active(user, active_within_days=active_within_days):
                return True

        return False

    def _upsert_user(self, user: User, source_chat: str) -> bool:
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username = f'@{user.username}' if user.username else None
        last_online = str(getattr(user, 'last_online_date', None) or '') or None

        return self.db.add_lead(
            user_id=user.id,
            username=username,
            full_name=full_name,
            source_chat=source_chat,
            status='NEW',
            last_online=last_online,
        )

    def _is_user_active(self, user: User, active_within_days: int = 7) -> bool:
        """A pragmatic 'active recently' check matching lead quality requirements."""
        status = getattr(user, 'status', None)

        allowed_statuses = {
            getattr(enums.UserStatus, 'ONLINE', None),
            getattr(enums.UserStatus, 'RECENTLY', None),
        }
        if active_within_days >= 7:
            allowed_statuses.add(getattr(enums.UserStatus, 'LAST_WEEK', None))
        if active_within_days >= 30:
            allowed_statuses.add(getattr(enums.UserStatus, 'LAST_MONTH', None))

        if status in allowed_statuses:
            return True

        # Fallback to explicit last_online timestamp when available
        last_online = getattr(user, 'last_online_date', None)
        if last_online:
            if last_online.tzinfo is not None:
                now = datetime.now(last_online.tzinfo)
            else:
                now = datetime.now()
            return (now - last_online) <= timedelta(days=active_within_days)

        return False
