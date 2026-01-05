import asyncio
import os
import sys
import json
import re
import time
import random
from pyrogram import Client, errors
from pyrogram.raw.functions.help import GetConfig

# Config
ACCOUNTS_JSON = "/Users/a1/Library/Application Support/TGFlow/accounts.json"
CREDENTIALS_FILE = "accounts_credentials.txt"
CODE_INPUT_FILE = "tools/auth_code.txt"

API_ID = 25740620
API_HASH = "5c9f431a8e61e6f2b42e7ed921529374"
TARGET_USERNAME = "HermannSaliter"

DEVICES = [
    {"model": "iPhone 13 Pro", "system_version": "15.6.1", "app_version": "8.9"},
    {"model": "Samsung S22 Ultra", "system_version": "Android 12", "app_version": "9.1.2"},
    {"model": "Pixel 6", "system_version": "Android 13", "app_version": "9.0.0"}
]

def load_credentials():
    creds = {}
    if not os.path.exists(CREDENTIALS_FILE):
        return creds
    with open(CREDENTIALS_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
    blocks = content.split('Account')
    for block in blocks:
        if not block.strip(): continue
        phone_match = re.search(r'Phone:\s*(\+[\d\s]+)', block)
        pass_match = re.search(r'Password:\s*(.+)', block)
        if phone_match and pass_match:
            phone = phone_match.group(1).replace(' ', '').strip()
            password = pass_match.group(1).strip()
            creds[phone] = password
    return creds

def get_account_info(target_phone):
    with open(ACCOUNTS_JSON, 'r') as f:
        data = json.load(f)
    clean_target = target_phone.replace(' ', '').replace('-', '')
    for acc in data:
        acc_phone = acc['phone'].replace(' ', '').replace('-', '')
        if acc_phone == clean_target:
            return acc
    return None

async def human_delay(min_s=2, max_s=5):
    delay = random.uniform(min_s, max_s)
    print(f"⏳ Waiting {delay:.1f}s...")
    await asyncio.sleep(delay)

async def auth_and_act(target_phone):
    acc = get_account_info(target_phone)
    if not acc:
        print(f"Account {target_phone} not found")
        return

    session_name = acc['session_name']
    creds = load_credentials()
    password = creds.get(acc['phone'].replace(' ', ''))
    device = random.choice(DEVICES)

    print(f"📱 Device: {device['model']}")
    print(f"🔗 Connecting: {acc['phone']}")
    
    if os.path.exists(CODE_INPUT_FILE):
        os.remove(CODE_INPUT_FILE)

    client = Client(
        session_name,
        api_id=API_ID,
        api_hash=API_HASH,
        device_model=device['model'],
        system_version=device['system_version'],
        app_version=device['app_version'],
        lang_code="en"
    )

    await client.connect()
    
    try:
        is_new_login = False
        try:
            me = await client.get_me()
            print(f"✅ Already authorized: {me.first_name}")
        except Exception:
            is_new_login = True
            
        if is_new_login:
            await human_delay(2, 4)
            print(f"📡 Sending code to {acc['phone']}...")
            sent_code = await client.send_code(acc['phone'])
            phone_code_hash = sent_code.phone_code_hash
            print("🕒 WAITING_FOR_CODE_FILE") 
            
            # Wait for code
            code = None
            for i in range(120):
                if os.path.exists(CODE_INPUT_FILE):
                    await asyncio.sleep(0.5)
                    with open(CODE_INPUT_FILE, 'r') as f:
                        code = f.read().strip()
                    if code:
                        print(f"📥 Read code: {code}")
                        break
                await asyncio.sleep(1)
            
            if not code:
                print("❌ Timeout waiting for code")
                return

            print("⌨️  Typing code...")
            await human_delay(3, 6)

            try:
                await client.sign_in(
                    phone_number=acc['phone'],
                    phone_code_hash=phone_code_hash,
                    phone_code=code
                )
                print("✅ Code accepted")
            except errors.SessionPasswordNeeded:
                print("🔐 Password required...")
                await human_delay(3, 5)
                if password:
                    print(f"🔑 Sending password...")
                    await client.check_password(password=password)
                    print("✅ Password accepted")
                else:
                    print("❌ No password found")
                    return

            me = await client.get_me()
            print(f"🎉 Login successful: {me.first_name}")
            
            # CRITICAL: Post-login sync simulation
            print("🔄 Initializing sync (Stay Online 60s)...")
            
            # Request config to look legit
            try:
                await client.invoke(GetConfig())
                print("   - Config fetched")
            except Exception as e:
                print(f"   - Config fetch failed: {e}")
                
            # Simulate reading messages/dialogs
            await asyncio.sleep(10)
            print("   - Syncing dialogs...")
            async for dialog in client.get_dialogs(limit=5):
                pass
            
            # Wait remainder of minute
            print("   - Idling...")
            await asyncio.sleep(40)
            print("✅ Sync complete")

        # --- PERFORM ACTION (Without Disconnecting) ---
        print(f"🚀 Executing Action: Send Message to {TARGET_USERNAME}")
        await human_delay(2, 5)
        
        await client.send_message(TARGET_USERNAME, f"Hello! This is {me.first_name} ({acc['phone']}). I am fully alive!")
        print("✅ Message sent!")
        
        # Stay online a bit more after action
        print("☕ Staying online for another 30s...")
        await asyncio.sleep(30)

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        print("🔌 Disconnecting...")
        await client.disconnect()
        if os.path.exists(CODE_INPUT_FILE):
            os.remove(CODE_INPUT_FILE)

if __name__ == "__main__":
    phone = sys.argv[1]
    asyncio.run(auth_and_act(phone))

