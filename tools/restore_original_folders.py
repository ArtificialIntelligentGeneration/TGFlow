import asyncio
import json
import sys
import logging
from pathlib import Path
from pyrogram import Client, errors
from pyrogram.raw.functions.messages import UpdateDialogFilter
from pyrogram.raw.types import DialogFilter

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app_paths import USER_DATA_DIR

# Data extracted from log bdd89738...txt
RESTORE_DATA = [
    {
        "title": "Рабочие чаты",
        "usernames": ["market2x2"]
    },
    {
        "title": "Удаленка",
        "usernames": ["rek_oglavnom"]
    },
    {
        "title": "Биржи",
        "usernames": [
            "job_t", "birzha_reklamy2", "trudsmart", "birzha_reklamy22", 
            "obyavleniya_ad", "teIe_work", "vakansii_tg_inst_tt_ut", 
            "twork_jobs", "uslugivtg", "tudasudarabota", "yslugutg",
            "reklama_klk_chat", "ads_sale_group", "tg_chat3", "tgseller4all",
            "fieryTGadmin", "birzha_reklamy5", "tgm_adm", "ebatbirga",
            "birgachat", "Chat_AdminovZ", "reklamakp", "rekwomen", 
            "booklt", "youradvt", "byrzha_reklami2", "AdHotChat"
        ]
    },
    {
        "title": "AiGen",
        "usernames": [
             "AiG_TG_channel", "AiGen_TCA", "AiGen_Bots", "AiGen_Guides",
             "AiGen_Promo", "AiGen_Design", "AiGen_UGC", "AiGen_Review"
        ]
    },
    {
        "title": "AI Infofield",
        "usernames": [
            "dealerAI", "ProductsAndStartups", "neuraldeep", "ai_newz",
            "msvcp60_dll", "oleglimited", "denissexy", "incubeai_pro",
            "seeallochnaya", "evilfreelancer", "c0mmit", "AIexTime",
            "llm_under_hood", "digital_ninjaa"
        ]
    },
    {
        "title": "Рассмотреть",
        "usernames": ["milaaaaaaaaaaaaaaaaaaaaaaam", "sqdworld", "wrld_pxh"]
    },
    {
        "title": "work",
        "usernames": ["vakansii_chatgpt"]
    },
    {
        "title": "vipee",
        "usernames": ["YOURUTNESchat"]
    }
    # Note: "Крипта", "ЧП", "Творчество", "Чаты", "Бизнес", "Клиенты Х", "Психология" 
    # had no resolveable usernames in the log (all errors), so we can't restore content, 
    # but we can try to create empty folders if Telegram allows (it doesn't usually).
]

TARGET_PHONE = "79934561930" # Account 1

async def restore_folders(client):
    print(f"Restoring folders to {TARGET_PHONE}...")
    
    # Get next ID
    try:
        existing = await client.invoke(GetDialogFilters())
        existing_ids = {f.id for f in existing if hasattr(f, 'id')}
        existing_titles = {f.title for f in existing if hasattr(f, 'title')}
    except:
        existing_ids = set()
        existing_titles = set()
    
    next_id = 2
    while next_id in existing_ids:
        next_id += 1
        
    for item in RESTORE_DATA:
        title = item['title']
        usernames = item['usernames']
        
        if title in existing_titles:
            print(f"  Skipping existing: {title}")
            continue
            
        print(f"  Restoring: {title} ({len(usernames)} chats)")
        
        input_peers = []
        for username in usernames:
            try:
                # 1. Resolve/Join
                try:
                    chat = await client.get_chat(username)
                    peer = await client.resolve_peer(chat.id)
                    input_peers.append(peer)
                    continue
                except: pass # Not joined or not found

                print(f"    Joining @{username}...")
                joined_chat = await client.join_chat(username)
                peer = await client.resolve_peer(joined_chat.id)
                input_peers.append(peer)
                await asyncio.sleep(2) # Avoid flood
                
            except errors.FloodWait as e:
                print(f"    FloodWait {e.value}s...")
                await asyncio.sleep(e.value)
            except Exception as e:
                print(f"    Error @{username}: {e}")
        
        if not input_peers:
            print(f"  ⚠️ Skipping '{title}' - no valid chats found/joined.")
            continue

        # Create Filter
        dialog_filter = DialogFilter(
            id=next_id,
            title=title,
            pinned_peers=[],
            include_peers=input_peers,
            exclude_peers=[],
            contacts=False,
            non_contacts=False,
            groups=False,
            broadcasts=False,
            bots=False,
            exclude_muted=False,
            exclude_read=False,
            exclude_archived=False,
            emoticon=None
        )
        
        try:
            await client.invoke(UpdateDialogFilter(id=next_id, filter=dialog_filter))
            print(f"  ✅ Restored '{title}'")
            next_id += 1
            while next_id in existing_ids: next_id += 1
            await asyncio.sleep(1)
        except Exception as e:
            print(f"  ❌ Failed '{title}': {e}")

async def main():
    accounts_path = USER_DATA_DIR / 'accounts.json'
    with open(accounts_path, 'r', encoding='utf-8') as f:
        accounts = json.load(f)
        
    target_acc = next((a for a in accounts if a['phone'].replace('+','').replace(' ','') == TARGET_PHONE), None)
    
    if not target_acc:
        print("Account not found")
        return

    session_target = str(USER_DATA_DIR / 'sessions' / TARGET_PHONE)
    async with Client(session_target, api_id=target_acc['api_id'], api_hash=target_acc['api_hash']) as tc:
        await restore_folders(tc)

if __name__ == '__main__':
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())



