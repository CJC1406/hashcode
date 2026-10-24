# Phase 2, experiment 3: P2c implementation report (controlled data only)

**Status:**
- **Technical prototype: complete and tested.** It covers the builder, the codec integration, the harness, runner and auditor support, and the tests.
- **Benchmark: blocked.** A valid P2c vocabulary needs an approved training corpus (D3). None exists, so no P2c vocabulary was frozen and no comparison against `sgtt`, P1, P2a or P2b was run.
- **No compression-effectiveness claim is made.**
- **Data used:**
  - a synthetic pseudo-word fixture, generated from code-point tables;
  - the controlled datasets `kn_hi_v1` (`359269f4…`) and `en_mixed_v1` (`6c4685c2…`), for smoke and correctness runs only.
  - Nothing was downloaded, no access gate was accepted, and no external corpus was used. No evaluation text was used to build or rank entries.
- **Plan:** `docs/phase2_p2c_plan.md` is unchanged. The success criteria (`docs/phase2_proposal.md` §7) are unchanged.

## 1. What existed before this step
- **Frozen vocabularies:** P1 (`8c85586c…`) and P2a (`c99ff52f…`). P2b uses the P2a vocabulary with HCC1 codec 3.
- **P2b codec:** `codec/include/p2b_codec.hpp`. It writes a width byte, an optional sorted `u16` mapping, `u8` or `u16` IDs, and a BTT2 footer with the table ID. It already accepts any P1-format vocabulary.
- **P2b result:** on controlled data, 13,331 bytes against 12,300 for `sgtt`. Long Indic text is the gap: P2b needs 1.6–2.0× as many tokens as `sgtt` there (`docs/phase2_p2b_report.md`).
- **P2c plan:** `docs/phase2_p2c_plan.md`, with the training-source review, the design and the owner decisions. No training source is approved.

## 2. What was implemented
| Part | File | Notes |
|---|---|---|
| Vocabulary builder | `codec/p2c/build_vocabulary.py` | separate from encoding and evaluation (plan §4.2–4.4) |
| Builder notes | `codec/p2c/README.md` | |
| Synthetic fixture generator | `tests/p2c/fixtures/make_synthetic_corpus.py` | pinned SHA-256 `17457b47…` |
| Builder tests | `tests/p2c/test_build_vocabulary.py` | 34 tests |
| Codec tests | `tests/p2c/P2cCodecTest.cpp` | 8 test cases |
| Sanitizer fuzz driver | `tests/p2c/asan_fuzz_driver.cpp` | |
| CMake | `tests/cmake/p2c_targets.cmake`, hooked from `attach_to_upstream.cmake` | builds the fixture vocabulary in the build directory |
| Harness | `benchmarks/phase1/column_harness.cpp` | optional method `p2c_learned_column` (P2b codec), enabled only when `HASHCODE_P2C_VOCABULARY` is set |
| Runner | `benchmarks/phase1/run_column_benchmark.py` | `--p2c-vocabulary PATH` |
| Auditor | `benchmarks/phase1/audit_column_results.py` | `p2c_learned_column` checked under the P2b width and mapping rules |

**Builder:**
- **Inputs:** the frozen P2a vocabulary (SHA-checked) and a JSONL corpus.
- **Steps:**
  1. Split documents by `SHA-256(doc_id) mod 20`.
  2. Segment each line into single-script runs and aksharas, using the P1 classification rules (Unicode 16.0.0, checked).
  3. Count candidates of one or more aksharas, at most 16 bytes, with and without the run's leading space (§3 D5, D6).
  4. Rank by `count × (P2a tokens − 1)`. Ties go to the longer entry, then ascending bytes.
  5. Take exactly L/2 entries per language. An L is eligible only if both quotas fill (§3 D1, D2).
  6. Choose L by the equal-weight per-language held-out ratio against P2b, with ties going to the smaller L (§3 D8).
  7. Write the vocabulary, SHA-256, manifest and held-out cross-check file.
- **Layout:** P2a IDs 0–5,247 unchanged, then learned Hindi entries, then learned Kannada entries, then P2a's ASCII entries truncated. Always 65,536 entries, so IDs stay `u16`.

**Codec decision:** the **P2b codec is reused unchanged** (HCC1 codec 3, BTT2 footer).
- **P2c is identified by its vocabulary:** the 8-byte table ID (SHA-256 prefix) in the footer. The manifest names it `p2c-learned`.
- **Why no new codec value:** the container and blob format are identical, so a new value would add a code path without adding information. Wrong-vocabulary blobs are already rejected by table ID (tested in both directions).
- **No P2b decoding behaviour changed.** No historical result was rewritten.

**Guards:**
- The builder refuses the controlled evaluation datasets, by SHA-256 and by any path under `datasets/`.
- It refuses to write under `codec/` without `--freeze`.
- It refuses to freeze from a corpus labelled synthetic or fixture.

## 3. Design decisions (resolved 2026-10-24, before any real data)
**What counted as provisional:** the builder README listed **five** provisional decisions, D1–D5 below. Report §3 listed the same five, plus a finding (D6) and a detail (D7). Ranking (D3) and L selection (D8) are resolved here too, because both determine the vocabulary.

**How these were decided:** every resolution follows from the codec's structure, the pre-registered per-language criterion, or reproducibility. **None was chosen by looking at fixture or evaluation results.** The fixture only tests that each rule is implemented as stated.

**Unchanged throughout:**
- deterministic construction;
- single-byte fallback (IDs 0–255);
- exactly 65,536 entries and `u16` IDs;
- the P2b codec and decoder.

The builder is now `p2c-builder-v2`.

### D1. Learned slots the corpus can't fill
- **Before:** unfilled slots were silently given back to ASCII entries, for any L. An unfilled L of 32,768 gave the same vocabulary as a smaller L, so the selection table could name an L that was never really built.
- **Alternatives considered:**
  - (a) keep giving slots back to ASCII;
  - (b) give them to the other language;
  - (c) fail the build;
  - (d) make that L ineligible.
- **Resolution: (d).**
  - An L is eligible only if **both** languages have at least L/2 ranked candidates (score > 0).
  - Ineligible L values are listed in the manifest (`fillable`, `eligible`) and skipped. If no candidate L is eligible, the build fails.
  - So a selected or frozen vocabulary never has an unfilled slot.
  - Giving slots back to ASCII remains only behind `--allow-unfilled`, for tests and diagnostics; `--freeze` refuses it.
- **Why:** it keeps the L table honest and makes a corpus too small for the L range fail loudly. The 65,536-entry total is unaffected.

### D2. A language's unused quota
- **Before:** a strict 50/50 split with no transfer.
- **Alternatives considered:**
  - transfer unused slots to the other language;
  - one joint ranking across both languages;
  - quotas proportional to each language's share of the corpus.
