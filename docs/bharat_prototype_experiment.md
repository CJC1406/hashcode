# Bharat Prototype Experiment — Design (Phase 1)

Status: design only. No implementation exists and no results have been measured. Nothing in this document is a performance claim.

## 1. Research question
Can a clearly defined, Bharat-oriented shared vocabulary improve storage efficiency for representative Indian-language and mixed-language strings, while reconstructing them exactly?

Script awareness is **not** assumed to help. Large LLM vocabularies such as Gemma3 (262K tokens) or OpenAI200K already contain Indic tokens and may do as well or better. The experiment is designed so that a negative result is a valid, reportable outcome.

## 2. Prototype P1: akshara token table with byte fallback
One narrow method, implemented in `codec/`. The upstream reference in `external/token-vldb2026` stays untouched.

### 2.1 Vocabulary (static, built deterministically, no training corpus)
- **IDs 0–255:** every single byte value, so every byte sequence can be encoded, including NUL, invalid UTF-8 and emoji.
- **IDs 256 and up:** for each supported Brahmic block, the UTF-8 byte strings of:
  - each independent vowel and digit;
  - each consonant, optionally followed by a nukta;
  - each consonant followed by exactly one of: a dependent vowel sign, a virama, an anusvara, a visarga or a candrabindu.
- **Initial scripts:** Devanagari, Bengali, Tamil, Telugu, Kannada, Malayalam. Gujarati, Gurmukhi and Odia come later, if the entry budget allows.
- **Size limit:** at most 65,536 entries, so IDs fit in 16 bits.
  - The exact count is computed from the Unicode block definitions at build time, not hand-written.
  - The generator script and its Unicode version are recorded; a table ID is the SHA-256 of the serialized table.
- **Pinned decisions:** whether to add common English or ASCII tokens (for example, the ASCII-only tokens of a reference vocabulary) is decision D1 in section 7. The first version is akshara entries plus byte fallback only.

### 2.2 Transformation and encoding
- **Encoder:** greedy longest-prefix match on bytes against the table, falling back to 1-byte tokens.
  - The match is byte-based and does not depend on UTF-8 validity or grapheme segmentation.
  - Grapheme clusters are used only to *generate* table entries, not to split the input.
