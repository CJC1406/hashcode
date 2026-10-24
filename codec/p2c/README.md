# P2c vocabulary builder (prototype; no frozen vocabulary)

**Frozen vocabulary:** `p2c_vocabulary_v1.bin` (SHA-256 `1e12dc48…`, 65,536 entries, 655,073 bytes, L = 32,768).
- **Source:** learned from the approved training source, Hindi + Kannada Wikipedia dump 20261001 (`docs/phase2_p2c_report.md` §11).
- **Licence:** CC BY-SA 4.0; see `LICENSE-vocabulary.md`.
- **Not evaluated yet:** FLORES+ is not approved, so nothing in this directory is a compression result.
- **Fixture tests:** the builder's own tests still use the synthetic pseudo-word fixture (`tests/p2c/fixtures/make_synthetic_corpus.py`). A vocabulary built from that fixture is a test vocabulary only.

## What it builds
`build_vocabulary.py` reads the frozen P2a vocabulary (SHA-256 `c99ff52f…`, the same vocabulary P2b uses) and a JSONL training corpus (`{"doc_id", "text"}` per line). It writes a 65,536-entry vocabulary in the P1/P2a file format:

| IDs | Entries |
|---|---|
| 0–5,247 | P2a core, unchanged: single bytes, akshara entries, space+akshara entries |
| next L/2 | learned Devanagari entries, in rank order (fewer only with the test-only `--allow-unfilled`) |
| next L/2 | learned Kannada entries, in rank order (fewer only with `--allow-unfilled`) |
| rest | P2a's ASCII entries in P2a order, truncated to reach 65,536 |

- **Codec:** the vocabulary is used with the **unchanged P2b codec** (HCC1 codec 3). Global IDs remain `u16`. The BTT2 footer carries the vocabulary's table ID (its SHA-256 prefix), so a P2c blob is rejected by a P2a/P2b decoder and the other way round (tested).
- **Rules** (builder v2; `docs/phase2_p2c_plan.md` §4.2–4.4 as amended; the decisions are in `docs/phase2_p2c_report.md` §3):
  - **Candidates:** 1 or more aksharas from one single-script run, bounded only by 16 bytes (at most 5 Indic code points), with or without the run's leading space.
  - **Score:** `count × (P2a tokens − 1)`, counting every occurrence, with no re-scoring. Ties go to the longer entry, then to ascending bytes.
  - **Quotas:** a strict 50/50 split. An L is eligible only if both languages fill L/2 entries.
  - **Held-out split:** `SHA-256(doc_id) mod 20 == 0`. Each held-out document belongs to the script it has more code points of. Columns are per language, 64 lines each.
  - **Choosing L:** from {4,096, 8,192, 16,384, 32,768}, the L that minimises the mean over Hindi and Kannada of held-out bytes ÷ held-out bytes with P2a (P2b), in exact fractions. Ties go to the smaller L.
- **Guards:**
  - It refuses the controlled evaluation datasets as a corpus, by SHA-256 and by any path under `datasets/`.
  - It refuses to write under `codec/` without `--freeze`.
  - It refuses `--freeze` with a corpus label that says "synthetic" or "fixture", and refuses `--freeze` together with `--fixed-l`, `--allow-unfilled`, or `--l-candidates` other than the four predeclared values.
  - `--allow-unfilled` exists for tests and diagnostics only. It gives unfilled learned slots back to ASCII entries; the fixture needs it.

## Outputs (to `--out-dir`)
- `<name>.bin`: the vocabulary.
- `<name>.sha256`.
- `<name>.manifest.json`: L selection table, ID ranges, corpus label and SHA-256, and `evaluation_data_read: false`.
- `<name>.heldout_check.tsv`: held-out column payloads and the expected P2b sizes, so the C++ tests can check that the Python size model matches the encoder.

## Commands
```bash
python3 -I tests/p2c/fixtures/make_synthetic_corpus.py /tmp/fixture.jsonl
python3 -I codec/p2c/build_vocabulary.py --corpus /tmp/fixture.jsonl \
  --corpus-label "synthetic unit-test fixture (not a real corpus)" --out-dir /tmp/p2c-fixture --allow-unfilled
python3 -I tests/p2c/test_build_vocabulary.py
```
The CMake target `hashcode_p2c_fixture_vocabulary` does the same thing inside the build directory, for `hashcode_p2c_tests` and for smoke runs.

## Design decisions
The five provisional decisions recorded earlier were resolved on 2026-10-24, before any real data was touched. So were the 16-byte/akshara bound, the held-out column values and L selection. The record is in `docs/phase2_p2c_report.md` §3 (D1–D8). They still need the owner's approval (plan §8.5). No real L is chosen and no vocabulary is frozen.

