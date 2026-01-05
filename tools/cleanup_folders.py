import asyncio
import json
import sys
from pathlib import Path
from pyrogram import Client
from pyrogram.raw.functions.messages import GetDialogFilters, UpdateDialogFilter
from pyrogram.raw.types import DialogFilter

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

TARGET_FOLDERS = ["папка1", "папка2", "папка3"]

async def cleanup_folders(account):
    print(f"Checking account: {account['name']} ({account['phone']})")
    session_path = USER_DATA_DIR / 'sessions' / f"{account['phone'].replace('+','').replace(' ','')}"
    session_name = str(session_path)
    
    async with Client(session_name, api_id=account['api_id'], api_hash=account['api_hash']) as client:
        try:
            filters = await client.invoke(GetDialogFilters())
            for f in filters:
                if hasattr(f, 'title') and f.title not in TARGET_FOLDERS:
                    print(f"  Deleting unwanted folder: {f.title} (ID: {f.id})")
                    try:
                        # Deleting a folder is done by updating it with empty filter or specific delete method if available?
                        # Actually UpdateDialogFilter with filter=None might work, or there's a specific call?
                        # Checking UpdateDialogFilter docs usually implies passing filter=None to delete?
                        # No, usually in raw API to delete a filter you typically update existing filters list or use UpdateDialogFilter 
                        # UpdateDialogFilter(id=..., filter=None) usually deletes it.
                        
                        await client.invoke(UpdateDialogFilter(id=f.id, filter=None))
                        print("    Deleted.")
                    except Exception as e:
                        print(f"    Error deleting: {e}")
                        
        except Exception as e:
            print(f"  Error fetching filters: {e}")

async def main():
    accounts_path = USER_DATA_DIR / 'accounts.json'
    if not accounts_path.exists():
        print("No accounts.json found")
        return

    with open(accounts_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)

    if not accounts:
        print("No accounts found")
        return

    # Check only Account 1 for now as that's where we messed up
    target_accs = [a for a in accounts if a['phone'].replace('+','').replace(' ','') == "79934561930"] # Account 1
    
    for acc in target_accs:
        await cleanup_folders(acc)

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())



