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

# Configure logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("AntispamTest")

# --- CONFIGURATION ---
TEST_USERS_FILE = "test_users.txt"
WAVE_INTERVAL = 60  # Seconds between waves
MESSAGES_PER_ACCOUNT_PER_WAVE = 1
# Placeholder message - will be asked from user or passed as arg
DEFAULT_MESSAGE = "Привет! Это тест проверки связи. Не отвечай, пожалуйста." 

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
        # Strip whitespace and remove backslashes (markdown artifacts)
        lines = [line.strip().replace('\\', '') for line in f if line.strip()]
    
    # Remove duplicates if any, preserving order (User requested keeping duplicates in previous turn, but now logic implies distribution)
    # Wait, user said "даже если они повторяются" (even if they repeat).
    # So we keep duplicates as per instruction.
    return lines

async def run_broadcast(message_text: str):
    accounts_data = await load_accounts()
    if not accounts_data:
        return

    recipients = load_recipients()
    if not recipients:
        logger.error("No recipients found.")
        return

    logger.info(f"Loaded {len(accounts_data)} accounts and {len(recipients)} recipients.")

    # Prepare clients
    clients = []
    for acc in accounts_data:
        phone = acc['phone'].replace('+','').replace(' ','')
        session_path = USER_DATA_DIR / 'sessions' / phone
        
        # Check if session file exists
        if not session_path.with_suffix(".session").exists() and not session_path.exists():
             logger.warning(f"Session for {acc['name']} ({phone}) not found. Skipping.")
             continue
             
        client = Client(
            str(session_path),
            api_id=acc['api_id'],
            api_hash=acc['api_hash']
        )
        client.name = acc['name']
        clients.append(client)

    if not clients:
        logger.error("No valid clients available.")
        return

    logger.info("Starting clients...")
    active_clients = []
    for app in clients:
        try:
            await app.start()
            active_clients.append(app)
            logger.info(f"✅ {app.name} started")
        except Exception as e:
            logger.error(f"❌ Failed to start {app.name}: {e}")
    
    if not active_clients:
        logger.error("No clients started successfully.")
        return

    # Distribute recipients to accounts (Round Robin)
    # We maintain a queue of recipients
    recipient_queue = list(recipients)
    
    wave_num = 1
    
    try:
        while recipient_queue:
            logger.info(f"\n🌊 WAVE {wave_num} START (Remaining: {len(recipient_queue)})")
            
            wave_tasks = []
            
            for client in active_clients:
                if not recipient_queue:
                    break
                
                # Take N recipients for this account for this wave
                targets = []
                for _ in range(MESSAGES_PER_ACCOUNT_PER_WAVE):
                    if recipient_queue:
                        targets.append(recipient_queue.pop(0))
                
                if targets:
                    wave_tasks.append(process_account_wave(client, targets, message_text))

            if not wave_tasks:
                break
                
            # Run wave tasks concurrently
            await asyncio.gather(*wave_tasks)
            
            if recipient_queue:
                logger.info(f"⏳ Waiting {WAVE_INTERVAL}s before next wave...")
                await asyncio.sleep(WAVE_INTERVAL)
                
            wave_num += 1

    except KeyboardInterrupt:
        logger.info("\n🛑 Broadcast stopped by user.")
    finally:
        logger.info("Stopping clients...")
        for app in active_clients:
            await app.stop()
        logger.info("Done.")

async def process_account_wave(client, targets, message):
    for target in targets:
        try:
            await client.send_message(target, message)
            logger.info(f"[{client.name}] -> {target}: ✅ Sent")
            # Small random delay between messages within same wave for same account
            await asyncio.sleep(random.uniform(1, 3)) 
            
        except errors.FloodWait as e:
            logger.warning(f"[{client.name}] -> {target}: 🌊 PEER_FLOOD (Wait {e.value}s)")
            # In a real scenario, we might want to:
            # 1. Wait and retry
            # 2. Skip and return to queue
            # 3. Stop account
            
            # For this test: Wait and retry once
            if e.value < 60:
                await asyncio.sleep(e.value)
                try:
                    await client.send_message(target, message)
                    logger.info(f"[{client.name}] -> {target}: ✅ Sent (after wait)")
                except Exception as retry_e:
                    logger.error(f"[{client.name}] -> {target}: ❌ Failed after wait: {retry_e}")
            else:
                 logger.error(f"[{client.name}] -> {target}: ❌ FloodWait too long ({e.value}s), skipping.")
                 
        except Exception as e:
            logger.error(f"[{client.name}] -> {target}: ❌ Error: {e}")

if __name__ == "__main__":
    msg = DEFAULT_MESSAGE
    if len(sys.argv) > 1:
        msg = sys.argv[1]
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_broadcast(msg))

