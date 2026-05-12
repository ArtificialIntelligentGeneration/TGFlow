
import sys
import os
from bs4 import BeautifulSoup

# Adjust path to include TGFlow
sys.path.append(os.path.join(os.getcwd(), 'TGFlow'))

try:
    from text_utils import html_to_telegram
except ImportError:
    print("Could not import html_to_telegram")
    sys.exit(1)

def verify():
    # Content from BusinessOffer.txt (simplified for repro)
    # Note the newline between closing </p> and opening <p>
    html_source = """<p>Line 1</p>
<p>Line 2</p>"""
    
    print("=== RAW HTML ===")
    print(repr(html_source))
    
    converted = html_to_telegram(html_source)
    
    print("\n=== CONVERTED ===")
    print(repr(converted))
    
    # We expect 'Line 1\nLine 2', NOT 'Line 1\n\nLine 2'
    if converted == 'Line 1\nLine 2':
        print("\n✅ OK: No extra newline.")
    elif converted == 'Line 1\n\nLine 2':
        print("\n❌ FAIL: Extra newline detected.")
    else:
        print(f"\n❓ UNEXPECTED: {repr(converted)}")

if __name__ == "__main__":
    verify()
