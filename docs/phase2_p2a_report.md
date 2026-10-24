# Phase 2, experiment 1: P2a (space+akshara entries)

**Status:**
- **Exploratory result on controlled data.**
  - H1 is supported: fallback is cut sharply, and P2a is 16–25% smaller than P1 for the Indic groups.
  - **P2a doesn't beat `sgtt`.** It is 55% larger by total bytes.
- **The Phase 2 success criterion can't be evaluated (blocked).** It requires real Hindi and Kannada data, and D3 isn't approved.
- **Data:** `phase1-kn-hi-v1` (SHA-256 `359269f4…`) and `phase1-en-mixed-v1` (`6c4685c2…`). Both are controlled, accepted for harness validation only, **not reviewed by native speakers, and not representative**. No external data was downloaded.

## 1. Design (one isolated change from frozen P1)
`codec/p2a/build_vocabulary.py` takes the **frozen P1 vocabulary** as its only input. It checks it against SHA-256 `8c85586c…` and then:

| IDs | Entries | Source |
|---|---|---|
| 0–255 | 256 single bytes | P1, unchanged |
| 256–2,751 | 2,496 Devanagari/Kannada akshara entries | P1, unchanged, same IDs |
| 2,752–5,247 | 2,496 entries: `" "` + each akshara entry above, in the same order | **new** |
| 5,248–65,535 | 60,288 ASCII entries | P1's ASCII entries in P1 order (o200k rank); P1's last 2,496 are dropped |

Results:
- **Vocabulary:** `p2a_vocabulary_v1.bin`, 65,536 entries, 445,881 bytes, SHA-256 `c99ff52fa92fa7c8be541c0358c10acd678aeaa98764bb474ef06077faa7face`, deterministic over 3 builds. The table ID is `c99ff52fa92fa7c8`.
- **Limits checked before implementation:**
  - the longest entry is 7 bytes, within the 16-byte limit and the `u8` length field;
  - exactly 65,536 distinct entries, so the IDs fit `u16`;
  - new entries can't collide with existing ones (they start with a space and contain non-ASCII bytes).
- **Codec and container, unchanged from P1:** the same `p1_codec.hpp`, greedy longest-prefix matching, `u16` IDs, and a 13-byte `BTT1` footer with the table ID. HCC1 codec value 2 is shared. The table ID distinguishes the vocabularies, and P1's decoder rejects P2a blobs (tested).
- **Not changed, on purpose:** ID width, column metadata, learned entries, and raw/codec selection (those are P2b–P2d).
- **Evaluation data used to build the vocabulary: none.**

## 2. Commands and outcomes
```bash
python3 -I codec/p2a/build_vocabulary.py                       # ×3, identical sha256 c99ff52f…
cmake --build external/token-vldb2026/build-arm64 --target hashcode_p2a_tests hashcode_p1_tests hashcode_column_tests phase1_column_harness hashcode_roundtrip_tests   # exit 0
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p2a_tests      # exit 0: 65,662 / 65,662 assertions, 6 test cases
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p1_tests       # exit 0: 7,652 / 7,652
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_column_tests   # exit 0: 697 / 697
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_roundtrip_tests "~[empty]"   # exit 42: the same 7 known failures (Phase 0 Findings 3, 4)
external/token-vldb2026/build-arm64/test/test                              # exit 42: the same 2 known upstream discrepancies
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset kn-hi-v1    --results-root results/phase2 --smoke --run-id p2a-kn-hi-column-smoke-1     # 15 rows ok
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset kn-hi-v1    --results-root results/phase2 --run-id p2a-kn-hi-column-full-1              # 150 rows ok, 0 problems
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset kn-hi-v1    --results-root results/phase2 --run-id p2a-kn-hi-column-full-2              # compare: 0 differences
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --results-root results/phase2 --smoke --run-id p2a-en-mixed-column-smoke-1  # 15 rows ok
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --results-root results/phase2 --run-id p2a-en-mixed-column-full-1           # 160 rows ok, 0 problems
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --results-root results/phase2 --run-id p2a-en-mixed-column-full-2           # compare: 0 differences
python3 -I benchmarks/phase1/audit_column_results.py results/phase2/<each of the 6 runs>                                                               # 0 problems each
python3 -I benchmarks/phase2/evaluate_p2a.py --out results/phase2/p2a-evaluation \
  --run kn-hi-v1=results/phase2/p2a-kn-hi-column-full-1 --run en-mixed-v1=results/phase2/p2a-en-mixed-column-full-1        # exit 0, 0 frozen-integrity problems
```
Logs are in `results/phase2/p2a_build_and_test_logs/`.

**Frozen integrity:** in the P2a runs, raw and both `sgtt` baselines are identical to `column-full-1` and `en-mixed-column-full-1`, and P1 is identical to `p1-*-column-full-1`, on all 21 non-timing columns.

**Test coverage:**
- P2a is exactly frozen P1 plus the rule above, checked ID for ID.
- The table ID matches the SHA-256.
- Exact round trips: empty input, ASCII, Hindi, Kannada, mixed scripts, emoji/ZWJ/₹, NUL, LF/CR/tab, leading, trailing and repeated spaces, invalid UTF-8, all 256 byte values, a long input, and every prefix cut.
- Longest-match boundaries.
- No read past the input.
- Valid IDs and footer, and rejection by P1's decoder.
- HCC1 boundaries, with reported sizes equal to serialized sizes.

**Correction during testing:** one test first expected `"  क"` to split as `" "` + `" क"`. Greedy matching actually takes the two-space ASCII entry `"  "` first, leaving `क` without its space. The expectation was wrong, not the codec. The test now asserts the real greedy behaviour, which is recorded as a limitation (§4).

