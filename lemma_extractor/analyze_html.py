"""Analyse internal structure of HTML lemma pages."""
import os
import re

ROOT = os.path.dirname(__file__)

def show_page_ends(directory, prefix, n=8):
    files = sorted(f for f in os.listdir(directory) if f.endswith('.html') and f.startswith(prefix))
    for fname in files[:n]:
        content = open(os.path.join(directory, fname), 'rb').read().decode('latin-1')
        lines = content.split('<br>')
        print(f'=== {fname} ===')
        shown = 0
        for line in reversed(lines):
            s = line.lstrip(); sp = len(line) - len(s)
            if s.strip():
                print(f'  {sp:3d}| {line[:100]}')
                shown += 1
                if shown >= 8:
                    break
        print()


def show_full_page(directory, fname):
    content = open(os.path.join(directory, fname), 'rb').read().decode('latin-1')
    lines = content.split('<br>')
    for line in lines:
        s = line.lstrip(); sp = len(line) - len(s)
        if s.strip():
            print(f'  {sp:3d}| {line[:100]}')


def find_footnote_patterns(directory, prefix, max_files=30):
    """Find inline footnote marks in text."""
    files = sorted(f for f in os.listdir(directory) if f.endswith('.html') and f.startswith(prefix))
    # Pattern: digit(s) directly after a word char, or surrounded by spaces, before punctuation
    fn_mark = re.compile(r'(\w)(\d+[a-z]?)(\s*[;,.\s])')
    for fname in files[:max_files]:
        content = open(os.path.join(directory, fname), 'rb').read().decode('latin-1')
        for m in fn_mark.finditer(content):
            # Exclude year/date patterns: preceded by digits (e.g. 1593)
            pre = content[max(0, m.start()-5):m.start()+len(m.group())+5]
            print(f'{fname}: ...{pre}...')


if __name__ == '__main__':
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'ends_nl'

    if cmd == 'ends_nl':
        d = os.path.join(ROOT, '..', 'schutte_binnenland')
        show_page_ends(d, 'schutte_nederlandseverte')
    elif cmd == 'ends_bl':
        d = os.path.join(ROOT, '..', 'schutte_buitenland')
        show_page_ends(d, 'schutte_buitenlandsevert')
    elif cmd == 'full':
        d = os.path.join(ROOT, '..', 'schutte_binnenland')
        show_full_page(d, sys.argv[2])
    elif cmd == 'footnotes':
        d = os.path.join(ROOT, '..', 'schutte_binnenland')
        find_footnote_patterns(d, 'schutte_nederlandseverte')
