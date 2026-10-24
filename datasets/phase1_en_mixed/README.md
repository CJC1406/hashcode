# Phase 1 dataset: `en_mixed_v1`

- **Version:** `phase1-en-mixed-v1`
- **File:** `en_mixed_v1.jsonl`, one JSON object per line.
- **Checksum:** `en_mixed_v1.sha256`. The SHA-256 is `6c4685c24ac3603d19ba9121a3c564f88cd3f78542cbc8efec090f7c031d47b0`.
- **Rebuild:** `python3 -I datasets/phase1_en_mixed/build_dataset.py`. This is deterministic; two builds gave the same checksum.
- **Separation:** this dataset is completely separate from `datasets/phase1/kn_hi_v1.jsonl` (`phase1-kn-hi-v1`), which it doesn't modify or extend. Sample IDs can't collide, because the language prefixes differ.

## Record schema
It's the same as `phase1-kn-hi-v1`: `sample_id`, `dataset_version`, `language`, `category`, `utf8_bytes`, `code_points`, `utf8_hex` (**authoritative bytes**), `text`, `note`, `provenance`.

Language labels:

| `language` | Meaning | Rule enforced by the builder |
|---|---|---|
| `en` | English only | no Devanagari or Kannada |
| `en-hi` | English mixed with Hindi (Devanagari script) | contains Latin letters **and** Devanagari, and no Kannada; `tiny` values are exempt |
| `en-kn` | English mixed with Kannada | contains Latin letters **and** Kannada, and no Devanagari; `tiny` values are exempt |

**Category change from `phase1-kn-hi-v1`:** the 8 labels are kept, except that `mixed` is replaced by **`structured`** (identifiers, `key=value` records, JSON-like and CSV-like rows, a UUID-shaped string, a reserved `example.com` address). Language mixing is now carried by the `language` label, so a `mixed` category would be redundant.

## Contents
81 samples, 19,437 bytes in total.

| Category | `en` | `en-hi` | `en-kn` | What it covers |
|---|---|---|---|---|
| `short` | 4 | 3 | 3 | everyday phrases |
| `medium` | 4 | 3 | 3 | single sentences |
| `long` | 3 | 2 | 2 | paragraphs |
| `repeated` | 4 | 3 | 3 | repeated word or phrase, sentence ×10 (en) or ×5 (mixed), paragraph ×10 |
| `punct_numerals` | 4 | 3 | 3 | currency, percentages, dates (ISO and DD/MM/YYYY), times, version strings |
| `structured` | 5 | 3 | 3 | identifiers and record-like strings, all fictional |
| `edge` | 7 | 3 | 3 | tabs, embedded LF, trailing CR LF, leading and trailing spaces, typographic quotes and dashes, emoji (including a skin-tone modifier), NBSP |
| `tiny` | 4 | 3 | 3 | empty string, single letter, digit or space, single short word |
| **total** | **35** (5,665 B) | **23** (6,584 B) | **23** (7,188 B) | |

- **Normalization:** none; all samples happen to be in NFC.
- **Bytes the benchmark now exercises:** 4 samples contain LF, 1 contains CR, and 3 contain tabs. There are no NUL bytes, which remain covered by `hashcode_column_tests`.
- **Large samples:** the three paragraph ×10 samples (`en-kn-repeated-003` with 5,299 B, `en-hi-repeated-003` with 4,809 B, `en-repeated-004` with 3,599 B) hold 70.5% of all bytes (13,707 of 19,437). They dominate any aggregate figure that sums bytes across samples.

## Provenance and licence
- **Origin:** written for this project on 2026-10-24 by the AI assistant working on the repository. Nothing was copied from external sources.
- **No personal data:**
  - order, invoice, SKU, train and bus numbers are fictional;
  - the UUID-shaped string is made up;
  - the e-mail address uses the reserved `example.com` domain (RFC 2606);
  - "Bengaluru" and "Delhi" appear only as city names.
- **Licence:** project-internal. These are original sentences with no third-party rights known.
- **Not independently reviewed.** No native speaker of English, Hindi or Kannada has reviewed the samples. The code-mixed sentences show one plausible writing style (Hindi or Kannada in native script with English words in Latin script). They aren't checked against real usage.
- **Accepted use: controlled evaluation inputs for checking the harness only,** the same status as `phase1-kn-hi-v1`.

## Limitations
- The dataset is small and synthetic. It is **not representative** of real English, Hindi–English or Kannada–English text, such as transliterated Hinglish in Roman script, which isn't included at all.
- Each language × category cell has only 2–7 values.
- Results on this dataset show the harness is correct and give an initial look at size behaviour. They mustn't be generalized.
