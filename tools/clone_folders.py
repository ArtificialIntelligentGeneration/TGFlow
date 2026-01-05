import asyncio
import json
import sys
import time
from pathlib import Path
from pyrogram import Client, errors
from pyrogram.raw.functions.messages import GetDialogFilters, UpdateDialogFilter
from pyrogram.raw.types import DialogFilter, InputPeerEmpty, InputPeerChannel, InputPeerUser, InputPeerChat

import logging

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

# Suppress Pyrogram noise
logging.getLogger("pyrogram").setLevel(logging.WARNING)

# Config
SOURCE_PHONE = "79604487797" # Admin
TARGET_ACCOUNTS_PHONES = [
    "79934561930",
    "79604480575",
    "79081733172",
    "79612987814",
    "79043408274"
]

TARGET_FOLDERS = ["папка1", "папка2", "папка3"]

from pyrogram.raw.functions.channels import GetChannels
from pyrogram.raw.functions.users import GetUsers

async def get_source_folders(client):
    me = await client.get_me()
    print(f"Fetching source folders from {me.phone_number}...")
    try:
        filters = await client.invoke(GetDialogFilters())
        folder_definitions = []
        
        for f in filters:
            if not hasattr(f, 'title'): continue
            if f.title not in TARGET_FOLDERS:
                continue
                
            print(f"  Processing folder: {f.title}")
            
            # Extract usernames/links
            usernames = []
            
            peers = getattr(f, 'include_peers', [])
            for p in peers:
                try:
                    # Use invoke to resolve using InputPeer directly (bypassing cache issues)
                    chat_info = None
                    if hasattr(p, 'channel_id'):
                        # It's a channel/supergroup
                        try:
                            chats_res = await client.invoke(GetChannels(id=[p]))
                            if chats_res.chats:
                                chat_info = chats_res.chats[0]
                        except Exception as e:
                            print(f"    Error getting channel info: {e}")
                    
                    elif hasattr(p, 'user_id'):
                        try:
                            users_res = await client.invoke(GetUsers(id=[p]))
                            if users_res.users:
                                chat_info = users_res.users[0]
                        except Exception as e:
                            print(f"    Error getting user info: {e}")
                            
                    # Check for username in raw object
                    if chat_info:
                        username = getattr(chat_info, 'username', None)
                        if username:
                            print(f"    Found: @{username}")
                            usernames.append(username)
                        else:
                            title = getattr(chat_info, 'title', getattr(chat_info, 'first_name', 'Unknown'))
                            print(f"    Skipping '{title}' (ID: {chat_info.id}) - No username")
                    else:
                        print(f"    Could not resolve info for peer: {p}")
                        
                except errors.FloodWait as e:
                    print(f"    FloodWait {e.value}s fetching chat info...")
                    await asyncio.sleep(e.value)
                except Exception as e:
                    print(f"    Error resolving peer {p}: {e}")
            
            if usernames or getattr(f, 'include_bots', False) or getattr(f, 'include_groups', False) or getattr(f, 'include_broadcasts', False):
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
        print(f"Error fetching source folders: {e}")
        return []

async def apply_folders(client, folder_defs):
    me = await client.get_me()
    print(f"Applying folders to {me.phone_number}...")
    
    # Get existing filters to avoid duplicates or overwrite
    try:
        existing = await client.invoke(GetDialogFilters())
        existing_titles = {f.title for f in existing if hasattr(f, 'title')}
    except:
        existing_titles = set()
    
    next_id = max([f.id for f in existing if hasattr(f, 'id')] + [0]) + 1
    
    for f_def in folder_defs:
        title = f_def['title']
        if title in existing_titles:
            print(f"  Skipping existing folder: {title}")
            continue
            
        print(f"  Creating folder: {title}")
        
        # 1. Join chats
        input_peers = []
        for username in f_def['usernames']:
            try:
                print(f"    Joining @{username}...")
                joined_chat = await client.join_chat(username)
                
                # Get InputPeer
                peer = await client.resolve_peer(joined_chat.id)
                input_peers.append(peer)
                
                await asyncio.sleep(2) # Safety delay
            except errors.UserAlreadyParticipant:
                print(f"    Already joined @{username}")
                # Still need input peer
                try:
                    chat = await client.get_chat(username)
                    peer = await client.resolve_peer(chat.id)
                    input_peers.append(peer)
                except: pass
            except errors.FloodWait as e:
                print(f"    FloodWait {e.value}s during join...")
                await asyncio.sleep(e.value)
                # Retry once
                try:
                    joined_chat = await client.join_chat(username)
                    peer = await client.resolve_peer(joined_chat.id)
                    input_peers.append(peer)
                except: pass
            except Exception as e:
                print(f"    Error joining @{username}: {e}")
        
        # 2. Create Filter
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
            print(f"  ✅ Created folder '{title}'")
            next_id += 1
            await asyncio.sleep(1)
        except Exception as e:
            print(f"  ❌ Failed to create folder '{title}': {e}")

async def main():
    accounts_path = USER_DATA_DIR / 'accounts.json'
    if not accounts_path.exists():
        print("No accounts.json")
        return

    with open(accounts_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)
        
    # Find Source
    source_acc = next((a for a in accounts if a['phone'].replace('+','') == SOURCE_PHONE), None)
    if not source_acc:
        print(f"Source account {SOURCE_PHONE} not found!")
        return

    # Find Targets
    target_accs = [a for a in accounts if a['phone'].replace('+','') in TARGET_ACCOUNTS_PHONES]
    if not target_accs:
        print("No target accounts found!")
        return

    print(f"Source: {source_acc['name']}")
    print(f"Targets: {[a['name'] for a in target_accs]}")
    
    # 1. Read Source
    session_name = str(USER_DATA_DIR / 'sessions' / SOURCE_PHONE)
    print("Connecting to Source...")
    async with Client(session_name, api_id=source_acc['api_id'], api_hash=source_acc['api_hash']) as source_client:
        print("Connected. Fetching folders...")
        folder_defs = await get_source_folders(source_client)
        
    print(f"\nLoaded {len(folder_defs)} folder definitions.")
    if not folder_defs:
        return

    # 2. Apply to Targets
    for acc in target_accs:
        phone = acc['phone'].replace('+','').replace(' ','')
        session_name = str(USER_DATA_DIR / 'sessions' / phone)
        
        print(f"\nProcessing target: {acc['name']} ({phone})...")
        try:
            async with Client(session_name, api_id=acc['api_id'], api_hash=acc['api_hash']) as target_client:
                await apply_folders(target_client, folder_defs)
        except Exception as e:
            print(f"Error processing {acc['name']}: {e}")
            
        print("Waiting 10s before next account...")
        await asyncio.sleep(10)

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())

