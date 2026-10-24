# Phase 1 Baseline Report: Kannada and Hindi

**Status:**
- Both modes work and pass validation.
  - **Column mode** (§C) is the primary comparison.
  - **Per-value mode** (§1–6) is kept as a diagnostic.
- The P1 entry criteria are met (§7). The dataset is accepted **for harness validation only**, and native-speaker review hasn't been confirmed. D1 and D2 are recorded.
- **P1 is implemented and evaluated (§P). Phase 1 exit decision: PASSED on its pre-registered gates, on controlled data only,** with the material caveat in §P.4.

**Runs reported:**
- **Column mode:** `results/phase1/column-full-1`, plus `column-full-2` for determinism; `column-smoke-1` and `column-smoke-2`.
- **Per-value mode:** `results/phase1/full-1`, plus `full-2` and `full-3` for determinism; `smoke-1` and `smoke-2`. `full-3` was re-run alongside column mode and has 0 differences from `full-1`.

## P. P1 evaluation and Phase 1 exit (measured 2026-10-24)
P1 is the akshara token table with byte fallback (`codec/p1/README.md`): vocabulary `p1-akshara-ascii-v1`, SHA-256 `8c85586c…`, 65,536 entries, 445,193 bytes, frozen before any measurement. It runs as HCC1 codec 2, next to the three unchanged baselines.

**Datasets** (controlled, harness validation only, **not reviewed by native speakers, not representative**):
- `phase1-kn-hi-v1`: SHA-256 `359269f4…36bb6fc`.
- `phase1-en-mixed-v1`: SHA-256 `6c4685c2…31d47b0`.
- Both checksums are unchanged.

### P.1 Commands and outcomes
```bash
python3 -I codec/p1/build_vocabulary.py                                          # ×3, identical sha256 8c85586c…
cmake --build external/token-vldb2026/build-arm64 --target hashcode_p1_tests hashcode_column_tests phase1_column_harness hashcode_roundtrip_tests   # exit 0
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p1_tests           # exit 0: 7,652 / 7,652 assertions, 7 test cases
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_column_tests       # exit 0: 697 / 697
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_roundtrip_tests "~[empty]"   # exit 42: 21,730 / 21,737, the same 7 known failures (Phase 0 Findings 3 and 4)
external/token-vldb2026/build-arm64/test/test                                  # exit 42: 57,640 / 57,642, the same 2 known upstream discrepancies
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset kn-hi-v1 --smoke --run-id p1-kn-hi-column-smoke-1        # 12 rows ok
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset kn-hi-v1 --run-id p1-kn-hi-column-full-1                 # 120 rows ok, 0 problems
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset kn-hi-v1 --run-id p1-kn-hi-column-full-2                 # compare with -full-1: 0 differences
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --smoke --run-id p1-en-mixed-column-smoke-1  # 12 rows ok
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --run-id p1-en-mixed-column-full-1           # 128 rows ok, 0 problems
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --run-id p1-en-mixed-column-full-2           # compare with -full-1: 0 differences
python3 -I benchmarks/phase1/audit_column_results.py results/phase1/<each of the 6 P1 runs>                               # 0 problems each
python3 -I benchmarks/phase1/evaluate_d2.py --out results/phase1/p1-d2-evaluation \
  --run kn-hi-v1=results/phase1/p1-kn-hi-column-full-1 --frozen kn-hi-v1=results/phase1/column-full-1 \
  --run en-mixed-v1=results/phase1/p1-en-mixed-column-full-1 --frozen en-mixed-v1=results/phase1/en-mixed-column-full-1   # exit 0, 0 baseline-integrity problems
```
Test logs are in `results/phase1/p1_build_and_test_logs/`.

### P.2 Correctness and reproducibility
- **P1 tests** cover:
  - empty input, ASCII, Hindi, Kannada, mixed scripts, emoji/ZWJ/₹, embedded NUL, LF/CRLF, invalid UTF-8, all 256 byte values, and both forms of canonically equivalent text;
  - every prefix cut, including cuts inside a character;
  - expected token boundaries, fallback counts, and a no-read-past-input check;
  - rejection of malformed blobs, and P1 inside HCC1 with empty values;
  - a structural check that the vocabulary isn't derived from data;
  - that the C++ table ID equals the build's SHA-256.
- **Benchmark:** all 248 P1-run rows are exact, value by value, in order, and the containers are byte-identical across 7 repetitions and across the two runs.
- **Frozen baselines reproduced:** the raw, OpenAI200K and Gemma3 rows in the P1 runs match `column-full-1` and `en-mixed-column-full-1` on all 21 non-timing columns.

### P.3 D2 result (pre-registered: median reduction against `baseline_c` of at least 5%)
| Group | Columns | **Median reduction vs `baseline_c`** | Columns at least 5% better | Range | D2 |
|---|---|---|---|---|---|
| hi | 8 | **+14.7%** | 4 | −329.0% … +55.1% | met |
| kn | 8 | **+17.0%** | 5 | −257.9% … +52.3% | met |
| en | 8 | **+27.0%** | 7 | −57.2% … +57.0% | met |
| en-hi | 8 | **+28.7%** | 6 | −211.9% … +56.9% | met |
| en-kn | 8 | **+32.5%** | 6 | −190.5% … +59.5% | met |

The per-column figures are in `results/phase1/p1-d2-evaluation/d2_per_column.csv`. Smallest method across the 40 columns: P1 on 22, raw on 7, OpenAI200K on 6, Gemma3 on 5.

### P.4 Caveat: the pass comes from per-column overhead, not from the akshara vocabulary
- **Byte-weighted, P1 loses.** Summed over the 40 evaluation columns:

  | | Bytes |
  |---|---|
  | raw | 43,859 |
  | best `sgtt` | **12,300** |
  | P1 | **23,223** (88.8% more than best `sgtt`) |

  On the grouped language columns:

  | Column | P1 | Best `sgtt` | P1 vs best `sgtt` |
  |---|---|---|---|
  | `col-hi-all` | 6,146 | 1,642 | −274% |
  | `col-kn-all` | 6,709 | 3,742 | −79% |
  | `col-en-hi-all` | 3,543 | 1,404 | −152% |
  | `col-en-kn-all` | 3,499 | 1,428 | −145% |
  | `col-en-all` | 2,562 | 3,185 | **+19.6%** |

