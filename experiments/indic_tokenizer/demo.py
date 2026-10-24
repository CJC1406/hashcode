"""Tokenizer demo: base Qwen3 tokenizer vs Qwen3 + ByteME-derived Indic tokens, on HAND-WRITTEN fixture sentences.

TOKENIZER EVALUATION ONLY: no model is loaded and no inference is run, so nothing here measures speed or output quality.
The sentences are hand-written fixtures (tests/indic_tokenizer/fixtures/demo_sentences.jsonl), not evaluation data, and the
counts are illustrative, not evidence of real-world token reduction.
Candidates: the real Wikipedia-derived manifest if it exists locally (default path below), otherwise --candidates.
Usage: python3 -I experiments/indic_tokenizer/demo.py [--candidates M.json] [--fixture F.jsonl]
"""
import argparse
import json
import pathlib
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import candidates as C  # noqa: E402
import evaluate as EV  # noqa: E402
import hf_bpe  # noqa: E402
import scripts as S  # noqa: E402

TOKENIZER = ROOT / "external/token-vldb2026/tokenizers/qwen3.json"
DEFAULT_CANDIDATES = pathlib.Path("/Users/Shared/hashcode-data/indic_tokenizer/wikipedia-20261001/candidates-bytme-k2048.json")
FIXTURE = ROOT / "tests/indic_tokenizer/fixtures/demo_sentences.jsonl"


def show(tk, ids):
    return " | ".join(repr(tk.token_bytes(i).decode("utf-8", "replace"))[1:-1] + (f"[{i}*]" if i in tk.added_ids else f"[{i}]") for i in ids)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", type=pathlib.Path, default=DEFAULT_CANDIDATES)
    ap.add_argument("--fixture", type=pathlib.Path, default=FIXTURE)
    ap.add_argument("--tokenizer", type=pathlib.Path, default=TOKENIZER)
    args = ap.parse_args(argv)
    try:
        m = C.load_manifest(args.candidates)
    except (C.CandidateError, OSError) as e:
        print(f"STOP: cannot use candidates {args.candidates}: {e}", file=sys.stderr)
        return 2
    base = hf_bpe.ByteLevelBPE(args.tokenizer)
    ext = C.extended_tokenizer(args.tokenizer, m)
    corpus = ", ".join(f["file"] for f in m["corpus"]["files"])
    print("TOKENIZER EVALUATION DEMO (no model inference; hand-written fixture sentences; not evidence of real-world results)")
    print(f"base tokenizer: {args.tokenizer.name} (sha256 {base.sha256[:16]}, Qwen3, {base.base_size} IDs, NFC + regex pre-tokenization)")
    print(f"extension: {m['k']} ByteME-derived tokens (pool '{m['pool']}'), IDs {m['id_range'][0]}-{m['id_range'][1]}, from {corpus} "
          f"(training split; {m['corpus']['heldout_documents_skipped']} held-out documents unused); * marks an extension token")
    print("(each token shows its bytes as text; '\ufffd' means the token holds only part of a UTF-8 character, as byte-level BPE splits"
          " Indic text; [id] is the native model token ID)")
    rows = [json.loads(l) for l in args.fixture.read_text(encoding="utf-8").splitlines() if l.strip()]
    totals = {}
    for r in rows:
        t = r["text"]
        a, b = base.encode(t), ext.encode(t)
        red = EV.reduction(len(a), len(b))
        ok_a, ok_b = base.decode_bytes(a) == t.encode(), ext.decode_bytes(b) == t.encode()
        tot = totals.setdefault(r["group"], [0, 0])
        tot[0] += len(a)
        tot[1] += len(b)
        print(f"\n[{r['group']}] {t}")
        print("  script spans: " + " ".join(f"{s}:{sub!r}" for s, sub in S.spans(t)))
        print(f"  base     ({len(a):>2} tokens): {show(base, a)}")
        print(f"  extended ({len(b):>2} tokens): {show(ext, b)}")
        print(f"  reduction {red:+.1f}%   exact round trip: base {ok_a}, extended {ok_b}")
    print("\nTotals by group (fixture sentences only):")
    for g, (a, b) in totals.items():
        print(f"  {g:6} base {a:>3}  extended {b:>3}  reduction {EV.reduction(a, b):+.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