- **Resolution:** **a strict 50/50 split; quotas never move between languages.** Under D1, an unused quota can't occur in a selected vocabulary.
- **Why:** the criterion needs at least 5% in **each** of Hindi and Kannada.
  - Scores scale with raw counts, so a joint or proportional ranking would hand slots to whichever language has more training text. Each language's result would then depend on corpus size.
  - Transfer only matters when a language runs out of candidates, which D1 already rejects.

### D3. Ranking, tie-breaks and re-scoring
- **Before and after (unchanged):**
  - Score is `count × (P2a tokens − 1)`, counting every occurrence, including overlapping ones.
  - Ties go to the **longer** entry first, then to **ascending bytes**.
  - Candidates already in P2a, and those that save nothing, are skipped.
  - There is **no re-scoring** after each pick.
- **Alternatives considered:**
  - re-tokenize and recount after each pick (BPE-like);
  - a fixed number of re-scoring rounds;
  - picking entries directly by held-out gain.
- **Resolution:** keep the procedure the plan pre-registered.
- **Why:**
  - **Cost:** one counting pass is deterministic and cheap.
  - **Redundancy:** overlapping picks (for example `ಞಧಿನೆ` and `ಞುಞಧಿ` from one word) waste slots. But L is chosen by the actual greedy-encoded held-out bytes, so that waste is measured, not hidden.
  - **One variable at a time:** a re-scoring builder would be a separate variant.
  - **Longer first:** at equal tokens saved, the longer entry covers more bytes per ID.
  - **Ascending bytes:** makes the order total, so the ranking depends only on the counts (tested to be independent of insertion order).

### D4. Corpus format
- **Before and after:** JSONL `{doc_id, text}` is the builder's only input.
  - Lines split on `\n`, and `\r` stays in the line. It belongs to neither script, so it never enters a candidate.
  - Text that can't be encoded as UTF-8 (lone surrogates) is rejected.
- **Alternatives considered:** plain text files, or reading source-native formats (for example a Wikipedia XML dump) directly.
- **Resolution:** keep JSONL. Each approved source gets its **own converter** (not written yet; it depends on the source). The converter must:
  - use the source's **stable** document ID as `doc_id`, because the held-out split hashes it;
  - apply **no Unicode normalization**;
  - follow a documented markup-stripping rule;
  - record the source version and the SHA-256 of its input and output.
- **Why:** source-specific parsing stays out of the builder, and the split stays reproducible across re-exports.

### D5. Single-akshara candidates
- **Before:** excluded, because the plan said 2–8 aksharas.
- **Alternatives considered:** keep them excluded; include only conjuncts; include any single akshara that saves at least one P2a token.
- **Resolution:** **include any single akshara**, with or without a leading space, that P2a needs **at least 2 tokens** for (`MIN_AKSHARAS = 1`). The existing score already excludes aksharas P2a covers in one token, so there is no special case.
- **Why:**
  - P2a splits conjuncts (`क्ष`, `त्र`, Kannada ottakshara) and aksharas with two signs at the virama.
  - These occur constantly inside words longer than 5 code points, where a whole-word entry can't fit (D6). Covering them is the only way a learned entry helps there.
  - They compete for slots under the same score.
  - This amends plan §4.2 **before any data**; it needs the owner's approval (plan §8.5).

### D6. 16-byte limit versus the 8-akshara bound
- **Before:** both limits were in the code. The 8-akshara bound never applied, because Devanagari and Kannada code points (and ZWJ/ZWNJ) are 3 bytes each.
- **Resolution:** **16 bytes is the only length limit**, and the akshara bound is removed.
  - 16 bytes is the P1/P2b codec limit and also upstream `sgtt`'s default maximum token size.
  - So an Indic entry has **at most 5 code points**, with or without its leading space (tested).
- **Consequence:** many Hindi and Kannada words can't be a single entry. For example, `नमस्ते` is 6 code points, 18 bytes. Raising the limit would mean a new codec version, because the tokenizer and lookup tables are fixed at 16. That is **not** done: it is out of scope, and would be a separate experiment.

### D7. Values in held-out columns
- **Before and after:** each held-out line is one value. A column holds up to 64 consecutive lines, and its payload is the concatenation of the lines, as in the harness and as in the plan's 64-sentence evaluation columns.
- **Change, from D8:** columns are now built **per language**.

### D8. Choosing L from held-out training data
- **Before:** the smallest **total** held-out bytes over all held-out columns, ties to the smaller L.
- **Alternatives considered:**
  - the plain total (weights each language by its share of the corpus);
  - equal-weight per-language ratios;
  - the worst of the two ratios (minimax);
  - a separate L per language (impossible: there is one vocabulary).
- **Resolution:**
  - **Candidates:** L ∈ {4,096, 8,192, 16,384, 32,768}, unchanged.
  - **Held-out split:** `SHA-256(doc_id) mod 20 == 0`, unchanged.
  - **Language of a held-out document:** the script with more code points. Documents with neither script, or a tie, are excluded and counted (`heldout_documents_without_language`).
  - **Objective:** **the mean over Hindi and Kannada of (held-out HCC1+P2b bytes with L) ÷ (the same with the P2a vocabulary, i.e. P2b)**, as exact fractions.
  - **Eligibility:** only L values eligible under D1 are scored.
  - **Ties:** the smaller L.
  - **Coverage:** both languages must have held-out columns, or selection fails.
  - FLORES+ and the evaluation datasets are never used.
- **Why:**
  - The criterion is per language, and the plain total would let the larger sub-corpus decide L.
  - A ratio against P2b makes the two languages comparable.
  - Exact fractions avoid floating-point ties.
  - The mean is a pre-registered choice; minimax was rejected to keep one smooth objective. Both remain proxies, since the criterion compares against `sgtt`, which the Python builder cannot run.
- **Not done:** L was **not** finalized and no real vocabulary was frozen. The fixture can't fill any default L (1,923 Hindi and 1,746 Kannada candidates, against 2,048 needed), which correctly makes a fixture build without `--allow-unfilled` fail.

## 3a. P2b corruption detection (separate issue; nothing changed)
- **Observation:** the sanitizer fuzz run (§4) mutated about 55,000 blobs. 20,087 of them decoded **without error to different bytes**; there were 0 sanitizer reports.
- **Cause:** P2b blobs carry **no checksum**.
  - With 65,536 entries, every 16-bit ID is valid; in width-1 blobs, every local ID below m is valid.
  - The decoder checks structure: width byte, mapping count and order, ID range, length, footer magic, version and table ID. It doesn't check content.
  - In HCC1, the length table catches a substitution only when the decoded size changes.
- **Scope:**
  - The same holds for P1/P2a (BTT1) and raw HCC1. P2c inherits it unchanged.
  - A text search of upstream `sgtt`'s sources found no checksum in its format either (only the LZ4 and XZ wrappers mention one). This was a `grep`, not a full review.