- **Where P1 wins:** in **all 29** columns where P1 beats `baseline_c`, P1 spends *more* bytes on token IDs than `sgtt`. It wins only through lower fixed per-column cost: no bitmap (`sgtt` Dense costs 25–153 B), and a 13-byte instead of 24-byte footer. Most evaluation columns are small, so the median favours this.
- **Where P1 loses:** every `repeated` column (−57% to −329%) and most `medium` and `long` Indic columns.
  - `sgtt` matches whole words of up to 16 bytes with 1–2-byte Dense IDs.
  - P1 matches one akshara (3–6 bytes) per 2-byte ID.
- **Fallback:** 24.4% of P1 tokens on `kn-hi-v1` and 24.7% on `en-mixed-v1` are single-byte fallbacks. Most are spaces (87% and 63%), because the vocabulary has no entries that combine a space with an akshara.
- **P1 against raw:** smaller on 33 of 40 columns. Raw is smaller on all 5 `tiny` columns, and on `col-en-punct_numerals` and `col-en-structured`.
- **Conclusion:** the pre-registered criterion is met and is reported as met. The evidence does **not** support "the akshara vocabulary compresses Hindi or Kannada better than `sgtt`"; on the byte-heavy columns it shows the opposite. A median over 8 small synthetic columns per group isn't a good proxy for storage cost. Phase 2 must use a byte-weighted criterion (`docs/phase2_proposal.md`).

### P.5 Vocabulary and amortization
- **Shared static vocabularies, not charged per column:**

  | Codec | Bytes |
  |---|---|
  | P1 | **445,193** |
  | OpenAI200K | 3,332,170 |
  | Gemma3 | 4,275,024 |

- **P1 break-even against raw HCC1** (linear extrapolation from these columns; not measured): ≈1.06 MB of text for `hi`, 0.89 MB `kn`, 0.80 MB `en`, 0.95 MB `en-hi`, 0.86 MB `en-kn`. These come from `vocabulary / ((raw − P1) / original)` on `col-<lang>-all`.
- The vocabulary is 7–10× smaller than the `sgtt` ones, but that only matters if it has to be stored per column, and here it doesn't.

### P.6 Timing (`col-all`, median of 7, Release; this machine only)
| | Encoder setup | Encode | Decoder setup | Decode |
|---|---|---|---|---|
| P1, `kn-hi` | 9.19 ms | 0.93 ms | 9.14 ms | 0.035 ms |
| P1, `en-mixed` | 9.45 ms | 0.87 ms | 9.38 ms | 0.049 ms |
| OpenAI200K, `kn-hi` | 2.73 ms | 0.25 ms | 2.57 ms | 0.053 ms |
| Gemma3, `kn-hi` | 3.34 ms | 0.31 ms | 3.83 ms | 0.053 ms |

P1's setup reads the vocabulary file, builds 15 hash maps and computes a SHA-256. None of P1's timing was optimized.

### P.7 Phase 1 exit decision
**PASSED, for the pre-registered Phase 1 scope (harness validation on controlled data).** Evidence:
- the harness and baselines are validated and reproducible;
- P1 is implemented with exact reconstruction (7,652 test assertions; 248 / 248 benchmark rows);
- the vocabulary doesn't use evaluation data;
- all storage is accounted for, and the vocabulary is reported separately;
- D2 is met in 5 / 5 groups.

**Not established, and blocked:**
- any claim about real Hindi, Kannada, English or code-mixed data (D3 needs approval);
- any claim that P1 is a better codec; the byte-weighted result is negative (§P.4);
- Linux x86-64, AVX-512, and sanitizer runs of the P1 and column code.

## C. Column mode (primary)
The format is defined in `docs/phase1_column_protocol.md`: an HCC1 container holding a varint length table and one unmodified upstream blob of the concatenated values. Upstream has no native column API for `sgtt`.

### C.1 Commands and outcomes
```bash
cmake --build external/token-vldb2026/build-arm64 --target hashcode_column_tests          # exit 0
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_column_tests                    # exit 0: All tests passed (697 assertions in 2 test cases)
cmake --build external/token-vldb2026/build-arm64 --target phase1_column_harness phase1_harness   # exit 0
python3 -I benchmarks/phase1/run_benchmark.py --run-id full-3                               # exit 0: 325 rows, 317 ok, 8 unsupported_input, 0 problems
python3 -I benchmarks/phase1/run_benchmark.py --compare results/phase1/full-1 results/phase1/full-3            # 0 differences
python3 -I benchmarks/phase1/run_column_benchmark.py --smoke --run-id column-smoke-1        # exit 0: 9 rows ok
python3 -I benchmarks/phase1/run_column_benchmark.py --smoke --run-id column-smoke-2        # exit 0
python3 -I benchmarks/phase1/run_column_benchmark.py --compare results/phase1/column-smoke-1 results/phase1/column-smoke-2   # 0 differences
python3 -I benchmarks/phase1/run_column_benchmark.py --run-id column-full-1 --per-value-run results/phase1/full-3   # exit 0: 90 rows ok, 0 problems
python3 -I benchmarks/phase1/run_column_benchmark.py --run-id column-full-2 --per-value-run results/phase1/full-3   # exit 0
python3 -I benchmarks/phase1/run_column_benchmark.py --compare results/phase1/column-full-1 results/phase1/column-full-2     # 0 differences
```
Build and test logs are in `results/phase1/column_build_logs/`.

### C.2 Correctness and determinism
- **Container tests (Catch2):** 16 cases × 3 methods, plus malformed-container checks: 697 / 697 assertions pass.
  - The cases are: zero values, one empty value, several empty values, empties between and at both ends, one-byte values, short Kannada and Hindi, a long paragraph, mixed scripts, embedded NUL bytes, values containing `\n`, combining marks and ZWJ/ZWNJ, precomposed and decomposed forms, repeated values, and values that would be ambiguous if concatenated.
