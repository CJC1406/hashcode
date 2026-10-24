# P1: akshara token table with byte fallback (`p1-akshara-ascii-v1`)

Project-owned codec, independent of upstream `sgtt`. The code is `codec/include/p1_codec.hpp`; the vocabulary is built by `build_vocabulary.py`.

## Frozen vocabulary
| | |
|---|---|
| File | `p1_vocabulary_v1.bin` (445,193 bytes), SHA-256 `8c85586c794d5589e7b640ebc0d2e9aa7a86e04ea28fe2dcf6ca4fb135ae2d43` |
| Table ID | `8c85586c794d5589`, the first 8 bytes of the SHA-256, written into every blob |
| Entries | 65,536, so IDs fit in `uint16` |
| Rebuild | `python3 -I codec/p1/build_vocabulary.py`. This is deterministic; three builds gave the same SHA-256. It refuses to run if the Unicode version isn't 16.0.0 |

Entries, in ID order:

| IDs | Count | Contents |
|---|---|---|
| 0–255 | 256 | every single byte (lossless fallback) |
| 256– | 128 + 91 | every assigned code point of the Devanagari (U+0900–097F) and Kannada (U+0C80–0CFF) blocks |
| | 53 + 37 | consonant + nukta |
| | 1,484 + 703 | consonant + one dependent sign (vowel sign, virama, anusvara, visarga, candrabindu) |
| | 62,784 | pure-ASCII entries of 2–16 bytes from `o200k.tiktoken` (OpenAI200K), in BPE rank order, until 65,536 entries |

**Inputs (no evaluation data is read):**
- Python `unicodedata` 16.0.0.
- `external/token-vldb2026/tokenizers/o200k.tiktoken`, SHA-256 `446a9538…1a2d`.

These are recorded in `p1_vocabulary_v1.manifest.json`. `tests/p1` checks structurally that every multi-byte entry is ASCII, or one or two code points from the two blocks.

**Consonant classification:** a block letter (`Lo`, name contains ` LETTER `) is an independent vowel if its name suffix is `A`, ends in ` A`, or equals a `VOWEL SIGN` suffix. Every other letter is treated as a consonant. This heuristic is reproducible from Unicode names, and a few letters that behave like consonants but aren't standard ones get entries anyway, for example `GLOTTAL STOP` and Kannada `NAKAARA POLLU`.

## Encoding
- **Greedy longest-prefix match on bytes,** from 16 bytes down to 2. Otherwise the single-byte ID is used, which is counted as a fallback.
- It reads only `[data, data + size)` and needs no padding.
- There's no sentinel value, and the ID width doesn't depend on how many vocabulary entries are used.
- **Blob:** `uint16` little-endian IDs, followed by a 13-byte footer: `BTT1`, version `0x01`, and the 8-byte table ID.
- **Decoder checks:** it rejects a bad magic, version or table ID, an odd ID byte count, and a truncated blob.
- **In HCC1:** codec value `2`. Value boundaries come from the HCC1 length table, and an empty payload is stored as `blob_length = 0`.

## How this relates to the design (`docs/bharat_prototype_experiment.md` §2)
These reconciliations were decided **before any P1 measurement**:
1. **Container:** HCC1 (D5) replaces the per-value `BTT1` header. HCC1 already stores the lengths, so the `BTT1` magic, version and table ID move into a footer.
2. **Scripts:** Devanagari and Kannada only, the recorded scope, instead of the six scripts listed in §2.1.
3. **English entries:** the design's "akshara entries plus byte fallback only" predates D1 and D1a. The leftover ID space is filled with ASCII-only OpenAI200K entries, following D1a.
4. **Single code points:** every assigned code point in the two blocks is an entry, a superset of "independent vowels and digits". Otherwise a lone anusvara or danda would fall back to 3 IDs.
5. **Classifier fix:** before measurement I fixed the classifier so that `SHORT A` and `CANDRA A` are vowels. The first build had treated them as consonants.

## Known weaknesses, measured in Phase 1
- **No multi-akshara tokens.** A Hindi or Kannada word costs one 2-byte ID per akshara, while `sgtt` uses whole-word tokens.
- **No space-prefixed akshara entries.** Spaces between Indic words fall back to single-byte IDs: 87% of fallback tokens on `kn-hi-v1` and 63% on `en-mixed-v1` are spaces.
- **Fixed 16-bit IDs.** There is no per-column width reduction like `sgtt`'s Dense IDs.