- **Not changed:** P2b's format, its decoder and every recorded result are unchanged.
- **Options for the owner:**
  - (a) leave integrity to the storage layer, and keep the compression formats as they are;
  - (b) a new P2b blob version or codec value with a CRC32C of the decoded payload. That adds 4 bytes per non-empty column, which must be charged in the accounting, and it would be a separate experiment;
  - (c) a checksum in the HCC1 container for **all** methods, so raw, `sgtt` and P2 pay the same.
- **Proposed comparison policy (a proposal, NOT an approved decision):**
  - Leave the P1/P2a/P2b/P2c codec formats and the HCC1 container unchanged.
  - For the compression comparison, rely on storage-layer integrity.
  - If integrity protection becomes a requirement, consider **one common container-level checksum, applied equally to every method** (raw, `sgtt`, P1–P2c), and charge it in the accounting.
  - No checksum change is implemented. **This needs the owner's decision** (§8).

## 3b. Consistency check of D1–D8 (2026-10-24)
The code (`codec/p2c/build_vocabulary.py`), tests (`tests/p2c/`), plan, builder README and this report were compared decision by decision.

| Decision | Where in the code | Tests | Finding |
|---|---|---|---|
| D1: an L is accepted only if both quotas fill; otherwise fail; `--allow-unfilled` is test-only | `eligible`, `select_l`, `build` (fixed-L check), CLI freeze guard | `test_eligibility_and_objective`, `test_fixed_l_must_be_fillable`, `test_ties_go_to_smaller_l`, CLI freeze test | Consistent. **Wording fixed:** the layout lines said "≤ L/2" without saying that fewer happens only with `--allow-unfilled` |
| D2: strict 50/50, no transfer | `assemble` slices each language separately | **added** `test_quotas_never_transfer` (10 Hindi against 100 Kannada candidates at L = 40 → 10 + 20, 10 slots to ASCII, L ineligible) | Consistent; previously not tested directly |
| D3: score = tokens saved, every occurrence; ties longer then bytes; no re-scoring | `count_candidates`, `rank` | `test_score_and_tie_breaks`, `test_ranking_independent_of_insertion_order`, **added** `test_overlapping_occurrences_all_count` | Consistent; overlapping occurrences were previously not tested directly |
| D4: JSONL only; converters keep stable IDs, no normalization | `read_corpus` (JSONL, string fields, unique `doc_id`, encodable text) | `test_malformed_corpora` | Consistent. **Limitation:** the builder can't check that a converter kept IDs stable or skipped normalization. These stay converter requirements, to be tested when a converter exists |
| D5: single aksharas when P2a needs ≥ 2 tokens | `MIN_AKSHARAS = 1`, plus `score > 0` in `rank` | `test_single_akshara_conjuncts_rank_when_they_save_tokens`, `test_exact_counts` | Consistent |
| D6: 16 bytes only; no akshara bound | `count_candidates` breaks at 16 bytes; `check_vocabulary` | `test_sixteen_byte_limit`, `test_no_separate_akshara_cap`, layout invariants | Consistent |
| D7: one line per value, 64 per column, per language | `heldout_columns`, `doc_language` | `test_heldout_columns_per_language`, `test_doc_language` | Consistent. **Recorded detail:** a mixed-script document goes wholly to the script with more code points; tied or script-less documents are excluded and counted |
| D8: four predeclared L values; equal-weight mean of per-language ratios against P2b; ties to smaller L | `select_l` (exact fractions) | `test_eligibility_and_objective`, `test_objective_weights_languages_equally`, `test_selection_requires_both_languages`, `test_ties_go_to_smaller_l` | **Gap fixed:** `--l-candidates` could override the four predeclared values even with `--freeze`. The CLI now refuses `--freeze` unless the candidates are exactly {4,096, 8,192, 16,384, 32,768} (tested) |
| §3a corruption policy | none (documentation only) | none | Recorded as a proposal, not a decision |

**Effect on the fixture vocabulary:** none. The fixes touch the CLI guard and documentation only, so the SHA-256 stays `39e4ac84…`.

## 4. Tests and commands
Logs: `results/phase2/p2c_build_and_test_logs/`.
```bash
cmake -S external/token-vldb2026 -B external/token-vldb2026/build-arm64      # finds Python 3.14.4 (Unicode 16.0.0)
cmake --build external/token-vldb2026/build-arm64 --target hashcode_p2c_tests hashcode_p2b_tests hashcode_p2a_tests hashcode_p1_tests hashcode_column_tests phase1_column_harness hashcode_roundtrip_tests   # exit 0
python3 -I tests/p2c/test_build_vocabulary.py                               # OK: 36 tests (builder v2, after the §3b fixes)
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p2c_tests       # exit 0: 73,385 / 73,385 assertions, 8 test cases (builder v2 fixture vocabulary)
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p2b_tests       # exit 0: 101 / 101
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p2a_tests       # exit 0: 65,662 / 65,662
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p1_tests        # exit 0: 7,652 / 7,652
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_column_tests    # exit 0: 697 / 697
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_roundtrip_tests "~[empty]"   # exit 42: the same 7 known failures
external/token-vldb2026/build-arm64/test/test                               # exit 42: the same 2 known upstream discrepancies
clang++ -std=c++23 -O1 -g -fsanitize=address,undefined ... tests/p2c/asan_fuzz_driver.cpp   # 0 sanitizer reports (see below)
```

**Builder tests (Python):**
- The fixture generator is deterministic and matches its pinned SHA-256.
- Two builds, and the CLI against the library, are byte-identical. The golden fixture-vocabulary SHA-256 is `39e4ac84…` for builder v2, built with `--allow-unfilled` (it was `32d139cf…` for v1). The CMake-built copy matches.
- With `L = 0` the builder reproduces P2a exactly (same SHA-256).
- Layout invariants:
  - core IDs equal P2a;
  - exactly 65,536 distinct entries;
  - learned entries are ≤ 16 bytes, valid UTF-8, single-script with an optional leading space, start on an akshara boundary, are 1–5 aksharas long, are not already in P2a, and appear in rank order;
  - the ASCII tail is P2a's ASCII prefix.
- Capacity: odd, negative and oversized L are rejected. The validator rejects duplicates, a changed core, mixed-script entries and the wrong entry count.
- Segmentation: conjuncts, nukta, ZWJ/ZWNJ, final virama, independent vowels, digits and danda, stray signs, script changes, leading spaces, and empty or ASCII-only lines.
- Candidates: exact counts, no joining across lines or documents, the 16-byte limit, and separate counts per language.
- Ranking: the score, both tie-breaks, skipping P2a entries, and independence from insertion order.
- Greedy tokenizer: matches a naive longest-prefix reference on 300 random byte strings (cuts inside code points included). A learned entry beats its P2a pieces.
- P2b size model: the width rule at 256 and 257 distinct IDs, and the empty payload.
- L selection: the arg-min with the smaller-L tie-break. On the fixture, all four default L values tie, so 4,096 is chosen.
- Held-out text never affects the counts: building from the training split alone gives the same vocabulary.
- Guards: both evaluation datasets are refused, as are paths under `datasets/`, duplicate or malformed documents, lone surrogates, `codec/` without `--freeze`, and `--freeze` with a fixture.

