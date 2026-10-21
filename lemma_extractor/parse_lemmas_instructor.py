#!/usr/bin/env python3
"""Parse Schutte lemma XML into structured JSON/XML via a local LLM + instructor.

Works with any OpenAI-compatible local server:

* Ollama      — ``--provider ollama``   (default, port 11434)
* LM Studio   — ``--provider lmstudio`` (port 1234; good on Apple Silicon)
* llama.cpp   — ``--provider llamacpp`` (port 8080)
* MLX server  — ``--provider mlx``      (port 8080)

Usage
-----
    cd lemma_extractor
    uv sync --extra llm

    # LM Studio: load a model, Developer → Start Server, then:
    uv run python parse_lemmas_instructor.py --provider lmstudio \\
        --model "qwen2.5-coder-7b-instruct" --corpus nl --nr 13 --xml

    # Ollama
    uv run python parse_lemmas_instructor.py --corpus nl --nr 13 --xml

Output
------
    parsed/{nl|bl}/{prefix}_{nr}.json
    parsed/{nl|bl}/{prefix}_{nr}.xml   (with --xml)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

from lemma_extractor.lemma_schema import ParsedLemma, parsed_lemma_to_xml

LEMMAS_DIR = ROOT / "lemmas"
OUT_DIR = ROOT / "parsed"

SYSTEM_PROMPT = """\
Je bent een historisch data-extractor voor het Schutte Repertorium \
(Nederlandse diplomatieke biografieën, 1584–1810).

Extraheer uit de lemma-tekst ALLEEN feiten die letterlijk of duidelijk \
afleidbaar zijn. Verzin niets. Ontbrekende velden: null of lege lijst.