- **Benchmark (`column-full-1`):** 30 columns × 3 methods = 90 rows, all `ok`.
  - Every value matches exactly, in order, including the empty values inside `col-tiny`, `col-hi-tiny` and `col-kn-tiny`.
  - Python re-parsed all 90 containers independently, and they match the reported layout.
- **Coverage note:** the dataset contains no NUL or newline bytes. Embedded NUL and `\n` handling is therefore checked only by the Catch2 container tests, not by the benchmark runs.
- **Identical input:** the ordered-sequence hash matches the dataset in every row.
- **Independent audit:** `python3 -I benchmarks/phase1/audit_column_results.py results/phase1/<run>` re-checks the CSV, containers and decoded values without re-running anything.
  - `column-full-1`, `column-full-2` and `column-smoke-1`: 0 problems each.
  - Ratio fields match `original / total`.
  - Raw rows have no vocabulary, bitmap or footer.
  - Every `sgtt` row discloses its shared vocabulary.
  - Dense ID width follows `used_tokens`: 1 byte up to 256, 2 bytes above (50 rows at 1 byte, 6 at 2 bytes).
- **Determinism:** containers are byte-identical across 7 repetitions, and `column-full-1` vs `column-full-2` shows 0 differences in 21 non-timing columns.

### C.3 Byte accounting (shared vocabulary not charged)
| Column | Method | Values | Original | Header | Boundary | Token IDs | Bitmap | Footer | **Total** | Distinct tokens / ID width | Ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|
| col-hi-all | raw | 32 | 10,511 | 6 | 41 | 10,511 | 0 | 0 | **10,558** | — | 0.996 |
| col-hi-all | OpenAI200K | 32 | 10,511 | 6 | 41 | 1,308 | 355 | 24 | **1,734** | 250 / 1 B | 6.062 |
| col-hi-all | Gemma3 | 32 | 10,511 | 6 | 41 | 1,183 | 388 | 24 | **1,642** | 230 / 1 B | 6.401 |
| col-kn-all | raw | 33 | 13,391 | 6 | 44 | 13,391 | 0 | 0 | **13,441** | — | 0.996 |
| col-kn-all | OpenAI200K | 33 | 13,391 | 6 | 44 | 3,396 | 272 | 24 | **3,742** | 279 / 2 B | 3.579 |
| col-kn-all | Gemma3 | 33 | 13,391 | 6 | 44 | 3,580 | 255 | 24 | **3,909** | 280 / 2 B | 3.426 |
| col-all | raw | 65 | 23,902 | 6 | 83 | 23,902 | 0 | 0 | **23,991** | — | 0.996 |
| col-all | OpenAI200K | 65 | 23,902 | 6 | 82 | 6,012 | 534 | 24 | **6,658** | 500 / 2 B | 3.590 |
| col-all | Gemma3 | 65 | 23,902 | 6 | 82 | 5,946 | 582 | 24 | **6,640** | 482 / 2 B | 3.600 |
| col-all-except-paragraph-x10 | raw | 63 | 7,544 | 6 | 78 | 7,544 | 0 | 0 | **7,628** | — | 0.989 |
| col-all-except-paragraph-x10 | OpenAI200K | 63 | 7,544 | 6 | 78 | 2,130 | 537 | 24 | **2,775** | 499 / 2 B | 2.719 |
| col-all-except-paragraph-x10 | Gemma3 | 63 | 7,544 | 6 | 78 | 2,066 | 589 | 24 | **2,763** | 480 / 2 B | 2.730 |
| col-zero-values | all three | 0 | 0 | 6 | 2 | 0 | 0 | 0 | **8** | — | blank |
| col-empty-values | all three | 2 | 0 | 6 | 4 | 0 | 0 | 0 | **10** | — | blank |

Every column, including the per-category ones, is in `results/phase1/column-full-1/measurements_column.csv`.

**Observations, measured on this dataset only:**
1. **Raw HCC1 costs about 0.4–1.1% in boundary metadata on the large columns,** and much more on tiny ones. For example, `col-tiny` is 18 value bytes stored in 34 bytes.
2. **Dense ID width depends on the column.**
   - When a column uses at most 256 distinct vocabulary tokens, IDs take 1 byte; above that, 2 bytes.
   - `col-hi-all` uses 250 distinct tokens with OpenAI200K and 230 with Gemma3, so it gets 1-byte IDs and a 6.1–6.4× ratio.
   - `col-kn-all` (279–280) and `col-all` (482–500) get 2-byte IDs, and land at 3.4–3.6×.
   - So column composition and size change the ratio non-monotonically. The Hindi and Kannada difference here comes mostly from crossing the 256-token threshold, not just from the script.
3. **Small columns lose to raw HCC1.** Comparing stored totals, 11 `sgtt` rows are no smaller than raw HCC1 (found by `audit_column_results.py`):
   - `col-tiny`, `col-hi-tiny`, `col-kn-tiny`, `col-hi-edge` and `col-kn-edge`, with both tokenizers;
   - `col-hi-short` with OpenAI200K only (143 vs 142 bytes).

   Their ratios against the original bytes are 0.13–0.94. Here the bitmap (25–90 bytes) and the footer outweigh the savings. *(Correction: this observation previously listed only the edge and tiny columns.)*
4. **Neither tokenizer is consistently better:**
   - Gemma3 is smaller on `col-hi-all` and `col-all`.
   - OpenAI200K is smaller on `col-kn-all`, `col-long` and `col-kn-mixed`.
   - The differences are a few percent, on a small synthetic dataset.

### C.4 Per-value vs column (Dense, the same values)
| Values | Method | Σ per-value totals | Column total | Notes |
|---|---|---|---|---|
| hi all (32) | raw | 10,511 | 10,558 | column adds 47 bytes of header and boundaries; per-value raw had no boundaries |
| hi all | OpenAI200K | 3,865 | 1,734 | per-value covers 31 values; the empty value is unsupported there |
| hi all | Gemma3 | 3,622 | 1,642 | same |
| kn all (33) | OpenAI200K | 4,349 | 3,742 | 32 values per-value |
| kn all | Gemma3 | 4,455 | 3,909 | same |
| all except paragraph ×10 (63) | OpenAI200K | 5,939 | 2,775 | 61 values per-value |
| all except paragraph ×10 | Gemma3 | 5,799 | 2,763 | same |
| short (10) | OpenAI200K | 668 | 240 | per-value ratio 0.43, column ratio 1.20 |
| short | Gemma3 | 628 | 231 | per-value ratio 0.46, column ratio 1.25 |