## 3. Results (controlled data, exploratory)
Each group uses its 8 non-overlapping `col-<language>-<category>` columns, from `p2a-*-column-full-1`. Shared vocabularies are not charged.

| Group | Original | Raw | Best `sgtt` | P1 | **P2a** | **P2a vs best `sgtt`** (bytes) | P2a vs P1 | Median vs `sgtt`: P2a (P1) | Fallback share P1 → P2a |
|---|---|---|---|---|---|---|---|---|---|
| hi | 10,511 | 10,619 | 2,479 | 6,297 | **4,694** | **−89.4%** | +25.5% | +27.0% (+14.7%) | 28.6% → 3.1% |
| kn | 13,391 | 13,502 | 2,861 | 6,860 | **5,757** | **−101.2%** | +16.1% | +27.6% (+17.0%) | 20.6% → 4.8% |
| en | 5,665 | 5,775 | 2,656 | 2,721 | **2,721** | **−2.4%** | 0.0% | +27.0% (+27.0%) | 18.6% → 18.6% |
| en-hi | 6,584 | 6,679 | 2,129 | 3,693 | **2,840** | **−33.4%** | +23.1% | +35.0% (+28.7%) | 29.4% → 6.7% |
| en-kn | 7,188 | 7,284 | 2,175 | 3,652 | **3,078** | **−41.5%** | +15.7% | +35.9% (+32.5%) | 24.4% → 9.3% |
| **All 40** | 43,339 | 43,859 | **12,300** | 23,223 | **19,090** | **−55.2%** | +17.8% | | |

A negative percentage means P2a is larger.

- **Payload only (token-ID bytes):** P2a 18,058 against best `sgtt` 6,044, which is **3.0× larger**. In the groups the ratio ranges from +98.7% (`en`) to +276.5% (`hi`). The gap is in the tokens themselves, not in metadata.
- **H1, fallback halved: supported on controlled data** for every Indic and mixed group. `en` is unchanged, as expected: its data has no Indic text, and none of the dropped ASCII entries are used.
- **P2a vs P1:** smaller on 25 of 40 columns, identical on 15, never larger.
- **P2a vs `baseline_c`, per column:** better on 31 of 40, because P1's per-column fixed-cost advantage is kept. The medians rise, but the byte totals still lose.
- **P2a vs raw HCC1:** 52.9–57.7% smaller, by total bytes.

**Vocabulary and amortization:**

| Codec | Shared vocabulary bytes |
|---|---|
| P2a | 445,881 (P1 + 688) |
| P1 | 445,193 |
| OpenAI200K | 3,332,170 |
| Gemma3 | 4,275,024 |

- None of these is charged per column.
- P2a's break-even against raw (linear extrapolation, not measured) is about 0.76–0.83 MB of text per group, computed as `vocabulary / ((raw − P2a) / original)`.

**Timing (`col-all`, median of 7, Release; this machine only):**

| | Encoder setup | Column encode | Decoder setup | Decode |
|---|---|---|---|---|
| P2a, `kn-hi` | 9.01 ms | 0.739 ms | 9.03 ms | 0.038 ms |
| P2a, `en-mixed` | 9.51 ms | 0.634 ms | 9.49 ms | 0.038 ms |
| P1, `kn-hi` | 9.42 ms | 1.020 ms | 9.53 ms | 0.042 ms |
| P1, `en-mixed` | 9.58 ms | 0.768 ms | 9.57 ms | 0.041 ms |
| OpenAI200K, `kn-hi` | 2.72 ms | 0.304 ms | 2.69 ms | 0.059 ms |
| Gemma3, `kn-hi` | 3.41 ms | 0.306 ms | 4.05 ms | 0.058 ms |

P2a encodes faster than P1 (fewer tokens), but still about 2.4× slower than `sgtt`, and its setup is about 3× longer.

## 4. Limitations
- The datasets are controlled and synthetic, with 8 small columns per group. These results can't satisfy the Phase 2 real-data criterion.
- **Greedy matching isn't optimal:** a run of spaces before an akshara is taken by an ASCII whitespace entry first (§2).
- Entries are added for a space before *every* akshara entry, including dependent signs that never follow a space in well-formed text. Those entries are unused, but they still cost ID space.
- No sanitizer, Linux x86-64 or native-speaker review was done for this experiment.

## 5. Outcome
- **H1:** supported on controlled data (exploratory).
- **P2a as a codec on controlled data:** fails to beat `sgtt` (exploratory). By total bytes it is 2.4–101% larger in every group.
- **Phase 2 success criterion (real data):** **blocked.** It needs D3 approval for FLORES+ evaluation-only use, its storage location, and a training source. No Kannada–English code-mixed source exists.

## 6. What the results justify next
- **The remaining gap is token-ID bytes (3×),** caused by short tokens and fixed 16-bit IDs.
- **P2b alone is unlikely to close it.** P2b is P2a with 1-byte IDs when a column uses ≤256 distinct tokens, plus a used-ID list. An **estimate** from the measured token counts, not a measurement, puts it at about 14,207 bytes over the 40 columns, still about 15.5% larger than `sgtt`.
- **Recommendation:**
  1. Implement and measure **P2b** as specified. It's cheap, needs no data, and tests the ID-width part of the gap.
  2. P2c (multi-akshara and word entries) is probably what's needed to reach `sgtt`. It **requires an approved training corpus** that is separate from evaluation data, so it is blocked on D3.
