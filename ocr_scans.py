"""
ocr_scans.py — batch OCR scan images using Tesseract, producing hOCR output.

hOCR is an HTML format with embedded layout info: content areas, paragraphs,
lines, and words each carry bounding-box coordinates and per-word confidence
scores. It is a lightweight alternative to PageXML suitable for downstream
text extraction and quality assessment.

Images are upscaled 2× before OCR (improves accuracy at ~200 DPI).
Already-processed files are skipped; safe to re-run.

Output: one .hocr file per image, written to a _ocr/ sibling directory.

  schutte_buitenland_scans/  →  schutte_buitenland_ocr/
  schutte_binnenland_scans/  →  schutte_binnenland_ocr/

Usage:
  python ocr_scans.py                  # process both corpora
  python ocr_scans.py --corpus bl      # BL only
  python ocr_scans.py --corpus nl      # NL only
  python ocr_scans.py --no-upscale     # skip 2x upscale (faster, lower quality)
  python ocr_scans.py --dry-run        # list files without processing
"""

import argparse
import subprocess
import tempfile
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

CORPORA = {
    "bl": {
        "scan_dir": "schutte_buitenland_scans",
        "ocr_dir":  "schutte_buitenland_ocr",
    },
    "nl": {
        "scan_dir": "schutte_binnenland_scans",
        "ocr_dir":  "schutte_binnenland_ocr",
    },
}


def ocr_image(img_path, out_stem, upscale, dry_run):
    """Run Tesseract on one image, writing <out_stem>.hocr."""
    out_path = Path(str(out_stem) + ".hocr")
    if out_path.exists():
        return "skip"

    if dry_run:
        return "dry"

    with tempfile.TemporaryDirectory() as tmp:
        work_img = img_path

        if upscale:
            scaled = Path(tmp) / "scaled.png"
            r = subprocess.run(
                ["convert", str(img_path), "-resize", "200%", str(scaled)],
                capture_output=True,
            )
            if r.returncode != 0:
                return f"ERROR (convert): {r.stderr.decode().strip()}"
            work_img = scaled

        # tesseract writes <out_stem>.hocr
        r = subprocess.run(
            ["tesseract", str(work_img), str(out_stem), "-l", "nld", "hocr"],
            capture_output=True,
        )
        if r.returncode != 0:
            return f"ERROR (tesseract): {r.stderr.decode().strip()}"

    return "ok"


def run(corpora, upscale, dry_run):
    for key, cfg in corpora.items():
        scan_dir = SCRIPT_DIR / cfg["scan_dir"]
        ocr_dir  = SCRIPT_DIR / cfg["ocr_dir"]

        if not scan_dir.exists():
            print(f"[{key}] scan dir not found: {scan_dir} — skipping")
            continue

        images = sorted(scan_dir.glob("*.jpg"))
        if not dry_run:
            ocr_dir.mkdir(exist_ok=True)

        print(f"\n=== {key.upper()} — {len(images)} pages → {ocr_dir.name} ===")
        total = len(images)
        counts = {"ok": 0, "skip": 0, "dry": 0, "error": 0}

        for i, img in enumerate(images, 1):
            out_stem = ocr_dir / img.stem
            status = ocr_image(img, out_stem, upscale, dry_run)

            if status == "skip":
                print(f"[{i}/{total}] skip  {img.name}")
                counts["skip"] += 1
            elif status == "dry":
                print(f"[{i}/{total}] would ocr  {img.name}")
                counts["dry"] += 1
            elif status == "ok":
                print(f"[{i}/{total}] ok    {img.name}")
                counts["ok"] += 1
            else:
                print(f"[{i}/{total}] {status}")
                counts["error"] += 1

        print(f"  done: {counts['ok']} processed, {counts['skip']} skipped, {counts['error']} errors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", choices=["bl", "nl", "both"], default="both")
    parser.add_argument("--no-upscale", action="store_true",
                        help="Skip 2x upscaling (faster but lower accuracy)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    selected = CORPORA if args.corpus == "both" else {args.corpus: CORPORA[args.corpus]}
    run(selected, upscale=not args.no_upscale, dry_run=args.dry_run)