Column mode removes the per-value footer and bitmap, at the cost of the boundary table. Across these groups that reduces stored bytes by 12–64%: 12–14% for Kannada, where the column needs 2-byte IDs, and about 55% for Hindi.

Per-value totals don't include boundary metadata, so they understate what per-value storage would really need for a column. Pairs are in `per_value_vs_column.csv`.

### C.5 Shared vocabulary and amortization
- **Primary comparison:** the vocabulary isn't charged, because it's a static asset shipped with the codec and shared by every column. Raw has no vocabulary.
- **One-shot comparison:** charging the full vocabulary (OpenAI200K 3,332,170 bytes; Gemma3 4,275,024 bytes) to a single column gives a one-shot ratio of at most 0.0072 for every column here; the largest is `col-all` with OpenAI200K.
- **Break-even (linear extrapolation, not measured):** this is the column size at which a column-specific vocabulary of that size would pay for itself.

  | | OpenAI200K | Gemma3 |
  |---|---|---|
  | Hindi | ≈ 4.0 MB of text | ≈ 5.0 MB |
  | Kannada | ≈ 4.6 MB | ≈ 6.0 MB |

  - It's computed as `vocabulary / ((raw_total − sgtt_total) / original_bytes)` from the 10–13 KB columns above.
  - It assumes the savings rate holds at scale. That's untested: the ID width and the bitmap both change with column size.
  - It only matters if a vocabulary had to be stored per column; upstream's is shared.

### C.6 Column timing (median of 7 repetitions, Release)
| | Encoder init | Column encode | Decoder init | Column decode |
|---|---|---|---|---|
| OpenAI200K, `col-all` | 1.34 ms | 0.127 ms | 1.32 ms | 0.018 ms |
| Gemma3, `col-all` | 1.74 ms | 0.149 ms | 2.14 ms | 0.027 ms |
| raw, `col-all` | — | 0.002 ms | — | 0.001 ms |

- Setup (tokenizer construction) is separated from encoding and decoding.
- These are medians over repetitions of a single column, so they only describe this column on this machine.

### C.7 D2 baseline: best applicable `sgtt` per evaluation column (measured, `column-full-1`)
D2 is defined in `docs/bharat_prototype_experiment.md` §6. The evaluation set for this dataset is the 16 non-overlapping `col-<lang>-<category>` columns. The best baseline is the smaller of the OpenAI200K and Gemma3 totals, both Dense, with the vocabulary not charged.

| Column | Values | Original | Raw HCC1 | OpenAI200K | Gemma3 | **Best `sgtt` (`baseline_c`)** | Best `sgtt` vs raw |
|---|---|---|---|---|---|---|---|
| col-hi-short | 5 | 128 | 142 | 143 | 137 | **137** (Gemma3) | 3.5% smaller |
| col-hi-medium | 4 | 446 | 460 | 238 | 242 | **238** (OpenAI200K) | 48.3% smaller |
| col-hi-long | 2 | 1,349 | 1,362 | 383 | 381 | **381** (Gemma3) | 72.0% smaller |
| col-hi-repeated | 4 | 7,965 | 7,980 | 1,156 | 1,081 | **1,081** (Gemma3) | 86.5% smaller |
| col-hi-punct_numerals | 3 | 273 | 286 | 241 | 222 | **222** (Gemma3) | 22.4% smaller |
| col-hi-mixed | 3 | 230 | 242 | 221 | 214 | **214** (Gemma3) | 11.6% smaller |
| col-hi-edge | 7 | 111 | 126 | 137 | 137 | **137** (tie) | raw is smaller |
| col-hi-tiny | 4 | 9 | 21 | 69 | 69 | **69** (tie) | raw is smaller |
| col-kn-short | 5 | 161 | 175 | 151 | 154 | **151** (OpenAI200K) | 13.7% smaller |
| col-kn-medium | 4 | 566 | 582 | 227 | 235 | **227** (OpenAI200K) | 61.0% smaller |
| col-kn-long | 2 | 1,670 | 1,683 | 398 | 412 | **398** (OpenAI200K) | 76.4% smaller |
| col-kn-repeated | 4 | 10,312 | 10,327 | 1,430 | 1,510 | **1,430** (OpenAI200K) | 86.2% smaller |
| col-kn-punct_numerals | 3 | 313 | 326 | 250 | 236 | **236** (Gemma3) | 27.6% smaller |
| col-kn-mixed | 3 | 271 | 283 | 221 | 242 | **221** (OpenAI200K) | 21.9% smaller |
| col-kn-edge | 8 | 89 | 105 | 137 | 133 | **133** (Gemma3) | raw is smaller |
| col-kn-tiny | 4 | 9 | 21 | 65 | 66 | **65** (OpenAI200K) | raw is smaller |

**When raw UTF-8 is the better practical choice:** on 4 of the 16 columns (both `edge` and both `tiny`), raw HCC1 stores fewer bytes than either `sgtt` baseline. These columns hold under about 120 bytes of text, so the fixed `sgtt` cost of a 24-byte footer plus a bitmap of 25 bytes or more isn't recovered. A real system would pick raw for columns like these. P1 is reported against raw HCC1 as well as against the best `sgtt` baseline.

**Aggregate vs median:**
- The per-column ratios in §C.3 are each `Σ original / total` for that one column.
- The audit also shows a median of 1.637 across all 56 `sgtt` rows with non-empty payload. **That number shouldn't be used:** the 30 columns overlap (`col-all` contains every sample), so samples are counted many times.
- Only medians over a declared non-overlapping set, such as the 16 columns above, are meaningful. Even those cover just 2–8 values per column of synthetic data, accepted for harness validation only and not reviewed by native speakers.