**Codec tests (C++, fixture vocabulary):**
- Layout and identity: the table ID equals the SHA-256 prefix and differs from P2a's. The core, learned and ASCII ranges are checked.
- Every 97th learned entry encodes as a single token where P2a needs more than one.
- Overlapping and concatenated candidates tokenize the same as a reference greedy implementation.
- Exact round trips: empty input, NUL, LF/CR/CRLF/tab, Hindi, Kannada, ASCII, mixed text, emoji/ZWJ/₹, invalid UTF-8, all 256 bytes, learned entries, 5,000 × `a`, every prefix cut, and long repetitive input (1-byte IDs).
- Fallback is counted.
- Wrong vocabulary is rejected in both directions (P2c blob with P2a, P2b blob with P2c), and a BTT1 blob is rejected.
- Malformed blobs are rejected: width, mapping count, local ID equal to m, footer magic, version and table ID, every truncation, and an odd 2-byte stream.
- ID `0xFFFF` decodes to the last entry and is not read out of bounds.
- HCC1: a learned entry split across two values reconstructs exactly, and reported sizes equal serialized sizes. An empty payload has no blob.
- The Python size model equals the C++ encoder on the held-out fixture columns (tokens, distinct IDs, width and blob bytes).

**Sanitizer fuzz (ASan + UBSan):**
- 12 inputs, round-tripped exactly.
- For each input, every truncation plus 4,000 random 1–3-byte mutations (some with deletions), about 55,000 malformed blobs in total.
- 0 sanitizer reports. 34,937 were rejected and 20,087 decoded without error.
- Acceptance is expected: P2b has no checksum, and every 16-bit value is a valid ID in a 65,536-entry table, so a mutated token byte decodes to *different* bytes rather than failing. This is an existing property of P2b, not something new in P2c.

**Smoke runs** (`results/phase2/`, 3 columns each; plumbing only, not evidence):

| Run | Rows | Validation | Audit | Comparison |
|---|---|---|---|---|
| `p2c-default-kn-hi-column-smoke-1` (no P2c vocabulary) | 18 | 0 problems | 0 problems | **0 differences** against the recorded `p2b-kn-hi-column-smoke-1` |
| `p2c-default-en-mixed-column-smoke-1` | 18 | 0 | 0 | **0 differences** against `p2b-en-mixed-column-smoke-1` |
| `p2c-fixture-kn-hi-column-smoke-1`, `-2` (fixture vocabulary) | 21 each | 0 | 0 each | runs 1 and 2: 0 differences |
| `p2c-fixture-en-mixed-column-smoke-1`, `-2` | 21 each | 0 | 0 each | runs 1 and 2: 0 differences |

- The default runs show that the harness change is inert when no P2c vocabulary is given.
- The fixture runs show that `p2c_learned_column` round-trips exactly, is deterministic, and passes the auditor's P2b width and mapping checks.
- Their `run_metadata.json` records the vocabulary's SHA-256 (`32d139cf…`, the **builder v1** fixture vocabulary) and its label, "synthetic unit-test fixture (not a real corpus)". They are kept as recorded.
- After the v2 decisions, two more smoke runs with the v2 fixture vocabulary (`39e4ac84…`), written to a scratch directory outside the repository, gave 21 rows each, 0 validation problems, 0 differences between them and 0 audit problems.
- **Their byte counts are deliberately not reported or compared.** The vocabulary was learned from meaningless pseudo-words.

## 5. Results
- **Compression results: none.** The only P2c vocabulary that can be built today comes from the synthetic fixture.
  - Comparing it against raw, `sgtt`, P1, P2a or P2b on the controlled datasets would measure pseudo-word coincidences, not P2c.
  - Building one from the controlled datasets is forbidden, because they are the evaluation data.
  - So, as instructed, **the benchmark part stops here.**
- **Fixture build:**
  - 228 training and 12 held-out documents, 1 held-out column.
  - **Builder v2:** 1,923 Hindi and 1,746 Kannada candidates ranked. No default L can be filled, so a normal build fails (D1). The test vocabulary is built with `--allow-unfilled`: 3,669 learned entries, with 427 slots returned to ASCII.
  - **Builder v1, for the record:** 1,576 and 1,413 candidates.
  - The table ID differs from P2a's.
  - These numbers describe the fixture only.

## 6. Accounting
- **Unchanged from P2b:** stored bytes per column = HCC1 header (6) + boundary table + width byte + mapping (if width 1) + token IDs + BTT2 footer (13).
- **How it is reported:**
  - the harness reports the mapping (with the width byte) as `bitmap_bytes`/`mapping_bytes` and the token IDs as `encoded_payload_bytes`;
  - the runner and auditor check that the components sum to the serialized container size;
  - the C++ tests check `blob = mapping + tokens + footer`, and the cross-check matches the Python model.
- **Vocabulary:** a shared static asset, reported separately and not charged per column, under the same rule as the baselines. The v2 fixture vocabulary is 465,966 bytes (v1: 462,766), against 445,881 for P2a, because learned entries are longer than the ASCII entries they replace. It is recorded in `shared_vocabulary_files.p2c` and in the one-shot fields.
- **Metadata change:** new runs now carry a `p2c_vocabulary` key in `run_metadata.json`, which is `null` without `--p2c-vocabulary`. Earlier runs are unchanged.

## 7. Outcome
| Item | Status |
|---|---|
| Builder (deterministic, isolated, P2a-derived, 65,536 entries, `u16`) | **complete** (prototype) |
| L-selection logic | **complete; tested on synthetic data only.** L is **not** finalized |
| Codec integration (P2b codec reused, vocabulary identified by table ID) | **complete** |
| Tests, sanitizer fuzz, smoke, repeated runs, audit | **complete:** all pass, with only the known failures |
| Frozen P2c vocabulary | **blocked:** needs an approved training corpus (D3) |
| Controlled-data comparison of P2c with the baselines | **blocked:** no valid vocabulary; using evaluation text is forbidden |
| Phase 2 success criterion (real data) | **blocked:** D3 (training source, FLORES+ approval) |

## 8. Approval checklist (all pending; nothing here is approved)
"Recommendation" is the project's suggestion. It is **not** an approval. Only the project owner can change a status.

