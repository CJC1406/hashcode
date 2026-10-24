"""Builds the frozen P1 vocabulary (p1_vocabulary_v1.bin), its SHA-256 and a manifest.

Inputs (and only these; no evaluation dataset is read):
  1. Python's unicodedata (the Unicode version is checked and recorded).
  2. external/token-vldb2026/tokenizers/o200k.tiktoken (OpenAI200K BPE ranks), for ASCII entries (decision D1a).
Entry order: 256 single bytes | Devanagari and Kannada akshara entries | ASCII entries by o200k rank, until 65,536.
File format: magic "P1V1", u32 LE entry count, then per entry: u8 length, bytes.
Run: python3 -I codec/p1/build_vocabulary.py
"""
import base64
import hashlib
import json
import pathlib
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent
O200K = ROOT / "external" / "token-vldb2026" / "tokenizers" / "o200k.tiktoken"
EXPECTED_UNICODE = "16.0.0"
MAX_ENTRIES = 65536
MAX_TOKEN_BYTES = 16
BLOCKS = {"devanagari": (0x0900, 0x097F), "kannada": (0x0C80, 0x0CFF)}
DEPENDENT_SIGN_MARKERS = ("VOWEL SIGN", "SIGN VIRAMA", "SIGN ANUSVARA", "SIGN VISARGA", "SIGN CANDRABINDU")


def block_chars(lo, hi):
    return [chr(c) for c in range(lo, hi + 1) if unicodedata.category(chr(c)) != "Cn"]


def classify(chars):
    """Consonants, nukta and dependent signs from Unicode names (heuristic documented in codec/p1/README.md)."""
    names = {ch: unicodedata.name(ch, "") for ch in chars}
    sign_suffixes = {n.split("VOWEL SIGN ", 1)[1] for n in names.values() if "VOWEL SIGN " in n}
    def is_independent_vowel(n):
        if " LETTER " not in n:
            return False
        suffix = n.split(" LETTER ", 1)[1]
        return suffix == "A" or suffix.endswith(" A") or suffix in sign_suffixes  # " A": SHORT A, CANDRA A
    consonants = [ch for ch, n in names.items() if unicodedata.category(ch) == "Lo" and " LETTER " in n and not is_independent_vowel(n)]
    nukta = [ch for ch, n in names.items() if n.endswith("SIGN NUKTA")]
    signs = [ch for ch, n in names.items() if unicodedata.category(ch) in ("Mn", "Mc") and any(m in n for m in DEPENDENT_SIGN_MARKERS)]
    return consonants, nukta, signs


def main():
    if unicodedata.unidata_version != EXPECTED_UNICODE:
        sys.exit(f"Unicode {unicodedata.unidata_version} != expected {EXPECTED_UNICODE}; the vocabulary would differ")
    entries, seen, sections = [], set(), {}

    def add(token, section):
        if token not in seen and len(token) <= MAX_TOKEN_BYTES:
            seen.add(token)
            entries.append(token)
            sections[section] = sections.get(section, 0) + 1

    for b in range(256):
        add(bytes([b]), "single_bytes")
    for script, (lo, hi) in BLOCKS.items():
        chars = block_chars(lo, hi)
        consonants, nukta, signs = classify(chars)
        for ch in chars:
            add(ch.encode(), f"{script}_code_points")
        for c in consonants:
            for n in nukta:
                add((c + n).encode(), f"{script}_consonant_nukta")
        for c in consonants:
            for s in signs:
                add((c + s).encode(), f"{script}_consonant_sign")
        sections[f"{script}_consonants"] = len(consonants)
        sections[f"{script}_dependent_signs"] = len(signs)

    o200k_bytes = O200K.read_bytes()
    ranked = []
    for line in o200k_bytes.splitlines():
        if line.strip():
            tok, rank = line.split()
            ranked.append((int(rank), base64.b64decode(tok)))
    ranked.sort()
    for _, tok in ranked:
        if len(entries) >= MAX_ENTRIES:
            break
        if 2 <= len(tok) <= MAX_TOKEN_BYTES and all(b < 128 for b in tok):
            add(tok, "ascii_from_o200k")

    blob = b"P1V1" + len(entries).to_bytes(4, "little") + b"".join(bytes([len(t)]) + t for t in entries)
    digest = hashlib.sha256(blob).hexdigest()
    (OUT / "p1_vocabulary_v1.bin").write_bytes(blob)
    (OUT / "p1_vocabulary_v1.sha256").write_text(f"{digest}  p1_vocabulary_v1.bin\n")
    manifest = {
        "vocabulary": "p1-akshara-ascii-v1", "entries": len(entries), "file_bytes": len(blob), "sha256": digest,
        "table_id_hex": digest[:16], "max_token_bytes": MAX_TOKEN_BYTES, "sections": sections,
        "inputs": {"unicodedata_version": unicodedata.unidata_version,
                   "o200k.tiktoken": {"path": str(O200K.relative_to(ROOT)), "sha256": hashlib.sha256(o200k_bytes).hexdigest(), "entries": len(ranked)}},
        "evaluation_data_read": False,
    }
    (OUT / "p1_vocabulary_v1.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: manifest[k] for k in ("entries", "file_bytes", "sha256", "sections")}, indent=1))


if __name__ == "__main__":
    main()
