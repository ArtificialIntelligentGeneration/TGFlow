import sys
import os
import json
import asyncio
import logging
import random
from pathlib import Path
from typing import List, Dict, Set

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app_paths import USER_DATA_DIR
from pyrogram import Client, errors, enums

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("AntispamBroadcast")

# --- CONFIGURATION ---
TEST_USERS_FILE = "test_users.txt"
# Random delay between 50 and 70 seconds
DELAY_MIN = 50
DELAY_MAX = 70

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

def load_recipients():
    if not os.path.exists(TEST_USERS_FILE):
        logger.error(f"{TEST_USERS_FILE} not found!")
        return []
    
    with open(TEST_USERS_FILE, 'r', encoding='utf-8') as f:
        # Load lines, strip whitespace, remove backslashes
        lines = [line.strip().replace('\\', '') for line in f if line.strip()]
    
    return lines

async def run_broadcast(message_text: str):
    logger.info("🚀 Starting Distributed Broadcast (5 Groups x 20 Leads)")
    
    # 1. Load Accounts (Filter for Account_1 to Account_5)
    all_accounts = await load_accounts()
    workers = [acc for acc in all_accounts if "Account_" in acc['name']]
    workers.sort(key=lambda x: x['name']) # Ensure 1..5 order
    
    if len(workers) < 5:
        logger.error(f"Need 5 worker accounts, found {len(workers)}.")
        return

    workers = workers[:5] # Take exactly 5
    logger.info(f"Workers: {[w['name'] for w in workers]}")

    # 2. Load Recipients
    recipients = load_recipients()
    if not recipients:
        logger.error("No recipients found.")
        return

    logger.info(f"Total recipients loaded: {len(recipients)}")

    # 3. Distribute into 5 groups of 20
    # User said "groups of 20 leads... should be 5 groups". 
    # 5 * 20 = 100. Our file has 100 lines. Perfect.
    
    groups = []
    chunk_size = 20
    for i in range(0, len(recipients), chunk_size):
        groups.append(recipients[i:i + chunk_size])
    
    # Ensure we have enough groups for workers (or fill with empty)
    while len(groups) < 5:
        groups.append([])
    
    # Assign groups to workers
    assignments = []
    for i, worker in enumerate(workers):
        if i < len(groups):
            assignments.append({
                'worker': worker,
                'targets': groups[i]
            })
            logger.info(f"[{worker['name']}] Assigned {len(groups[i])} leads")

    # 4. Prepare Clients
    clients = []
    for assign in assignments:
        acc = assign['worker']
        phone = acc['phone'].replace('+','').replace(' ','')
        session_path = USER_DATA_DIR / 'sessions' / phone
        
        client = Client(
            str(session_path),
            api_id=acc['api_id'],
            api_hash=acc['api_hash']
        )
        client.name = acc['name']
        # Attach targets to client object for easy access
        client.targets_list = assign['targets'] 
        clients.append(client)

    # 5. Start Clients
    active_clients = []
    for app in clients:
        try:
            await app.start()
            active_clients.append(app)
            logger.info(f"✅ {app.name} started")
        except Exception as e:
            logger.error(f"❌ Failed to start {app.name}: {e}")

    if not active_clients:
        return

    # 6. Execution Loop
    # We want to run them "in parallel" conceptually, but with individual delays?
    # Or synchronized waves?
    # "interval from 50 to 70 seconds" usually implies wait time between messages for EACH account.
    
    tasks = []
    for client in active_clients:
        tasks.append(process_worker_queue(client, message_text))
    
    await asyncio.gather(*tasks)

    # Cleanup
    logger.info("\nStopping clients...")
    for app in active_clients:
        await app.stop()
    logger.info("Done.")

async def process_worker_queue(client, message):
    targets = client.targets_list
    total = len(targets)
    
    for i, target in enumerate(targets):
        try:
            # Check for self-sending block (skip if target is me - unlikely for mass list but good practice)
            # Actually just send.
            
            logger.info(f"[{client.name}] Sending to {target} ({i+1}/{total})...")
            
            await client.send_message(
                target, 
                message, 
                parse_mode=enums.ParseMode.MARKDOWN, 
                disable_web_page_preview=True
            )
            logger.info(f"[{client.name}] ✅ Sent to {target}")
            
        except errors.FloodWait as e:
            logger.warning(f"[{client.name}] 🌊 FloodWait {e.value}s")
            # Simple retry logic: wait and retry once
            if e.value < 300: # Wait up to 5 mins
                logger.info(f"[{client.name}] Waiting {e.value}s...")
                await asyncio.sleep(e.value)
                try:
                    await client.send_message(
                        target, 
                        message, 
                        parse_mode=enums.ParseMode.MARKDOWN, 
                        disable_web_page_preview=True
                    )
                    logger.info(f"[{client.name}] ✅ Sent to {target} (after wait)")
                except Exception as retry_e:
                    logger.error(f"[{client.name}] ❌ Failed retry to {target}: {retry_e}")
            else:
                logger.error(f"[{client.name}] ❌ FloodWait too long, skipping {target}")
                
        except errors.PeerFlood:
            # Specific handling if PeerFlood raises directly without duration
            logger.error(f"[{client.name}] ❌ PEER_FLOOD (Critical limit), stopping worker.")
            return # Stop this worker entirely

        except Exception as e:
            logger.error(f"[{client.name}] ❌ Error to {target}: {e}")

        # Wait before next message (except after the last one)
        if i < total - 1:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            logger.info(f"[{client.name}] ⏳ Waiting {delay:.1f}s...")
            await asyncio.sleep(delay)

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_broadcast(DEFAULT_MESSAGE))

