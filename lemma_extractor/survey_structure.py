"""Survey the reliability of indentation-based structure detection across all HTML pages."""
import os
import re
from collections import Counter

ROOT = os.path.join(os.path.dirname(__file__), '..')


def survey(directory, prefix, label):
    files = sorted(f for f in os.listdir(directory) if f.endswith('.html') and f.startswith(prefix))

    indent_counter = Counter()
    indent0_patterns = Counter()
    # footnote at page bottom: starts with a number (possibly alphanumeric like 10a) followed by spaces
    footnote_re = re.compile(r'^\d+[a-z]?\.\s')
    # lemma entry: like "5.   Mr. ..." — number, dot, 3-5 spaces, uppercase
    lemma_entry_re = re.compile(r'^\d+\.\s{3,6}[A-Z]')
    # period/role header: starts with a 4-digit year
    period_re = re.compile(r'^\d{4}')
    # page number line: only digits and whitespace, typically 82-char indented
    page_num_re = re.compile(r'^\s*\d+\s*$')

    pages_with_footnotes = 0
    pages_without_footnotes = 0
    indent0_anomalies = []

    for fname in files:
        content = open(os.path.join(directory, fname), 'rb').read().decode('latin-1')
        lines = [l for l in content.split('<br>') if l.strip()]
        has_fn = False
        for line in lines:
            if page_num_re.match(line):
                continue  # skip page number line
            s = line.lstrip()
            sp = len(line) - len(s)
            indent_counter[sp] += 1
            if sp == 0:
                if footnote_re.match(s):
                    indent0_patterns['footnote'] += 1
                    has_fn = True
                elif period_re.match(s):
                    indent0_patterns['period_header'] += 1
                elif lemma_entry_re.match(s):
                    indent0_patterns['lemma_entry'] += 1
                else:
                    key = s[:50]
                    indent0_patterns['other'] += 1
                    indent0_anomalies.append(f'{fname}: {key}')
        if has_fn:
            pages_with_footnotes += 1
        else:
            pages_without_footnotes += 1

    print(f'\n{"="*60}')
    print(f'{label}: {len(files)} pages')
    print(f'{"="*60}')

    print('\n--- Indent level distribution ---')
    total = sum(indent_counter.values())
    for sp, cnt in sorted(indent_counter.items()):
        bar = '#' * (cnt // max(1, total // 200))
        print(f'  indent {sp:3d}: {cnt:5d}  {bar}')

    print('\n--- Indent-0 patterns ---')
    for pat, cnt in indent0_patterns.most_common():
        print(f'  {cnt:4d}  {pat}')

    print(f'\nPages WITH page-bottom footnotes:    {pages_with_footnotes}')
    print(f'Pages WITHOUT page-bottom footnotes: {pages_without_footnotes}')

    if indent0_anomalies:
        print(f'\n--- Indent-0 "other" anomalies ({len(indent0_anomalies)} lines) ---')
        for a in indent0_anomalies[:30]:
            print(f'  {a}')
        if len(indent0_anomalies) > 30:
            print(f'  ... and {len(indent0_anomalies)-30} more')


if __name__ == '__main__':
    survey(
        os.path.join(ROOT, 'schutte_binnenland'),
        'schutte_nederlandsevertegenwoordigersinbuitenland',
        'Binnenland (NL vertegenwoordigers)'
    )
    survey(
        os.path.join(ROOT, 'schutte_buitenland'),
        'schutte_buitenlandsevertegenwoordigersinnederland',
        'Buitenland (buitenlandse vertegenwoordigers)'
    )
