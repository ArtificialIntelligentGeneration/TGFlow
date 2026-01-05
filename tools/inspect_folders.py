import asyncio
import json
import sys
from pathlib import Path
from pyrogram import Client
from pyrogram.raw.functions.messages import GetDialogFilters

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

async def list_folders(account):
    print(f"Checking account: {account['name']} ({account['phone']})")
    session_path = USER_DATA_DIR / 'sessions' / f"{account['phone'].replace('+','').replace(' ','')}"
    session_name = str(session_path)
    
    # Simple client open (no locks, assume app closed)
    client = Client(session_name, api_id=account['api_id'], api_hash=account['api_hash'])
    
    try:
        await client.start()
    except Exception as e:
        print(f"  Error starting client: {e}")
        return

    try:
        filters = await client.invoke(GetDialogFilters())
        print(f"  Found {len(filters)} filters:")
        for f in filters:
            if hasattr(f, 'title'):
                print(f"    - Title: {f.title}")
                print(f"      ID: {f.id}")
                
                # Check included peers
                inc_peers = getattr(f, 'include_peers', [])
                print(f"      Includes: {len(inc_peers)} peers")
                
                if inc_peers:
                    # Resolve peers to get usernames
                    try:
                        # Convert InputPeer/Peer to actual entities if possible, or just use get_chat
                        # We need to iterate and fetch info.
                        # This might be slow for many peers, but okay for inspection.
                        for p in inc_peers:
                            peer_id = None
                            if hasattr(p, 'user_id'): peer_id = p.user_id
                            elif hasattr(p, 'channel_id'): peer_id = int(f"-100{p.channel_id}")
                            elif hasattr(p, 'chat_id'): peer_id = -int(p.chat_id)
                            
                            if peer_id:
                                try:
                                    chat = await client.get_chat(peer_id)
                                    print(f"          {chat.type}: {chat.title} | ID: {chat.id} | @{chat.username or 'No Username'}")
                                except Exception as e:
                                    print(f"          Error fetching chat {peer_id}: {e}")
                    except Exception as e:
                         print(f"      Error resolving peers: {e}")

    except Exception as e:
        print(f"  Error fetching filters: {e}")
    finally:
        if client.is_connected:
            await client.stop()

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

    # Check accounts
    target_indices = [0] # Default to admin
    
    if len(sys.argv) > 1:
        if sys.argv[1] == 'all':
            target_indices = range(len(accounts))
        else:
            try:
                target_indices = [int(sys.argv[1])]
            except:
                print(f"Invalid index: {sys.argv[1]}")
                return

    for idx in target_indices:
        if 0 <= idx < len(accounts):
            await list_folders(accounts[idx])
        else:
            print(f"Account index {idx} out of range")

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
