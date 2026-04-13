"""
download_scans.py — download scan images for both Schutte corpora from the Huygens server.

  BL (buitenlandsevertegenwoordigersinnederland): schutte_1, saved to schutte_buitenland_scans/
  NL (nederlandsevertegenwoordigersinbuitenland): schutte_2, saved to schutte_binnenland_scans/

Already-downloaded files are skipped so the script is safe to re-run.
A polite delay is inserted between requests to avoid hammering the server.

Usage:
  python download_scans.py             # default 2 s delay, both corpora
  python download_scans.py --delay 3   # slower
  python download_scans.py --dry-run   # list URLs without downloading
"""

import argparse
import subprocess
import time
from pathlib import Path

BASE = "https://resources.huygens.knaw.nl/retroapp/service_schutte/service_schutte"

CORPORA = [
    {
        "service":  "schutte_1",
        "prefix":   "schutte_buitenlandsevertegenwoordigersinnederland",
        "html_dir": "schutte_buitenland",
        "out_dir":  "schutte_buitenland_scans",
    },
    {
        "service":  "schutte_2",
        "prefix":   "schutte_nederlandsevertegenwoordigersinbuitenland",
        "html_dir": "schutte_binnenland",
        "out_dir":  "schutte_binnenland_scans",
    },
]

SCRIPT_DIR = Path(__file__).parent


def page_ids(html_dir, prefix):
    """Yield page stem names derived from the local HTML files."""
    return sorted(p.stem for p in html_dir.glob(f"{prefix}_*.html"))


def download(stems, base_url, out_dir, delay, dry_run):
    out_dir.mkdir(exist_ok=True)
    total = len(stems)
    for i, stem in enumerate(stems, 1):
        out_path = out_dir / f"{stem}.jpg"
        if out_path.exists():
            print(f"[{i}/{total}] skip  {stem}.jpg (already downloaded)")
            continue

        url = f"{base_url}/{stem}.jpg"
        if dry_run:
            print(f"[{i}/{total}] would fetch  {url}")
            continue

        print(f"[{i}/{total}] downloading  {stem}.jpg …", end=" ", flush=True)
        try:
            result = subprocess.run(
                ["curl", "-s", "-f", "-o", str(out_path), url],
                capture_output=True
            )
            if result.returncode == 0:
                size_kb = out_path.stat().st_size // 1024
                print(f"{size_kb} KB")
            else:
                print(f"ERROR: curl exit {result.returncode} — {result.stderr.decode().strip()}")
                if out_path.exists():
                    out_path.unlink()
        except Exception as e:
            print(f"ERROR: {e}")
            if out_path.exists():
                out_path.unlink()

        if i < total:
            time.sleep(delay)

    if not dry_run:
        downloaded = sum(1 for p in out_dir.glob("*.jpg"))
        print(f"  Done. {downloaded} files in {out_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Seconds to wait between requests (default: 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print URLs without downloading")
    args = parser.parse_args()

    for corpus in CORPORA:
        html_dir = SCRIPT_DIR / corpus["html_dir"]
        out_dir  = SCRIPT_DIR / corpus["out_dir"]
        base_url = f"{BASE}/{corpus['service']}/html"
        stems    = page_ids(html_dir, corpus["prefix"])
        print(f"\n=== {corpus['service']} ({corpus['prefix']}) — {len(stems)} pages ===")
        download(stems, base_url, out_dir, args.delay, args.dry_run)
