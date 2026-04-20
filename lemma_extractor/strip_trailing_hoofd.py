"""One-shot repair: strip trailing hoofd lines from all lemma XML files."""
from pathlib import Path

BASE = Path(__file__).parent.parent / "lemmas"
fixed = 0

for f in sorted(BASE.rglob("*.xml")):
    lines = f.read_text(encoding="utf-8").splitlines()
    changed = False
    while lines:
        # Find last non-empty, non-</lemma> line
        last_idx = None
        for i in range(len(lines) - 1, -1, -1):
            s = lines[i].strip()
            if s and s != "</lemma>":
                last_idx = i
                break
        if last_idx is None:
            break
        if 'type="hoofd"' in lines[last_idx]:
            lines.pop(last_idx)
            changed = True
        else:
            break

    if changed:
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        fixed += 1

print(f"Fixed {fixed} files")
