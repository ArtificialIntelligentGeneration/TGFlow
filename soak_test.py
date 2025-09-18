#!/usr/bin/env python3
"""
Soak Test for Anti-Spam Mechanisms

This script validates the anti-spam functionality by simulating various
scenarios that trigger FloodWait, PeerFlood, and other rate limiting behaviors.

Usage:
    python soak_test.py --accounts 2 --messages 50 --delay 1

Options:
    --accounts: Number of test accounts to use (default: 1)
    --messages: Messages per account (default: 10)
    --delay: Base delay between messages in seconds (default: 2)
    --floodwait-test: Enable FloodWait triggering tests
    --peerflood-test: Enable PeerFlood triggering tests
    --adaptive-test: Test adaptive FloodWait behavior
    --spambot-test: Test @SpamBot integration (requires real accounts)
    --duration: Test duration in minutes (default: 30)
"""

import sys
import time
import random
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from antispam_manager import AntiSpamManager
from broadcast_state import BroadcastState


class AntiSpamTester:
    """Tester for anti-spam mechanisms."""

    def __init__(self, config):
        self.config = config
        self.antispam = AntiSpamManager(config)
        self.logger = logging.getLogger(__name__)

        # Test results
        self.results = {
            'floodwait_events': [],
            'peerflood_events': [],
            'adaptive_pauses': [],
            'spambot_interactions': [],
            'state_saves': 0,
            'errors': []
        }

    def simulate_floodwait_scenario(self, account_name: str, base_wait: int = 60):
        """Simulate FloodWait handling."""
        self.logger.info(f"Testing FloodWait for {account_name} with base {base_wait}s")

        # Test basic FloodWait
        adapted_wait, explanation = self.antispam.get_adaptive_floodwait(account_name, base_wait)
        self.results['floodwait_events'].append({
            'account': account_name,
            'base_wait': base_wait,
            'adapted_wait': adapted_wait,
            'explanation': explanation,
            'timestamp': datetime.now().isoformat()
        })

        # Test multiple FloodWaits to see adaptation
        for i in range(3):
            time.sleep(0.1)  # Small delay
            adapted_wait, explanation = self.antispam.get_adaptive_floodwait(account_name, base_wait)
            self.results['adaptive_pauses'].append({
                'account': account_name,
                'iteration': i + 1,
                'adapted_wait': adapted_wait,
                'explanation': explanation,
                'timestamp': datetime.now().isoformat()
            })

        self.logger.info(f"FloodWait test completed for {account_name}")

    def simulate_peerflood_scenario(self, account_name: str):
        """Simulate PeerFlood handling."""
        self.logger.info(f"Testing PeerFlood for {account_name}")

        # Create mock client
        class MockClient:
            def send_message(self, bot_username, command):
                self.logger.info(f"Mock: sending {command} to {bot_username}")
                return True

        mock_client = MockClient()

        # Trigger PeerFlood handling
        self.antispam.handle_peerflood(account_name, mock_client, self.logger.info)

        # Check if account is paused
        is_paused, reason = self.antispam.is_account_paused(account_name)
        self.results['peerflood_events'].append({
            'account': account_name,
            'paused': is_paused,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        })

        self.logger.info(f"PeerFlood test completed for {account_name}")

    def test_broadcast_state_management(self, num_messages: int = 100):
        """Test broadcast state save/load functionality."""
        self.logger.info(f"Testing broadcast state management with {num_messages} messages")

        # Create test broadcast state
        accounts = [{'name': f'account_{i}', 'recipients': [f'user_{j}' for j in range(10)]}
                   for i in range(3)]
        state = BroadcastState('test_session', accounts, 'Test message')

        # Simulate message sending
        for i in range(num_messages):
            account_idx = i % len(accounts)
            account_name = accounts[account_idx]['name']
            recipient = accounts[account_idx]['recipients'][i % len(accounts[account_idx]['recipients'])]
            wave_idx = i // len(accounts)

            state.mark_message_sent(account_name, recipient, wave_idx)

            # Occasionally mark account as failed
            if random.random() < 0.05:  # 5% chance
                state.mark_account_failed(account_name)

        # Save state
        save_path = state.save()
        self.results['state_saves'] += 1

        # Load state
        loaded_state = BroadcastState.load('test_session')
        if loaded_state:
            loaded_stats = loaded_state.get_stats()
            self.logger.info(f"State loaded successfully: {loaded_stats['total_sent']} messages")
        else:
            self.results['errors'].append('Failed to load broadcast state')

        # Cleanup
        try:
            save_path.unlink()
        except:
            pass

    def run_comprehensive_test(self, duration_minutes: int = 30):
        """Run comprehensive soak test."""
        self.logger.info(f"Starting comprehensive soak test for {duration_minutes} minutes")

        end_time = datetime.now() + timedelta(minutes=duration_minutes)
        test_accounts = [f'test_acc_{i}' for i in range(5)]

        while datetime.now() < end_time:
            try:
                # Randomly select test type
                test_type = random.choice(['floodwait', 'peerflood', 'state', 'idle'])

                if test_type == 'floodwait':
                    account = random.choice(test_accounts)
                    base_wait = random.randint(30, 300)
                    self.simulate_floodwait_scenario(account, base_wait)

                elif test_type == 'peerflood':
                    account = random.choice(test_accounts)
                    self.simulate_peerflood_scenario(account)

                elif test_type == 'state':
                    num_messages = random.randint(10, 200)
                    self.test_broadcast_state_management(num_messages)

                # Small delay between tests
                time.sleep(random.uniform(1, 5))

            except Exception as e:
                self.results['errors'].append(str(e))
                self.logger.error(f"Test error: {e}")
                time.sleep(5)  # Longer delay on error

        self.logger.info("Comprehensive soak test completed")

    def generate_report(self):
        """Generate test report."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'config': self.config,
            'results': self.results,
            'summary': {
                'total_floodwait_events': len(self.results['floodwait_events']),
                'total_peerflood_events': len(self.results['peerflood_events']),
                'total_adaptive_pauses': len(self.results['adaptive_pauses']),
                'total_spambot_interactions': len(self.results['spambot_interactions']),
                'total_state_saves': self.results['state_saves'],
                'total_errors': len(self.results['errors'])
            }
        }

        return report


def main():
    parser = argparse.ArgumentParser(description='Anti-Spam Soak Test')
    parser.add_argument('--accounts', type=int, default=1, help='Number of test accounts')
    parser.add_argument('--messages', type=int, default=10, help='Messages per account')
    parser.add_argument('--delay', type=float, default=2.0, help='Base delay between messages')
    parser.add_argument('--floodwait-test', action='store_true', help='Enable FloodWait tests')
    parser.add_argument('--peerflood-test', action='store_true', help='Enable PeerFlood tests')
    parser.add_argument('--adaptive-test', action='store_true', help='Test adaptive behavior')
    parser.add_argument('--spambot-test', action='store_true', help='Test @SpamBot integration')
    parser.add_argument('--state-test', action='store_true', help='Test state management')
    parser.add_argument('--comprehensive', action='store_true', help='Run comprehensive soak test')
    parser.add_argument('--duration', type=int, default=30, help='Test duration in minutes')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Anti-spam configuration
    config = {
        'peerflood_pause_minutes': 30,
        'spambot_auto_start': args.spambot_test,
        'spambot_delay_seconds': 10,
        'spambot_max_tries': 3,
        'floodwait_adaptive': args.adaptive_test,
        'floodwait_base_seconds': 60,
        'floodwait_max_multiplier': 5
    }

    # Create tester
    tester = AntiSpamTester(config)

    try:
        if args.comprehensive:
            tester.run_comprehensive_test(args.duration)
        else:
            # Run individual tests
            if args.floodwait_test:
                for i in range(args.accounts):
                    tester.simulate_floodwait_scenario(f'account_{i}', 60)

            if args.peerflood_test:
                for i in range(args.accounts):
                    tester.simulate_peerflood_scenario(f'account_{i}')

            if args.state_test:
                tester.test_broadcast_state_management(args.messages)

        # Generate and save report
        report = tester.generate_report()

        report_file = Path(f'antispam_soak_report_{int(time.time())}.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            import json
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n📊 Test completed. Report saved to: {report_file}")
        print(f"Summary: {report['summary']}")

    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
