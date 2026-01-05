import asyncio
import os
import random
from pyrogram import Client, errors

ACCOUNTS_JSON = "/Users/a1/Library/Application Support/TGFlow/accounts.json"
API_ID = 25740620
API_HASH = "5c9f431a8e61e6f2b42e7ed921529374"
TARGET_USERNAME = "HermannSaliter"

async def check_all():
    import json
    with open(ACCOUNTS_JSON, 'r') as f:
        accounts = json.load(f)

    # Filter out main account
    test_accounts = [a for a in accounts if a['name'] != 'HermannSaliter']
    
    print(f"Checking {len(test_accounts)} accounts...")

    for acc in test_accounts:
        phone = acc['phone']
        session_path = acc['session_name'] # Pyrogram adds .session automatically if passing path? No, usually expects session_name
        # If session_name is full path without extension, Pyrogram handles it.
        
        print(f"\n--- Checking {phone} ---")
        if not os.path.exists(f"{session_path}.session"):
            print(f"❌ Session file missing for {phone}")
            continue

        try:
            # We connect, send message, and disconnect carefully
            async with Client(session_path, api_id=API_ID, api_hash=API_HASH) as app:
                me = await app.get_me()
                print(f"✅ Logged in as: {me.first_name}")
                
                msg = f"Ping from {me.first_name} ({phone})"
                await app.send_message(TARGET_USERNAME, msg)
                print(f"✅ Message sent to {TARGET_USERNAME}")
                
                # Small delay to be safe
                await asyncio.sleep(random.uniform(2, 5))
                
        except errors.AuthKeyUnregistered:
             print(f"❌ Session INVALID (Revoked): {phone}")
        except errors.UserDeactivated:
             print(f"❌ User BANNED: {phone}")
        except Exception as e:
             print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_all())

