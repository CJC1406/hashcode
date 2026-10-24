# Phase 0 — Baseline Findings

Status: Phase 0 (research and baseline) is ready to close. The paper's published benchmarks have **not** been reproduced; that is a separate milestone.

Line numbers below refer to the working tree on `fix/arm64-build`. In `src/tokenizer/Decoder.cpp` they include the lines added by the ARM64 patch.

## A. Research scope

### Reference baseline
- **Reference:** "Accelerating String-Heavy Queries with LLM Token Tables" (PVLDB 2026).
- **Implementation:** `https://github.com/umbra-db/token-vldb2026.git`, commit `e202e36e2b33a4768d1122f96880b64416234175`.
- **Local copy:** `external/token-vldb2026`, branch `fix/arm64-build`.
- The upstream algorithms, encoded formats and upstream tests are unchanged. The only local changes are the uncommitted build and portability edits listed below.

### What has and has not been reproduced
| Item | Status |
|---|---|
| `sgtt_core` library and upstream Catch2 tests build on macOS ARM64 | Done, with the local changes listed below |
| Upstream Catch2 suite run | Done: 2 known failures (section B) |
| Independent byte-for-byte round-trip tests | Done: project-owned suite in `tests/` |
| `sgtt` CLI build | Not done. `PerfEvent` timing has a full implementation only on Linux, and Apple's libc++ has no `std::chrono::zoned_time` |
| Paper's benchmark results (compression ratios, query times) | Not reproduced |
| Linux x86-64 reference run | Not done |
| Scalar vs AVX-512 decoder equivalence | Not checked; ARM64 has no AVX-512 path |

