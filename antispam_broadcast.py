import sys
import os
import json
import asyncio
import logging
import random
import argparse
from pathlib import Path
from typing import List, Dict, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app_paths import USER_DATA_DIR
from pyrogram import Client, errors, enums

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("AntispamBroadcast")

DEFAULT_MESSAGE = """Привет, есть места в 2-х бизнес каналах. Каналы каждый день на трафике и на прямом посте. Давайте договоримся на размещение вашего проекта? 

— [INWAYUP | БИЗНЕС](https://t.me/+sA7TFWJHbBU2ZTk6)
— [Бизнес Мысли](https://t.me/+bnKPWXSq9mI5MjQy)"""

async def load_accounts():
    accounts_path = USER_DATA_DIR / 'accounts.json'
    if not accounts_path.exists():
        logger.error(f"accounts.json not found at {accounts_path}")
        return []
    
    with open(accounts_path, 'r', encoding='utf-8') as f:
        return json.load(f)

async def get_client(acc_data):
    phone = acc_data['phone'].replace('+','').replace(' ','')
    session_path = USER_DATA_DIR / 'sessions' / phone
    
    if not session_path.with_suffix(".session").exists() and not session_path.exists():
            return None
            
    client = Client(
        str(session_path),
        api_id=acc_data['api_id'],
        api_hash=acc_data['api_hash']
    )
    client.name = acc_data['name']
    return client

async def run_broadcast_test():
    logger.info("🚀 Starting Broadcast Test to Main Account")
    
    all_accounts = await load_accounts()
    if not all_accounts:
        logger.error("No accounts found.")
        return

    # Identify Senders (Account_1 to Account_5) and Target (HermannSaliter)
    senders_data = []
    target_data = None
    
    for acc in all_accounts:
        if "Account_" in acc['name']:
             senders_data.append(acc)
        else:
             # Assuming any non-Account_X is the main/admin
             if target_data is None: 
                 target_data = acc
    
    # Sort senders to be sure 1-5
    senders_data.sort(key=lambda x: x['name'])
    
    if not target_data:
        logger.error("Could not find Main/Admin account (target).")
        return
    
    logger.info(f"Target Account identified: {target_data['name']}")
    logger.info(f"Sender Accounts ({len(senders_data)}): {[a['name'] for a in senders_data]}")
    
    # 1. Start Target Client to get its Username/ID
    logger.info("Connecting to target account to resolve address...")
    target_client = await get_client(target_data)
    if not target_client:
        logger.error("Target session missing.")
        return
        
    target_username = None
    async with target_client:
        me = await target_client.get_me()
        if me.username:
            target_username = f"@{me.username}"
        else:
            logger.warning(f"Target account {target_data['name']} has no username. Using ID.")
            target_username = me.id # ID might not be sufficient if not in contacts, but worth a try or we use phone import
            
    logger.info(f"Target address: {target_username}")

    # 2. Start Senders and Send
    for acc in senders_data:
        client = await get_client(acc)
        if not client:
            logger.warning(f"Session missing for {acc['name']}")
            continue
            
        try:
            async with client:
                logger.info(f"[{client.name}] Sending...")
                await client.send_message(target_username, DEFAULT_MESSAGE, parse_mode=enums.ParseMode.MARKDOWN, disable_web_page_preview=True)
                logger.info(f"[{client.name}] ✅ Sent successfully")
                
        except errors.FloodWait as e:
            logger.warning(f"[{client.name}] 🌊 FloodWait {e.value}s")
        except Exception as e:
            logger.error(f"[{client.name}] ❌ Error: {e}")
            
        # Delay between accounts
        await asyncio.sleep(random.uniform(2, 4))

    logger.info("Done.")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_broadcast_test())
