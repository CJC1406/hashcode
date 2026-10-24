# Phase 1 Benchmark Protocol: Kannada and Hindi baselines

## Scope
- **Inputs:** Kannada and Hindi only, as valid UTF-8 (`datasets/phase1/kn_hi_v1.jsonl`; see its README).
- **Methods:** raw UTF-8, and upstream `sgtt` with OpenAI200K and with Gemma3.
- **Not yet included:** the P1 akshara table (`docs/bharat_prototype_experiment.md`) is added only after the conditions in `docs/phase1_benchmark_report.md` §7 are met.
- **Two storage modes:**
  - **Per-value mode** (this document; `phase1_harness`, `run_benchmark.py`): each sample is its own upstream blob. It's kept as a diagnostic comparison.
  - **Column mode** (`docs/phase1_column_protocol.md`; `phase1_column_harness`, `run_column_benchmark.py`): many values in one HCC1 container around a single upstream blob. **Column mode is the primary comparison**, because upstream targets database text columns.

## What is measured
| Method | Upstream configuration (`TokenizerConfig`) | What the stored blob contains |
|---|---|---|
| `raw_utf8` | none | the UTF-8 bytes. This is the uncompressed baseline, not a compression method |
| `sgtt_openai200k_dense` | `tokenizer=OpenAI200K`, `tokenIdEncoding=DenseIds` | renumbered token IDs + zstd-compressed bitmap of used vocabulary entries + 24-byte footer |
| `sgtt_openai200k_sparse` | `tokenizer=OpenAI200K`, `tokenIdEncoding=SparseIds` | original vocabulary token IDs (4 bytes each) + 24-byte footer |
| `sgtt_gemma3_dense` | `tokenizer=Gemma3`, `DenseIds` | as Dense above |
| `sgtt_gemma3_sparse` | `tokenizer=Gemma3`, `SparseIds` | as Sparse above |

- **Shared settings:** `compressor=sgtt` (`compressor::parseCompressor("sgtt")`). Everything else is the upstream default: `maxTokenSize=16`, `hashMap=BoostMap`, short-token optimization `ArrayShortTokens2`, `simd=Scalar` (ARM64), and token compression `Identity`.
- **Dense is upstream's default** (`defaultTokenIdEncoding = DenseIds`). Sparse is measured as well, because it has no per-value bitmap.
- **FrequentIds and `tok` are excluded,** because of Phase 0 Findings 1–4.
- The complete storage encoding is measured, not just tokenization. `Compressor::compress` returns the full blob that upstream needs in order to decode, and `total_stored_bytes` is its exact size.
- **Storage unit: per value.** Each sample is encoded as its own blob. Upstream is designed for database text columns, so per-value mode charges the footer and bitmap to every value. Column mode, with one blob per column of values, is specified in `docs/phase1_column_protocol.md`.

## Byte accounting
Here `sgtt_*` covers all four `sgtt` methods.

| Column | `raw_utf8` | `sgtt_*` |
|---|---|---|
| `payload_bytes` | original bytes | `token_count × token_id_bytes` (both read from upstream `getInfo()`) |
| `footer_bytes` | blank | 24 (`static_assert(sizeof(Footer) == 24)` in `Tokenizer.hpp`) |
| `bitmap_bytes` | blank | `metadata_bytes − 24`: the zstd bitmap for Dense, 0 for Sparse |
| `metadata_bytes` | 0 | `total_stored_bytes − payload_bytes` |
| `total_stored_bytes` | original bytes | size of the blob returned by `compress` |
| `shared_vocabulary_bytes` | 0 | size of the static vocabulary compiled into `sgtt_core`: OpenAI200K 3,332,170 bytes; Gemma3 4,275,024 bytes |
| `total_stored_bytes_oneshot_with_vocabulary` | original bytes | `total_stored_bytes + shared_vocabulary_bytes` |

The vocabulary sizes are the `*_dict.bin` and `*_lengths.bin` files under `src/tokens/`; their SHA-256s are in `run_metadata.json`.

Checks applied to every row:
- `payload + metadata == total`.
- Sparse bitmap is 0, and the footer is 24.
- The payload equals `token_count × token_id_bytes`.
- The artifact length equals `2 × total`.

Vocabulary treatment:
- The vocabulary is a **shared static asset**, not stored per value. `compression_ratio` and `size_reduction_percent` therefore leave it out.
- The `*_oneshot` columns charge it in full to that single value, as the worst case of storing one value alone.
- Any amortization in between has to be stated explicitly in the report.

