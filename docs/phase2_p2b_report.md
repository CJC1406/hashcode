# Phase 2, experiment 2: P2b (per-column token-ID width)

**Status:**
- **Exploratory result on controlled data.** P2b **beats P2a by total bytes** (30.2% smaller) but **doesn't beat the best `sgtt` baseline** (8.4% larger over 40 columns).
- **The Phase 2 real-data criterion is blocked.** There's no approved real Hindi or Kannada data (D3).
- **Data:** `phase1-kn-hi-v1` (SHA-256 `359269f4…`) and `phase1-en-mixed-v1` (`6c4685c2…`). Both are controlled, accepted for harness validation only, **not reviewed by native speakers, and not representative**. No external data was used.

## 1. Design (one isolated change from P2a)
- **Vocabulary:** the frozen P2a vocabulary (`codec/p2a/p2a_vocabulary_v1.bin`, SHA-256 `c99ff52f…`), unchanged. There's no new vocabulary, and evaluation text is never used to build one.
- **Tokenization:** P1/P2a's greedy longest-prefix match, unchanged, so the fallback rate is identical to P2a's.
- **What changes:** only how the token IDs are stored per column.

**Serialized layout:** the blob is HCC1 **codec 3** (`codec/include/p2b_codec.hpp`). HCC1 values 0–2 are unchanged, so existing raw, `sgtt`, P1 and P2a containers still decode.

