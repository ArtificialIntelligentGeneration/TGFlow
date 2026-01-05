import asyncio
import os
import sys
import json
import base64
import time
import qrcode
from pyrogram import Client, errors
from pyrogram.raw import functions

# Config
ACCOUNTS_JSON = "/Users/a1/Library/Application Support/TGFlow/accounts.json"
CREDENTIALS_FILE = "accounts_credentials.txt"
API_ID = 25740620
API_HASH = "5c9f431a8e61e6f2b42e7ed921529374"

def get_account_info(target_phone):
    with open(ACCOUNTS_JSON, 'r') as f:
        data = json.load(f)
    clean_target = target_phone.replace(' ', '').replace('-', '')
    for acc in data:
        acc_phone = acc['phone'].replace(' ', '').replace('-', '')
        if acc_phone == clean_target:
            return acc
    return None

def load_password(target_phone):
    if not os.path.exists(CREDENTIALS_FILE):
        return None
    with open(CREDENTIALS_FILE, 'r') as f:
        content = f.read()
    import re
    blocks = content.split('Account')
    for block in blocks:
        phone_match = re.search(r'Phone:\s*(\+[\d\s]+)', block)
        pass_match = re.search(r'Password:\s*(.+)', block)
        if phone_match and pass_match:
            p = phone_match.group(1).replace(' ', '').strip()
            if p == target_phone.replace(' ', ''):
                return pass_match.group(1).strip()
    return None

async def qr_login(target_phone):
    acc = get_account_info(target_phone)
    if not acc:
        print(f"Account {target_phone} not found")
        return

    session_name = acc['session_name']
    password = load_password(acc['phone'])
    
    print(f"Initializing QR Login for {target_phone}...")
    
    client = Client(session_name, api_id=API_ID, api_hash=API_HASH)
    await client.connect()
    
    try:
        try:
            me = await client.get_me()
            print(f"✅ Already authorized: {me.first_name}")
            return
        except Exception:
            pass
            
        print("Requesting QR Token...")
        result = await client.invoke(
            functions.auth.ExportLoginToken(
                api_id=API_ID,
                api_hash=API_HASH,
                except_ids=[]
            )
        )
        
        if isinstance(result, type(None)): 
            print("Error: Got None from ExportLoginToken")
            return

        token_bytes = result.token
        token_b64 = base64.urlsafe_b64encode(token_bytes).decode('utf-8').rstrip('=')
        url = f"tg://login?token={token_b64}"
        
        print("\n" + "="*40)
        print("SCAN THIS QR CODE WITH YOUR PHONE:")
        print("(Settings -> Devices -> Link Desktop Device)")
        print("="*40 + "\n")
        
        qr = qrcode.QRCode()
        qr.add_data(url)
        qr.print_ascii(invert=True)
        
        print(f"\nURL: {url}\n")
        print("Waiting for scan... (Press Ctrl+C to abort)")
        
        start_time = time.time()
        
        while time.time() - start_time < result.expires:
            await asyncio.sleep(2)
            
            try:
                check = await client.invoke(
                    functions.auth.ExportLoginToken(
                        api_id=API_ID,
                        api_hash=API_HASH,
                        except_ids=[]
                    )
                )
            except errors.SessionPasswordNeeded:
                print("\n🔐 2FA Password required!")
                if password:
                    print(f"Sending password: {password}")
                    await client.check_password(password=password)
                    print("✅ Password accepted!")
                    
                    # After password, we need to check if we are truly logged in
                    me = await client.get_me()
                    print(f"\n🎉 SUCCESS! Logged in as {me.first_name} {me.last_name or ''}")
                    return
                else:
                    print("❌ No password found in file.")
                    return
            except Exception as e:
                 # Sometimes polling throws error if session not ready, ignore simple errors
                 # print(f"Poll error: {e}")
                 pass
            
            if hasattr(check, 'authorization'):
                me = check.authorization.user
                print(f"\n🎉 SUCCESS! Logged in as {me.first_name} {me.last_name or ''}")
                return
                
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.disconnect()

if __name__ == "__main__":
    phone = sys.argv[1]
    asyncio.run(qr_login(phone))
