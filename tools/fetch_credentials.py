import asyncio
import os
from datetime import datetime
from pyrogram import Client
import json
import re

# Configuration from accounts.json
SESSION_PATH = "/Users/a1/Library/Application Support/TGFlow/sessions/79604487797"
API_ID = "25740620"
API_HASH = "5c9f431a8e61e6f2b42e7ed921529374"

async def main():
    print(f"Connecting to session: {SESSION_PATH}")
    app = Client(
        SESSION_PATH,
        api_id=API_ID,
        api_hash=API_HASH
    )

    found_accounts = []

    async with app:
        me = await app.get_me()
        print(f"Logged in as: {me.first_name} ({me.phone_number})")
        
        print("Scanning Saved Messages...")
        # Saved Messages is "me" or "self"
        async for message in app.get_chat_history("me"):
            if not message.text:
                continue
                
            # Check date (assuming today/recent)
            # Message date is a datetime object
            # User said "Jan 1st", which is today (2026-01-01 in this sim)
            if message.date.year == 2026 and message.date.month == 1 and message.date.day == 1:
                text = message.text
                print(f"--- Message {message.id} ---\n{text}\n----------------")
                found_accounts.append({"text": text, "id": message.id})

    if found_accounts:
        with open("raw_messages.json", "w", encoding="utf-8") as f:
            # simple dump of list of dicts
            import json
            json.dump([m["text"] for m in found_accounts], f, indent=2, ensure_ascii=False)
        print("Saved raw messages to raw_messages.json")

if __name__ == "__main__":
    asyncio.run(main())