## Formulas
Applied per row, using `total_stored_bytes` (or the one-shot total for the `*_oneshot` columns):
- `compression_ratio = original_bytes / total_stored_bytes`. Above 1 means smaller than raw.
- `size_reduction_percent = (original_bytes − total_stored_bytes) / original_bytes × 100`. Negative means the stored form is larger.

Undefined values are left as empty CSV fields, never 0 or infinity:
- when `original_bytes == 0`;
- when the total is unknown;
- when the row's status isn't `ok`.

Token counts are never substituted for byte counts.

Summaries (`summary.csv`), per language × category × method and per language overall:
- the aggregate ratio, `Σ original / Σ total` over rows that can be measured;
- the median per-row ratio;
- the median token count, and median times;
- sample counts by status.

## Correctness
For every `sgtt` row:
1. Encode with `Compressor::create(config)->compress(...)`.
2. Decode with a separate `Compressor::create(config, blob)` followed by `decompress`.
3. Compare the decoded bytes with the original bytes using `memcmp` → `roundtrip_exact`.

Two independent checks are made in Python:
- `input_fnv1a64` must equal Python's FNV-1a of the dataset bytes. This shows every method received identical input.
- The decoded bytes in `artifacts.tsv` must equal the dataset bytes.

Other rules:
- Text is never normalized.
- **Empty input** isn't sent to `sgtt`, because upstream asserts `uncompressedSize > 0` (Phase 0 Finding 1). Those rows get `status=unsupported_input`, are counted separately, and are not counted as failures.
- **Failures** are reported, never dropped: `error`, `roundtrip_mismatch`, or `nondeterministic_encoding` (the blob differs between repetitions).

## Timing
- **Clock:** `std::chrono::steady_clock`, in milliseconds, in the Release build (`-O3 -DNDEBUG`).
- **Each repetition builds new compressor instances.** The four phases are timed separately:
  - `setup_encode`: `Compressor::create`, which builds the tokenizer and its hash maps.
  - `encode`: `compress`.
  - `setup_decode`: `create` from the blob, plus sizing the output buffer.
  - `decode`: `decompress`.
- **Repetitions:** 7 per sample and method for a full run, 3 for a smoke run. Each row reports the median of the repetitions, and summaries report the median of the row medians.
- **Timing isn't reproducible bit for bit;** only the non-timing columns are checked for determinism. Timing values are for comparisons on the same machine only. Here that is an Apple M3 with 8 GB RAM, other processes not controlled, and the CPU frequency not pinned.

## Reproducibility
- `run_metadata.json` records:
  - the dataset path, SHA-256 and version;
  - the upstream remote, commit, branch and uncommitted changes;
  - the build type and flags, the compiler, CMake and Python versions, and the host;
  - the SHA-256 of the harness binary and source;
  - the vocabulary file SHA-256s;
  - the exact harness command and its exit code.
- The input bytes sent to the harness are kept in `input.tsv`. Raw per-row harness output is kept in `raw_harness.csv`, and every encoded blob and decoded output in `artifacts.tsv`.
- `--compare RUN_A RUN_B` checks 17 non-timing columns for equality, including the encoded and decoded hashes and the status.

## Commands
```bash
# build (Release; the hook adds tests/ and benchmarks/ targets without editing upstream)
cd external/token-vldb2026
cmake -S . -B build-arm64 -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-isystem /opt/homebrew/opt/boost/include" \
  -DCMAKE_EXE_LINKER_FLAGS="-L/opt/homebrew/opt/jemalloc/lib" \
  "-DCMAKE_PROJECT_static-global-token-table_INCLUDE=/Users/cjc/Downloads/hashcode/tests/cmake/attach_to_upstream.cmake"
cmake --build build-arm64 --target phase1_harness --parallel $(sysctl -n hw.ncpu)

# run (from the project root)
cd /Users/cjc/Downloads/hashcode
python3 -I benchmarks/phase1/run_benchmark.py --smoke              # 8 samples, 3 repetitions
python3 -I benchmarks/phase1/run_benchmark.py                      # 65 samples, 7 repetitions
python3 -I benchmarks/phase1/run_benchmark.py --compare results/phase1/<A> results/phase1/<B>
```
The runner exits non-zero if the harness reports a failure or any validation check fails.

## Adding a script or a method
- **A script:** add samples to `build_dataset.py` with a new `language` code, then rebuild the dataset; this produces a new version and checksum.
- **A method:** add an entry to `methods()` in `harness.cpp`. A non-upstream method such as P1 must provide its own blob, report `payload`/`metadata`/`dictionary` bytes, and pass the same checks.
