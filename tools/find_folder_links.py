import asyncio
import sys
import datetime
from pathlib import Path
from pyrogram import Client

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

SOURCE_PHONE = "79604487797" # Admin

async def find_folder_links():
    session_path = USER_DATA_DIR / 'sessions' / SOURCE_PHONE
    print(f"Connecting to {SOURCE_PHONE}...")
    
    async with Client(str(session_path)) as app:
        me = await app.get_me()
        print(f"Connected as {me.first_name} ({me.phone_number})")
        
        print("Scanning Saved Messages...")
        folder_links = []
        
        # Scan last 100 messages in Saved Messages (Self)
        async for msg in app.get_chat_history("me", limit=100):
            if not msg.date: continue
            
            # Check date (Jan 2, 2026)
            # Note: Server time might differ slightly, checking loosely around today
            # Or just check content for links.
            
            text = msg.text or msg.caption or ""
            if "t.me/addlist/" in text:
                print(f"Found message from {msg.date}: {text[:50]}...")
                
                # Extract links
                import re
                links = re.findall(r'(https?://t\.me/addlist/[a-zA-Z0-9_-]+)', text)
                for link in links:
                    if link not in folder_links:
                        folder_links.append(link)
                        print(f"  -> Found Link: {link}")
        
        return folder_links

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    links = loop.run_until_complete(find_folder_links())
    
    if links:
        print("\nSUMMARY OF LINKS FOUND:")
        for l in links:
            print(l)
    else:
        print("\nNo folder links found in the last 100 saved messages.")



