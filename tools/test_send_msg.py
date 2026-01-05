import asyncio
from pyrogram import Client

SESSION = "/Users/a1/Library/Application Support/TGFlow/sessions/79081733172"
API_ID = 25740620
API_HASH = "5c9f431a8e61e6f2b42e7ed921529374"
TARGET_USERNAME = "HermannSaliter"

async def test_send():
    print(f"Connecting to {SESSION}...")
    try:
        app = Client(SESSION, api_id=API_ID, api_hash=API_HASH)
        async with app:
            me = await app.get_me()
            print(f"Logged in as: {me.first_name} {me.last_name or ''}")
            
            print(f"Sending message to {TARGET_USERNAME}...")
            await app.send_message(TARGET_USERNAME, "Test message from TGFlow (Account 3)")
            print("Message sent successfully!")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_send())