## Real-data tools (approved source: Wikipedia `hiwiki` + `knwiki`, dump 20261001)
**Fixture tests prove the tools behave as specified. They don't show anything about real-world compression.**

### Converter: `convert_wikipedia.py` (`p2c-wikipedia-converter-v1`, markup rule `wikitext-strip-v1`)
- **Input:** `<wiki>-<date>-pages-articles.xml.bz2`. Its SHA-1 is checked against the official `<wiki>-<date>-sha1sums.txt` **before** any parsing.
- **Output:** JSONL `{"doc_id": "<wiki>:<page id>", "text": ...}`, in dump order, plus a stats JSON. It refuses to write inside the repository.
- **Pages kept:** namespace 0 only, no redirects, `<text>` present, and text non-empty after stripping. Every skipped page is counted by reason.
- **Unicode:** no normalization, no case folding, no entity decoding.
- **The markup rule** is listed step by step in the module docstring.

### Vocabulary checker: `check_vocabulary.cpp` (CMake target `hashcode_p2c_check_vocabulary`)
- **Code reuse:** it uses the existing `p1::Vocabulary` loader and the P2b codec, and defines no format of its own.
- **Format checks:**
  - the `P1V1` magic and entry count;
  - entry lengths 1–16 and no truncation or trailing bytes;
  - IDs 0–255 are the single bytes, with no duplicates;
  - exactly 65,536 entries;
  - an independent re-parse that matches the Python builder's reading;
  - table ID = SHA-256 prefix, and optionally the SHA-256 against a `.sha256` file.
- **Layout against P2a** (`--p2a`): core IDs 0–5,247 equal P2a's; learned entries are single-script with an optional leading space, Devanagari before Kannada, and not already in P2a; the ASCII tail is P2a's ASCII prefix.
- **Round trips:** every entry encodes as exactly one token (its own ID) and decodes exactly. So do 210 mixed inputs: all 256 bytes, invalid UTF-8, emoji and ZWJ, both spellings of क़, cuts inside code points, and random concatenations of entries.
- **Size model** (`--heldout-check`): the Python size model equals the C++ encoder on the held-out columns.
- **Exit codes:** 0 OK, 1 a check failed, 2 malformed file or usage error. It prints a JSON summary.

### Pipeline: `run_wikipedia_pipeline.py`
1. Refuse to run if any `*.partial` file is present or an input is missing.
2. Verify the official SHA-1s.
3. Check that each bz2 stream is complete.
4. Convert both wikis. An existing conversion is reused only if its recorded checksums still match.
5. Run the exact-overlap check against the controlled evaluation datasets. It only reads them, and only reports.
6. Run two independent builds with `--freeze` (all D1–D8 guards) and compare them byte for byte.
7. Run the C++ checker.
8. Copy the vocabulary into `codec/p2c/` without ever overwriting different content.
9. Do smoke round trips in the HCC1 harness on the controlled datasets, with the auditor. This is validation only.
10. Run the unit tests.

**It stops before any evaluation.**
- **Exit codes:** 10 missing or partial input, 11 checksum, 12 unreadable dump, 13 conversion, 14 overlap check, 15 build, 16 the builds differ, 17 checker, 18 frozen-file conflict, 19 tests or audit.
- **Where outputs go:** training text, the held-out check files and smoke artifacts stay in `/Users/Shared/hashcode-data/wikipedia/20261001/`. Only text-free records go to `results/phase2/p2c-wikipedia-20261001-build/`.
- **`--synthetic-dry-run`:** runs everything on hand-written XML (`tests/p2c/fixtures/synthetic_wiki_dumps.py`) in a temporary directory, with test-only `--allow-unfilled` and nothing written to `codec/`.

**Safe offline:**
- every unit test;
- `--synthetic-dry-run`;
- the checker on any existing vocabulary.

**Needs the verified downloads:** the real pipeline.

```bash
python3 -I tests/p2c/test_convert_wikipedia.py; python3 -I tests/p2c/test_check_vocabulary.py; python3 -I tests/p2c/test_pipeline_dry_run.py
python3 -I tests/p2c/fixtures/synthetic_wiki_dumps.py /tmp/p2c-dry && python3 -I codec/p2c/run_wikipedia_pipeline.py --synthetic-dry-run --data-root /tmp/p2c-dry
python3 -I codec/p2c/run_wikipedia_pipeline.py      # real run: only after both downloads have finished (refuses *.partial)
```
