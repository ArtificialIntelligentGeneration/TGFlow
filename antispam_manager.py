import time
import threading
import logging
from typing import Dict, Optional, Tuple, Any
from pathlib import Path
import json
from datetime import datetime

from app_paths import USER_DATA_DIR


class AntiSpamManager:
    """Manages anti-spam strategies for Telegram broadcasting.

    Handles:
    - PeerFlood pause strategy
    - @SpamBot integration
    - Adaptive FloodWait pauses
    - Account pause/resume logic
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize AntiSpamManager with configuration.

        Args:
            config: Dictionary with antispam settings
        """
        # PeerFlood settings
        self.peerflood_pause_minutes = config.get('peerflood_pause_minutes', 30)
        self.peerflood_max_pause_hours = config.get('peerflood_max_pause_hours', 24)  # Safety cap
        self.spambot_auto_start = config.get('spambot_auto_start', False)
        self.spambot_delay_seconds = config.get('spambot_delay_seconds', 10)
        self.spambot_max_tries = config.get('spambot_max_tries', 3)

        # FloodWait settings
        self.floodwait_adaptive = config.get('floodwait_adaptive', False)
        self.floodwait_base_seconds = config.get('floodwait_base_seconds', 60)
        self.floodwait_max_multiplier = config.get('floodwait_max_multiplier', 5)
        self.floodwait_max_pause_seconds = config.get('floodwait_max_pause_seconds', 1800)  # 30 min safety cap

        # State management
        self.paused_accounts: Dict[str, Dict] = {}  # account_name -> pause_info
        self.floodwait_multipliers: Dict[str, float] = {}  # account_name -> current_multiplier
        self.active_spambot_checks: Dict[str, threading.Thread] = {}  # account_name -> thread

        # Logging
        self.logger = logging.getLogger(__name__)

    def handle_peerflood(self, account_name: str, client: Any, log_callback: callable) -> None:
        """Handle PeerFlood error with pause strategy and optional @SpamBot integration.

        Args:
            account_name: Name of the account that got PeerFlood
            client: Pyrogram client instance
            log_callback: Function to emit log messages
        """
        pause_until = time.time() + (self.peerflood_pause_minutes * 60)

        self.paused_accounts[account_name] = {
            'until': pause_until,
            'reason': 'PeerFlood',
            'paused_at': time.time()
        }

        log_callback(f"<span style='color:orange'>{account_name}: ❌ PEER_FLOOD → пауза {self.peerflood_pause_minutes} мин</span>")

        if self.spambot_auto_start:
            # Start @SpamBot check in background thread
            if account_name not in self.active_spambot_checks:
                thread = threading.Thread(
                    target=self._run_spambot_check,
                    args=(account_name, client, log_callback),
                    daemon=True,
                    name=f"SpamBot-{account_name}"
                )
                self.active_spambot_checks[account_name] = thread
                thread.start()
                log_callback(f"<span style='color:blue'>{account_name}: 🤖 @SpamBot запущен для снятия ограничений...</span>")
        else:
            log_callback(f"<span style='color:orange'>{account_name}: ⏳ Ожидание {self.peerflood_pause_minutes} мин (автозапуск @SpamBot отключен)</span>")

    def _run_spambot_check(self, account_name: str, client: Any, log_callback: callable) -> None:
        """Run @SpamBot interaction to remove restrictions.

        Args:
            account_name: Account name
            client: Pyrogram client
            log_callback: Log callback function
        """
        try:
            # Initial delay before starting @SpamBot
            time.sleep(self.spambot_delay_seconds)
            log_callback(f"<span style='color:blue'>{account_name}: 🤖 Начинаем проверку @SpamBot...</span>")

            for attempt in range(self.spambot_max_tries):
                try:
                    # Send /start to @SpamBot
                    client.send_message('@SpamBot', '/start')
                    log_callback(f"<span style='color:blue'>{account_name}: 🤖 Отправлена команда /start боту (попытка {attempt + 1})</span>")

                    # Wait for response
                    time.sleep(3)

                    # Get recent messages from @SpamBot
                    try:
                        chat = client.get_chat('@SpamBot')
                        messages = client.get_chat_history('@SpamBot', limit=5)

                        # Analyze last message
                        last_message = None
                        for msg in messages:
                            if msg.from_user and msg.from_user.username == 'SpamBot':
                                last_message = msg
                                break

                        if last_message and last_message.text:
                            response_text = last_message.text.lower()
                            log_callback(f"<span style='color:blue'>{account_name}: 🤖 Ответ @SpamBot: {last_message.text[:100]}...</span>")

                            # Check for restriction removal indicators
                            if any(phrase in response_text for phrase in [
                                'ограничений нет', 'no restrictions', 'good to go',
                                'можно отправлять', 'you can send', 'unrestricted'
                            ]):
                                # Restrictions removed - remove pause
                                if account_name in self.paused_accounts:
                                    del self.paused_accounts[account_name]
                                log_callback(f"<span style='color:green'>{account_name}: ✅ @SpamBot: ограничения сняты, аккаунт активирован</span>")
                                return
                            elif any(phrase in response_text for phrase in [
                                'ограничения', 'restrictions', 'wait', 'подождите'
                            ]):
                                # Still restricted, continue waiting
                                log_callback(f"<span style='color:orange'>{account_name}: ⏳ @SpamBot: ограничения еще активны, продолжаем ожидание</span>")
                            else:
                                log_callback(f"<span style='color:orange'>{account_name}: ❓ @SpamBot: неясный ответ, продолжаем ожидание</span>")
                        else:
                            log_callback(f"<span style='color:orange'>{account_name}: ❓ @SpamBot: нет ответа от бота</span>")

                    except Exception as e:
                        log_callback(f"<span style='color:orange'>{account_name}: ⚠️ Ошибка чтения ответа @SpamBot: {str(e)}</span>")

                    # Wait between attempts (except last)
                    if attempt < self.spambot_max_tries - 1:
                        delay = 30 + (attempt * 15)  # Progressive delay: 30s, 45s, 60s
                        log_callback(f"<span style='color:blue'>{account_name}: ⏳ Ожидание {delay}с перед следующей проверкой @SpamBot...</span>")
                        time.sleep(delay)

                except Exception as e:
                    log_callback(f"<span style='color:orange'>{account_name}: ⚠️ Ошибка взаимодействия с @SpamBot (попытка {attempt + 1}): {str(e)}</span>")
                    if attempt < self.spambot_max_tries - 1:
                        time.sleep(10)  # Short delay before retry

            # All attempts failed
            log_callback(f"<span style='color:orange'>{account_name}: ⚠️ @SpamBot: не удалось снять ограничения после {self.spambot_max_tries} попыток, продолжаем паузу</span>")

        except Exception as e:
            log_callback(f"<span style='color:red'>{account_name}: ❌ Критическая ошибка @SpamBot: {str(e)}</span>")
        finally:
            # Clean up thread reference
            self.active_spambot_checks.pop(account_name, None)

    def get_adaptive_floodwait(self, account_name: str, base_wait: int) -> Tuple[int, str]:
        """Calculate adaptive FloodWait pause.

        Args:
            account_name: Account name
            base_wait: Base wait time from FloodWait error

        Returns:
            Tuple of (adapted_wait_seconds, explanation_string)
        """
        if not self.floodwait_adaptive:
            return base_wait, f"базовая пауза {base_wait}s"

        # Get or initialize multiplier for this account
        multiplier = self.floodwait_multipliers.get(account_name, 1.0)

        # Calculate adapted wait
        adapted_wait = min(base_wait * multiplier, base_wait * self.floodwait_max_multiplier)

        # Apply safety cap (never exceed configured max pause)
        adapted_wait = min(adapted_wait, self.floodwait_max_pause_seconds)

        # Increase multiplier for next time (exponential backoff)
        new_multiplier = min(multiplier * 2.0, self.floodwait_max_multiplier)
        self.floodwait_multipliers[account_name] = new_multiplier

        explanation = f"адаптивная пауза {base_wait}s x{multiplier:.1f} = {adapted_wait:.0f}s (cap: {self.floodwait_max_pause_seconds}s)"

        return int(adapted_wait), explanation

    def is_account_paused(self, account_name: str) -> Tuple[bool, Optional[str]]:
        """Check if account is currently paused.

        Args:
            account_name: Account name to check

        Returns:
            Tuple of (is_paused, reason_or_none)
        """
        if account_name in self.paused_accounts:
            pause_info = self.paused_accounts[account_name]
            if time.time() < pause_info['until']:
                remaining_seconds = int(pause_info['until'] - time.time())
                remaining_minutes = remaining_seconds // 60
                remaining_seconds %= 60
                reason = f"{pause_info['reason']} (осталось {remaining_minutes}:{remaining_seconds:02d})"
                return True, reason
            else:
                # Pause expired, remove it
                del self.paused_accounts[account_name]
                return False, None
        return False, None

    def reset_account_multiplier(self, account_name: str) -> None:
        """Reset FloodWait multiplier for account (on successful send).

        Args:
            account_name: Account name
        """
        self.floodwait_multipliers[account_name] = 1.0

    def force_resume_account(self, account_name: str) -> bool:
        """Force resume a paused account (admin override).

        Args:
            account_name: Account name

        Returns:
            True if account was paused and now resumed, False otherwise
        """
        if account_name in self.paused_accounts:
            del self.paused_accounts[account_name]
            return True
        return False

    def get_pause_status(self) -> Dict[str, Dict]:
        """Get current pause status for all accounts.

        Returns:
            Dict of account_name -> pause_info
        """
        # Clean expired pauses
        current_time = time.time()
        expired = [acc for acc, info in self.paused_accounts.items() if current_time >= info['until']]
        for acc in expired:
            del self.paused_accounts[acc]

        return self.paused_accounts.copy()

    def save_state(self, filepath: Path) -> None:
        """Save current state to file.

        Args:
            filepath: Path to save state file
        """
        state = {
            'paused_accounts': self.paused_accounts,
            'floodwait_multipliers': self.floodwait_multipliers,
            'timestamp': time.time(),
            'version': '1.0'
        }

        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to save antispam state: {e}")

    def load_state(self, filepath: Path) -> bool:
        """Load state from file.

        Args:
            filepath: Path to state file

        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            if not filepath.exists():
                return False

            with open(filepath, 'r', encoding='utf-8') as f:
                state = json.load(f)

            # Validate version
            if state.get('version') != '1.0':
                self.logger.warning("State file version mismatch, ignoring")
                return False

            # Check if state is not too old (max 24 hours)
            timestamp = state.get('timestamp', 0)
            if time.time() - timestamp > 24 * 3600:
                self.logger.info("State file too old, ignoring")
                return False

            self.paused_accounts = state.get('paused_accounts', {})
            self.floodwait_multipliers = state.get('floodwait_multipliers', {})

            # Clean expired pauses
            current_time = time.time()
            expired = [acc for acc, info in self.paused_accounts.items() if current_time >= info['until']]
            for acc in expired:
                del self.paused_accounts[acc]

            self.logger.info(f"Loaded antispam state: {len(self.paused_accounts)} paused accounts")
            return True

        except Exception as e:
            self.logger.error(f"Failed to load antispam state: {e}")
            return False


# Global instance for easy access
_antispam_instance: Optional[AntiSpamManager] = None


def get_antispam_manager(config: Dict[str, Any]) -> AntiSpamManager:
    """Get or create global AntiSpamManager instance.

    Args:
        config: Antispam configuration

    Returns:
        AntiSpamManager instance
    """
    global _antispam_instance
    if _antispam_instance is None:
        _antispam_instance = AntiSpamManager(config)
    return _antispam_instance


def reset_antispam_manager():
    """Reset global AntiSpamManager instance (for testing)."""
    global _antispam_instance
    _antispam_instance = None