| # | Item | Status | Recommendation (not an approval) |
|---|---|---|---|
| 1 | D1: an L only if both quotas fill; `--allow-unfilled` test-only | **pending** | approve as written (§3) |
| 2 | D2: strict 50/50, no transfer | **pending** | approve |
| 3 | D3: tokens-saved score, every occurrence, longer-then-bytes ties, no re-scoring | **pending** | approve |
| 4 | D4: JSONL only; converters keep stable IDs and don't normalize | **pending** | approve; the converter is written only after a source is approved |
| 5 | D5: single aksharas that P2a needs ≥ 2 tokens for (amends plan §4.2) | **pending** | approve |
| 6 | D6: 16-byte limit only; no akshara bound | **pending** | approve |
| 7 | D7: one line per value, 64 per column, per language | **pending** | approve |
| 8 | D8: the four predeclared L values; equal-weight per-language ratio against P2b; ties to smaller L (amends plan §4.4) | **pending** | approve |
| 9 | Corruption-detection policy (§3a) | **pending** | the proposal: formats unchanged, storage-layer integrity for the comparison, and a common container-level checksum for all methods only if integrity becomes a requirement |
| 10 | Training source, version and licence for the published vocabulary file (§9) | **pending** | review Wikipedia `hiwiki` + `knwiki` (dump 20261001) first. That means accepting CC BY-SA 4.0 + attribution for the vocabulary file if it counts as Adapted Material, or getting legal advice. Sangraha *Verified* comes second, pending clarification from AI4Bharat |
| 11 | Commercial status of ByteME/Hashcode | **pending** | owner to state; it decides whether CC BY-NC sources (IITB) are eligible |
| 12 | FLORES+ (evaluation only): accept the access gate | **pending** | the owner accepts it personally; Claude does not |
| 13 | FLORES+: storage outside every Git repository (`/Users/Shared/hashcode-data/`) | **pending** | approve |
| 14 | FLORES+: publish aggregates only (no text-bearing artifacts) | **pending** | approve |
| 15 | FLORES+: decontamination filter on the training data (plan §4.1) | **pending** | owner to confirm that this is compatible with "should not be used as training data", or decline it and record it as a limitation |
| 16 | Download of the approved source (CLAUDE.md rule 11) | **pending** | approve the specific files and sizes at that time |
| 17 | Permission to commit this work | **pending** | everything is uncommitted and unstaged |

**Unchanged:** the success criterion. On approved real Hindi and Kannada evaluation data, P2c needs at least 5% fewer total stored bytes than the best applicable `sgtt` baseline, and no evaluated group may be more than 5% worse. It stays **blocked** until the data is approved.

## 9. Training-source review (read-only, 2026-10-24)
Only public web pages were read: dataset cards, the papers and dump directory listings. **No dataset was downloaded, cloned or processed, and no access gate was accepted.**

**This is not legal advice.** A licence label on a dataset card is the publisher's statement about *their* release. It does not by itself settle rights in the underlying source text.

FLORES+ is **not** a training candidate. It remains evaluation-only, and none of its conditions are approved yet (§8, items 12–15).

| | **AI4Bharat Sangraha** | **Wikipedia dumps** | **AI4Bharat IndicCorp v2** |
|---|---|---|---|
| **Dataset and subset** | `ai4bharat/sangraha`; subsets *Verified*, *Unverified*, *Synthetic*; splits `hin_Deva` and `kan_Knda` (plus romanized `_Latn`) | `hiwiki`, `knwiki`, pages-articles; latest complete dump **20261001** | `ai4bharat/IndicCorpV2`; splits `hin_Deva`, `kan_Knda` |
| **Publisher; official URL** | AI4Bharat; huggingface.co/datasets/ai4bharat/sangraha. Paper: IndicLLMSuite, arXiv:2403.06350 (ACL 2024) | Wikimedia Foundation; dumps.wikimedia.org/hiwiki/20261001/, …/knwiki/20261001/ | AI4Bharat; huggingface.co/datasets/ai4bharat/IndicCorpV2. Paper: ACL 2023, aclanthology.org/2023.acl-long.693 (arXiv:2212.05409) |
| **Hindi/Kannada content** | Card table, tokens (millions): Hindi Verified 12,617.3, Unverified 12,348.3, Synthetic 9,578.7; Kannada Verified 1,778.3, Unverified 388.8, Synthetic 12,087.4 | `hiwiki-20261001-pages-articles-multistream.xml.bz2` 240.2 MB; `knwiki-…` 112.3 MB (compressed; listing only). md5 and sha1 sum files are published | Paper Table 3: Hindi 6,107M tokens, Kannada 875M tokens. Viewer: about 152M and 48.7M rows |
| **Format** | Parquet, viewer fields `doc_id` (64-character string) and `text` | MediaWiki XML with wikitext markup; needs a markup-stripping converter (D4). The page-ID field must be confirmed on the actual file before relying on it | Viewer: one `text` column, **no document ID**. The IndicBERT README describes preprocessing input as "one sentence per line, empty line between documents"; the release format isn't confirmed |
| **Stated dataset licence** | Card label **`cc-by-4.0`**; no licence text on the card. The paper says artifacts are "released with permissive licenses" | Dumps page: original text under **GFDL and CC BY-SA 4.0**; some text CC BY-SA only. Terms of Use §7 apply (foundation.wikimedia.org/wiki/Policy:Terms_of_Use) | Card and paper: datasets "will be released under a **CC-0** license" (no metadata tag seen) |
| **Licence URL** | creativecommons.org/licenses/by/4.0/ (by label only) | creativecommons.org/licenses/by-sa/4.0/legalcode.en; dumps.wikimedia.org/legal.html | creativecommons.org/publicdomain/zero/1.0/ (by statement only) |
| **Source-content rights and other conditions** | Card: **not stated**. Paper's ethics statement: "The legal landscape regarding the use of web-sourced content for training models remains ambiguous across different jurisdictions."<br>No statement about robots.txt or takedown was found.<br>*Unverified* comes from CulturaX and MADLAD-400 (paper), whose own terms were **not reviewed**.<br>*Synthetic* is machine-translated English Wikimedia text, possibly carrying CC BY-SA obligations | **Attribution:** by link or URL, or a list of authors (Terms of Use §7).<br>**Share-alike:** modified content must be CC BY-SA 4.0 or later.<br>**Risk:** dumps "may contain" unnoticed infringements and fair-use material, used "AT YOUR OWN RISK".<br>**Licence text:** CC BY-SA 4.0 defines Adapted Material as modification "in a manner requiring permission". §4 treats extracting a substantial portion of a database's contents into another database as Adapted Material where sui generis database rights exist | News articles crawled from the web (paper §4.1, Limitations: "crawled from public domains", which reads as publicly accessible, not as public-domain copyright).<br>**No statement** about the copyright of the news text.<br>AI4Bharat's CC0 can't waive rights it doesn't hold |
| **Vocabulary construction and distribution** | **Unclear.** CC BY 4.0 would permit it with attribution *if* the label covers the underlying text, which isn't established | **Unclear.** Use is permitted under the licence. Whether a ranked list of ≤ 16-byte substrings is Adapted Material (and so CC BY-SA), and whether database rights apply, is unresolved | **Unclear.** It depends on rights in the news text, which aren't addressed |
| **Plausible candidate?** | **Yes, *Verified* subset only.** It has `doc_id` fields, matching D4. Exclude *Synthetic* (machine-translated, partly romanized, Wikimedia-derived, overlaps FLORES+ domains) and *Unverified* (third-party terms) | **Yes, the clearest written licence.** Its register is encyclopedic, so it may not resemble database strings (a methodological limitation). Decontamination against FLORES+ is still needed | **Weakest.** No stable document IDs (D4 would need IDs synthesized from a pinned file and position, stable only within that revision), and the news-copyright question is open |
| **Needs legal or owner review** | Does CC BY 4.0 cover the crawled, OCR'd and transcribed sources? What attribution form? Ask AI4Bharat | Accept CC BY-SA 4.0 + attribution for the vocabulary file (or get advice); pin the dump date and checksums | Rights in the news sources; whether document boundaries exist in the release |

