import asyncio
import json
import sys
import logging
from pathlib import Path
from pyrogram import Client, errors
from pyrogram.raw.functions.messages import UpdateDialogFilter, GetDialogFilters
from pyrogram.raw.types import DialogFilter

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

TARGET_LINK = "https://t.me/+9qx0NDUIPuZhYjhi"
TARGET_TITLE = "группа6"
TARGET_FOLDER = "папка3"

TARGET_PHONES = [
    "79934561930", # Account 1
    "79604480575", # Account 2
    "79081733172", # Account 3
    "79612987814", # Account 4
    "79043408274"  # Account 5
]

async def fix_folder3(account):
    phone = account['phone'].replace('+','').replace(' ','')
    if phone not in TARGET_PHONES: return

    print(f"\n=== Processing: {account['name']} ({phone}) ===")
    session_path = USER_DATA_DIR / 'sessions' / phone
    
    async with Client(str(session_path), api_id=account['api_id'], api_hash=account['api_hash']) as client:
        
        # 1. Join Chat
        input_peer = None
        try:
            print(f"  Joining '{TARGET_TITLE}'...")
            joined = await client.join_chat(TARGET_LINK)
            input_peer = await client.resolve_peer(joined.id)
            print("  ✅ Joined successfully.")
            
        except errors.UserAlreadyParticipant:
            print("  ℹ️ Already in chat. Resolving...")
            # We need to find the chat to get InputPeer
            # Since we don't have ID easily, and resolving by username is impossible (no username),
            # we check dialogs or try to use the invite link to 'peek' (checkChatInvite)?
            # Or assume we can get it via get_dialogs if we just joined.
            
            found = False
            async for d in client.get_dialogs():
                if d.chat.title == TARGET_TITLE:
                    input_peer = await client.resolve_peer(d.chat.id)
                    found = True
                    break
            
            if not found:
                print("  ⚠️ Already participant but could not find in dialogs. Trying ImportChatInvite to refresh...")
                try:
                    joined = await client.join_chat(TARGET_LINK)
                    input_peer = await client.resolve_peer(joined.id)
                except Exception as e:
                     print(f"  ❌ Could not resolve: {e}")

        except errors.FloodWait as e:
            print(f"  ⏳ FloodWait {e.value}s. Waiting...")
            await asyncio.sleep(e.value)
            try:
                print(f"  Retrying join...")
                joined = await client.join_chat(TARGET_LINK)
                input_peer = await client.resolve_peer(joined.id)
                print("  ✅ Joined successfully (after wait).")
            except Exception as e2:
                print(f"  ❌ Retry failed: {e2}")

        except Exception as e:
            print(f"  ❌ Error joining: {e}")

        if not input_peer:
            print("  ⚠️ Skipping folder creation: No input peer.")
            return

        # 2. Create/Update Folder
        try:
            filters = await client.invoke(GetDialogFilters())
            existing_ids = {f.id for f in filters if hasattr(f, 'id')}
            
            # Check if folder exists
            target_id = None
            for f in filters:
                if hasattr(f, 'title') and f.title == TARGET_FOLDER:
                    target_id = f.id
                    break
            
            if target_id:
                print(f"  Updating existing folder '{TARGET_FOLDER}' (ID: {target_id})...")
            else:
                target_id = 2
                while target_id in existing_ids: target_id += 1
                print(f"  Creating new folder '{TARGET_FOLDER}' (ID: {target_id})...")

            new_filter = DialogFilter(
                id=target_id,
                title=TARGET_FOLDER,
                pinned_peers=[],
                include_peers=[input_peer],
                exclude_peers=[],
                contacts=False, non_contacts=False, groups=False, broadcasts=False, bots=False,
                exclude_muted=False, exclude_read=False, exclude_archived=False,
                emoticon=None
            )
            
            await client.invoke(UpdateDialogFilter(id=target_id, filter=new_filter))
            print(f"  ✅ Folder '{TARGET_FOLDER}' fixed.")
            
        except Exception as e:
            print(f"  ❌ Error saving folder: {e}")

async def main():
    accounts_path = USER_DATA_DIR / 'accounts.json'
    with open(accounts_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)

    for acc in accounts:
        await fix_folder3(acc)
        # Small delay between accounts
        await asyncio.sleep(2)

if __name__ == '__main__':
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())



