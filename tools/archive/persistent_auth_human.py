import asyncio
import os
import sys
import json
import re
import time
import random
from pyrogram import Client, errors

# Config
ACCOUNTS_JSON = "/Users/a1/Library/Application Support/TGFlow/accounts.json"
CREDENTIALS_FILE = "accounts_credentials.txt"
CODE_INPUT_FILE = "tools/auth_code.txt"

API_ID = 25740620
API_HASH = "5c9f431a8e61e6f2b42e7ed921529374"

# Human-like Device Configs
DEVICES = [
    {"model": "iPhone 13 Pro", "system_version": "15.6.1", "app_version": "8.9"},
    {"model": "Samsung S22 Ultra", "system_version": "Android 12", "app_version": "9.1.2"},
    {"model": "Pixel 6", "system_version": "Android 13", "app_version": "9.0.0"},
    {"model": "MacBook Pro", "system_version": "macOS 12.5", "app_version": "4.2.1 k"},
    {"model": "Desktop", "system_version": "Windows 10", "app_version": "4.3.1 x64"}
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

async def persistent_auth(target_phone):
    acc = get_account_info(target_phone)
    if not acc:
        print(f"Account {target_phone} not found")
        return

    session_name = acc['session_name']
    creds = load_credentials()
    password = creds.get(acc['phone'].replace(' ', ''))

    # Select random device profile to look unique
    device = random.choice(DEVICES)
    print(f"📱 Using device profile: {device['model']}")

    print(f"CONNECTING: {acc['phone']}")
    
    # Ensure code file is clean
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
        # Check if authorized
        try:
            me = await client.get_me()
            print(f"ALREADY_AUTH: {me.first_name}")
            await client.disconnect()
            return
        except Exception:
            pass 

        await human_delay(2, 4)

        print(f"SENDING_CODE: {acc['phone']}")
        sent_code = await client.send_code(acc['phone'])
        phone_code_hash = sent_code.phone_code_hash
        print("WAITING_FOR_CODE_FILE") 
        
        await human_delay(1, 2)

        # Wait loop
        code = None
        for i in range(120):
            if os.path.exists(CODE_INPUT_FILE):
                # Read with small delay to ensure write complete
                await asyncio.sleep(0.5)
                with open(CODE_INPUT_FILE, 'r') as f:
                    code = f.read().strip()
                if code:
                    print(f"READ_CODE: {code}")
                    break
            await asyncio.sleep(1)
            
        if not code:
            print("TIMEOUT_WAITING_CODE")
            return

        # Simulate typing delay
        print("⌨️  Simulating typing...")
        await human_delay(2, 5)

        try:
            await client.sign_in(
                phone_number=acc['phone'],
                phone_code_hash=phone_code_hash,
                phone_code=code
            )
            print("CODE_ACCEPTED")
        except errors.SessionPasswordNeeded:
            print("PASSWORD_NEEDED")
            await human_delay(2, 4)
            
            if password:
                print(f"USING_PASSWORD: {password}")
                await client.check_password(password=password)
                print("PASSWORD_ACCEPTED")
            else:
                print("NO_PASSWORD_FOUND")
                return

        me = await client.get_me()
        print(f"SUCCESS_LOGIN: {me.first_name}")
        
        # Warm up session - don't disconnect immediately
        print("☕ Warming up session (keeping alive for 10s)...")
        await asyncio.sleep(10)
        
        # Maybe check news or something harmless (get_me is enough)
        await client.get_me()

    except Exception as e:
        print(f"ERROR: {e}")
    finally:
        await client.disconnect()
        if os.path.exists(CODE_INPUT_FILE):
            os.remove(CODE_INPUT_FILE)

if __name__ == "__main__":
    phone = sys.argv[1]
    asyncio.run(persistent_auth(phone))