Regels:
- naam: volledige openingsnaam met titels (zoals in de eerste zin).
- jaren: ambtsperiode + functie indien aanwezig (bijv. "1656-1687 resident").
- carrière: chronologische lijst van functies/missies met jaar indien bekend.
- familie: alleen uit "Zoon/Dochter van …" en huwelijkszinnen.
- bronnen: bibliografische regels (N.N.B.W., Van der Aa, Balen, …), niet de voetnoten.
- Negeer paginahoofden en genummerde voetnoten (noot).
- Antwoord uitsluitend als JSON die het schema volgt.
"""


def _nr_from_path(path: Path) -> str:
    """Extract nr token from nl_0013.xml / bl_0418a.xml → '13' / '418a'."""
    m = re.search(r"_(.+)\.xml$", path.name)
    if not m:
        raise ValueError(f"unexpected lemma filename: {path.name}")
    raw = m.group(1)
    # strip leading zeros for numeric ids, keep alphabetic suffixes
    if raw.isdigit():
        return str(int(raw))
    m2 = re.match(r"^0*(\d+[a-zA-Z]*)$", raw)
    return m2.group(1) if m2 else raw


def _list_lemma_files(corpus: str, nr: str | None) -> list[Path]:
    directory = LEMMAS_DIR / corpus
    if not directory.is_dir():
        raise FileNotFoundError(f"lemma dir not found: {directory}")
    if nr is not None:
        # try zero-padded and raw forms
        candidates = [
            directory / f"{corpus}_{nr}.xml",
            directory / f"{corpus}_{nr.zfill(4)}.xml" if nr.isdigit() else None,
        ]
        for c in candidates:
            if c and c.exists():
                return [c]
        # fuzzy: match stem ending
        hits = sorted(directory.glob(f"{corpus}_*{nr}.xml"))
        if hits:
            return hits
        raise FileNotFoundError(f"no lemma file for {corpus} nr={nr}")
    return sorted(directory.glob(f"{corpus}_*.xml"))


PROVIDERS = {
    # OpenAI-compatible local servers (Apple Silicon friendly)
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "api_key": "ollama",
        "default_model": "qwen2.5-coder:7b",
        "mode": "JSON",  # json_object
    },
    "lmstudio": {
        "base_url": "http://localhost:1234/v1",
        "api_key": "lm-studio",
        "default_model": "local-model",
        # instructor Mode.JSON_SCHEMA wrongly sends type=json_object;
        # OPENROUTER_STRUCTURED_OUTPUTS sends type=json_schema (LM Studio OK)
        "mode": "OPENROUTER_STRUCTURED_OUTPUTS",
    },
    "llamacpp": {
        "base_url": "http://localhost:8080/v1",
        "api_key": "llamacpp",
        "default_model": "local-model",
        "mode": "MD_JSON",
    },
    "mlx": {
        "base_url": "http://localhost:8080/v1",
        "api_key": "mlx",
        "default_model": "local-model",
        "mode": "MD_JSON",
    },
}


def _lemma_text(xml_path: Path, max_chars: int | None = 3500) -> str:
    """Flatten classified lemma XML; keep high-signal zones only.

    Skips footnotes/page headers. Prefers loopbaan + personalia + bronnen,
    then truncates to *max_chars* to keep local inference fast.
    """
    root = ET.parse(xml_path).getroot()
    prefer = ("loopbaan", "personalia", "bronnen", "hoofd", "entry")
    primary: list[str] = []
    other: list[str] = []
    for el in root.findall("line"):
        ltype = el.get("type", "")
        if ltype in ("paginahoofd", "noot"):
            continue
        text = (el.text or "").strip()
        if not text:
            continue
        (primary if ltype in prefer or not ltype else other).append(text)

    body = "\n".join(primary + other)
    if max_chars and len(body) > max_chars:
        body = body[:max_chars].rsplit("\n", 1)[0] + "\n…"
    return body


def _normalize_base_url(url: str) -> str:
    """Ensure base_url ends with /v1 for the OpenAI client."""
    u = url.rstrip("/")
    if u.endswith("/v1"):
        return u
    return u + "/v1"


def _resolve_mode(name: str):
    import instructor

    mode = getattr(instructor.Mode, name, None)
    if mode is None:
        raise SystemExit(f"Unknown instructor mode: {name}")
    return mode


def _make_client(base_url: str, model: str, api_key: str = "local", mode_name: str = "JSON"):
    try:
        import instructor
        from openai import OpenAI
    except ImportError as e:
        raise SystemExit(
            "Missing LLM deps. Install with:\n"
            "  uv sync --extra llm\n"
            f"({e})"
        ) from e

    raw = OpenAI(base_url=_normalize_base_url(base_url), api_key=api_key or "local")
    return instructor.from_openai(raw, mode=_resolve_mode(mode_name)), model


def parse_one(
    client,
    model: str,
    text: str,
    *,
    max_retries: int = 2,
) -> ParsedLemma:
    return client.chat.completions.create(
        model=model,
        response_model=ParsedLemma,
        max_retries=max_retries,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extraheer gestructureerde gegevens uit dit Schutte-lemma:\n\n"
                    f"{text}"
                ),
            },
        ],
    )


def run(args: argparse.Namespace) -> None:
    corpora = ["nl", "bl"] if args.corpus == "all" else [args.corpus]

    provider = PROVIDERS.get(args.provider, {})
    base_url = args.base_url or provider.get("base_url", "http://localhost:11434/v1")
    model = args.model or provider.get("default_model", "local-model")
    api_key = args.api_key or provider.get("api_key", "local")
    mode_name = args.mode or provider.get("mode", "JSON")

    client, model = _make_client(base_url, model, api_key=api_key, mode_name=mode_name)

    stats = {"ok": 0, "skip": 0, "fail": 0}

    for corpus in corpora:
        files = _list_lemma_files(corpus, args.nr)
        if args.limit is not None:
            files = files[: args.limit]

        out_dir = Path(args.out_dir) / corpus
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n=== {corpus}: {len(files)} lemmas → {out_dir} ===")
        print(f"  provider={args.provider}  model={model}  mode={mode_name}")
        print(f"  base_url={_normalize_base_url(base_url)}  max_chars={args.max_chars}")

        for path in files:
            nr = _nr_from_path(path)
            # keep zero-padded stem for filenames when numeric
            stem = path.stem  # e.g. nl_0013
            json_path = out_dir / f"{stem}.json"
            xml_path = out_dir / f"{stem}.xml"

            if args.resume and json_path.exists():
                print(f"  [skip] {stem}")
                stats["skip"] += 1
                continue

            text = _lemma_text(path, max_chars=args.max_chars)
            if not text.strip():
                print(f"  [empty] {stem}")
                stats["fail"] += 1
                continue

            t0 = time.time()
            try:
                parsed = parse_one(client, model, text, max_retries=args.retries)
            except Exception as exc:
                print(f"  [fail] {stem}: {exc}")
                stats["fail"] += 1
                continue

            payload = {
                "corpus": corpus,
                "schutte_nr": nr,
                "source": str(path.relative_to(ROOT)),
                "provider": args.provider,
                "model": model,
                "parsed": parsed.model_dump(mode="json"),
            }
            json_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if args.xml:
                xml_path.write_text(
                    parsed_lemma_to_xml(parsed, nr),
                    encoding="utf-8",
                )

            elapsed = time.time() - t0
            naam = parsed.bewoner.naam or "?"
            print(f"  [ok]   {stem}  {elapsed:.1f}s  {naam[:60]}")
            stats["ok"] += 1

    print(
        f"\nDone. ok={stats['ok']}  skipped={stats['skip']}  failed={stats['fail']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Parse Schutte lemmas with a local OpenAI-compatible LLM "
            "(Ollama, LM Studio, llama.cpp, MLX) + instructor"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Providers (Apple Silicon friendly):
  ollama     http://localhost:11434/v1   (default)
  lmstudio   http://localhost:1234/v1    LM Studio → Developer → Start Server
  llamacpp   http://localhost:8080/v1    llama.cpp server / llama-server
  mlx        http://localhost:8080/v1    mlx_lm.server

Examples:
  # Ollama (default)
  uv run python parse_lemmas_instructor.py --corpus nl --nr 13

  # LM Studio — load a model in the UI, start the server, then:
  uv run python parse_lemmas_instructor.py --provider lmstudio \\
      --model "openai/gpt-oss-20b" --corpus nl --nr 13 --xml --retries 0
""",
    )
    parser.add_argument(
        "--corpus",
        choices=["nl", "bl", "all"],
        default="nl",
        help="Corpus to parse (default: nl)",
    )
    parser.add_argument(
        "--nr",
        default=None,
        help="Single schutte_nr (e.g. 13 or 418a); default: all files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max number of lemmas (after --nr filter)",
    )
    parser.add_argument(
        "--provider",
        choices=list(PROVIDERS),
        default="ollama",
        help="Local backend shortcut (default: ollama)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id as known to the server (default depends on --provider)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override OpenAI-compatible base URL (with or without /v1)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key if the server requires one (LM Studio optional)",
    )
    parser.add_argument(
        "--mode",
        default=None,
        choices=[
            "JSON",
            "JSON_SCHEMA",
            "MD_JSON",
            "TOOLS",
            "OPENROUTER_STRUCTURED_OUTPUTS",
        ],
        help=(
            "Instructor mode. For LM Studio use OPENROUTER_STRUCTURED_OUTPUTS "
            "(default) or MD_JSON; do not use JSON/JSON_SCHEMA (sends json_object)."
        ),
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=3500,
        help="Truncate lemma text to this many chars (default: 3500; 0 = no limit)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUT_DIR,
        help=f"Output directory (default: {OUT_DIR})",
    )
    parser.add_argument(
        "--xml",
        action="store_true",
        help="Also write Dutch XML alongside JSON",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip lemmas that already have a JSON file",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=1,
        help="Instructor validation retries (default: 1)",
    )
    args = parser.parse_args()
    if args.max_chars == 0:
        args.max_chars = None
    run(args)


if __name__ == "__main__":
    main()
