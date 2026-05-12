
import re
import html
from bs4 import BeautifulSoup

def _preprocess_html(raw: str) -> str:
    """Rough replacement of <span style="..."> with semantic tags before parsing."""
    # span with bold
    raw = re.sub(r"<span[^>]*font-weight:[^>]*>(.*?)</span>", r"<b>\1</b>", raw, flags=re.S | re.I)
    # span with italic
    raw = re.sub(r"<span[^>]*font-style\s*:\s*italic[^>]*>(.*?)</span>", r"<i>\1</i>", raw, flags=re.S | re.I)
    return raw

def html_to_telegram(html_content: str) -> str:
    """
    Converts WYSIWYG HTML (from QTextEdit) to Telegram-supported HTML.
    
    Why HTML?
    - Markdown (Legacy) has poor escaping support.
    - MarkdownV2 is too strict and requires escaping everything.
    - HTML allows mixing <b> tags with literal special chars like *, [, ], etc.
    
    Features:
    - Converts <br> and <p> to newlines (preserving paragraphs).
    - Preserves <b>, <i>, <a>.
    - ESCAPES all other text (so <, >, & are safe).
    """
    if not html_content:
        return ""
        
    html_content = _preprocess_html(html_content)
    soup = BeautifulSoup(html_content, 'html.parser')

    def node2html(node) -> str:
        from bs4.element import NavigableString, Tag
        if isinstance(node, NavigableString):
            # Если это просто пробельные символы (например, перенос строки между тегами <p>),
            # и мы находимся на верхнем уровне (body), пропускаем их.
            # QTextEdit генерирует <p>...</p>\n<p>...</p>.
            # Если не пропускать, получим лишнюю пустую строку.
            if node.isspace() and node.parent.name in ('body', '[document]', 'html'):
                return ''
            
            # Escape plain text so <, >, & are treated as text, not tags.
            # * and _ remain literal.
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
            # Inner text must be processed (escaped/formatted)
            inner = ''.join(node2html(c) for c in node.children) or href
            return f'<a href="{href}">{inner}</a>'
            
        if name == 'br':
            return '\n'
            
        if name == 'p':
            inner = ''.join(node2html(c) for c in node.children)
            if not inner:
                return ''
            return inner + '\n'

        # div/span etc. – recursive
        return ''.join(node2html(c) for c in node.children)

    res = ''.join(node2html(c) for c in soup.body or soup.children)

    # Collapse more than 2 consecutive newlines to 2 (to preserve one empty line between paragraphs)
    res = re.sub(r'\n{3,}', '\n\n', res)
    # Trim spaces at start/end
    res = res.strip()
    return res
