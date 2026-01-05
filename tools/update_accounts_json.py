import json
import os

ACCOUNTS_FILE = "/Users/a1/Library/Application Support/TGFlow/accounts.json"
SESSIONS_DIR = "/Users/a1/Library/Application Support/TGFlow/sessions"

API_ID = "25740620"
API_HASH = "5c9f431a8e61e6f2b42e7ed921529374"

new_accounts = [
    {"phone": "+79934561930", "name": "Account_1"},
    {"phone": "+79604480575", "name": "Account_2"},
    {"phone": "+79081733172", "name": "Account_3"},
    {"phone": "+79612987814", "name": "Account_4"},
    {"phone": "+79043408274", "name": "Account_5"},
]

def main():
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            accounts = json.load(f)
    else:
        accounts = []

    existing_phones = {acc.get('phone') for acc in accounts}

    for new_acc in new_accounts:
        phone = new_acc['phone']
        if phone in existing_phones:
            print(f"Account {phone} already exists. Skipping.")
            continue
        
        # session_name in accounts.json seems to lack extension in the example I saw earlier?
        # Let's check the existing entry.
        # "session_name": "/Users/a1/Library/Application Support/TGFlow/sessions/79604487797"
        # It doesn't have .session extension in the JSON string, Pyrogram adds it.
        
        session_path = os.path.join(SESSIONS_DIR, phone.replace('+', ''))
        account_entry = {
            "api_id": API_ID,
            "api_hash": API_HASH,
            "phone": phone,
            "name": new_acc['name'],
            "session_name": session_path
        }
        accounts.append(account_entry)
        print(f"Added {phone}")

    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)
    print("Updated accounts.json")

if __name__ == "__main__":
    main()