### C.8 English and mixed-language baseline: `phase1-en-mixed-v1` (newly measured 2026-10-24)
**Dataset:**
- `datasets/phase1_en_mixed/`: 81 samples and 19,437 bytes, split into `en` (35 samples, 5,665 B), `en-hi` (23, 6,584 B) and `en-kn` (23, 7,188 B). SHA-256 `6c4685c2…31d47b0`.
- It is a separate, controlled dataset written for the project, **not independently reviewed** and **not representative of real-world use**.
- `phase1-kn-hi-v1` and its checksum are unchanged.

**Commands:**
- `run_column_benchmark.py` gained a `--dataset` option. The default `kn-hi-v1` behaves exactly as before: `column-smoke-3` vs `column-smoke-1` shows 0 differences.
- Methods: the established `raw_utf8_column`, `sgtt_openai200k_column` and `sgtt_gemma3_column`, all Dense, in HCC1.

```bash
python3 -I datasets/phase1_en_mixed/build_dataset.py              # ×2, identical sha256 6c4685c2…
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --smoke --run-id en-mixed-column-smoke-1   # exit 0, 9 rows ok
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --smoke --run-id en-mixed-column-smoke-2   # exit 0; compare: 0 differences
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --run-id en-mixed-column-full-1            # exit 0, 32 columns × 3 = 96 rows ok, 0 problems
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --run-id en-mixed-column-full-2            # exit 0
python3 -I benchmarks/phase1/run_column_benchmark.py --compare results/phase1/en-mixed-column-full-1 results/phase1/en-mixed-column-full-2   # 0 differences in 21 non-timing columns
python3 -I benchmarks/phase1/audit_column_results.py results/phase1/en-mixed-column-full-1   # 0 problems (same for -full-2 and -smoke-1)
```

**Correctness:**
- All 96 rows are exact, value by value, in order. This includes the 3 empty values and the samples containing LF, CR, tabs and emoji: 4 LF and 1 CR, **so newline handling is now exercised by a benchmark run**.
- The components equal the container size in every row.
- Every method received an identical ordered input.
- There are no failed or unsupported cases. Empty values are stored as length 0 in HCC1, so the codec isn't called for them.

**Grouped columns (these overlap; not independent observations):**

| Column | Values | Original | Raw HCC1 | OpenAI200K total (IDs / bitmap / footer) | Distinct tokens / width | Gemma3 total (IDs / bitmap / footer) | Distinct tokens / width | Best `sgtt` vs raw |
|---|---|---|---|---|---|---|---|---|
| col-en-all | 35 | 5,665 | 5,714 | 3,185 (2,424 / 688 / 24) | 296 / 2 B | 3,250 (2,522 / 655 / 24) | 265 / 2 B | 44.3% smaller |
| col-en-hi-all | 23 | 6,584 | 6,620 | 1,445 (932 / 453 / 24) | 208 / 1 B | 1,404 (916 / 428 / 24) | 185 / 1 B | 78.8% smaller |
| col-en-kn-all | 23 | 7,188 | 7,224 | 1,431 (991 / 380 / 24) | 212 / 1 B | 1,428 (978 / 390 / 24) | 199 / 1 B | 80.2% smaller |
| col-mixed-all | 46 | 13,772 | 13,835 | 4,516 (3,846 / 583 / 24) | 321 / 2 B | 4,406 (3,788 / 531 / 24) | 289 / 2 B | 68.2% smaller |
| col-all | 81 | 19,437 | 19,541 | 7,468 (6,268 / 1,073 / 24) | 575 / 2 B | 7,421 (6,308 / 986 / 24) | 508 / 2 B | 62.0% smaller |

- The `sgtt` totals also include the HCC1 header and boundary bytes, which are the same as raw's: for example 49 bytes for `col-en-all` and 104 for `col-all`.
- Two overlapping figures to avoid: `col-zero-values` (8 bytes for every method) and `col-empty-values` (11 bytes for every method), since there's nothing to encode.
- **Why the grouped columns look good:** they are dominated by the three paragraph ×10 samples, which hold 70.5% of the bytes. Without them, `col-all-except-paragraph-x10` has a best-`sgtt` total of 3,495 against 5,827 raw, i.e. 40.0% smaller.
- **Grouped ratios don't show a language effect:**
  - `col-en-all` (1.78×) and `col-mixed-all` (3.05–3.13×) cross the 256-distinct-token threshold and use 2-byte IDs.
  - `col-en-hi-all` and `col-en-kn-all` (4.56–5.03×) stay at 1-byte IDs.
  - The language groups also differ in how much repeated text they contain.

**D2 baseline (`baseline_c`), 24 non-overlapping `col-<language>-<category>` columns:**

