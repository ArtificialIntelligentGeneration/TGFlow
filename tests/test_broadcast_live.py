import sys
import os
import json
import logging
from pathlib import Path
from PyQt6.QtCore import QCoreApplication

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import main after path setup
import main
from app_paths import USER_DATA_DIR
import script_manager

# Configure logging to stdout
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def test_broadcast():
    print("Initializing QCoreApplication...")
    app = QCoreApplication(sys.argv)
    
    accounts_path = USER_DATA_DIR / 'accounts.json'
    if not accounts_path.exists():
        print(f"Error: {accounts_path} not found.")
        return

    print(f"Loading accounts from {accounts_path}...")
    with open(accounts_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)

    if not accounts:
        print("Error: No accounts found.")
        return

    # Use the first account
    test_account = accounts[0]
    print(f"Using account: {test_account.get('name')} ({test_account.get('phone')})")
    
    # Modify recipients to send to specific users for testing
    test_account['recipients'] = ["@zakup2x2", "@zakup2x2", "@zakup2x2"]
    
    # Load script content
    script_name = "Тестовый скрипт.txt"
    print(f"Loading script: {script_name}...")
    try:
        message_content = script_manager.load_script(script_name)
    except FileNotFoundError:
        print(f"Error: Script '{script_name}' not found.")
        return

    # Prepare worker
    print("Creating OptimizedBroadcastWorker...")
    worker = main.OptimizedBroadcastWorker(
        accounts_info=[test_account],
        message=message_content,
        media_files=[],
        inter_wave_delay_min=10.0,
        inter_wave_delay_max=20.0
    )
    
    # Connect signals to stdout
    worker.log.connect(lambda msg: print(f"[WORKER LOG] {msg}"))
    worker.progress.connect(lambda val, txt: print(f"[PROGRESS] {val}%: {txt}"))
    
    print("Starting worker.run()...")
    # Call run directly to execute in main thread (simpler for script)
    # Or start() if we want thread behavior, but then we need app.exec()
    # run() is blocking, which is good for CLI test.
    try:
        worker.run()
    except KeyboardInterrupt:
        print("Interrupted.")
    except Exception as e:
        print(f"Worker Exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_broadcast()

