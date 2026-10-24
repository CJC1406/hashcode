# Token Tables for Bharat — Development Instructions

## Project objective
Research and implement lossless, script-aware token-table compression for Indian-language database strings.

The primary reference is "Accelerating String-Heavy Queries with LLM Token Tables" (PVLDB 2026). Additional references are BtrBlocks (SIGMOD 2023) and NNCP.

## Development environment
- macOS on Apple Silicon
- Antigravity IDE with Claude Code
- C++23 for reproducing the original implementation
- C++17 or later for our own codec, subject to design decisions
- Python 3 for dataset preparation and analysis
- CMake for builds
- Git for version control

## Repository structure
- research/: papers and technical notes
- external/: third-party reference implementations
- datasets/: corpora and test data
- codec/: proposed compression engine
- tests/: correctness and property-based tests
- benchmarks/: benchmark programs
- experiments/: evaluation scripts
- results/: measured outputs
- docs/: specifications and reports

## Rules
1. Work only on the currently assigned phase.
2. Read the relevant paper and source code before proposing algorithmic changes.
3. Do not modify code under external/ without explicit permission.
4. Do not invent benchmark results, citations, speedups, or compression ratios.
5. Never claim that an experimental hypothesis is proven without evidence.
6. Preserve exact lossless round-trip correctness.
7. Distinguish Unicode code points, UTF-8 bytes, and grapheme clusters.
8. Account for metadata, dictionary size, and fallback overhead in compression measurements.
9. Write tests for edge cases, mixed scripts, empty strings, invalid input, and Unicode handling.
10. Explain the rationale and trade-offs for each architectural decision.
11. Before executing destructive commands or downloading large datasets, request approval.
12. Maintain reproducible experiment configurations and record compiler versions, hardware, and dataset provenance.

## Workflow
For each phase:
1. Explain the objective.
2. Identify relevant research.
3. Propose implementation tasks.
4. Implement only approved tasks.
5. Run tests.
6. Record results and limitations.
7. Prepare a phase completion report.

## Project status (updated 2026-10-24)
Run project Git commands only from `/Users/cjc/Downloads/hashcode`. `/Users/cjc` is an unrelated repository.

**Phase 1: complete for controlled harness validation** (`docs/phase1_benchmark_report.md` §P).
- **P1** (`codec/p1/`, vocabulary SHA-256 `8c85586c…`):
  - Exact reconstruction (7,652 test assertions; 248 / 248 benchmark rows).
  - Deterministic vocabulary built without evaluation data; repeat runs identical.
  - Met the pre-registered D2 median criterion in 5 / 5 language groups.
- **But it is not a better codec:** byte-weighted over 40 columns, P1 is 88.8% larger than the best `sgtt` baseline (23,223 vs 12,300 bytes). Its encoding is about 3× slower, and about 24% of its tokens are single-byte fallbacks, mostly spaces.

**Current phase: Phase 2** (`docs/phase2_proposal.md`, proposal not yet approved).
- **Hypothesis H1:** space+akshara entries cut fallback.
- **First experiment: P2a** (`codec/p2a/`, SHA-256 `c99ff52f…`), which is frozen P1 plus space+akshara entries.
  - On the controlled data it cut fallback sharply and was 16–25% smaller than P1 for the Indic groups.
  - It is still 55% larger than `sgtt` (19,090 vs 12,300 bytes; `docs/phase2_p2a_report.md`).

**Unproven:** any effectiveness on real Hindi, Kannada or code-mixed text.

**Outstanding:**
- D3 real-data approval: FLORES+ for evaluation only; a training source; a Kannada–English code-mixed source.
- Linux x86-64 testing.
- Sanitizer runs of the P1/P2a and column code.
- Native-speaker review of the controlled datasets.
- Both controlled datasets are for harness validation only.