| Column | Values | Original | Raw HCC1 | OpenAI200K | Gemma3 | **`baseline_c`** | Best `sgtt` vs raw |
|---|---|---|---|---|---|---|---|
| col-en-short | 4 | 48 | 60 | 100 | 106 | **100** (OpenAI200K) | raw is smaller |
| col-en-medium | 4 | 254 | 267 | 227 | 224 | **224** (Gemma3) | 16.1% smaller |
| col-en-long | 3 | 998 | 1,013 | 569 | 599 | **569** (OpenAI200K) | 43.8% smaller |
| col-en-repeated | 4 | 3,891 | 3,906 | 1,001 | 1,043 | **1,001** (OpenAI200K) | 74.4% smaller |
| col-en-punct_numerals | 4 | 133 | 146 | 236 | 210 | **210** (Gemma3) | raw is smaller |
| col-en-structured | 5 | 189 | 203 | 287 | 282 | **282** (Gemma3) | raw is smaller |
| col-en-edge | 7 | 149 | 165 | 229 | 200 | **200** (Gemma3) | raw is smaller |
| col-en-tiny | 4 | 3 | 15 | 70 | 70 | **70** (tie) | raw is smaller |
| col-en-hi-short | 3 | 72 | 83 | 108 | 115 | **108** (OpenAI200K) | raw is smaller |
| col-en-hi-medium | 3 | 242 | 254 | 206 | 208 | **206** (OpenAI200K) | 18.9% smaller |
| col-en-hi-long | 2 | 893 | 906 | 395 | 392 | **392** (Gemma3) | 56.7% smaller |
| col-en-hi-repeated | 3 | 4,987 | 5,001 | 866 | 834 | **834** (Gemma3) | 83.3% smaller |
| col-en-hi-punct_numerals | 3 | 163 | 175 | 224 | 202 | **202** (Gemma3) | raw is smaller |
| col-en-hi-structured | 3 | 127 | 138 | 226 | 208 | **208** (Gemma3) | raw is smaller |
| col-en-hi-edge | 3 | 92 | 103 | 135 | 114 | **114** (Gemma3) | raw is smaller |
| col-en-hi-tiny | 3 | 8 | 19 | 71 | 65 | **65** (Gemma3) | raw is smaller |
| col-en-kn-short | 3 | 78 | 89 | 123 | 114 | **114** (Gemma3) | raw is smaller |
| col-en-kn-medium | 3 | 222 | 234 | 179 | 213 | **179** (OpenAI200K) | 23.5% smaller |
| col-en-kn-long | 2 | 984 | 997 | 366 | 383 | **366** (OpenAI200K) | 63.3% smaller |
| col-en-kn-repeated | 3 | 5,467 | 5,481 | 912 | 885 | **885** (Gemma3) | 83.9% smaller |
| col-en-kn-punct_numerals | 3 | 189 | 201 | 236 | 218 | **218** (Gemma3) | raw is smaller |
| col-en-kn-structured | 3 | 136 | 148 | 198 | 212 | **198** (OpenAI200K) | raw is smaller |
| col-en-kn-edge | 3 | 98 | 109 | 141 | 141 | **141** (tie) | raw is smaller |
| col-en-kn-tiny | 3 | 14 | 25 | 74 | 75 | **74** (OpenAI200K) | raw is smaller |

**What this shows (measured on this controlled dataset only):**
- **Raw HCC1 is smaller than the best `sgtt` baseline on 17 of the 24 columns,** in all three language groups. `sgtt` wins only on `medium`, `long` and `repeated`.
- In the losing columns the text is 3–189 bytes. The Dense bitmap (28–153 bytes per column in these categories) plus the 24-byte footer isn't recovered. Structured and numeric English strings are short, mostly made of rarely repeated tokens, and lose too.
- Neither tokenizer is consistently better: OpenAI200K is best on 9 columns, Gemma3 on 13, and 2 are ties.
- Across both datasets, the practical choice for short, structured, numeric or edge-case columns is raw. A real system would need a per-column choice between raw and `sgtt`. P1 has to be reported against raw HCC1 as well as against `baseline_c`.

**D2 outcome:**
- **Not evaluable yet.** There's no P1 candidate, so there's no `candidate_c`. The table above is the fixed `baseline_c` for this dataset's 24 evaluation columns: 8 per language group.
- When P1 exists, D2 is computed separately for `en`, `en-hi` and `en-kn`, with 8 columns each, plus the 16 `kn-hi-v1` columns. A median over 8 columns is a weak statistic, and the criterion is a project acceptance criterion, not a significance test.

**Shared vocabulary:**
- Not charged in the totals above; same rule as §C.5.
- Charging the full vocabulary (OpenAI200K 3,332,170 B; Gemma3 4,275,024 B) to one column gives one-shot ratios of at most 0.0058, the highest being `col-all`.
- **Break-even (linear extrapolation from these 6–7 KB columns, not measured):**

  | | OpenAI200K | Gemma3 |
  |---|---|---|
  | `en` | ≈ 7.5 MB of text | ≈ 9.8 MB |
  | `en-hi` | ≈ 4.2 MB | ≈ 5.4 MB |
  | `en-kn` | ≈ 4.1 MB | ≈ 5.3 MB |

  This uses the same formula and caveats as §C.5. English breaks even later because its savings per byte are lower here (0.44 vs 0.79–0.81).

**Timing:**
- On `col-all`, encoder setup was 2.60 ms (OpenAI200K) and 3.33 ms (Gemma3), column encoding 0.30 and 0.32 ms, decoder setup 2.63 and 3.94 ms, and column decoding 0.093 and 0.086 ms. Raw: 0.003 ms encode, 0.002 ms decode.
- These setup times are about twice those in `column-full-1` (1.3 and 1.7 ms) for the same call. **Setup time clearly varies between runs on this machine**, which is the likely explanation for the setup difference noted in §C.6.
- The setup medians are lower than in the per-value harness (≈2.4 and ≈3.3 ms). The setup call is the same; the difference has not been explained.
- Timing applies to this machine only.
- Dataset `phase1-kn-hi-v1` (SHA-256 `359269f4…36bb6fc`): 65 samples.
- Upstream commit `e202e36`, branch `fix/arm64-build`, with the 8 documented build and portability edits.
- Release build on an Apple M3, macOS 27.0.1, Apple clang 21.0.0.

## 1. Commands run
```bash
python3 -I datasets/phase1/build_dataset.py                       # wrote 65 samples, sha256 359269f4…
cmake --build external/token-vldb2026/build-arm64 --target phase1_harness   # exit 0
python3 -I benchmarks/phase1/run_benchmark.py --smoke --run-id smoke-1     # exit 0
python3 -I benchmarks/phase1/run_benchmark.py --smoke --run-id smoke-2     # exit 0
python3 -I benchmarks/phase1/run_benchmark.py --compare results/phase1/smoke-1 results/phase1/smoke-2   # 0 differences, exit 0
python3 -I benchmarks/phase1/run_benchmark.py --run-id full-1              # exit 0
python3 -I benchmarks/phase1/run_benchmark.py --run-id full-2              # exit 0
python3 -I benchmarks/phase1/run_benchmark.py --compare results/phase1/full-1 results/phase1/full-2     # 0 differences, exit 0
```

