
import re
import html
from bs4 import BeautifulSoup

def _preprocess_html(raw: str) -> str:
    # span font-weight -> b
    raw = re.sub(r"<span[^>]*font-weight:[^>]*>(.*?)</span>", r"<b>\1</b>", raw, flags=re.S | re.I)
    # span font-style -> i
    raw = re.sub(r"<span[^>]*font-style\s*:\s*italic[^>]*>(.*?)</span>", r"<i>\1</i>", raw, flags=re.S | re.I)
    return raw

def html_to_tg_html(raw_html: str) -> str:
    """Converts WYSIWYG HTML to Telegram-supported HTML."""
    raw_html = _preprocess_html(raw_html)
    soup = BeautifulSoup(raw_html, 'html.parser')
    
    def node2html(node) -> str:
        from bs4.element import NavigableString, Tag
        if isinstance(node, NavigableString):
            # ESCAPE plain text so <>& are safe. 
            # * and _ are NOT escaped in HTML mode, so they render literally.
            return html.escape(str(node))
        
        if not isinstance(node, Tag):
            return ''
            
        name = node.name.lower()
        
        if name in ('b', 'strong'):
            inner = ''.join(node2html(c) for c in node.children)
            return f"<b>{inner}</b>"
            
        if name in ('i', 'em'):
            inner = ''.join(node2html(c) for c in node.children)
            return f"<i>{inner}</i>"
            
        if name == 'a':
            href = node.get('href', '')
            inner = ''.join(node2html(c) for c in node.children) or href
            return f'<a href="{href}">{inner}</a>'
            
        if name == 'br':
            return '\n'
            
        if name == 'p':
            inner = ''.join(node2html(c) for c in node.children)
            if not inner.strip():
                return ''
            return inner + '\n'
            
        # div/span etc -> recursive
        return ''.join(node2html(c) for c in node.children)

    res = ''.join(node2html(c) for c in soup.body or soup.children)
    
    # Normalize newlines: 3+ -> 2
    res = re.sub(r'\n{3,}', '\n\n', res)
    return res.strip()

def verify():
    # Test case 1: Business Offer (simple)
    html1 = """
    <p>Привет, есть места.</p>
    <p>Давайте договоримся?<br></p>
    <p><a href="http://example.com">LINK</a></p>
    """
    
    # Test case 2: Torture Test (special chars)
    # User wants *literal* stars to show as stars, unless they used <b>.
    # Note: If user typed *Text* in editor, it is PLAIN TEXT "*Text*".
    # In HTML mode, "<b>Text</b>" -> Bold. "*Text*" -> Literal *Text*. 
    # This solves the ambiguity!
    html2 = """
    <p><b>Bold Text</b></p>
    <p><i>Italic Text</i></p>
    <p>Literal *Stars* and [Brackets]</p>
    <p>Math: 2 < 3 && 5 > 1</p>
    """
    
    print("=== TEST 1 (Business) ===")
    print(html_to_tg_html(html1))
    
    print("\n=== TEST 2 (Torture) ===")
    res2 = html_to_tg_html(html2)
    print(res2)
    
    # Assertions
    assert "&lt;" in res2, "Less than should be escaped"
    assert "<b>Bold Text</b>" in res2
    assert "Literal *Stars*" in res2 # No backslashes!

if __name__ == '__main__':
    verify()
