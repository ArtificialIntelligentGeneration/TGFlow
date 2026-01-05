import sys
import os
import json
import asyncio
import logging
import random
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app_paths import USER_DATA_DIR
from pyrogram import Client, errors, enums
from pyrogram.raw.functions.messages import GetDialogFilters

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Silence pyrogram
logging.getLogger("pyrogram").setLevel(logging.WARNING)

TARGET_FOLDERS = ["папка3"] # Test specifically folder 3 (Group 6)

async def get_chats_from_folders(client, folder_titles):
    print(f"[{client.name}] Fetching folders...")
    try:
        filters = await client.invoke(GetDialogFilters())
    except Exception as e:
        print(f"[{client.name}] Error fetching filters: {e}")
        return []

    target_folders = []
    for f in filters:
        if hasattr(f, 'title') and f.title in folder_titles:
            target_folders.append(f)
    
    if not target_folders:
        print(f"[{client.name}] No matching folders found.")
        return []

    print(f"[{client.name}] Fetching dialogs...")
    dialogs = []
    async for d in client.get_dialogs():
        dialogs.append(d)
        
    target_chats = set()
    
    for f in target_folders:
        include_ids = set()
        for p in getattr(f, 'include_peers', []) or []:
             if hasattr(p, 'user_id'): include_ids.add(p.user_id)
             elif hasattr(p, 'chat_id'): include_ids.add(-int(p.chat_id))
             elif hasattr(p, 'channel_id'): include_ids.add(int(f"-100{p.channel_id}"))
        
        for d in dialogs:
            if d.chat.id in include_ids:
                # Use ID as address for reliability
                address = d.chat.id
                target_chats.add(address)

    return list(target_chats)

async def process_broadcast(accounts, message):
    print(f"\n🚀 Starting broadcast for {len(accounts)} accounts")
    
    # Simple sequential broadcast for test (like optimized worker but simpler)
    # 1. Prepare clients
    # 2. Iterate waves
    
    # Just do one pass per account for simplicity of test
    for acc in accounts:
        name = acc['name']
        phone = acc['phone'].replace('+','').replace(' ','')
        recipients = acc.get('recipients', [])
        
        if not recipients:
            print(f"[{name}] No recipients. Skipping.")
            continue
            
        print(f"\n[{name}] Sending to {len(recipients)} chats...")
        session_path = USER_DATA_DIR / 'sessions' / phone
        
        async with Client(str(session_path), api_id=acc['api_id'], api_hash=acc['api_hash']) as client:
            client.name = name
            
            for chat_id in recipients:
                try:
                    await client.send_message(chat_id, message)
                    print(f"  ✅ Sent to {chat_id}")
                    await asyncio.sleep(random.uniform(2, 5))
                except errors.FloodWait as e:
                    print(f"  ⏳ FloodWait {e.value}s")
                    await asyncio.sleep(e.value)
                    try:
                        await client.send_message(chat_id, message)
                        print(f"  ✅ Sent to {chat_id} (after wait)")
                    except Exception as e2:
                        print(f"  ❌ Failed to {chat_id}: {e2}")
                except Exception as e:
                    print(f"  ❌ Failed to {chat_id}: {e}")
        
        print(f"[{name}] Done. Waiting 5s...")
        await asyncio.sleep(5)

async def prepare_and_run():
    accounts_path = USER_DATA_DIR / 'accounts.json'
    if not accounts_path.exists(): return

    with open(accounts_path, 'r', encoding='utf-8') as f:
        all_accounts = json.load(f)
        
    target_phones = ["79934561930", "79604480575", "79081733172", "79612987814", "79043408274"]
    target_accounts = [a for a in all_accounts if a['phone'].replace('+','').replace(' ','') in target_phones]
    
    prepared_accounts = []
    
    # Pre-fetch recipients
    for acc in target_accounts:
        phone = acc['phone'].replace('+','').replace(' ','')
        session_path = USER_DATA_DIR / 'sessions' / phone
        
        # We need to open client to get folders
        async with Client(str(session_path), api_id=acc['api_id'], api_hash=acc['api_hash']) as client:
             client.name = acc['name']
             recipients = await get_chats_from_folders(client, TARGET_FOLDERS)
             if recipients:
                 acc['recipients'] = recipients
                 prepared_accounts.append(acc)
                 print(f"[{acc['name']}] Ready with {len(recipients)} recipients")
    
    if not prepared_accounts:
        print("No accounts ready.")
        return

    message = "Тест папки 3 (Группа 6). Проверка доступа."
    await process_broadcast(prepared_accounts, message)

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(prepare_and_run())