## 2. Validation results (full-1)
- **Rows:** 325 (65 samples × 5 methods).
  - `ok`: 317.
  - `unsupported_input`: 8. These are the 2 empty samples × 4 `sgtt` methods; upstream asserts the input isn't empty.
  - Errors, round-trip mismatches, non-deterministic encodings: 0.
  - Validation problems found by the runner: 0.
- **Identical input:** in all 325 rows, `input_fnv1a64` equals Python's hash of the dataset bytes, so every method received the same bytes.
- **Exact round trips:** 317 / 317 `ok` rows, including the two non-NFC samples. The decoded bytes in `artifacts.tsv` were also checked independently in Python.
- **Deterministic encoding:**
  - Within a run, all 252 `sgtt` rows produced byte-identical blobs across all 7 repetitions.
  - Across runs, `full-1` and `full-2` agree on all 17 non-timing columns for all 325 rows, and so do `smoke-1` and `smoke-2` (40 rows).
- **Byte accounting:** `payload + metadata = total` holds in every row, with a footer of 24 bytes, a Sparse bitmap of 0, and `payload = tokens × ID size`.

## 3. Size results: per-value mode, shared vocabulary not charged
Ratios use `original_bytes / total_stored_bytes`. A value above 1 means the stored form is smaller than raw.

| Language | Method | Σ original | Σ stored | Aggregate ratio | Median per-sample ratio | Median size change |
|---|---|---|---|---|---|---|
| hi | raw_utf8 | 10,511 | 10,511 | 1.000 | 1.000 | 0.0% |
| hi | sgtt_openai200k_dense | 10,511 | 3,865 | 2.720 | 0.509 | −96.6% |
| hi | sgtt_openai200k_sparse | 10,511 | 5,984 | 1.757 | 0.750 | −33.3% |
| hi | sgtt_gemma3_dense | 10,511 | 3,622 | 2.902 | 0.621 | −61.0% |
| hi | sgtt_gemma3_sparse | 10,511 | 5,472 | 1.921 | 0.788 | −26.8% |
| kn | raw_utf8 | 13,391 | 13,391 | 1.000 | 1.000 | 0.0% |
| kn | sgtt_openai200k_dense | 13,391 | 4,349 | 3.079 | 0.583 | −72.8% |
| kn | sgtt_openai200k_sparse | 13,391 | 7,576 | 1.768 | 0.737 | −35.8% |
| kn | sgtt_gemma3_dense | 13,391 | 4,455 | 3.006 | 0.592 | −71.9% |
| kn | sgtt_gemma3_sparse | 13,391 | 7,936 | 1.687 | 0.665 | −50.3% |

Counts: Hindi has 31 measurable `sgtt` samples per method; Kannada has 32. The raw row counts include the empty sample, which has an undefined ratio.

Median per-sample ratio by category, Sparse:

| Category | hi OpenAI200K | hi Gemma3 | kn OpenAI200K | kn Gemma3 |
|---|---|---|---|---|
| tiny | 0.107 | 0.107 | 0.107 | 0.107 |
| short | 0.646 | 0.750 | 0.596 | 0.596 |
| edge | 0.417 | 0.469 | 0.301 | 0.301 |
| punct_numerals | 0.759 | 0.788 | 0.830 | 0.676 |
| mixed | 1.063 | 1.000 | 1.159 | 1.140 |
| medium | 1.435 | 1.469 | 1.557 | 1.464 |
| repeated | 1.782 | 1.843 | 1.448 | 1.557 |
| long | 2.025 | 2.239 | 1.884 | 1.837 |

Dense per category is in `summary.csv`. Dense is smaller than Sparse only on long and repeated samples.

**How to read this:**
1. **The aggregate and the median disagree, and both are true.**
   - The aggregate is dominated by the two paragraph ×10 samples, which hold 68% of all bytes.
   - The median sample is a short string, and it **expands**.
   - Only 25 of 63 measurable samples (Sparse) and 17 of 63 (Dense) are smaller than raw.
2. **Most of the expansion is fixed per-value overhead:**
   - every `sgtt` blob carries a 24-byte footer;
   - Dense blobs also carry a zstd-compressed bitmap of used tokens, 25–147 bytes (median 44 for OpenAI200K, 43 for Gemma3);
   - Sparse uses 4-byte token IDs.
   - That's why a 3-byte single letter becomes 28 bytes stored (Sparse).
3. **Token density on the medium and long samples (Sparse)**, in UTF-8 bytes per token:

   | | OpenAI200K | Gemma3 |
   |---|---|---|
   | Hindi | 8.63 | 9.45 |
   | Kannada | 8.01 | 7.74 |

   - These counts come from upstream's own encoder matching against its static vocabulary. They are **not** the models' own BPE token counts.
   - Decoded tokens often split an akshara. For example, `kn-medium-001` contains the tokens `ಾ` and `ುತ್ತ`, which start with a dependent vowel sign.
   - This is an observation, not evidence that an akshara table would be smaller.
4. **Gemma3 vs OpenAI200K:** neither is consistently ahead across languages and categories on this dataset.
5. **One-shot storage, including the shared vocabulary:**
   - The vocabulary is 3,332,170 bytes for OpenAI200K and 4,275,024 bytes for Gemma3.
   - The highest one-shot ratio for any sample is 0.0028.
   - In practice, the vocabulary only pays off when it's shared across a very large amount of data; the break-even point hasn't been measured.

These numbers describe this small synthetic dataset in per-value mode only. They don't describe real Kannada or Hindi database columns.

## 4. Timing (Release, median of 7 repetitions per row, then median over rows)
| Method | Setup to encode | Encode | Setup to decode | Decode |
|---|---|---|---|---|
| sgtt_openai200k_dense | ≈2.42 ms | 0.123 ms | ≈2.43 ms | 0.016 ms |
| sgtt_openai200k_sparse | ≈2.40 ms | 0.0012–0.0013 ms | ≈2.40 ms | 0.0005–0.0007 ms |
| sgtt_gemma3_dense | ≈3.31 ms | 0.164 ms | ≈3.36–3.91 ms | 0.025–0.028 ms |
| sgtt_gemma3_sparse | ≈3.31 ms | 0.0050–0.0054 ms | ≈3.34–3.85 ms | 0.0014–0.0023 ms |

