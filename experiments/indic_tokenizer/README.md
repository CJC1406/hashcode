# Indic tokenizer experiment (Plan C)
This is a tokenizer-only prototype for reducing **native LLM input tokens** for Hindi and Kannada. It extends Qwen3's own tokenizer with ByteME-derived candidate strings, and is separate from the ByteME storage codec.

Documentation, results and blockers are in `docs/indic_tokenizer.md`. Tests are in `tests/indic_tokenizer/`.
