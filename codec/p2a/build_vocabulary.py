"""Builds the P2a vocabulary (p2a_vocabulary_v1.bin): frozen P1 plus space+akshara entries, and nothing else.

Only input: codec/p1/p1_vocabulary_v1.bin, checked against its recorded SHA-256. No evaluation data is read.
Rule (one isolated change from P1, docs/phase2_proposal.md variant P2a):
  IDs 0-255           P1's 256 single bytes (unchanged)
  next 2,496          P1's Devanagari/Kannada akshara entries, unchanged and in P1 order
  next 2,496          b" " + each of those akshara entries, in the same order
  remaining           P1's ASCII entries in P1 (o200k rank) order, truncated so the total is exactly 65,536
Same file format as P1: magic "P1V1", u32 LE entry count, then per entry u8 length + bytes.
Run: python3 -I codec/p2a/build_vocabulary.py
"""
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent
P1 = ROOT / "codec" / "p1" / "p1_vocabulary_v1.bin"
P1_SHA256 = "8c85586c794d5589e7b640ebc0d2e9aa7a86e04ea28fe2dcf6ca4fb135ae2d43"
MAX_ENTRIES = 65536
MAX_TOKEN_BYTES = 16


def read_vocabulary(blob):
    if blob[:4] != b"P1V1":
        sys.exit("P1 vocabulary: bad magic")
    count, pos, entries = int.from_bytes(blob[4:8], "little"), 8, []
    for _ in range(count):
        n = blob[pos]
        entries.append(blob[pos + 1:pos + 1 + n])
        pos += 1 + n
    if pos != len(blob):
        sys.exit("P1 vocabulary: trailing bytes")
    return entries


def main():
    p1_blob = P1.read_bytes()
    if hashlib.sha256(p1_blob).hexdigest() != P1_SHA256:
        sys.exit("P1 vocabulary does not match its frozen SHA-256; P2a must be derived from the frozen P1")
    p1 = read_vocabulary(p1_blob)
    singles, rest = p1[:256], p1[256:]
    akshara = [e for e in rest if not all(b < 128 for b in e)]
    ascii_ = [e for e in rest if all(b < 128 for b in e)]
    if rest != akshara + ascii_:
        sys.exit("unexpected P1 layout: akshara entries must precede ASCII entries")
    spaced = [b" " + e for e in akshara]
    if any(len(e) > MAX_TOKEN_BYTES for e in spaced):
        sys.exit("space+akshara entry longer than the maximum token length")
    keep_ascii = MAX_ENTRIES - len(singles) - len(akshara) - len(spaced)
    entries = singles + akshara + spaced + ascii_[:keep_ascii]
    if len(entries) != MAX_ENTRIES or len(set(entries)) != len(entries):
        sys.exit("P2a vocabulary must have exactly 65,536 distinct entries")

    blob = b"P1V1" + len(entries).to_bytes(4, "little") + b"".join(bytes([len(t)]) + t for t in entries)
    digest = hashlib.sha256(blob).hexdigest()
    (OUT / "p2a_vocabulary_v1.bin").write_bytes(blob)
    (OUT / "p2a_vocabulary_v1.sha256").write_text(f"{digest}  p2a_vocabulary_v1.bin\n")
    dropped = ascii_[keep_ascii:]
    manifest = {
        "vocabulary": "p2a-space-akshara-v1", "entries": len(entries), "file_bytes": len(blob), "sha256": digest,
        "table_id_hex": digest[:16], "max_token_bytes": max(map(len, entries)),
        "sections": {"single_bytes": len(singles), "akshara_from_p1": len(akshara), "space_plus_akshara": len(spaced),
                     "ascii_from_p1": keep_ascii, "ascii_dropped_from_p1": len(dropped)},
        "id_ranges": {"single_bytes": [0, 255], "akshara": [256, 255 + len(akshara)],
                      "space_plus_akshara": [256 + len(akshara), 255 + 2 * len(akshara)], "ascii": [256 + 2 * len(akshara), MAX_ENTRIES - 1]},
        "inputs": {"p1_vocabulary": {"path": str(P1.relative_to(ROOT)), "sha256": P1_SHA256}},
        "evaluation_data_read": False,
    }
    (OUT / "p2a_vocabulary_v1.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: manifest[k] for k in ("entries", "file_bytes", "sha256", "sections")}, indent=1))


if __name__ == "__main__":
    main()
