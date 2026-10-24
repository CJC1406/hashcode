# Token Tables for Bharat

Hashcode 14.0, Track 04 (Data Compression). The project measures token-table compression of Hindi, Kannada, English and mixed-language strings against the upstream implementation from "Accelerating String-Heavy Queries with LLM Token Tables" (PVLDB 2026).

## Status
- **Phase 0:** the upstream baseline builds on Apple Silicon. Its known failures and four upstream bugs are documented in `docs/phase0_baseline_findings.md`.
- **Phase 1:** benchmark harness in per-value and column mode (HCC1 container), comparing raw UTF-8 with upstream `sgtt` (OpenAI200K and Gemma3 vocabularies). See:
  - `docs/phase1_benchmark_report.md`
  - `docs/phase1_column_protocol.md`
  - `docs/bharat_prototype_experiment.md`
- **P1** (the Bharat-specific akshara token table, `codec/p1/`) is implemented and evaluated.
  - **Phase 1 passed its pre-registered gate on controlled data.**
  - But byte-weighted, P1 stores 88.8% more than the best `sgtt` baseline. Its wins come from lower fixed per-column cost (see `docs/phase1_benchmark_report.md` §P).
- **Phase 2:** the proposal awaits approval (`docs/phase2_proposal.md`). Experiment 1, **P2a** (`codec/p2a/`, space+akshara entries), was run on controlled data only.
  - It cut fallback sharply and is 16–25% smaller than P1 for the Indic groups.
  - It is still 55% larger than the best `sgtt` baseline by total bytes (`docs/phase2_p2a_report.md`).
  - Experiment 2, **P2b** (per-column ID width), is 30.2% smaller than P2a, but still 8.4% larger than the best `sgtt` baseline (`docs/phase2_p2b_report.md`).
  - Experiment 3, **P2c** (learned entries; `codec/p2c/`), has its builder and codec integration implemented and tested on a synthetic fixture only. No P2c vocabulary is frozen and nothing was benchmarked, because there is no approved training corpus (`docs/phase2_p2c_report.md`).
  - The real-data criterion is blocked on data approval (D3).

- **Plan C (separate track):** a tokenizer-only prototype to reduce native LLM input tokens for Hindi and Kannada by extending Qwen3's tokenizer with ByteME-derived tokens (`docs/indic_tokenizer.md`). It has been measured on fixtures only, and no model has been trained or run.

Both datasets (`datasets/phase1/`, `datasets/phase1_en_mixed/`) are small, synthetic, **for harness validation only**, and **not reviewed by native speakers**. Their results are not evidence of real-world compression performance.

## Upstream reference (not included in this repository)
The upstream code is not vendored here: it has no licence file. Fetch it at the pinned commit and apply the project's ARM64/portability patch. The patch makes 8 build-only edits and changes no algorithms or formats.

```bash
git clone https://github.com/umbra-db/token-vldb2026.git external/token-vldb2026
git -C external/token-vldb2026 checkout e202e36e2b33a4768d1122f96880b64416234175
git -C external/token-vldb2026 apply ../../patches/token-vldb2026-arm64-portability.patch
```

## Build and run (macOS, Apple Silicon)
Requirements: Homebrew `boost` and `jemalloc`, CMake 3.28 or later, and Apple clang with C++23.

```bash
brew install boost jemalloc
cd external/token-vldb2026
cmake -S . -B build-arm64 -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-isystem $(brew --prefix boost)/include" \
  -DCMAKE_EXE_LINKER_FLAGS="-L$(brew --prefix jemalloc)/lib" \
  "-DCMAKE_PROJECT_static-global-token-table_INCLUDE=$PWD/../../tests/cmake/attach_to_upstream.cmake"
cmake --build build-arm64 --target hashcode_column_tests hashcode_p1_tests phase1_harness phase1_column_harness hashcode_roundtrip_tests
cd ../..
python3 -I codec/p1/build_vocabulary.py       # optional: rebuilds the frozen P1 vocabulary (same SHA-256)
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_column_tests
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_p1_tests
python3 -I benchmarks/phase1/run_column_benchmark.py --smoke
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --smoke
```

## Layout
| Path | Contents |
|---|---|
| `benchmarks/phase1/` | C++ harnesses, the HCC1 column format, Python runners, the result audit and the D2 evaluation |
| `codec/` | the P1 codec (`include/p1_codec.hpp`) and its frozen vocabulary and builder (`p1/`) |
| `tests/` | project-owned Catch2 tests, attached to the upstream build through a CMake hook |
| `datasets/` | frozen Phase 1 datasets with builders, checksums and READMEs |
| `results/phase1/`, `results/phase2/` | recorded benchmark runs. Paths in `run_metadata.json` are relative to the repository root, **except** in the six `results/phase1/p1-*-column-*` runs, which record absolute paths from the original machine and are kept unmodified as recorded. Absolute paths also remain in the build and test logs (`*_logs/` directories) and in some commands in `docs/` |
| `patches/` | the build/portability patch for the upstream checkout |
| `docs/` | findings, protocols, reports and the P1 design |
