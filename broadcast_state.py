import json
import time
from pathlib import Path
from typing import Dict, Set, Tuple, Optional
from datetime import datetime

from app_paths import USER_DATA_DIR


class BroadcastState:
    """Manages broadcast session state for resume functionality.

    Tracks:
    - Sent messages (account, recipient) pairs
    - Failed accounts
    - Session metadata
    - Progress information
    """

    def __init__(self, session_id: str, accounts_info: list, message: str):
        """Initialize broadcast state.

        Args:
            session_id: Unique session identifier
            accounts_info: List of account information
            message: Message being sent
        """
        self.session_id = session_id
        self.accounts_info = accounts_info
        self.message = message
        self.start_time = time.time()

        # Progress tracking
        self.sent_messages: Set[Tuple[str, str]] = set()  # (account_name, recipient) pairs
        self.failed_accounts: Set[str] = set()
        self.wave_progress: Dict[str, int] = {}  # account_name -> last_completed_wave_index
        self.total_sent = 0
        self.total_failed = 0

        # Session metadata
        self.last_update = time.time()
        self.version = "1.0"

    def mark_message_sent(self, account_name: str, recipient: str, wave_idx: int):
        """Mark a message as successfully sent.

        Args:
            account_name: Name of the account
            recipient: Recipient identifier
            wave_idx: Wave index (0-based)
        """
        self.sent_messages.add((account_name, recipient))
        self.wave_progress[account_name] = max(self.wave_progress.get(account_name, -1), wave_idx)
        self.total_sent += 1
        self.last_update = time.time()

    def mark_account_failed(self, account_name: str):
        """Mark an account as failed.

        Args:
            account_name: Name of the failed account
        """
        self.failed_accounts.add(account_name)
        self.last_update = time.time()

    def is_message_sent(self, account_name: str, recipient: str) -> bool:
        """Check if a message was already sent.

        Args:
            account_name: Name of the account
            recipient: Recipient identifier

        Returns:
            True if message was already sent
        """
        return (account_name, recipient) in self.sent_messages

    def is_account_failed(self, account_name: str) -> bool:
        """Check if an account has failed.

        Args:
            account_name: Name of the account

        Returns:
            True if account has failed
        """
        return account_name in self.failed_accounts

    def get_resume_wave_start(self, account_name: str) -> int:
        """Get the wave index to resume from for an account.

        Args:
            account_name: Name of the account

        Returns:
            Wave index to start from (0-based)
        """
        last_completed = self.wave_progress.get(account_name, -1)
        return last_completed + 1

    def get_unsent_messages(self, account_name: str, recipients: list) -> list:
        """Get list of recipients that haven't been sent to yet.

        Args:
            account_name: Name of the account
            recipients: Full list of recipients for this account

        Returns:
            List of recipients that haven't received the message yet
        """
        return [recipient for recipient in recipients
                if not self.is_message_sent(account_name, recipient)]

    def get_stats(self) -> Dict:
        """Get current broadcast statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            'session_id': self.session_id,
            'total_sent': self.total_sent,
            'total_failed': self.total_failed,
            'failed_accounts': len(self.failed_accounts),
            'active_accounts': len(self.accounts_info) - len(self.failed_accounts),
            'start_time': datetime.fromtimestamp(self.start_time).strftime('%Y-%m-%d %H:%M:%S'),
            'duration': time.time() - self.start_time,
            'last_update': datetime.fromtimestamp(self.last_update).strftime('%Y-%m-%d %H:%M:%S')
        }

    def save(self, filepath: Optional[Path] = None) -> Path:
        """Save broadcast state to file.

        Args:
            filepath: Optional custom filepath

        Returns:
            Path where state was saved
        """
        if filepath is None:
            states_dir = USER_DATA_DIR / 'broadcast_states'
            states_dir.mkdir(parents=True, exist_ok=True)
            filepath = states_dir / f"{self.session_id}.json"

        state_data = {
            'session_id': self.session_id,
            'accounts_info': self.accounts_info,
            'message': self.message,
            'start_time': self.start_time,
            'sent_messages': list(self.sent_messages),
            'failed_accounts': list(self.failed_accounts),
            'wave_progress': self.wave_progress,
            'total_sent': self.total_sent,
            'total_failed': self.total_failed,
            'last_update': self.last_update,
            'version': self.version
        }

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving broadcast state: {e}")
            raise

        return filepath

    @classmethod
    def load(cls, session_id: str) -> Optional['BroadcastState']:
        """Load broadcast state from file.

        Args:
            session_id: Session identifier

        Returns:
            BroadcastState instance or None if not found
        """
        states_dir = USER_DATA_DIR / 'broadcast_states'
        filepath = states_dir / f"{session_id}.json"

        if not filepath.exists():
            return None

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                state_data = json.load(f)

            # Validate version
            if state_data.get('version') != '1.0':
                print(f"Unsupported state version: {state_data.get('version')}")
                return None

            # Create instance
            instance = cls(
                session_id=state_data['session_id'],
                accounts_info=state_data['accounts_info'],
                message=state_data['message']
            )

            # Restore state
            instance.start_time = state_data['start_time']
            instance.sent_messages = set(tuple(msg) for msg in state_data['sent_messages'])
            instance.failed_accounts = set(state_data['failed_accounts'])
            instance.wave_progress = state_data['wave_progress']
            instance.total_sent = state_data['total_sent']
            instance.total_failed = state_data['total_failed']
            instance.last_update = state_data['last_update']

            return instance

        except Exception as e:
            print(f"Error loading broadcast state: {e}")
            return None

    @classmethod
    def find_resume_candidates(cls) -> list:
        """Find available sessions that can be resumed.

        Returns:
            List of session info dictionaries
        """
        states_dir = USER_DATA_DIR / 'broadcast_states'
        if not states_dir.exists():
            return []

        candidates = []
        for filepath in states_dir.glob("*.json"):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Check if session is recent (not older than 24 hours)
                if time.time() - data.get('last_update', 0) > 24 * 3600:
                    continue

                candidates.append({
                    'session_id': data.get('session_id'),
                    'start_time': data.get('start_time'),
                    'total_sent': data.get('total_sent', 0),
                    'failed_accounts': len(data.get('failed_accounts', [])),
                    'last_update': data.get('last_update'),
                    'message_preview': data.get('message', '')[:50] + '...' if len(data.get('message', '')) > 50 else data.get('message', '')
                })

            except Exception:
                continue

        # Sort by last update time (most recent first)
        candidates.sort(key=lambda x: x['last_update'], reverse=True)
        return candidates

    def cleanup_old_states(self, max_age_hours: int = 24):
        """Clean up old broadcast state files.

        Args:
            max_age_hours: Maximum age in hours for state files
        """
        states_dir = USER_DATA_DIR / 'broadcast_states'
        if not states_dir.exists():
            return

        cutoff_time = time.time() - (max_age_hours * 3600)

        for filepath in states_dir.glob("*.json"):
            try:
                if filepath.stat().st_mtime < cutoff_time:
                    filepath.unlink()
            except Exception:
                continue
