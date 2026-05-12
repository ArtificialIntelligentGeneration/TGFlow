
import re
from bs4 import BeautifulSoup

# --- Logic from main.py ---
MD_SPECIALS = ['*', '`', '[', ']']

def _escape_md_main(text: str) -> str:
    link_pattern = r'(\[[^\]]+\]\([^\)]+\))'
    links = []
    def replace_link(match):
        links.append(match.group(0))
        return f'__LINK_PLACEHOLDER_{len(links)-1}__'
    text_with_placeholders = re.sub(link_pattern, replace_link, text)
    specials_re = re.escape(''.join(MD_SPECIALS))
    pattern = fr'(?<!\\)([{specials_re}])'
    escaped_text = re.sub(pattern, r'\\\1', text_with_placeholders)
    for i, link in enumerate(links):
        escaped_text = escaped_text.replace(f'__LINK_PLACEHOLDER_{i}__', link)
    return escaped_text

def _preprocess_html(raw: str) -> str:
    raw = re.sub(r"<span[^>]*font-weight:[^>]*>(.*?)</span>", r"<b>\1</b>", raw, flags=re.S | re.I)
    raw = re.sub(r"<span[^>]*font-style\s*:\s*italic[^>]*>(.*?)</span>", r"<i>\1</i>", raw, flags=re.S | re.I)
    return raw

def html_to_md_main(html: str) -> str:
    html = _preprocess_html(html)
    soup = BeautifulSoup(html, 'html.parser')
    def node2md(node) -> str:
        from bs4.element import NavigableString, Tag
        if isinstance(node, NavigableString):
            return _escape_md_main(str(node))
        if not isinstance(node, Tag):
            return ''
        name = node.name.lower()
        if name in ('b', 'strong'):
            inner = ''.join(node2md(c) for c in node.children)
            return f"*{inner}*"
        if name in ('i', 'em'):
            inner = ''.join(node2md(c) for c in node.children)
            return f"_{inner}_"
        if name == 'a':
            href = node.get('href', '')
            body = ''.join(node2md(c) for c in node.children) or href
            return f"[{body}]({href})"
        if name in ('br',):
            return '\n'
        if name in ('p',):
            inner = ''.join(node2md(c) for c in node.children)
            if not inner.strip(): return ''
            return inner + '\n'
        return ''.join(node2md(c) for c in node.children)

    md = ''.join(node2md(child) for child in soup.body or soup.children)
    md = re.sub(r'\n{3,}', '\n\n', md)
    md = md.strip()
    return md

# --- Logic from mini_broadcast.py ---
def html_to_md_mini(html: str) -> str:
    html = _preprocess_html(html)
    soup = BeautifulSoup(html, 'html.parser')
    def node2md(node) -> str:
        from bs4.element import NavigableString, Tag
        if isinstance(node, NavigableString):
            return _escape_md_main(str(node)) # reusing escape from main as they looked identical
        if not isinstance(node, Tag):
            return ''
        name = node.name.lower()
        if name in ('b', 'strong'):
            inner = ''.join(node2md(c) for c in node.children)
            return f"*{inner}*"
        if name in ('i', 'em'):
            inner = ''.join(node2md(c) for c in node.children)
            return f"_{inner}_"
        if name == 'a':
            href = node.get('href', '')
            body = ''.join(node2md(c) for c in node.children) or href
            return f"[{body}]({href})"
        if name in ('br',):
            return '\n'
        if name in ('p',):
            inner = ''.join(node2md(c) for c in node.children)
            if not inner.strip(): return ''
            return inner + '\n'
        return ''.join(node2md(c) for c in node.children)

    md = ''.join(node2md(child) for child in soup.body or soup.children)
    md = re.sub(r'\n{3,}', '\n\n', md)
    md = re.sub(r'\n\n+', '\n', md) # The suspect line
    md = md.strip()
    return md

# --- Test Cases ---
test_html = """
<p>Hello World</p>
<p>This is a second paragraph.</p>
<p><br></p>
<p>This paragraph contains <b>bold</b> and <i>italic</i> and a <a href="http://google.com">link</a>.</p>
<p>These are specials: * [ ] `</p>
"""

print("=== MAIN.PY output ===")
print(repr(html_to_md_main(test_html)))
print("\n=== MINI_BROADCAST.PY output ===")
print(repr(html_to_md_mini(test_html)))