| Field | Size | Accounted as |
|---|---|---|
| ID width | 1 byte: `1` or `2` | mapping (`bitmap_bytes`, `mapping_bytes`) |
| width 1 only: `m` = number of distinct global IDs used | unsigned LEB128 varint (`m` from 1 to 256) | mapping |
| width 1 only: mapping | `m` × `u16` LE global IDs, **strictly increasing**; a local ID is its index in this list | mapping |
| token stream | width 1: `n` × `u8` local IDs; width 2: `n` × `u16` LE global IDs | token payload (`encoded_payload_bytes`) |
| footer | `BTT2` + version `0x01` + 8-byte table ID (the vocabulary's SHA-256 prefix, `c99ff52fa92fa7c8`) = 13 bytes | `footer_bytes` |

The token count is derived from the blob size, so it isn't stored. HCC1's header and length table are unchanged. Every component is counted, and `header + boundary + mapping + tokens + footer = container size` is checked for every row.

**Width rule:**
- Width 1 **if and only if** `m ≤ 256` **and** `1 + varint(m) + 2m + n < 1 + 2n`, i.e. the mapping pays for itself. Otherwise width 2 with global IDs and no mapping.
- It is one rule for every column, and the width byte makes every blob self-describing. This is unlike Finding 4, where the decoder had to infer the scheme from usage counts.
- Columns with more than 256 distinct tokens always get width 2, so there is no truncation.

**Decoder rejects:**
- a width other than 1 or 2;
- a mapping count of 0 or more than 256, and a truncated count or mapping;
- a mapping that isn't strictly increasing, and global IDs outside the vocabulary;
- local IDs ≥ `m`, and an odd 2-byte stream;
- a wrong footer magic, version or vocabulary ID, including P1/P2a `BTT1` blobs.

**Not changed, on purpose:** the vocabulary, learned entries (P2c), and raw/codec selection (P2d).

## 2. Commands and outcomes
```bash
cmake --build external/token-vldb2026/build-arm64 --target hashcode_p2b_tests hashcode_p2a_tests hashcode_p1_tests hashcode_column_tests phase1_column_harness hashcode_roundtrip_tests   # exit 0
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p2b_tests      # exit 0: 101 / 101 assertions, 7 test cases
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p2a_tests      # exit 0: 65,662 / 65,662
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p1_tests       # exit 0: 7,652 / 7,652
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_column_tests   # exit 0: 697 / 697
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_roundtrip_tests "~[empty]"   # exit 42: the same 7 known failures (Phase 0 Findings 3, 4)
external/token-vldb2026/build-arm64/test/test                              # exit 42: the same 2 known upstream discrepancies
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset kn-hi-v1    --results-root results/phase2 --smoke --run-id p2b-kn-hi-column-smoke-1     # 18 rows ok
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset kn-hi-v1    --results-root results/phase2 --run-id p2b-kn-hi-column-full-1              # 180 rows ok, 0 problems
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset kn-hi-v1    --results-root results/phase2 --run-id p2b-kn-hi-column-full-2              # compare: 0 differences
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --results-root results/phase2 --smoke --run-id p2b-en-mixed-column-smoke-1  # 18 rows ok
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --results-root results/phase2 --run-id p2b-en-mixed-column-full-1           # 192 rows ok, 0 problems
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --results-root results/phase2 --run-id p2b-en-mixed-column-full-2           # compare: 0 differences
python3 -I benchmarks/phase1/audit_column_results.py results/phase2/<each of the 6 P2b runs>                                                             # 0 problems each
python3 -I benchmarks/phase2/evaluate_p2b.py --out results/phase2/p2b-evaluation \
  --run kn-hi-v1=results/phase2/p2b-kn-hi-column-full-1 --run en-mixed-v1=results/phase2/p2b-en-mixed-column-full-1          # exit 0, 0 frozen-integrity problems
```
Logs are in `results/phase2/p2b_build_and_test_logs/`. The modified auditor still reports 0 problems on the frozen `column-full-1` and P2a runs.

**Frozen integrity:** in the P2b runs, all of these are identical to their frozen runs on all 21 non-timing columns:
- raw and both `sgtt` baselines (`column-full-1`, `en-mixed-column-full-1`);
- P1 (`p1-*-column-full-1`);
- P2a (`p2a-*-column-full-1`).

**Test coverage (`tests/p2b/P2bCodecTest.cpp`):**
- Exact round trips: empty input, ASCII, Hindi, Kannada, mixed scripts, NUL, LF/CR/CRLF/tab, emoji and other multibyte text, invalid UTF-8, all 256 byte values, repetitive input.
- **Exactly 1, 255, 256 and 257 distinct IDs** (width 1, 1, 1, 2), with mapping and token byte counts checked.
- Width 2 when a mapping wouldn't pay off.
- A sorted, deterministic mapping that doesn't depend on first-use order.
- Rejection of: unknown width, mapping count 0, local ID ≥ `m`, a duplicate (non-increasing) mapping, footer magic, version and vocabulary ID, truncated mappings and blobs, odd 2-byte streams, P1-format blobs.
- **Global IDs outside the vocabulary,** in both width modes, using a temporary 266-entry vocabulary. The P2a vocabulary uses all 65,536 IDs, so it can't produce an out-of-range ID.
- HCC1 boundaries, with reported sizes equal to serialized sizes.

**Corrections during testing:** both were bugs in the test code, not the codec.
- One assertion read the mapping at the wrong offset.
- One tamper test copied only one byte, so it could have passed for the wrong reason.

Both now use the documented layout.

## 3. Results (controlled data, exploratory)
Each group uses its 8 non-overlapping `col-<language>-<category>` columns, from `p2b-*-column-full-1`. Shared vocabularies are not charged; see the end of this section.

| Group | Raw | Best `sgtt` | P1 | P2a | **P2b** | **P2b vs `sgtt`** | P2b vs P2a | P2b token / mapping / fixed bytes | Width 1 / 2 columns | Median vs `sgtt` (P2b) |
|---|---|---|---|---|---|---|---|---|---|---|
| hi | 10,619 | 2,479 | 6,297 | 4,694 | **3,209** | **−29.4%** | +31.6% | 2,532 / 467 / 210 | 2 / 6 | +26.4% |
| kn | 13,502 | 2,861 | 6,860 | 5,757 | **3,796** | **−32.7%** | +34.1% | 3,088 / 495 / 213 | 2 / 6 | +27.0% |
| en | 5,775 | 2,656 | 2,721 | 2,721 | **2,091** | **+21.3%** | +23.2% | 1,735 / 143 / 213 | 1 / 7 | +26.7% |
| en-hi | 6,679 | 2,129 | 3,693 | 2,840 | **2,040** | **+4.2%** | +28.2% | 1,693 / 149 / 198 | 1 / 7 | +34.3% |
| en-kn | 7,284 | 2,175 | 3,652 | 3,078 | **2,195** | **−0.9%** | +28.7% | 1,836 / 161 / 198 | 1 / 7 | +35.4% |
| **All 40** | 43,859 | **12,300** | 23,223 | 19,090 | **13,331** | **−8.4%** | **+30.2%** | 10,884 / 1,415 / 1,032 | 7 / 33 | +32.3% |

Positive means P2b is smaller. "Fixed" is the HCC1 header and boundaries plus the 13-byte footer. The mapping figure includes the 1-byte width field in every column.

**Where the bytes go:**
- **Width 1 is used only on the 7 `long` and `repeated` columns.** On the other 33, the mapping wouldn't pay off, so P2b stores exactly P2a's IDs plus the width byte: **P2a + 1 byte**.
- **All of P2b's savings over P2a come from those 7 columns.**
- **P2b beats `baseline_c` on 32 of 40 columns,** all the small ones, because it has no bitmap.
- **It loses on every Indic `long` and `repeated` column, by 49–76%.**
  - Even with 1-byte IDs, P2b emits **1.6–2.0× as many tokens** as `sgtt` there, because `sgtt` matches whole words.

    | Column | P2b token bytes | `sgtt` token bytes |
    |---|---|---|
    | `col-hi-repeated` | 1,674 | 860 |
    | `col-kn-repeated` | 2,114 | 1,247 |
    | `col-hi-long` | 278 | 139 |
    | `col-kn-long` | 342 | 209 |

  - The sorted mapping adds another 196–265 bytes per column.
- **Payload only (token bytes), over all 40 columns:** 10,884 for P2b against 6,044 for `sgtt`, about 80% more.
- **Fallback:** 7.3% of tokens overall, identical to P2a (same tokenization).
- **P2b against raw HCC1:** 63.8–71.9% smaller per group.
- **Pre-measurement estimate vs actual:** the estimate (14,207 bytes, 15.5% larger) was pessimistic. It assumed width 1 for every column with ≤256 distinct tokens. The measured rule chooses width 1 only where it pays off.

**Vocabulary and amortization:**
- P2b uses the P2a vocabulary (445,881 B) unchanged. P1's is 445,193 B; OpenAI200K's 3,332,170 B; Gemma3's 4,275,024 B.
- All are shared static assets, reported separately and never charged per column, the same rule for every method.
- The per-column mapping is **not** a vocabulary cost. It's stored in each column and counted in its total.

**Timing (`col-all`, median of 7, Release; this machine only):**

| | Encoder setup | Column encode | Decoder setup | Decode |
|---|---|---|---|---|
| P2b, `kn-hi` | 9.06 ms | 0.897 ms | 9.22 ms | 0.049 ms |
| P2b, `en-mixed` | 9.25 ms | 0.740 ms | 9.17 ms | 0.042 ms |
| P2a, `kn-hi` | 9.25 ms | 0.767 ms | 9.06 ms | 0.035 ms |
| OpenAI200K, `kn-hi` | 2.57 ms | 0.249 ms | 2.54 ms | 0.051 ms |
| Gemma3, `kn-hi` | 3.44 ms | 0.288 ms | 4.01 ms | 0.073 ms |

- P2b's encoding costs slightly more than P2a's: it sorts the distinct IDs and looks up local IDs.
- It is about 3× slower than `sgtt` to encode, and its setup takes about 3× longer.
- `col-all` itself uses width 2 (422 distinct IDs).

## 4. Decision
| Question | Answer (controlled data) |
|---|---|
| Does P2b beat P2a by total bytes? | **Yes:** 13,331 against 19,090 (−30.2%). It is +1 byte on 33 width-2 columns and much smaller on the 7 width-1 columns |
| Does P2b beat the best `sgtt` baseline by total bytes? | **No:** 13,331 against 12,300 (+8.4%). It beats `sgtt` for `en` (−21.3%) and `en-hi` (−4.2%), but not `hi` (+29.4%), `kn` (+32.7%) or `en-kn` (+0.9%) |
| Does it meet the Phase 2 real-data criterion (≥5% fewer total bytes than `sgtt` for real Hindi and Kannada; no group more than 5% worse)? | **Blocked:** no approved real data. On controlled data the Hindi and Kannada parts would fail by about 30% |

## 5. Remaining gap and next experiment
- **The remaining gap is 1,031 bytes overall.** It comes almost entirely from the Indic `long` and `repeated` columns, where P2b needs 1.6–2.0× as many tokens as `sgtt`.
- **A cheaper mapping won't close it.** Delta-varint coding of the sorted mapping was **computed exactly from the stored mappings, not implemented**. It would save 591 bytes (1,366 → 775), giving about 12,740 bytes in total. That's still 3.6% larger than `sgtt`, and the Indic groups would still lose.
- **What the results justify next:**
  - **P2c:** multi-akshara and word entries chosen by frequency on an **approved training corpus that is separate from evaluation data**. That's the only lever that targets the token count. **It is blocked on D3.**
  - **Optional, without new data:** a P2b′ with a delta-varint mapping. It's cheap but can't reach the target alone.

## 6. Limitations
- The datasets are controlled and synthetic, with 8 small columns per group. These results can't satisfy the Phase 2 criterion.
- The width rule depends on the column's own content, so ratios depend on how columns are composed.
- The mapping uses fixed 2-byte entries (see §5).
- No sanitizer, Linux x86-64 or native-speaker review was done for this experiment.
