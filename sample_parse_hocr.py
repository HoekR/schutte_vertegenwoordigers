import sys
from pathlib import Path
sys.path.insert(0, 'lemma_extractor/src')
from lemma_extractor.parse_html import parse_page as html_parse
from lemma_extractor.parse_hocr import parse_page as hocr_parse

SAMPLES = [
    ('bl', 'schutte_buitenland/schutte_buitenlandsevertegenwoordigersinnederland_0002.html'),
    ('nl', 'schutte_binnenland/schutte_nederlandsevertegenwoordigersinbuitenland_0003.html'),
]

for corpus, stem in SAMPLES:
    html_path = Path(stem)
    hocr_path = Path(stem
        .replace('schutte_buitenland/', 'schutte_buitenland_ocr/')
        .replace('schutte_binnenland/', 'schutte_binnenland_ocr/')
        .replace('.html', '.hocr'))

    html_lines = [l for l in html_parse(html_path, corpus) if l['zone'] != 'blank']
    hocr_lines = [l for l in hocr_parse(hocr_path, corpus) if l['zone'] != 'blank']

    print()
    print('=' * 72)
    print('  CORPUS=%s  %s' % (corpus.upper(), html_path.name))
    print('  HTML lines=%d  hOCR lines=%d' % (len(html_lines), len(hocr_lines)))
    print('=' * 72)
    print('  %15s | %15s | %4s | %s' % ('HTML zone', 'hOCR zone', 'off', 'text'))
    print('  %s-+-%s-+-%s-+-%s' % ('-'*15, '-'*15, '-'*4, '-'*40))
    for h, o in zip(html_lines, hocr_lines):
        marker = '  ' if h['zone'] == o['zone'] else '>>'
        low = ' [!]' if o['low_conf'] else ''
        print('%s %15s | %15s | %4d | %s%s' % (
            marker, h['zone'], o['zone'], o['x_offset'], o['text'][:45], low))
