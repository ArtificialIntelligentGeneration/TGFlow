import asyncio
import json
import sys
from pathlib import Path
from pyrogram import Client
from pyrogram.raw.functions.chatlists import CheckChatlistInvite, JoinChatlistInvite
from pyrogram.raw.types.chatlists import ChatlistInvite, ChatlistInviteAlready
from pyrogram.raw.functions.messages import UpdateDialogFilter
from pyrogram.raw.types import DialogFilter, InputPeerChannel, InputPeerChat, InputPeerUser
from pyrogram import errors

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

FOLDER_LINKS = [
    "https://t.me/addlist/vGr0ISWXRaZiNWVi",
    "https://t.me/addlist/79nRD67fbLI2NWYy",
    "https://t.me/addlist/xYn3_Urr3Bs1ODJi"
]

TARGET_PHONES = [
    "79934561930", # Account 1
    "79604480575", # Account 2
    "79081733172", # Account 3
    "79612987814", # Account 4
    "79043408274"  # Account 5
]

async def join_folders(account):
    phone = account['phone'].replace('+','').replace(' ','')
    if phone not in TARGET_PHONES: return

    print(f"\nProcessing: {account['name']} ({phone})")
    session_path = USER_DATA_DIR / 'sessions' / phone
    
    async with Client(str(session_path), api_id=account['api_id'], api_hash=account['api_hash']) as client:
        for link in FOLDER_LINKS:
            slug = link.split('addlist/')[-1]
            print(f"  -> Processing slug: {slug}")
            
            try:
                # 1. Check Invite
                invite = await client.invoke(CheckChatlistInvite(slug=slug))
                
                if isinstance(invite, ChatlistInviteAlready):
                    print("     ℹ️ Already joined this folder (ChatlistInviteAlready).")
                    continue
                
                if isinstance(invite, ChatlistInvite):
                    title = invite.title
                    print(f"     Folder Title: '{title}'")
                    peers = list(invite.peers)
                    print(f"     Peers in invite: {len(peers)}")
                    
                    # Try joining normally
                    try:
                        await client.invoke(JoinChatlistInvite(slug=slug, peers=peers))
                        print(f"     ✅ Successfully added folder '{title}' via Link")
                    except Exception as e:
                        if "FILTER_INCLUDE_EMPTY" in str(e):
                            print("     ⚠️ FILTER_INCLUDE_EMPTY: Maybe we are already in these chats but folder is missing?")
                            # Fallback: Try to create folder manually with these peers if possible
                            # But invite.peers are 'Peer' objects, we need InputPeers.
                            # We can try to resolve them if we are already members.
                            
                            # Let's check if we can access these chats
                            valid_input_peers = []
                            for p in peers:
                                try:
                                    # Convert Peer to InputPeer
                                    # This requires us to 'know' the peer (have access hash)
                                    # If we are joined, get_chat should work
                                    
                                    peer_id = None
                                    if hasattr(p, 'channel_id'): peer_id = int(f"-100{p.channel_id}")
                                    elif hasattr(p, 'chat_id'): peer_id = -int(p.chat_id)
                                    
                                    if peer_id:
                                        chat = await client.get_chat(peer_id)
                                        input_peer = await client.resolve_peer(chat.id)
                                        valid_input_peers.append(input_peer)
                                        print(f"       Found existing chat: {chat.title}")
                                except Exception as resolve_err:
                                    print(f"       Could not resolve peer {p}: {resolve_err}")
                            
                            if valid_input_peers:
                                print(f"     Creating folder '{title}' manually with {len(valid_input_peers)} chats...")
                                # Get next ID
                                try:
                                    existing = await client.invoke(CheckChatlistInvite(slug=slug)) # Just to check filters? No.
                                    # Actually need GetDialogFilters
                                    from pyrogram.raw.functions.messages import GetDialogFilters
                                    existing_filters = await client.invoke(GetDialogFilters())
                                    ids = {f.id for f in existing_filters if hasattr(f, 'id')}
                                    next_id = 2
                                    while next_id in ids: next_id += 1
                                except: next_id = 50 # Fallback
                                
                                new_filter = DialogFilter(
                                    id=next_id,
                                    title=title,
                                    pinned_peers=[],
                                    include_peers=valid_input_peers,
                                    exclude_peers=[],
                                    contacts=False, non_contacts=False, groups=False, broadcasts=False, bots=False,
                                    exclude_muted=False, exclude_read=False, exclude_archived=False,
                                    emoticon=None
                                )
                                await client.invoke(UpdateDialogFilter(id=next_id, filter=new_filter))
                                print(f"     ✅ Manually created folder '{title}'")
                            else:
                                print("     ❌ Cannot create manual folder: No access to chats.")

                        elif "ALREADY_JOINED" in str(e) or "CHATLIST_JOIN_EXISTS" in str(e):
                             print("     ℹ️ Already joined this folder (RPC Error).")
                        else:
                             print(f"     ❌ Error joining: {e}")
                        
                else:
                    print(f"     ⚠️ Unexpected invite type: {type(invite)}")
                    
            except Exception as e:
                 print(f"     ❌ Error checking invite: {e}")
            
            await asyncio.sleep(2)

async def main():
    accounts_path = USER_DATA_DIR / 'accounts.json'
    with open(accounts_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)

    for acc in accounts:
        await join_folders(acc)

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
