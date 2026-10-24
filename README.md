# Token Tables for Bharat

Hashcode 14.0, Track 04 (Data Compression). The project measures token-table compression of Hindi, Kannada, English and mixed-language strings against the upstream implementation from "Accelerating String-Heavy Queries with LLM Token Tables" (PVLDB 2026).

## Status
- **Phase 0:** the upstream baseline builds on Apple Silicon. Its known failures and four upstream bugs are documented in `docs/phase0_baseline_findings.md`.
- **Phase 1:** benchmark harness in per-value and column mode (HCC1 container), comparing raw UTF-8 with upstream `sgtt` (OpenAI200K and Gemma3 vocabularies). See:
  - `docs/phase1_benchmark_report.md`
  - `docs/phase1_column_protocol.md`
  - `docs/bharat_prototype_experiment.md`
- **P1** (the Bharat-specific akshara token table) is not implemented yet.

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
cmake --build build-arm64 --target hashcode_column_tests phase1_harness phase1_column_harness hashcode_roundtrip_tests
cd ../..
external/token-vldb2026/build-arm64/hashcode_tests/hashcode_column_tests
python3 -I benchmarks/phase1/run_column_benchmark.py --smoke
python3 -I benchmarks/phase1/run_column_benchmark.py --dataset en-mixed-v1 --smoke
```

## Layout
| Path | Contents |
|---|---|
| `benchmarks/phase1/` | C++ harnesses, the HCC1 column format, Python runners and the result audit |
| `tests/` | project-owned Catch2 tests, attached to the upstream build through a CMake hook |
| `datasets/` | frozen Phase 1 datasets with builders, checksums and READMEs |
| `results/phase1/` | recorded benchmark runs. Run metadata contains local absolute paths from the original machine |
| `patches/` | the build/portability patch for the upstream checkout |
| `docs/` | findings, protocols, reports and the P1 design |
