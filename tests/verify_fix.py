
import sys
import os

# Adjust path to include TGFlow
sys.path.append(os.path.join(os.getcwd(), 'TGFlow'))

try:
    from text_utils import html_to_telegram
except ImportError:
    print("Could not import html_to_telegram from text_utils.")
    sys.exit(1)

def verify():
    # Note: Source string has newlines between tags. 
    # With the fix, we ignore those source-code newlines.
    # <p> results in inner text + '\n'.
    test_html = """
<p>Hello World</p>
<p>This is a second paragraph.</p>
<p><br></p>
<p>This paragraph contains <b>bold</b> and <i>italic</i> and a <a href="http://google.com">link</a>.</p>
<p>These are specials: * [ ] & < > `</p>
"""
    
    # Expected HTML (Telegram-friendly)
    # <p> -> \n
    # Empty <p><br></p> -> \n\n (Visual gap)
    
    expected_html = (
        "Hello World\n"  # No extra newline
        "This is a second paragraph.\n"
        "\n" # The <br> paragraph adds a newline, plus the previous p ended with \n.
             # Wait. <p><br></p>. node2html -> '\n'. p adds '\n'. Total '\n\n'.
             # Previous p 'Hello World\n' + 'This is...\n' + '\n\n' + 'This paragraph...\n'
        
        "This paragraph contains <b>bold</b> and <i>italic</i> and a <a href=\"http://google.com\">link</a>.\n"
        "These are specials: * [ ] &amp; &lt; &gt; `"
    )
    
    # Let's count explicitly:
    # 1. <p>Hello World</p> -> "Hello World\n"
    #    (Source \n ignored)
    # 2. <p>This is...</p> -> "This is a second paragraph.\n"
    #    (Source \n ignored)
    # 3. <p><br></p> -> inner="\n". + "\n" = "\n\n"
    # 4. <p>This paragraph...</p> -> "This paragraph contains... link</a>.\n"
    # 5. <p>These are...</p> -> "These are specials... `"
    
    # Note: the last p also adds \n, but html_to_telegram does .strip() at the end.
    
    expected_html = (
        "Hello World\n"
        "This is a second paragraph.\n\n"
        "This paragraph contains <b>bold</b> and <i>italic</i> and a <a href=\"http://google.com\">link</a>.\n"
        "These are specials: * [ ] &amp; &lt; &gt; `"
    )
    
    result_html = html_to_telegram(test_html)
    
    print("=== EXPECTED ===")
    print(repr(expected_html))
    print("\n=== RESULT ===")
    print(repr(result_html))
    
    if result_html == expected_html:
        print("\n✅ VERIFICATION PASSED: HTML formatting matches expectation.")
    else:
        print("\n❌ VERIFICATION FAILED: Output does not match expectation.")
        # print differences
        import difflib
        print('\n'.join(difflib.unified_diff(expected_html.splitlines(), result_html.splitlines())))
        sys.exit(1)

if __name__ == "__main__":
    verify()
