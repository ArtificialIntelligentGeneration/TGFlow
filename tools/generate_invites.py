import asyncio
import json
import sys
from pathlib import Path
from pyrogram import Client
from pyrogram.raw.functions.messages import GetDialogFilters

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

SOURCE_PHONE = "79604487797" # Admin
TARGET_FOLDERS = ["папка1", "папка2", "папка3"]

async def generate_invites():
    session_path = USER_DATA_DIR / 'sessions' / SOURCE_PHONE
    print(f"Connecting to Admin ({SOURCE_PHONE})...")
    
    invites_data = {} # folder_name -> list of invite links
    
    async with Client(str(session_path)) as client:
        filters = await client.invoke(GetDialogFilters())
        
        for f in filters:
            if not hasattr(f, 'title') or f.title not in TARGET_FOLDERS:
                continue
                
            print(f"\nProcessing folder: {f.title}")
            invites_data[f.title] = []
            
            peers = getattr(f, 'include_peers', [])
            for p in peers:
                try:
                    # Resolve peer ID
                    peer_id = None
                    if hasattr(p, 'channel_id'): peer_id = int(f"-100{p.channel_id}")
                    elif hasattr(p, 'chat_id'): peer_id = -int(p.chat_id)
                    
                    if peer_id:
                        chat = await client.get_chat(peer_id)
                        title = chat.title or "Unknown"
                        
                        # Check permissions - can we generate link?
                        # Usually admins can. If not admin, maybe we can't.
                        # Let's try export_chat_invite_link
                        try:
                            link = await client.export_chat_invite_link(peer_id)
                            print(f"  -> Generated link for '{title}': {link}")
                            invites_data[f.title].append({
                                "title": title,
                                "id": peer_id,
                                "link": link
                            })
                        except Exception as e:
                            print(f"  ❌ Could not generate link for '{title}': {e}")
                            
                except Exception as e:
                    print(f"  Error processing peer: {e}")
                    
    # Save to file
    output_path = Path("invites.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(invites_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nSaved invites to {output_path.absolute()}")

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(generate_invites())