Ranges are the Hindi and Kannada values.
- Setup builds the tokenizer and its hash maps. It costs about 20× the time to encode one sample with Dense, and about 600–2,000× with Sparse. It should be paid once per column in practice.
- Dense encoding is slower than Sparse mainly because of the bitmap and its zstd compression.
- Timing varies between runs and should only be compared on the same machine.

## 5. Comparability
- **All three baselines receive identical bytes** (checked by hash in every row) and are measured with the same accounting.
- **Raw UTF-8 vs `sgtt`:** comparable on stored bytes per value.
- **OpenAI200K vs Gemma3:** comparable. They use the same compressor, configuration and accounting, and differ only in tokenizer.
- **Not yet comparable with upstream's intended use:** per-value mode charges the footer and bitmap to every value. Upstream targets whole database text columns, where those costs are paid once per column. The per-value results therefore show the worst case for `sgtt` on short strings and shouldn't be read as upstream's column-level performance.
- **Excluded:** FrequentIds and `tok` (Phase 0 Findings 1–4), and empty input for `sgtt` (an upstream precondition).

## 6. Unsupported measurements and blockers
| Item | Status |
|---|---|
| Column-mode storage | **Done** (§C). HCC1 uses a varint length table, which settles D5 for the baselines. Column mode uses Dense IDs only |
| Sparse IDs in column mode | Not run. It would be a straightforward addition |
| Columns at realistic sizes (MB and up) | Not measured. The largest column here is 23,902 bytes |
| Empty input on `sgtt` | Not executed, because it is outside the upstream contract. Recorded as `unsupported_input` |
| Native-model BPE token counts | Not measured. `token_count` is upstream's static-table matching |
| Amortized vocabulary cost at realistic column sizes | Not measured. Only "not charged" and "fully charged" are reported |
| Sanitizer run of this harness and of the column container | Not done. The Phase 0 ASan/UBSan build exists, and only the narrow `tok` driver has run under it. 24 GiB is now free, so a sanitizer build of `hashcode_column_tests` is feasible |
| Linux x86-64 and AVX-512 paths | Not available on this machine. Needed to check the upstream expectation discrepancies, and Finding 1 on x86 |
| Known failures | Upstream's own Catch2 suite has **2** failing assertions: the OpenAI200K expectation and the `tok` size (Phase 0 §B). Our round-trip suite has **7** failing assertions, caused by upstream bugs: Finding 3 (4 × `tok` NUL loss) and Finding 4 (3 × FrequentIds full vocabulary). None affects the Dense `sgtt` paths used here |
| English and mixed-language evaluation data (D1) | Controlled data only: `phase1-en-mixed-v1` (§C.8), written for the project and not independently reviewed. There's no real-world English, Hindi–English or Kannada–English data, and no Roman-script Hinglish |
| Representative real-world data | Not available. The dataset is small and synthetic, and **hasn't been reviewed by a native speaker**. It is accepted for harness validation only |

## 7. When P1 can start
P1 (the akshara token table) can start when **all** of these hold:
1. ✅ All three column baselines run on identical inputs: the ordered-sequence hash is checked in every row.
2. ✅ Value boundaries and empty values round-trip exactly: 697 Catch2 assertions, and 90 / 90 benchmark rows.
3. ✅ Byte accounting is verified: the components sum to the container size, and an independent Python parse agrees.
4. ✅ Repeated runs give identical non-timing results: 0 differences, in column mode and in per-value mode.
5. ✅ Column-mode outputs and commands are documented (`docs/phase1_column_protocol.md`, §C).
6. ✅ The reference is unchanged: the same 8 approved upstream edits, none added by this task.
7. ✅ **Dataset acceptance recorded (2026-10-24):** `phase1-kn-hi-v1` is for harness validation only. **Native-speaker review hasn't been confirmed.** P1 results on it mustn't be read as evidence about Hindi or Kannada compression.
8. ✅ **D1 and D2 recorded (2026-10-24)** in `docs/bharat_prototype_experiment.md` §6–7.
   - **D1:** English and other ASCII-relevant tokens are part of the intended P1 evaluation, with results reported separately by language.
   - **D2:** a median reduction of at least 5% against `baseline_c` (§C.7), computed over the 16 non-overlapping columns, with all container and codec bytes counted and the vocabulary reported separately with an amortization analysis.
   - **D5:** HCC1, which P1 must use.

**Status:**
- P1 *implementation* can start on this dataset, with the goal of validating the harness.
- Progress on a P1 *evaluation* (2026-10-24):
  - ✅ **D1a recorded:** the upstream OpenAI200K and Gemma3 vocabularies through `sgtt`, checked against the code (`docs/bharat_prototype_experiment.md` §7).
  - ✅ **A separate controlled English/mixed dataset** (`phase1-en-mixed-v1`) and its `baseline_c` are measured (§C.8). It is for harness validation only and is not independently reviewed.
  - ⬜ **D3:** an independently reviewed or real-world dataset with documented provenance and licence. Candidates and their licence terms are recorded, but nothing is approved or downloaded. Until then, P1 results say nothing about language-level effectiveness.

P1 must then be added to `column_harness.cpp`, and optionally `harness.cpp`, as a fourth method, with the same checks: identical input hash, exact round trip, determinism, and components summing to the total. Raw and upstream methods stay unchanged.

Because of observation C.3 (2), P1 has to report its ID width and number of distinct tokens per column. Ratios have to be compared at the same column composition.

**Unresolved P1 design points:**
- **Token boundaries:** whether matching follows akshara (grapheme-cluster) boundaries from Unicode rules, or is greedy matching on bytes like upstream.
- **Vocabulary:** its size and ID width (8 or 16 bits), and whether it's derived from Unicode block structure or learned from a corpus.
- **Fallback:** single-byte tokens for unseen sequences (required for losslessness), and their cost.
- **Dictionary cost:** whether the dictionary is static and shared like upstream's, or stored per column; how it's amortized.
- **Normalization:** none. Canonically equivalent byte sequences stay distinct.