**Unresolved after this review:**
- whether any frequency-ranked token list is a copyright- or database-relevant derivative under each licence;
- whether the Sangraha and IndicCorp v2 labels extend to the underlying sources;
- the terms of CulturaX and MADLAD-400;
- the Wikipedia page-ID field in the actual dump, which can only be confirmed after an approved download.

**Sources (read 2026-10-24):**
- huggingface.co/datasets/ai4bharat/sangraha
- arxiv.org/abs/2403.06350 and arxiv.org/html/2403.06350
- github.com/AI4Bharat/IndicLLMSuite
- huggingface.co/datasets/ai4bharat/IndicCorpV2
- github.com/AI4Bharat/IndicBERT
- ar5iv.labs.arxiv.org/html/2212.05409
- dumps.wikimedia.org/legal.html
- dumps.wikimedia.org/hiwiki/ and /hiwiki/20261001/
- dumps.wikimedia.org/knwiki/ and /knwiki/20261001/
- foundation.wikimedia.org/wiki/Policy:Terms_of_Use
- creativecommons.org/licenses/by-sa/4.0/legalcode.en

The two papers' PDFs could not be read here: rendering them needs poppler, which is not installed and was not installed. Their HTML versions were used instead.

## 10. Decision sheet and proposed next data step (2026-10-24; nothing approved, nothing executed)
**Recommendation is not approval.** Every item below stays **pending** until the project owner approves it. The success criterion (§8) is unchanged.

### 10.1 Design decisions: one line each
| # | Decision | Needs owner input? | Recommended default |
|---|---|---|---|
| D1 | An L counts only if both languages fill their L/2 slots, else the build fails; `--allow-unfilled` is test-only and can't be frozen. | no (technical) | approve |
| D2 | Strict 50/50 Hindi/Kannada slots; unused slots never move to the other language. | no (technical) | approve |
| D3 | Rank by tokens saved, counting every occurrence; ties go to the longer entry, then byte order; no re-scoring. | no (technical, as pre-registered) | approve |
| D4 | The builder reads only JSONL; each source converter keeps stable document IDs and doesn't normalize Unicode. | no (technical) | approve |
| D5 | Single aksharas are candidates when P2a needs ≥ 2 tokens for them. | **yes:** it amends the pre-registered plan §4.2 | approve |
| D6 | 16 bytes is the only length limit; the unused 8-akshara bound is removed. | no (it changes nothing in practice) | approve |
| D7 | Held-out values are lines, 64 per column, built per language. | no (technical) | approve |
| D8 | L is chosen from the four predeclared values by the equal-weight per-language held-out ratio against P2b; ties go to the smaller L. | **yes:** it amends the pre-registered plan §4.4 | approve |
| §3a | Codec formats stay unchanged and the comparison relies on storage-layer integrity; a common container-level checksum for all methods only if integrity becomes a requirement. | **yes:** a project policy | approve the proposal |

### 10.2 Recommended training source: Wikipedia `hiwiki` + `knwiki`, dump **20261001**
| Priority | Wikipedia 20261001 | Sangraha *Verified* | IndicCorp v2 |
|---|---|---|---|
| Explicit licence for the text itself | **yes**: GFDL + CC BY-SA 4.0 (dumps legal page; Terms of Use §7) | dataset label only (CC BY 4.0); source rights not stated | dataset statement only (CC0); news-source rights not stated |
| Stable document IDs | **yes**: page IDs (field to confirm in the file) | yes (`doc_id`) | **no** |
| Both languages | yes | yes | yes |
| Reproducible extraction | **yes**: dated dump with published checksums | card has no version or date | card has no version or date |

- **Why Wikipedia:** it is the only candidate whose licence is stated *for the text by its rights holders' platform*, and it has a pinned version with checksums.
- **Known limitation:** encyclopedic register may not resemble database strings. This affects how far results generalize, not whether the source may be used.
- **Proposed CC BY-SA 4.0 compliance (a proposal; not legal advice):**
  - Publish the P2c vocabulary file **under CC BY-SA 4.0 in any case**, conservatively, without deciding whether it legally needs to be. Put this in `codec/p2c/LICENSE-vocabulary.md`.
  - Include an attribution notice: "Derived from Hindi and Kannada Wikipedia (dumps hiwiki-20261001 and knwiki-20261001), by Wikipedia contributors", with the dump URLs, licence links and a statement that the content was modified (extracted and ranked substrings).
  - Code stays under whatever licence the owner chooses. **The repository currently has no licence file.**
- **Still unresolved:** whether a frequency-ranked list of ≤ 16-byte substrings is *Adapted Material*, or a database extraction under CC BY-SA 4.0 §4. Licensing the file as CC BY-SA sidesteps the question for our own release. But it means anyone reusing the vocabulary file inherits share-alike, and **the owner must accept that**. No legal conclusion is drawn here.
- **Commercial status:** CC BY-SA permits commercial use, so the commercial-status question **doesn't block** this source. It still matters for any CC BY-NC source.
- **Availability:** Wikimedia keeps only recent dumps. If 20261001 is removed before approval, the next complete dump would need the same review. Its date and checksums would change, and nothing else.

### 10.3 Proposed data step (prepared, **not executed**)
**Files to approve for download** (sizes from the dump listing; compressed):
- `https://dumps.wikimedia.org/hiwiki/20261001/hiwiki-20261001-pages-articles.xml.bz2` (230.5 MB);
- `https://dumps.wikimedia.org/knwiki/20261001/knwiki-20261001-pages-articles.xml.bz2` (110.3 MB);
- `hiwiki-20261001-sha1sums.txt` and `knwiki-20261001-sha1sums.txt` from the same directories, to verify the downloads.

