
import os
import sys
from pathlib import Path

home = Path.home()
scripts_dir = home / 'Library' / 'Application Support' / 'TGFlow' / 'scripts' / 'leads'

files_to_check = ["BusinessOffer.txt", "Тестовый.txt", "Тестовый скрипт.txt"]

for fname in files_to_check:
    fpath = scripts_dir / fname
    if fpath.exists():
        print(f"\n=== CONTENT OF {fname} ===")
        with open(fpath, 'r', encoding='utf-8') as f:
            print(f.read())
        print("=== END CONTENT ===\n")
