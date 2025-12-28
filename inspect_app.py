
import sys
import os
# Mock app_paths to avoid creating dirs/logs if needed, but it should be fine.
from main import TelegramApp

print(f"Checking TelegramApp for load_config...")
if hasattr(TelegramApp, 'load_config'):
    print("SUCCESS: load_config exists.")
else:
    print("FAILURE: load_config NOT found.")
    print("Methods found:", dir(TelegramApp)[-10:])