- **Decoder:** concatenates the byte strings for the IDs. It is lossless by construction, because every ID maps to a fixed byte string and every input byte is covered by the fallback.
- **Container** (one encoded blob per column sample):

  | Field | Size |
  |---|---|
  | magic `BTT1` | 4 bytes |
  | format version | 1 byte |
  | table ID (first 8 bytes of the table's SHA-256) | 8 bytes |
  | original byte length | varint |
  | token count | varint |
  | payload: token IDs | `uint16` little-endian, `2 × token count` bytes |

  - A decoder rejects an unknown magic, version or table ID.
  - Empty input encodes as the header with token count 0, and decodes to empty.
- **Requirements carried over from the Phase 0 findings:**
  - No sentinel value may collide with a valid key (lesson from Finding 3).
  - No read outside `[input, input + length)`, and no padding requirement on callers (Finding 2).
  - Empty input is defined and tested (Finding 1).
  - No special-case ID scheme that depends on how many vocabulary entries happen to be used (Finding 4).

### 2.3 Out of scope for P1
Learned or corpus-trained vocabularies, transliteration, Unicode normalization (it isn't reversible, so it's forbidden), entropy coding on top of the IDs, SIMD, and integration into Umbra or DuckDB. These are candidates for P2, depending on P1's results.

## 3. Dataset

Categories (every category is evaluated separately and none is mixed into another):

| Category | Content |
|---|---|
| `en` | English-only sentences or rows |
| `hi`, `bn`, `ta`, `te`, `kn`, `ml` | one Indian language each, in its native script |
| `mixed` | English and Indian-language text in the same string (code-mixing, product names, addresses) |
| `short` | strings of 16 bytes or fewer (typical database values) |
| `long` | strings of 4 KiB or more |
| `marks` | combining marks, viramas, ZWJ/ZWNJ, nukta (precomposed and decomposed), chillu |
| `rare` | emoji, emoji ZWJ sequences, uncommon and supplementary-plane characters |

Text experiments use **valid UTF-8 only**. Arbitrary-byte correctness (invalid UTF-8, NUL runs, all 256 byte values) is covered separately in `tests/`, and every method must pass it.

Sources, to be confirmed before any download; downloads need approval (CLAUDE.md rule 11):
- **Synthetic, project-authored:** the inputs already in `tests/roundtrip/RoundTripTest.cpp`, plus generated `short`/`marks`/`rare` sets. Provenance: this repository.
- **Candidate natural text:** a parallel-sentence benchmark such as FLORES-200, which would give the same content across languages, and per-language Wikipedia dumps.
  - Licences must be checked from the source before use. My understanding is that both are CC BY-SA, but that is unverified here.
  - Only small samples with a pinned version and checksum, stored under `datasets/raw/` with a `PROVENANCE.md`.
- **Optional:** real database strings, if the user provides them, with their licence or permission recorded.

Known limitations:
- Wikipedia and FLORES text is formal prose, not database values.
- Code-mixed text is scarce and may need to be synthesized; any synthesized data must be labelled as such.

## 4. Methods compared (identical inputs)
| ID | Method | Notes |
|---|---|---|
| R0 | raw UTF-8 | size baseline |
| R1 | upstream `sgtt`, OpenAI200K, Sparse and Dense IDs | reference token table |
| R2 | upstream `sgtt`, Gemma3, Dense IDs | large multilingual vocabulary |
| R3 | zstd level 3 and level 19 (vcpkg zstd 1.5.7) | general-purpose |
| P1 | akshara token table (section 2) | proposed |

- `tok` and FrequentIds are excluded from the baselines because of Phase 0 Findings 1–4.
- Each reference method is called through the upstream API with the buffer contract of `test/Tester.hpp` (16 bytes of padding after the input).

## 5. Evaluation protocol

### 5.1 Measurements (per method × category × sample)
- `original_bytes`: UTF-8 bytes of the input.
- `payload_bytes`: encoded token or compressed data.
- `metadata_bytes`: headers, footers, offsets and any per-sample bitmaps or orderings.
- `dictionary_bytes`: the serialized vocabulary or dictionary needed to decode.
- `total_bytes_oneshot = payload_bytes + metadata_bytes + dictionary_bytes`
- `total_bytes_amortized = payload_bytes + metadata_bytes + dictionary_bytes / n_samples_sharing_dictionary`
- **Static shared tables** (upstream LLM tables, P1): report `dictionary_bytes` separately as the shipped table size. `total_bytes_amortized` treats the table as shared across all samples in the run, and the one-shot figure includes it in full.
- Encode and decode time in nanoseconds, using a monotonic clock (`std::chrono::steady_clock`). Upstream `PerfEvent` is Linux-only.
- `roundtrip_exact`: decoded bytes equal original bytes. A failure makes that row's size and time invalid.

### 5.2 Formulas
- `compression_ratio = original_bytes / total_bytes`
- `size_reduction_pct = (original_bytes − total_bytes) / original_bytes × 100`
- These are computed for both the one-shot and the amortized total, and labelled as such.
- **Zero denominators:**
  - If `original_bytes == 0`, the ratio and reduction are reported as `NA`, not 0 or infinity. The stored `total_bytes` is still reported, and the round trip must still be exact.
  - `total_bytes == 0` is invalid and counted as a failure.
- Category results are aggregated as sum of original over sum of total, with the median of per-sample values reported next to it.

### 5.3 Procedure
1. Pin the commits (reference and project), compiler, flags and dataset checksums in the run record.
2. Use a Release build only. Build the reference unmodified, apart from the documented portability patch.
3. For each method and sample: 1 warm-up run, then 11 timed repetitions. Report the median and interquartile range.
4. Run on the same machine with nothing else heavy running. Record free disk space and power state. Timing on this 8 GB M3 is only valid for comparisons made on the same machine.
5. Check every output against the original; report and exclude any row that isn't exact.
6. Write one CSV per run to `results/<run_id>/` and generate plots from the CSV only.

### 5.4 CSV schema (`results/<run_id>/measurements.csv`)
```
run_id,timestamp_utc,host,os,cpu,compiler,build_flags,reference_commit,project_commit,
method,method_config,table_id,dataset,dataset_version,dataset_sha256,category,sample_id,n_strings,
original_bytes,payload_bytes,metadata_bytes,dictionary_bytes,total_bytes_oneshot,total_bytes_amortized,
compression_ratio_oneshot,compression_ratio_amortized,size_reduction_pct_oneshot,size_reduction_pct_amortized,
encode_ns_median,encode_ns_iqr,decode_ns_median,decode_ns_iqr,repetitions,roundtrip_exact
```
`NA` marks undefined values. Booleans are `true`/`false`.

## 6. Decision criteria (D2, recorded 2026-10-24)
**Scope note:** the current scope is Hindi and Kannada, plus English and mixed-language data (D1). The six-language list in §2–3 is future work.

All criteria assume 100% exact round trips. Any unresolved correctness failure in P1 means **reject until fixed**, whatever the sizes.

**Acceptance criterion (project criterion, not a test of statistical significance):** P1's median stored-size reduction against the best applicable `sgtt` baseline in column mode is **at least 5%**.

The terms are defined as follows:
- **Storage unit:** an HCC1 column (`docs/phase1_column_protocol.md`). P1 must use the same container: same header and same length table.
- **Stored bytes:** `total_stored_bytes`, which includes the container header, the boundary metadata, and every codec byte (token IDs or payload, bitmap, footer, and any P1 per-column metadata). Shared vocabularies are **not** included in this number; see the last point.
- **Best applicable `sgtt` baseline, per column `c`:** `baseline_c = min(total(sgtt_openai200k_column, c), total(sgtt_gemma3_column, c))`. Both use Dense IDs, the upstream default, and the vocabulary isn't charged. If more upstream configurations are added later (for example Sparse), they join the minimum, and this must be stated.
- **Per-column reduction:** `reduction_c = (baseline_c − candidate_c) / baseline_c × 100`.
- **Statistic:** the median of `reduction_c` over a **declared, non-overlapping** set of evaluation columns, fixed before P1 is measured. Columns with `original_payload_bytes = 0` are excluded, because the ratio is undefined. For `phase1-kn-hi-v1`, this set is the 16 `col-<lang>-<category>` columns.
- **Reporting:** Hindi, Kannada, English and mixed-language results are each reported separately. A pooled median is never shown alone.
- **Vocabulary:** P1's vocabulary or dictionary size is reported separately, together with an explicit amortization analysis: the column size at which it breaks even, as done for upstream in `docs/phase1_benchmark_report.md` §C.5. A vocabulary stored per column counts as stored bytes.
- **Practical check, reported but not part of the 5% criterion:** P1 compared with raw HCC1 for each column. When raw HCC1 is smaller than both P1 and the best `sgtt` baseline, raw is the better practical choice for that column. On `phase1-kn-hi-v1` this is already the case for `col-hi-edge`, `col-hi-tiny`, `col-kn-edge` and `col-kn-tiny` (report §C.7).
- **Timing:** reported with setup, encode, decoder setup and decode kept separate. It isn't part of the acceptance criterion.
- **Data:** `phase1-kn-hi-v1` results validate the harness only (see §7). Meeting the 5% criterion on it is **not** evidence about real Hindi or Kannada data.

*Superseded:* this section first proposed a 10% "continue" threshold, together with English-regression, decode-time and reject rules. Those were never adopted; D2 replaces them.

## 7. Decisions
**Recorded 2026-10-24:**
- **Dataset acceptance:** `phase1-kn-hi-v1` (65 synthetic Hindi/Kannada samples written for the project) is accepted **for harness validation only**. **It hasn't been reviewed by a native speaker.** Its results mustn't be presented as evidence of Hindi or Kannada compression performance in general.
- **D1, English tokens:** the intended P1 evaluation includes English and other ASCII-relevant tokens.
  - Hindi, Kannada, English and mixed-language results must be identifiable separately.
  - No English or mixed-language performance has been evaluated yet. The existing `mixed` samples are only 3 per language and are part of the harness-validation dataset.
- **D2:** see §6.
- **D5, column container:** HCC1, the same for every method.

- **D1a, English/ASCII token source (recorded 2026-10-24):** the existing upstream vocabularies, OpenAI200K and Gemma3, used through the existing `sgtt` harness. This was checked against the code and the shipped vocabularies:
  - **Vocabulary used for encoding:** the static token tables compiled into `sgtt_core` (`src/tokens/<name>/*_dict.bin`, at most 16 bytes per entry).
    - OpenAI200K has 196,010 entries; 128,561 are pure ASCII and 3,547 contain Devanagari.
    - Gemma3 has 251,472 entries; 150,255 are pure ASCII and 10,286 contain Devanagari.
    - Each has about 1,150–1,180 entries containing Kannada.
    - Common English pieces such as ` the`, `tion`, ` order` and ` status` are present in both.
  - **`sgtt` matching:** greedy longest-prefix matching. At each position it tries entries from 16 bytes down to 1 (`StandardEncoder.hpp`, the `FIND16(16)`…`FIND1` sequence), with single-byte fallback.
  - **Stored token IDs:** Dense IDs (1 byte if a column uses at most 256 distinct tokens, else 2 bytes), plus a zstd bitmap and a 24-byte footer.
  - **Not the models' own tokenizers.** These vocabularies come from LLM tokenizers, but `sgtt` doesn't apply those tokenizers' BPE merges or pre-tokenization. **It hasn't been checked whether `sgtt` produces the same token sequence as the original tokenizer, and it shouldn't be assumed.**
  - **Evaluation sentences are a separate question:** `phase1-en-mixed-v1` was written for the project (see its README). Real-world sources fall under D3.
  - **Consequence for P1:** P1's English/ASCII coverage has to be compared against these vocabularies. If P1 includes ASCII entries of its own, their count and source must be reported, and they count towards P1's vocabulary size.

**Still open:**
- **D3, real-world or independently reviewed evaluation data.** Findings so far (2026-10-24, from the official pages; **nothing downloaded**):

  | Candidate | Source | Languages | Licence and terms (as stated on the page) | Format and size | Use here |
  |---|---|---|---|---|---|
  | **FLORES+** (successor to FLORES-200, run by OLDI) | huggingface.co/datasets/openlanguagedata/flores_plus. The original FLORES-200 repo (github.com/facebookresearch/flores) is archived and gives no licence in its README | about 230 varieties, including `eng_Latn`, `hin_Deva`, `kan_Knda` | **CC BY-SA 4.0**. Access requires accepting conditions (Hugging Face login and token). "**It should not be used as training data**", and saved copies **should not be redistributed publicly** unless protected from scraping | JSONL per language and split; dev 997 + devtest 1,012 sentences per language; about 225 MB in total | Parallel en/hi/kn sentences of formal web prose (Wikinews, Wikijunior, Wikivoyage), mostly translated from English. Suits single-language evaluation. **No natural code-mixing.** If P1's vocabulary were learned from it, that would break the no-training term. FLORES text **must not be committed** to this repository |
  | **IndicCorp v2** (AI4Bharat) | huggingface.co/datasets/ai4bharat/IndicCorpV2 | 23 Indic splits, including `hin_Deva` (≈152M rows) and `kan_Knda` (≈48.7M rows). **No English split** | The card says the datasets are released under **CC0**. **It doesn't address copyright in the underlying web-crawled text**, and the crawl sources aren't named | text, about 275 GB in total; per-language file sizes aren't listed | Large monolingual Hindi and Kannada web text, likely to contain some English words inline. Use needs a deterministic sample and a provenance record, and the crawl-copyright question needs clarifying |
  | **Code-mixed Hindi–English** (not AI4Bharat) | for example COMI-LINGUA (huggingface.co/datasets/LingoIITGN/COMI-LINGUA) and L3Cube-HingCorpus | Hindi–English in Devanagari and/or Roman script | **not checked** | not checked | the only natural code-mixed candidates found. **No Kannada–English code-mixed corpus was found** |

  **Unresolved:**
  - whether evaluation-only use of FLORES+ fits the project; the vocabulary must not be trained on it;
  - where gated data is stored, given the redistribution terms (outside the repository, or in a git-ignored path);
  - whether the CC0 label on IndicCorp v2 covers the crawled text;
  - which code-mixed source to use, if any, after its licence is checked;
  - how to get Kannada–English mixed text at all.

  **Downloading anything needs approval** (CLAUDE.md rule 11).
- **D4:** answered in practice: harnesses are in `benchmarks/phase1/`, and aggregation is Python in the same directory.

## 8. First implementation task
*Done:* the harness was built first. P1 was added only after the harness reproduced the reference sizes deterministically.
- Correctness comes from `tests/`.
- Sizes come from the actual encoded buffers, and times from `steady_clock`.

## 9. Phase 1 closing decisions and blockers (2026-10-24)
| Topic | Status | Record |
|---|---|---|
| **D3: evaluation data** | **Open, and it blocks language-level claims.** FLORES+ is CC BY-SA 4.0, gated, evaluation-only and not to be redistributed publicly. IndicCorp v2 is labelled CC0 but its crawled text isn't addressed. No Kannada–English code-mixed corpus has been found. Nothing is downloaded, and storage and attribution aren't decided | §7 table; needs user approval |
| **P1 tokenization** | **Implemented** (`codec/p1/`): greedy longest-prefix on bytes, 16 down to 2 bytes, fixed `uint16` IDs | `codec/p1/README.md` |
| **P1 vocabulary** | **Frozen** before measurement (`p1-akshara-ascii-v1`, SHA-256 `8c85586c…`). Structural, built from Unicode 16.0.0 and `o200k.tiktoken`, with **no evaluation data** (checked by a test) | `codec/p1/README.md` |
| **English/ASCII coverage (D1, D1a)** | 62,784 ASCII entries, all present in OpenAI200K and 49,887 in Gemma3, against 128,561 and 150,255 pure-ASCII entries in those vocabularies | `codec/p1/README.md` |
| **Byte fallback** | IDs 0–255 = all single bytes. Exact reconstruction is tested on empty input, NUL, invalid UTF-8, all 256 byte values, and every prefix cut | `tests/p1/P1CodecTest.cpp` |
| **Baseline reproducibility** | The three baselines in the P1 runs are identical to the frozen runs on all 21 non-timing columns | `results/phase1/p1-d2-evaluation/d2_summary.json` |
| **Storage accounting** | Header + boundaries + IDs + bitmap + footer = container size for every row (the audit finds 0 problems). Vocabularies are reported separately | report §P |
| **D2** | Pre-registered as at least a 5% median reduction against `baseline_c`. **Met in all 5 language groups,** but a byte-weighted view shows P1 88.8% larger in total. The median over 8 small synthetic columns rewards low fixed per-column cost | report §P |

**Superseded by implementation:** the per-value `BTT1` header in §2.2 (HCC1 is used instead) and the six-script list in §2.1. See `codec/p1/README.md`, "How this relates to the design".
