import asyncio
import json
import sys
from pathlib import Path
from pyrogram import Client, errors
from pyrogram.raw.functions.messages import UpdateDialogFilter
from pyrogram.raw.types import DialogFilter

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

TARGET_PHONES = [
    "79934561930", # Account 1
    # "79604480575", # Account 2 (Already has them, verify?) Let's skip to be safe/fast, or check?
                     # User said Account 2 is fine, but re-checking won't hurt if check logic is good.
                     # Let's include all new accounts to be sure.
    "79604480575",
    "79081733172", # Account 3
    "79612987814", # Account 4
    "79043408274"  # Account 5
]

async def process_account(account, invites_data):
    phone = account['phone'].replace('+','').replace(' ','')
    if phone not in TARGET_PHONES: return

    print(f"\n=== Processing: {account['name']} ({phone}) ===")
    session_path = USER_DATA_DIR / 'sessions' / phone
    
    async with Client(str(session_path), api_id=account['api_id'], api_hash=account['api_hash']) as client:
        
        # Get existing filters to properly manage IDs
        try:
            from pyrogram.raw.functions.messages import GetDialogFilters
            existing_filters = await client.invoke(GetDialogFilters())
            existing_ids = {f.id for f in existing_filters if hasattr(f, 'id')}
            existing_titles = {f.title for f in existing_filters if hasattr(f, 'title')}
        except:
            existing_ids = set()
            existing_titles = set()
            
        next_id = 2
        while next_id in existing_ids: next_id += 1

        for folder_title, links in invites_data.items():
            print(f"  Folder: {folder_title}")
            
            # 1. Join Chats
            folder_input_peers = []
            
            for item in links:
                link = item['link']
                title = item['title']
                
                try:
                    # Check if already joined (resolve via ID if possible? No, we don't have ID mapping for this user yet)
                    # Just try join_chat. Pyrogram handles "already joined" gracefully usually returning the chat.
                    
                    # But join_chat with link might return Chat or ChatInviteLink
                    print(f"    Joining '{title}'...")
                    joined = await client.join_chat(link)
                    
                    # Get InputPeer
                    peer = await client.resolve_peer(joined.id)
                    folder_input_peers.append(peer)
                    await asyncio.sleep(2)
                    
                except errors.UserAlreadyParticipant:
                    print(f"    Already in '{title}'")
                    # We need to resolve it to add to folder
                    # Since we are participant, get_chat should work?
                    # But we don't have ID easily unless we parse link or saved it.
                    # We saved ID in invites.json! But that ID is from Admin perspective. 
                    # IDs are global for channels/supergroups. So we can try get_chat(id).
                    try:
                        chat = await client.get_chat(item['id'])
                        peer = await client.resolve_peer(chat.id)
                        folder_input_peers.append(peer)
                    except Exception as e:
                        print(f"    Could not resolve '{title}' after already joined: {e}")

                except errors.FloodWait as e:
                    print(f"    FloodWait {e.value}s...")
                    await asyncio.sleep(e.value)
                    # Retry once
                    try:
                        joined = await client.join_chat(link)
                        peer = await client.resolve_peer(joined.id)
                        folder_input_peers.append(peer)
                    except: pass
                    
                except Exception as e:
                    print(f"    ❌ Error joining '{title}': {e}")

            if not folder_input_peers:
                print(f"    ⚠️ No chats available for folder '{folder_title}'. Skipping creation.")
                continue
                
            # 2. Create/Update Folder
            if folder_title in existing_titles:
                print(f"    ℹ️ Folder '{folder_title}' already exists. Updating...")
                # Find ID
                fid = next((f.id for f in existing_filters if hasattr(f, 'title') and f.title == folder_title), None)
                if fid:
                    target_id = fid
                else:
                    target_id = next_id
                    next_id += 1
            else:
                print(f"    Creating folder '{folder_title}'...")
                target_id = next_id
                next_id += 1
                while next_id in existing_ids: next_id += 1

            # Build Filter
            new_filter = DialogFilter(
                id=target_id,
                title=folder_title,
                pinned_peers=[],
                include_peers=folder_input_peers,
                exclude_peers=[],
                contacts=False, non_contacts=False, groups=False, broadcasts=False, bots=False,
                exclude_muted=False, exclude_read=False, exclude_archived=False,
                emoticon=None
            )
            
            try:
                await client.invoke(UpdateDialogFilter(id=target_id, filter=new_filter))
                print(f"    ✅ Folder '{folder_title}' configured successfully.")
            except Exception as e:
                print(f"    ❌ Error saving folder '{folder_title}': {e}")
                
            await asyncio.sleep(1)

async def main():
    # Load invites
    if not Path("invites.json").exists():
        print("invites.json not found!")
        return
        
    with open("invites.json", "r", encoding="utf-8") as f:
        invites_data = json.load(f)

    # Load accounts
    accounts_path = USER_DATA_DIR / 'accounts.json'
    with open(accounts_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)

    for acc in accounts:
        await process_account(acc, invites_data)

if __name__ == '__main__':
    # Silence pyrogram logger
    import logging
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())



