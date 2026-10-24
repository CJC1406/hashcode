# Phase 1 dataset: `kn_hi_v1`

- **Version:** `phase1-kn-hi-v1`
- **File:** `kn_hi_v1.jsonl`, one JSON object per line.
- **Checksum:** `kn_hi_v1.sha256`. The SHA-256 is `359269f4dbacd71e9442e3a1b38785e603698931fe4e8afa22e51b5ae36bb6fc`, and `run_benchmark.py` refuses to run if it doesn't match.
- **Rebuild:** `python3 -I datasets/phase1/build_dataset.py`. This regenerates the JSONL deterministically from the Python source.

## Record schema
| Field | Meaning |
|---|---|
| `sample_id` | stable ID `<language>-<category>-<NNN>` |
| `language` | `hi` (Hindi, Devanagari) or `kn` (Kannada) |
| `category` | `short`, `medium`, `long`, `repeated`, `punct_numerals`, `mixed`, `edge`, `tiny` |
| `utf8_hex` | **authoritative** input bytes |
| `text` | the same string, for reading; must equal `bytes.fromhex(utf8_hex).decode()` |
| `utf8_bytes`, `code_points` | lengths |
| `note` | what an edge case exercises |
| `provenance`, `dataset_version` | origin and version |

## Contents
65 samples, 23,902 bytes in total:
- **Hindi:** 32 samples, 10,511 bytes.
- **Kannada:** 33 samples, 13,391 bytes.

| Category | Hindi | Kannada | Notes |
|---|---|---|---|
| `short` | 5 | 5 | everyday phrases |
| `medium` | 4 | 4 | single sentences |
| `long` | 2 | 2 | paragraphs |
| `repeated` | 4 | 4 | repeated word, phrase, sentence ×10, paragraph ×10 |
| `punct_numerals` | 3 | 3 | currency, ASCII and native-script digits |
| `mixed` | 3 | 3 | native script with occasional English words |
| `edge` | 7 | 8 | nukta (precomposed and decomposed), ZWJ/ZWNJ after virama, conjuncts, candrabindu/visarga, two-part Kannada vowel sign (precomposed and decomposed), isolated combining mark, NBSP |
| `tiny` | 4 | 4 | empty string, single letter, single mark or punctuation |

No Unicode normalization is applied. Two samples are deliberately not in NFC:
- `hi-edge-001`: `U+095B` is an NFC composition exclusion.
- `kn-edge-002`: decomposed `U+0CC6 U+0CC2`.

Each is paired with its canonically equivalent counterpart, which has different bytes.

## Provenance and licence
- **Origin:** written for this project on 2026-10-24 by the AI assistant working on the repository. Nothing was copied from external sources. There is no personal data: order numbers are fictional and postal codes are generic.
- **Licence:** project-internal. These are original sentences with no third-party rights known.
- **Native-speaker review: not done.** No review by a native Hindi or Kannada speaker has been confirmed (status as of 2026-10-24). Grammar and naturalness may be imperfect. Byte-level correctness is unaffected.
- **Accepted use (decision recorded 2026-10-24): harness validation only.** Results on this dataset show that the benchmark is correct and give an initial look at size behaviour. They are not evidence of Hindi or Kannada compression performance in general.

## Limitations
- The dataset is small and synthetic. It isn't representative of real Kannada or Hindi database text, and isn't tuned to any domain.
- It is only for checking that the harness is correct and for an initial look at size behaviour. Results on it mustn't be generalized.
- The two paragraph ×10 samples are large: `kn-repeated-004` is 9,219 bytes and `hi-repeated-004` is 7,139 bytes. Together they are 68% of all bytes, so they dominate any aggregate figure that sums bytes across samples.
