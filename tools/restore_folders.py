import asyncio
import json
import sys
from pathlib import Path
from pyrogram import Client
from pyrogram.raw.functions.messages import GetDialogFilters, UpdateDialogFilter
from pyrogram.raw.types import DialogFilter
from pyrogram.raw.functions.channels import GetChannels
from pyrogram.raw.functions.users import GetUsers
from pyrogram import errors

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

# Folders to restore (from previous successful clone)
RESTORE_FOLDERS = [
    "AiGen", 
    "AI Infofield", 
    "Chocopay", # Was on source, maybe restoring? Let's restore all main ones.
    "Рассмотреть", 
    "Depth",
    "Relocate",
    "Students",
    "work",
    "vipee",
    "Клиенты Х",
    "Психология",
    "Бизнес", 
    "Творчество",
    "Чаты",
    "Крипта",
    "ЧП",
    "Биржи"
]

SOURCE_PHONE = "79604487797" # Admin
TARGET_PHONE = "79934561930" # Account 1

async def get_folder_defs(client):
    print(f"Fetching source folders from {SOURCE_PHONE}...")
    try:
        filters = await client.invoke(GetDialogFilters())
        folder_definitions = []
        
        for f in filters:
            if not hasattr(f, 'title'): continue
            if f.title not in RESTORE_FOLDERS:
                continue
                
            print(f"  Processing source folder: {f.title}")
            
            # Extract usernames
            usernames = []
            peers = getattr(f, 'include_peers', [])
            
            for p in peers:
                try:
                    chat_info = None
                    if hasattr(p, 'channel_id'):
                        try:
                            chats_res = await client.invoke(GetChannels(id=[p]))
                            if chats_res.chats: chat_info = chats_res.chats[0]
                        except: pass
                    elif hasattr(p, 'user_id'):
                        try:
                            users_res = await client.invoke(GetUsers(id=[p]))
                            if users_res.users: chat_info = users_res.users[0]
                        except: pass
                            
                    if chat_info:
                        username = getattr(chat_info, 'username', None)
                        if username:
                            usernames.append(username)
                            
                except Exception:
                    pass
            
            folder_definitions.append({
                'title': f.title,
                'usernames': usernames,
                'flags': {
                    'contacts': getattr(f, 'include_contacts', False),
                    'non_contacts': getattr(f, 'include_non_contacts', False),
                    'groups': getattr(f, 'include_groups', False),
                    'broadcasts': getattr(f, 'include_broadcasts', False),
                    'bots': getattr(f, 'include_bots', False),
                    'exclude_muted': getattr(f, 'exclude_muted', False),
                    'exclude_read': getattr(f, 'exclude_read', False),
                    'exclude_archived': getattr(f, 'exclude_archived', False),
                },
                'emoticon': getattr(f, 'emoticon', None)
            })
            
        return folder_definitions
    except Exception as e:
        print(f"Error fetching: {e}")
        return []

async def restore_folders(client, folder_defs):
    print(f"Restoring folders to {TARGET_PHONE}...")
    
    try:
        existing = await client.invoke(GetDialogFilters())
        existing_titles = {f.title for f in existing if hasattr(f, 'title')}
    except:
        existing_titles = set()
    
    # Telegram Filter IDs usually start from 2 or higher (0 and 1 reserved?)
    # But usually we pick ID that is not taken.
    # FILTER_ID_INVALID often means we try to use ID that is too large or not allowed?
    # Or maybe we need to find "holes" in IDs.
    
    existing_ids = {f.id for f in existing if hasattr(f, 'id')}
    next_id = 2
    while next_id in existing_ids:
        next_id += 1
    
    for f_def in folder_defs:
        title = f_def['title']
        if title in existing_titles:
            print(f"  Skipping existing: {title}")
            continue
            
        print(f"  Restoring: {title} ({len(f_def['usernames'])} chats)")
        
        input_peers = []
        for username in f_def['usernames']:
            try:
                # Try to resolve directly first (maybe already joined)
                try:
                    chat = await client.get_chat(username)
                    peer = await client.resolve_peer(chat.id)
                    input_peers.append(peer)
                    continue
                except: pass

                # Join if needed
                joined_chat = await client.join_chat(username)
                peer = await client.resolve_peer(joined_chat.id)
                input_peers.append(peer)
                await asyncio.sleep(1.5)
            except errors.FloodWait as e:
                print(f"    FloodWait {e.value}s...")
                await asyncio.sleep(e.value)
            except Exception as e:
                print(f"    Error {username}: {e}")
        
        # Create Filter
        flags = f_def['flags']
        dialog_filter = DialogFilter(
            id=next_id,
            title=title,
            pinned_peers=[],
            include_peers=input_peers,
            exclude_peers=[],
            contacts=flags['contacts'],
            non_contacts=flags['non_contacts'],
            groups=flags['groups'],
            broadcasts=flags['broadcasts'],
            bots=flags['bots'],
            exclude_muted=flags['exclude_muted'],
            exclude_read=flags['exclude_read'],
            exclude_archived=flags['exclude_archived'],
            emoticon=f_def['emoticon']
        )
        
        try:
            await client.invoke(UpdateDialogFilter(id=next_id, filter=dialog_filter))
            print(f"  ✅ Restored '{title}'")
            next_id += 1
            await asyncio.sleep(1)
        except Exception as e:
            print(f"  ❌ Failed '{title}': {e}")

async def main():
    accounts_path = USER_DATA_DIR / 'accounts.json'
    with open(accounts_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)
        
    source_acc = next((a for a in accounts if a['phone'].replace('+','').replace(' ','') == SOURCE_PHONE), None)
    target_acc = next((a for a in accounts if a['phone'].replace('+','').replace(' ','') == TARGET_PHONE), None)
    
    if not source_acc or not target_acc:
        print("Account not found")
        return

    # Get Defs
    session_source = str(USER_DATA_DIR / 'sessions' / SOURCE_PHONE)
    async with Client(session_source, api_id=source_acc['api_id'], api_hash=source_acc['api_hash']) as sc:
        folder_defs = await get_folder_defs(sc)
        
    if not folder_defs:
        print("No folders found to restore.")
        return

    # Restore
    session_target = str(USER_DATA_DIR / 'sessions' / TARGET_PHONE)
    async with Client(session_target, api_id=target_acc['api_id'], api_hash=target_acc['api_hash']) as tc:
        await restore_folders(tc, folder_defs)

if __name__ == '__main__':
    import logging
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())

