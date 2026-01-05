import sys
import os
import json
import asyncio
import logging
from pathlib import Path
from PyQt6.QtCore import QCoreApplication

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import main after path setup
import main
from app_paths import USER_DATA_DIR
from mini_broadcast import open_client
from pyrogram.raw.functions.messages import GetDialogFilters

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

async def get_chats_from_folders(client, folder_titles):
    print(f"Fetching folders (filters)...")
    try:
        filters = await client.invoke(GetDialogFilters())
    except Exception as e:
        print(f"Error fetching filters: {e}")
        return []

    target_folders = []
    for f in filters:
        if hasattr(f, 'title') and f.title in folder_titles:
            print(f"Found folder: {f.title} (ID: {f.id})")
            target_folders.append(f)
    
    if not target_folders:
        print(f"No matching folders found for: {folder_titles}")
        return []

    print("Fetching dialogs to match against folders...")
    dialogs = []
    me = await client.get_me()
    async for d in client.get_dialogs():
        dialogs.append(d)
    
    print(f"Total dialogs fetched: {len(dialogs)}")
    
    # Debug: Print some dialog IDs to verify format
    print("DEBUG: First 5 dialog IDs:")
    for i, d in enumerate(dialogs[:5]):
        print(f"  {d.chat.id} ({d.chat.type})")
        
    target_chats = set()
    
    for f in target_folders:
        include_ids = set()
        
        # Extract IDs from include_peers
        for p in getattr(f, 'include_peers', []) or []:
             # Debug print
             print(f"DEBUG: Found include peer type: {type(p)}")
             if hasattr(p, 'user_id'): 
                 include_ids.add(p.user_id)
                 print(f"  -> user_id: {p.user_id}")
             elif hasattr(p, 'chat_id'): 
                 # Basic group: -chat_id
                 include_ids.add(-int(p.chat_id))
                 print(f"  -> chat_id: {p.chat_id} (mapped to {-int(p.chat_id)})")
             elif hasattr(p, 'channel_id'): 
                 # Channel/Supergroup: -100{channel_id}
                 # Note: raw ID is positive, Pyrogram ID is -100...
                 peer_id = int(f"-100{p.channel_id}")
                 include_ids.add(peer_id)
                 print(f"  -> channel_id: {p.channel_id} (mapped to {peer_id})")
        
        # Extract IDs from exclude_peers
        exclude_ids = set()
        for p in getattr(f, 'exclude_peers', []) or []:
             if hasattr(p, 'user_id'): exclude_ids.add(p.user_id)
             elif hasattr(p, 'chat_id'): exclude_ids.add(-int(p.chat_id))
             elif hasattr(p, 'channel_id'): exclude_ids.add(int(f"-100{p.channel_id}"))

        inc_contacts = getattr(f, 'include_contacts', False)
        inc_non_contacts = getattr(f, 'include_non_contacts', False)
        inc_groups = getattr(f, 'include_groups', False)
        inc_channels = getattr(f, 'include_broadcasts', False)
        inc_bots = getattr(f, 'include_bots', False)
        
        print(f"Processing folder '{f.title}': includes {len(include_ids)} specific peers")
        print(f"  Flags: contacts={inc_contacts}, non_contacts={inc_non_contacts}, groups={inc_groups}, channels={inc_channels}, bots={inc_bots}")

        for d in dialogs:
            chat = d.chat
            cid = chat.id
            ctype = str(chat.type) # private, group, supergroup, channel, bot? (bot is private usually)
            
            # Check exclusions
            if cid in exclude_ids:
                continue
            
            match = False
            # Explicit inclusion
            if cid in include_ids:
                match = True
            
            # Flags logic
            else:
                is_private = (str(chat.type) == 'ChatType.PRIVATE')
                is_bot = getattr(chat, 'is_bot', False) # Pyrogram Chat object doesn't always have is_bot, need to check how it's exposed
                # actually d.chat.type is an enum.
                
                # Check enum string representation
                type_str = str(chat.type)
                
                # Logic for Private chats and Bots
                if 'PRIVATE' in type_str:
                    if not is_bot:
                        # Assume contact/non-contact logic is hard to check without full contact list, 
                        # but for test we can relax or assume all privates match if flag set
                        if inc_contacts or inc_non_contacts: match = True
                    elif inc_bots:
                         match = True
                
                # Logic for Bots (if ChatType.BOT is used)
                if 'BOT' in type_str and inc_bots:
                    match = True
                
                if ('GROUP' in type_str or 'SUPERGROUP' in type_str) and inc_groups:
                    match = True
                
                if 'CHANNEL' in type_str and inc_channels:
                    match = True
            
            if match:
                username = chat.username or ""
                title = chat.title or chat.first_name or "Unknown"
                address = f"@{username}" if username else str(cid)
                print(f"  -> Added chat: {title} ({address}) from folder '{f.title}'")
                target_chats.add(address) # Use address/ID as recipient string

    return list(target_chats)

