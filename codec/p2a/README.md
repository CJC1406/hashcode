# P2a: P1 plus space+akshara entries (`p2a-space-akshara-v1`)

Phase 2, experiment 1. The results are in `docs/phase2_p2a_report.md`.

- **Vocabulary:** `p2a_vocabulary_v1.bin`, 65,536 entries, 445,881 bytes, SHA-256 `c99ff52fa92fa7c8be541c0358c10acd678aeaa98764bb474ef06077faa7face`.
- **Build:** `python3 -I codec/p2a/build_vocabulary.py`.
  - Its only input is `codec/p1/p1_vocabulary_v1.bin`, verified against SHA-256 `8c85586c…`.
  - No evaluation data is read.
- **Rule:** P1's single bytes and akshara entries, unchanged (IDs 0–2,751); then `" "` + each akshara entry (IDs 2,752–5,247); then P1's ASCII entries in P1 order, truncated to 65,536 in total.
- **Codec:** `codec/include/p1_codec.hpp`, unchanged. The blob is `u16` IDs plus the 13-byte `BTT1` footer, with this vocabulary's table ID `c99ff52fa92fa7c8`. It is HCC1 codec value 2.
- **Tests:** `tests/p2a/P2aCodecTest.cpp` (target `hashcode_p2a_tests`).
