import json, re

with open('_site/data/lemmas_nl.json') as f:
    nl = json.load(f)

# 1. Lemma with footnotes
print("=== LEMMA WITH FOOTNOTES ===")
for lemma in nl:
    if lemma.get('footnotes'):
        print(f"Nr {lemma['schutte_nr']}: {lemma['toc_title']}")
        for ln in lemma['lines']:
            print(f"  [{ln['zone']}] {repr(ln['text'][:200])}")
        print("  FOOTNOTES:", lemma['footnotes'])
        break

print()
print("=== LEMMA WITH NR. REFERENCE ===")
for lemma in nl:
    for ln in lemma.get('lines', []):
        if re.search(r'\bnr\.\s*\d+', ln['text'], re.I):
            print(f"Nr {lemma['schutte_nr']}: {lemma['toc_title']}")
            for l2 in lemma['lines']:
                print(f"  [{l2['zone']}] {repr(l2['text'][:200])}")
            break
    else:
        continue
    break

print()
print("=== LEMMA WITH 'zie sub' REFERENCE ===")
for lemma in nl:
    for ln in lemma.get('lines', []):
        if re.search(r'zie\s+sub', ln['text'], re.I):
            print(f"Nr {lemma['schutte_nr']}: {lemma['toc_title']}")
            for l2 in lemma['lines']:
                print(f"  [{l2['zone']}] {repr(l2['text'][:200])}")
            break
    else:
        continue
    break

print()
print("=== MULTIPLE ZONES EXAMPLE ===")
for lemma in nl:
    zones = set(ln['zone'] for ln in lemma.get('lines', []))
    if len(zones) >= 3:
        print(f"Nr {lemma['schutte_nr']}: {lemma['toc_title']} — zones: {zones}")
        for l2 in lemma['lines']:
            print(f"  [{l2['zone']}] {repr(l2['text'][:200])}")
        break