That is about 341 MB in total; disk space is about 23 GB free. The non-multistream files are chosen because they stream sequentially, with no index needed.

**Storage, outside every Git repository** (the directory doesn't exist yet; creating it is part of the approval):
- `/Users/Shared/hashcode-data/wikipedia/20261001/raw/`: the downloaded files, kept unmodified.
- `/Users/Shared/hashcode-data/wikipedia/20261001/train/p2c_train_wikipedia_20261001.jsonl`: the converter output.
- **Committed to the repository:** only a manifest, `datasets/external_manifests/wikipedia_hiwiki_knwiki_20261001.json`, with URLs, dump date, licence strings, sizes, SHA-1 from Wikimedia, SHA-256 of every input and output, document counts and the converter version. **No text** is committed.

**Converter design** (`codec/p2c/convert_wikipedia.py`; design only, **not written yet**):
- **Libraries:** Python standard library only (`bz2`, `xml.etree.ElementTree.iterparse`), streaming.
- **Pages kept:** main-namespace articles only (`ns == 0`); redirects are skipped.
- **Document IDs:** `doc_id = "hiwiki:<page id>"` or `"knwiki:<page id>"`. The revision ID goes in a sidecar count only, not in the ID, so the held-out split depends only on the page.
- **Wikitext to plain text:** a fixed, versioned, documented rule:
  - drop comments, `<ref>…</ref>`, templates `{{…}}` (nested), tables `{|…|}`, file/image and category links, and HTML tags;
  - `[[target|label]]` becomes `label`, and `[[target]]` becomes `target`;
  - `[url label]` becomes `label`;
  - remove `''`/`'''` emphasis, and keep headings' text;
  - collapse runs of blank lines.
- **No Unicode normalization,** case folding or script filtering. Bytes are kept as Wikipedia stores them.
- **Output:** JSONL `{"doc_id", "text"}`, hiwiki pages first and then knwiki, each in dump order. It is deterministic: two runs must give the same SHA-256.
- **Tests:** tests on small, hand-written synthetic XML snippets, never real dump text:
  - ID stability;
  - the markup rules;
  - no normalization (NFC and NFD inputs stay distinct);
  - skipping redirects and namespaces;
  - deterministic output.

**Separation of training and evaluation:**
- **Training:** Wikipedia only.
- **L selection:** the builder's 5% held-out split of the same training corpus.
- **Never training data:** the controlled datasets (the builder refuses them) and FLORES+.
- FLORES+ comes from Wikinews, Wikijunior and Wikivoyage, which are separate projects. Decontamination against it (plan §4.1) is still pending.

**After the conversion** (each step is a separate later action):
1. Build with `--freeze` and the default L candidates.
2. Commit the vocabulary, manifest and licence notice **before** any evaluation.
3. Only then, and only with FLORES+ approved, run the evaluation.

### 10.4 Evaluation-only data (separate; all pending)
FLORES+ 4.6 `devtest` for `hin_Deva`, `kan_Knda`, `eng_Latn` needs four approvals:
- (a) the owner accepts the access gate personally;
- (b) storage at `/Users/Shared/hashcode-data/flores_plus/4.6/`;
- (c) publishing aggregates only, with no text-bearing artifacts;
- (d) whether it may be used as a decontamination filter on the training data.

It is never used for training or for choosing L.

## 11. Wikipedia 20261001 training preparation (in progress; nothing evaluated)
**Approved by the owner:**
- D1–D8 and the corruption policy;
- Wikipedia `hiwiki` + `knwiki` dump 20261001 as the training source;
- CC BY-SA 4.0 for the vocabulary file;
- downloading the four files to `/Users/Shared/hashcode-data/wikipedia/20261001/`.

**Not approved:** FLORES+ and commits.

### 11.1 Tools (implemented and tested offline)
| Tool | File | Tests (all synthetic or hand-written) |
|---|---|---|
| Converter | `codec/p2c/convert_wikipedia.py` | `tests/p2c/test_convert_wikipedia.py`: 16 tests, covering markup rules, namespaces, redirects, empty and deleted text, page IDs (not revision or contributor IDs), no normalization (क़ U+0958 against U+0915 U+093C, é composed against decomposed), checksum refusal, truncated bz2, malformed XML, duplicate or bad IDs, refusing output inside the repo, and determinism |
| Builder v3 | `codec/p2c/build_vocabulary.py` | `tests/p2c/test_build_vocabulary.py`: 41 tests. The new ones show that streaming and sharded counting are **exactly equal** to the in-memory reference (1/3/5/7/8/9 shards, split files), and the fixture SHA-256 `39e4ac84…` is unchanged from v2 |
| Vocabulary checker | `codec/p2c/check_vocabulary.cpp` | `tests/p2c/test_check_vocabulary.py`: 5 tests, covering valid P2a and fixture vocabularies; 9 malformed files (exit 2); 7 well-formed but invalid files (exit 1: 65,535 entries, wrong SHA-256, changed core, mixed script, Kannada before Devanagari, ASCII order, wrong held-out sizes); usage errors |
| Overlap check | `codec/p2c/check_eval_overlap.py` | `tests/p2c/test_check_eval_overlap.py`: 2 tests (a planted sample is found; a clean file shows no hits) |
| Pipeline | `codec/p2c/run_wikipedia_pipeline.py` | `tests/p2c/test_pipeline_dry_run.py`: 5 tests on synthetic dumps, covering a deterministic end-to-end run, safe reruns, a changed conversion not being reused, exit codes 10/11/12/13, and the usage guards |

**Why the builder changed (v2 to v3):** this machine has **8 GiB of RAM**. v3 streams the corpus and counts each distinct word once, weighted by its frequency. It ranks candidates in shards by first code point and keeps an exact top L/2 per language. The rules and output are identical to v2 (tested).

**Synthetic dry run:**
- **Result:** the full pipeline (verify, bz2 check, convert, overlap, two builds, checker, smoke runs and audit, unit tests) finished with exit 0 in about 9 s.
- **Outputs:** 161 articles per wiki; the two builds were identical; the checker passed with all 65,536 entries round-tripping; smoke audits showed 0 problems.
- **Status:** this is **synthetic; not evidence of compression**.

### 11.2 Real run (to be filled in after the downloads finish and are verified)
| Item | Value |
|---|---|
Run on 2026-10-25 with `python3 -I codec/p2c/run_wikipedia_pipeline.py`; exit 0; it stopped before evaluation.
Records (no article text): `results/phase2/p2c-wikipedia-20261001-build/` (`pipeline_record.json`, `pipeline.log`, `checker.json`, `eval_overlap.json`, converter stats).

**Downloads:**
- The first connection ran at about 90 KB/s.
- It was stopped at 113 MB and **resumed** (`curl -C -`) on fresh connections to the same official server, at about 5 MB/s.
- The Kannada files were fetched in parallel.
- The final files match the server's sizes and the official SHA-1s.

| Item | hiwiki | knwiki |
|---|---|---|
| Dump URL | https://dumps.wikimedia.org/hiwiki/20261001/hiwiki-20261001-pages-articles.xml.bz2 | https://dumps.wikimedia.org/knwiki/20261001/knwiki-20261001-pages-articles.xml.bz2 |
| Size | 241,701,076 B | 115,640,184 B |
| SHA-1, published = verified | `eb8929c38f0791f87a93c6d65919226b3068a0da` ✓ | `66f6d094b04f750821ce00d5f4270023e1df0755` ✓ |
| SHA-256 | `ec56cc94fdad94b6d342997b62f18fed56aa35215df2331a2fbf6ab0386d1952` | `52fcddd79939e367ddf311cab131a6d63e1a212124744e7c5b26207a0d3e660c` |
| Uncompressed XML (bz2 stream complete) | 1,689,650,798 B | 777,856,566 B |
| Pages seen | 328,615 | 94,396 |
| Articles written | **174,576** | **35,929** |
| Skipped: other namespace / redirect / empty after stripping / missing text | 81,813 / 70,976 / 1,250 / 0 | 46,809 / 10,617 / 1,041 / 0 |
| Training JSONL (outside Git) | `hiwiki-20261001-articles.jsonl`, 711,412,337 B | `knwiki-20261001-articles.jsonl`, 462,871,769 B |
| JSONL SHA-256 | `1a0dec701c7ee2444902fe73f20431cfae419ce5c1f97d6ac6b47b000ad319c6` | `14becc475ea7bf95c6ab9fdb12c751f526009df1a6185841ae0349b9637350f8` |

Converter: `p2c-wikipedia-converter-v1`, markup rule `wikitext-strip-v1`. Training text is in `/Users/Shared/hashcode-data/wikipedia/20261001/train/`, outside every Git repository.

**Split and overlap:**
- **Documents:** 210,505 in total; 199,919 for training and 10,586 held out (`SHA-256(doc_id) mod 20 == 0`).
- **Held-out columns:** 1,747 Hindi and 669 Kannada; 2 held-out documents had no clear language.
- **Overlap check:** none of the 146 controlled evaluation samples, and none of their lines of 32 bytes or more (83 probes), occurs in the training text.
- **Evaluation data:** read only for this check, and never used for building.

**Vocabulary (frozen; `codec/p2c/p2c_vocabulary_v1.{bin,sha256,manifest.json}`):**

| Item | Value |
|---|---|
| SHA-256 / table ID | `1e12dc488beddfdf0242268fd17cdd90e93d834be0a81e6780754bcbc629dc84` / `1e12dc488beddfdf` |
| Entries, file size | 65,536 (u16 IDs), 655,073 B |
| Builder | `p2c-builder-v3`, 16 shards, `--freeze` guards on, `allow_unfilled = false` |
| Distinct training runs; candidates with a positive score | 2,827,437; Hindi 962,339, Kannada 738,161 |
| **Selected L** | **32,768**, of {4,096, 8,192, 16,384, 32,768}; all four can be filled |
| Learned entries | Hindi **16,384** (IDs 5,248–21,631), Kannada **16,384** (IDs 21,632–38,015); 0 slots returned to ASCII |
| ASCII entries | 27,520 (IDs 38,016–65,535) |
| Two independent builds | **byte-identical** (`.bin`, `.sha256`, manifest, held-out check file) |
| C++ checker | **OK**: layout against P2a; 65,536/65,536 entries round-trip as single tokens; 210/210 mixed inputs; Python size model = C++ encoder on 2,416/2,416 held-out columns |
| HCC1 smoke runs with the frozen vocabulary + auditor | kn-hi-v1: 21 rows, 0 problems; en-mixed-v1: 21 rows, 0 problems (round-trip validation only) |
| Unit tests run by the pipeline | builder 41, converter 16, checker 5, overlap 2, pipeline dry run 5: all OK |
| Licence notice | `codec/p2c/LICENSE-vocabulary.md` (CC BY-SA 4.0, attribution; the database-right question remains unresolved) |

**L-selection table:** the internal selection statistic, computed on held-out **training** text. **This is not an evaluation and not a compression claim.**

| L | Held-out bytes, Hindi | Held-out bytes, Kannada | Mean ratio against P2b (P2b: Hindi 15,152,132, Kannada 8,593,244) |
|---|---|---|---|
| 4,096 | 10,584,384 | 5,676,672 | 0.6796 |
| 8,192 | 9,840,800 | 5,231,077 | 0.6291 |
| 16,384 | 9,220,059 | 4,861,923 | 0.5871 |
| 32,768 | 8,763,602 | 4,588,013 | **0.5561** |

**Timings** (this machine: Apple Silicon, 8 GiB RAM):

| Step | Time | Peak memory |
|---|---|---|
| SHA-1 check | 0.5 s | |
| bz2 integrity check | 53 s | |
| Convert hiwiki / knwiki | 83 s / 41 s | |
| Overlap check | 43 s | |
| Build 1 / build 2 | 287 s / 271 s | about 1.9 GB per build |
| Total | about 13 min | |

**Blocker for any compression claim:** an approved, independent evaluation dataset. FLORES+ isn't approved, and the controlled datasets are for harness validation only.

### 11.3 Controlled-data demo (harness demonstration, not an evaluation)
`docs/phase2_p2c_demo.md`; command `python3 -I benchmarks/phase2/p2c_demo.py`.

**Result:** over the 40 controlled columns, P2c stores **9,061 B**, against 12,300 B for the best `sgtt` and 13,331 B for P2b. All rows are exact, all four runs audit with 0 problems, and the two runs per dataset show 0 differences.

**Not evidence:** this is controlled harness data, so it is not evidence for the real-data criterion, which stays blocked on an approved independent evaluation dataset.

**English:** P2c is 3.3% larger than P2b for `en` (fewer ASCII entries).

## 12. Independent evaluation workflow (prepared, not run)
`docs/phase2_p2c_evaluation.md` has the workflow, the commands, the official FLORES+ file metadata and the pending approvals.

**Implementation:**
- `benchmarks/phase2/evaluate_p2c.py` reuses the runner (new `--external-dataset` option; data and artifacts stay outside the repository), the harness and the auditor (new `--dataset-path` option).
- The vocabulary SHA-256 and the criterion are pinned in the code.
- Only aggregates are published, after a text guard.

**Status:**
- **Tests:** synthetic only (`tests/p2c/test_evaluate_p2c.py`, 8 tests).
- **Data:** no evaluation data has been accessed.
- **Criterion:** not evaluated.

**Fix found while testing:** the pipeline's time-stamped build and smoke directories could collide when two runs started within the same second. Microseconds are now included in the stamps. Frozen outputs are not affected.