async def run_test():
    accounts_path = USER_DATA_DIR / 'accounts.json'
    if not accounts_path.exists():
        print("No accounts.json")
        return

    with open(accounts_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)
        
    if not accounts:
        print("No accounts")
        return
        
    acc = accounts[0]
    print(f"Using account: {acc['name']}")
    
    session_name = str(USER_DATA_DIR / 'sessions' / f"{acc['phone'].replace('+','').replace(' ','')}")
    
    client = open_client(session_name, acc['api_id'], acc['api_hash'])
    if not client.is_connected:
        await client.start()
        
    try:
        target_folders = ["папка1", "папка2", "папка3"]
        recipients = await get_chats_from_folders(client, target_folders)
        
        if not recipients:
            print("No recipients found in specified folders.")
            return

        print(f"Total unique recipients: {len(recipients)}")
        print(recipients)
        
        # Load script content
        script_path = USER_DATA_DIR / 'scripts' / 'Тестовый скрипт.txt'
        if not script_path.exists():
            # Create dummy if not exists
            script_path.parent.mkdir(parents=True, exist_ok=True)
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write("Это тестовый скрипт для рассылки.")
                
        with open(script_path, 'r', encoding='utf-8') as f:
            message_content = f.read()

        acc['recipients'] = recipients
        
        # CLOSE CLIENT BEFORE WORKER STARTS TO AVOID LOCK
        if client.is_connected:
            print("Closing initial client to release session lock...")
            await client.stop()
            # Wait a bit for lock release
            import time
            time.sleep(2.0)
            
        # Manually release file lock if it was attached
        if hasattr(client, '_file_lock'):
            try:
                client._file_lock.release()
                print("Force released file lock")
            except: pass
        
        # Return data to run worker outside of async loop
        return acc, message_content
        
    finally:
        # Client might be closed already
        if client and client.is_connected:
            await client.stop()
            if hasattr(client, '_file_lock'):
                try: client._file_lock.release()
                except: pass

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(run_test())
    except Exception as e:
        print(f"Error in prepare: {e}")
        result = None
    finally:
        loop.close()

    if result:
        acc, message_content = result
        
        # Reset event loop for the worker which might need a fresh one
        # since the previous one was closed
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        
        print("Initializing worker in main thread...")
        
        app = QCoreApplication.instance()
        if not app:
            app = QCoreApplication(sys.argv)

        worker = main.OptimizedBroadcastWorker(
            accounts_info=[acc],
            message=message_content,
            media_files=[],
            inter_wave_delay_min=2.0,
            inter_wave_delay_max=5.0
        )
        
        worker.log.connect(lambda msg: print(f"[LOG] {msg}"))
        worker.progress.connect(lambda val, txt: print(f"[PROG] {val}% {txt}"))
        
        print("Starting broadcast...")
        try:
            worker.run() # Blocking run
        except KeyboardInterrupt:
            print("Interrupted")