### Environment
- **Host:** macOS 27.0.1 (build 26A434), Apple M3, `arm64`, 8 logical CPUs, 8 GB RAM.
- **Compiler:** Apple clang 21.0.0 (clang-2100.3.34.2), libc++, `-std=gnu++23`.
- **Tools:** CMake 4.4.4; Python 3.14.4; Catch2 v3.11.0 (fetched by the upstream build).
- **Dependencies:**
  - Homebrew: Boost 1.92.0 (`/opt/homebrew/opt/boost`), jemalloc 5.4.0 (`/opt/homebrew/opt/jemalloc`).
  - vcpkg (upstream's own setup): brotli 1.2.0, liblzma 5.8.4, lz4 1.10.0, snappy 1.2.2, zstd 1.5.7.
- **Release flags (`build-arm64`):** `-isystem /opt/homebrew/opt/boost/include -O3 -DNDEBUG -fno-tree-vectorize`; linker `-L/opt/homebrew/opt/jemalloc/lib`.

The full provenance, including SHA-256 checksums of the dictionaries involved in the findings, is in `<scratchpad>/phase0/environment.txt`.

### Local changes required to build (uncommitted, upstream repo)
- **ARM64 compatibility:**
  - `src/CMakeLists.txt`: the AVX-512 flags are only applied on x86-64.
  - `src/tokenizer/Decoder.cpp`: the AVX-512 decoder is compiled only on x86-64. ARM64 always uses the scalar decoder (`decodeImpl`).
- **Portability (missing standard headers, one macOS type mismatch):**
  - `FsstConfig.hpp`: added `<string>`.
  - `LookupTableDecoder.cpp`: added `<bit>`.
  - `FsstCompressor.cpp`: added `<algorithm>`.
  - `LongestPrefixMatcher.cpp`: added `<algorithm>`.
  - `HuffmanCompressor.cpp`: `min` → `min<size_t>`.
  - `Mmap.cpp`: the Linux-only `MADV_HUGEPAGE` hint is guarded with `#ifdef`.
- None of these changes token ordering, IDs, encoded formats or compression algorithms.

### Build commands
```bash
cd external/token-vldb2026
cmake -S . -B build-arm64 -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS="-isystem /opt/homebrew/opt/boost/include" \
  -DCMAKE_EXE_LINKER_FLAGS="-L/opt/homebrew/opt/jemalloc/lib" \
  "-DCMAKE_PROJECT_static-global-token-table_INCLUDE=/Users/cjc/Downloads/hashcode/tests/cmake/attach_to_upstream.cmake"
cmake --build build-arm64 --target sgtt_core test hashcode_roundtrip_tests --parallel $(sysctl -n hw.ncpu)
```
The `CMAKE_PROJECT_..._INCLUDE` hook attaches our `tests/` target to upstream's build without editing `external/`.

## B. Baseline test evidence

All results below were re-run on 2026-10-24 from the Release build. Logs are in `<scratchpad>/phase0/logs/`.

### Upstream Catch2 suite
`./build-arm64/test/test` → exit 42
```
test cases:     4 |     2 passed | 2 failed
assertions: 57642 | 57640 passed | 2 failed
```
The two failures are upstream test-expectation discrepancies, not confirmed codec bugs:

1. **OpenAI200K tokenizer expectation.**
   - Reproduce: `./build-arm64/test/test "TokenizerTest" -c "openai200k"`
   - The shipped dictionary leaves out the two-byte NUL token `\x00\x00`, because `extract_tokens.py:315-323` deliberately removes multi-byte tokens that contain a NUL byte.
   - The expected IDs for the alice text decode exactly against a dictionary with `\x00\x00` restored at ID 256. Our IDs decode the text byte for byte against the shipped dictionary.
   - The "quick brown fox" expectation in the same file matches the shipped dictionary.
   - Impact: token-ID compatibility with the older dictionary. The tested round trip is unaffected.
2. **`TokenizerCompressor` ("tok") size expectation.**
   - Reproduce: `./build-arm64/test/test "CompressorTest" -c "tok onPairCutoff=0 onPairStoreLengths=0"`
   - The test expects 4,522 bytes; we produce 4,526 bytes, i.e. 2 more 16-bit IDs. The round-trip checks pass.
   - This compressor uses sparse IDs and has no sort, so the suspected `std::sort` tie-ordering cause doesn't apply.
   - An independent Python model of the compressor on the shipped dictionary also produces 4,526 bytes.
   - Where the expected size came from is unknown.

Both are treated as unresolved baseline discrepancies until a Linux x86-64 run reproduces or explains them. The expectations are left unchanged.

### Project-owned round-trip suite (`tests/roundtrip/RoundTripTest.cpp`)
Every check compares the decoded output with the original **bytes**.

`./build-arm64/hashcode_tests/hashcode_roundtrip_tests "~[empty]"` → exit 42
```
test cases:     8 |     5 passed | 3 failed
assertions: 21737 | 21730 passed | 7 failed
```
| Test case | Result |
|---|---|
| sgtt: 13 base tokenizers × Sparse/Dense/Frequent IDs, 50 fixed inputs | 3,900 / 3,900 |
| sgtt: 26 patched/random tokenizer variants × 3 ID encodings | 7,800 / 7,800 |
| sgtt: OpenAI200K, max token size 1–16 × 3 ID encodings | 4,798 / 4,800 (Finding 4) |
| sgtt: Huffman token compressor (OpenAI 50K/100K/200K, Dense) | 300 / 300 |
| tok | 96 / 100 (Finding 3) |
| token-boundary prefixes, and random bytes of length 1–256 and 4,096 | 4,750 / 4,750 |
| long inputs, 1 MiB or more | 72 / 72 |
| FrequentIds, max token size 1: full vs partial vocabulary | 14 / 15 (Finding 4) |

The fixed inputs cover:
- ASCII, and nine Indian scripts: Hindi, Bengali, Tamil, Telugu, Kannada, Malayalam, Gujarati, Gurmukhi and Odia.
- Indic digits, and mixed-script text with currency and emoji.
- Viramas, ZWJ/ZWNJ, chillu, and nukta in both precomposed and decomposed form.
- Leading and stacked combining marks, BOM/NBSP/soft hyphen, emoji ZWJ sequences.
- Invalid UTF-8, NUL bytes, all 256 byte values, and 10,000-byte repeats.

**Empty input**, one process per configuration:
- Command: `"[empty]" -c "<config>"`
- 40 configurations: 27 pass and 13 crash with SIGSEGV. All 13 crashes are FrequentIds (Finding 1). `tok` passes.

**Historical totals** reported before this re-run match the current ones, with one exception: Huffman was 288 / 288 before 2 NUL inputs were added to the fixed set, and is now 300 / 300.

**Correctness is not compression:** these tests show that bytes survive the round trip. They say nothing about compression ratio or speed.

## C. Findings 1–4

Evidence classifications used: **Confirmed behavior**, **Confirmed root cause**, **Strongly indicated by source analysis**, **Hypothesis requiring further validation**. None of the findings is patched; upstream code is unchanged.

### Finding 1 — FrequentIds crashes on empty input
- **Affected:** `sgtt` with `tokenIdEncoding=FrequentIds`, all 13 base tokenizers, empty input, Release build. Sparse, Dense and `tok` handle empty input.
- **Reproduce:** `./build-arm64/hashcode_tests/hashcode_roundtrip_tests "[empty]" -c "sgtt tokenizer=openai50k encoding=frequent"`
- **Expected:** upstream's contract excludes empty input. `Tokenizer.cpp:154-155` (compress) and `:235-236` (decompress) assert `numberOfTokens > 0` and `uncompressedSize > 0`. Release defines `NDEBUG`, which removes those asserts, so nothing rejects empty input there.
- **Observed:**
  - SIGSEGV, with lldb reporting `EXC_BAD_ACCESS address=0x0` in `StandardDecoder<uint128>::decodeImpl<uint8_t>`.
  - The faulting instruction is `ldr w10, [x8, x9, lsl #2]` with `x8 = 0` and `x9 = 0`: a 32-bit load from a null base.
  - Logs: `release_empty_per_config.log`, `release_finding1_lldb.log`.
- **Source locations:**
  - FrequentIds decoder block: `Decoder.cpp:446-510`.
  - `originalTokenSize = state.tokenOrder.size() / state.usedTokens` at `:499`.
  - `default: unreachable()` at `:505`.
- **Classification:** the crash is **confirmed behavior**. The mechanism is a **hypothesis requiring further validation**, though the register evidence supports it.
- **Likely mechanism (unconfirmed):**
  - Empty input gives `usedTokens == 0`, so line 499 divides 0 by 0.
  - On ARM64 `udiv` doesn't trap and returns 0. The `switch` then reaches `unreachable()`, which is undefined behaviour.
  - The registers look like the `uint32_t` dictionary-build loop reading `tokenOrder[0]` from an empty, null array.
  - Neither UBSan nor the assert has been observed directly. On x86-64 the same division would raise SIGFPE instead.
- **Impact:** a crash on an input upstream doesn't support. Sparse/Dense passing in Release depends on undefined behaviour, so it isn't evidence that empty input is supported.
- **Sanitizer status:** not run; it needs the full library linked under UBSan (section D).
- **Next experiment:**
  - Run the same case in the Debug sanitizer build. Expect the `Tokenizer.cpp:154` assert first, because Debug has no `NDEBUG`.
  - Then run it in a separate sanitizer build that defines `NDEBUG`, for example the smaller `-O1 -gline-tables-only` variant, without editing upstream code. Look for a UBSan `integer-divide-by-zero` report at `Decoder.cpp:499`.
- **Decision recorded:** our tests keep empty input as a separate, isolated case. We don't treat a crash as acceptable, and we don't claim upstream supports empty input. Our Bharat codec must define empty-input behaviour explicitly (see `docs/bharat_prototype_experiment.md`).

### Finding 2 — `tok` reads before the input start for inputs of 1–7 bytes
- **Affected:** `TokenizerCompressor` (`tok`), inputs shorter than 8 bytes.
- **Reproduce (sanitizer):** `ASAN_OPTIONS=detect_leaks=0 <scratchpad>/phase0/asan_tok_driver <0..6>`. This is a narrow ASan/UBSan binary made from the sanitizer build's `TokenizerCompressor.cpp.o` and its dictionary object. Each input sits at the start of its own heap allocation.
- **Expected:** no access outside the input and its 16 bytes of trailing padding.
- **Observed:**
  - For every length from 1 to 7, AddressSanitizer reports `heap-buffer-overflow`: a `READ of size 8` in `unalignedLoad<uint64_t>` (`CompilerHints.hpp:77`), called from `TokenizerCompressor::compress` at **`TokenizerCompressor.cpp:242`**.
  - The read is "located (8 − length) bytes before" the input region, from 7 bytes before for length 1 down to 1 byte before for length 7.
  - The length-8 control passes cleanly.
  - In Release, the same inputs round-trip correctly, because the stray bytes are shifted away.
  - Logs: `logs/asan_tok/case_0..7.log`.
- **Source:** line 242 `unalignedLoad<uint64_t>(reader - 8 + remaining)`. Line 235 `while (reader < limit - 8)` also computes a pointer before the buffer when the input is shorter than 8 bytes.
- **Classification:** **confirmed root cause**, by sanitizer report plus source.
- **Impact:** a memory-safety bug (out-of-bounds read). The decoded output is still correct in the observed runs.
- **Patched:** no.
- **Next experiment:** none needed to confirm it. If `tok` is used as a baseline, give it inputs with at least 8 readable bytes before the start.

### Finding 3 — `tok` loses NUL bytes
- **Affected:** `tok` only. All `sgtt` configurations pass the same inputs.
- **Reproduce:** `./build-arm64/hashcode_tests/hashcode_roundtrip_tests "[tok]"`, or `asan_tok_driver 8` / `9`.
- **Expected:** exact round trip.
- **Observed:**
  - `abcdefgh\0\0\0ijklmnop` (19 bytes) decodes to 17 bytes, differing from offset 9.
  - `abcdefghij\0\0` (12 bytes) decodes to 11 bytes. `\0\0` decodes to 1 byte.
  - Control: `abcdefgh\0\0ijklmnop` (two NULs in the middle) is exact.
  - Under ASan/UBSan the same data loss occurs, with **no sanitizer report**.
- **Source:**
  - `lossy_hash_map` uses `Key{}` (0) to mark an empty slot (`LossyHashMap.hpp:159`), and `find` compares `values[slot].first == key` (`:97`).
  - The 3-byte lookup key is `(uint32)text << 8` (`TokenizerCompressor.cpp:221-222`). It is 0 for three NUL bytes, or for two NULs at the end, where the shifted padding is also 0.
  - So `find(0)` returns an empty slot as a hit with value 0, the 1-byte token `\x00`. The reader then advances 3 bytes.
- **Classification:** **confirmed behavior (data loss)** and **confirmed root cause**.
  - A Python model of the same logic was run on 5 inputs, and 4 of them were also run in C++: `\0\0`, three NULs in the middle, two NULs at the end, and the two-NUL control.
  - The C++ results match the model on all 4, including the 17-byte length and the offset-9 mismatch.
  - Every access stays in bounds, so this is a logic error rather than a memory-safety bug.
- **Impact:** silent data loss for any input with three NUL bytes in a row, or two at the end.
- **Patched:** no.
- **Next experiment:** none needed to confirm it. Our codec's tests must include NUL runs.

### Finding 4 — FrequentIds corrupts data when the input uses the whole vocabulary
- **Affected:** `sgtt` with `FrequentIds` whenever every vocabulary entry appears in the input (`usedTokens == tokenCount`). In practice that means `maxTokenSize=1`, where the vocabulary is the 256 single-byte tokens and the input contains all 256 byte values.
- **Reproduce:**
  - `./build-arm64/hashcode_tests/hashcode_roundtrip_tests "[vocab]" -s`
  - `./build-arm64/hashcode_tests/hashcode_roundtrip_tests "[tokensize]"`
- **Expected:** exact round trip.
- **Observed:**
  - **All 256 byte values**, each value v appearing v + 1 times (no frequency ties): `used_tokens 256 == available_tokens 256`, same size, content differs from offset 0.
  - **Control: 255 values** (0x80 left out): `used_tokens 255 < available_tokens 256`, exact byte match.
  - A diagnostic built from the Release objects shows every one of the 32,896 bytes decoding as `255 − b` (`00→ff`, `01→fe`, `ff→00`) and none decoding any other way.
  - Logs: `release_finding4_vocab.log`, and `test_results.txt` for the diagnostic.
- **Source:**
  - The encoder renumbers IDs by frequency only `if (usedTokens != tokenCount)` (`StandardEncoder.hpp:1225`).
  - Otherwise the IDs stay in their original numbering, but the frequency order is still written (`Tokenizer.cpp:218`) and the footer still says FrequentIds.
  - The decoder always applies the frequency mapping (`Decoder.cpp:446-510`), so an original ID `i` decodes as the token at frequency rank `i`. Here that is byte `255 − i`.
- **Classification:** **confirmed root cause**.
  - The control case isolates the `used == available` condition.
  - Removing ties rules out the order of equal-frequency tokens.
  - The `255 − b` pattern is exactly what the source predicts, for all 32,896 bytes.
- **Impact:** silent data loss with the size preserved.
- **Sanitizer status:** not run; the round-trip binary couldn't be linked. No memory error is expected.
- **Patched:** no.
- **Next experiment:** check whether a larger vocabulary can also be fully used in practice (a small custom vocabulary). This matters for any FrequentIds-style ID scheme in our codec.

## D. Sanitizer limitations
- **Build:** `<scratchpad>/asan/build`, Debug, separate from `build-arm64` and outside the upstream repo. It reuses the existing vcpkg and Catch2 checkouts; nothing new was downloaded.
  - `sgtt_core`: `-fsanitize=undefined -fno-omit-frame-pointer -g -O0 -Wall -Wextra -fsanitize=address`.
  - Link: `-fsanitize=address -fsanitize=undefined`, jemalloc 5.4.0.
- **Heap checking works with jemalloc:** a probe with a deliberate heap over-read was reported (`heap-buffer-overflow … asan_probe.cpp:7`), even though Homebrew jemalloc exports plain `malloc`/`free`.
- **Not run: `hashcode_roundtrip_tests` under ASan/UBSan.** Linking failed with `ld: write() failed, errno=28 (No space left on device)`.
  - Free space on the data volume was 4.6 GiB before the link and 2.5 GiB right after the failure, then recovered to between 3.3 and 4.3 GiB.
  - Earlier in Phase 0 it fell as low as about 700 MiB.
  - Each Debug+ASan executable is about 2 GB. The build's objects take 3.9 GB and have been kept.
- **What actually ran under sanitizers:** the probe, and the narrow `tok` driver (Findings 2 and 3, 11 cases). Results are in `<scratchpad>/phase0/sanitizer_status.txt`.
- **Still unverified under sanitizers:** Finding 1, Finding 4, and all `sgtt` suites. **The full sanitizer suite has not passed; it hasn't run.**

## E. Limitations and next steps
- The paper's benchmark results are not reproduced.
- The paper PDF isn't in `research/papers/`. All Phase 0 findings come from the upstream code and tests and haven't been checked against the paper's text.
- Linux x86-64 validation is outstanding. It's needed to settle both upstream test discrepancies and Finding 1's behaviour on x86.
- Scalar vs AVX-512 decoder equivalence hasn't been checked.
- The `sgtt` CLI and its timing don't work on macOS. Benchmarks need either a portable timer or a Linux run.
- Performance on this Mac isn't comparable to the paper: no AVX-512 decoder, no transparent huge pages, a different allocator version, 8 GB RAM, and a nearly full disk.
- The Bharat-specific compression contribution must be implemented and measured separately from the reference. It's specified in `docs/bharat_prototype_experiment.md`.
- The reference implementation stays unchanged apart from the build and portability edits listed in section A. Findings 1–4 are documented, not patched.
- `<scratchpad>` is a session-temporary directory: `/private/tmp/claude-501/-Users-cjc-Downloads-hashcode/4e62390a-4e54-4a0d-94e1-ad8ac4621ee5/scratchpad`. Copy `phase0/*.txt` and `phase0/logs/` into the project, for example `results/phase0/`, if they need to outlive the session.

## Rules for reporting
- Don't change the existing expectations just to make the suite pass.
- Keep the actual output, test commands, dictionary version, compiler and platform in later reports.
- Treat the two upstream failures as unresolved baseline discrepancies until they are reproduced independently or explained.

## Next actions
| Priority | Action | Why |
|---|---|---|
| 1 | Implement the measurement harness and the reference baseline described in `docs/bharat_prototype_experiment.md` | Results must exist before any new method can be judged |
| 2 | Run on Linux x86-64 | Settles the upstream discrepancies and Finding 1 on x86, and gives AVX-512 coverage |
| 3 | Finish the sanitizer suite once disk space allows | Findings 1 and 4 and the `sgtt` suites are not sanitizer-checked |
| 4 | Decide whether to port `sgtt` timing to macOS | Only needed if the native CLI is required |

## Decision
Leave the upstream test expectations and Findings 1–4 unpatched and documented, use the project-owned round-trip suite as the correctness gate, and start the Bharat prototype experiment.
