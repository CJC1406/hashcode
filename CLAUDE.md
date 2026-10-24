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

##Current issue

The original project build fails on Apple Silicon because compiler commands include Intel AVX-512 flags such as -mavx512f, -mavx512bw, -mavx512dq, and -mavx512vl.

Investigate how the build configuration selects these flags and whether the project supports ARM64 or macOS.

Do not simply remove compiler flags or alter algorithms without understanding the implications. Identify the affected files and propose a minimal, reversible solution first.
Current phase: Phase 0 — research and baseline reproduction.
