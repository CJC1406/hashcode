"""ByteME-derived Indic candidate tokens for a model tokenizer (separate from the storage codec; the frozen P2c file is only read).

Pools (the same scoring for both, so they form a fair ablation):
  bytme  ("B")  the frozen P2c learned entries (akshara-aligned, <= 16 bytes) PLUS whole words (single-script runs, with or
                without their leading space, any length) that begin with a P2c learned entry;
  words  ("C")  whole words only, chosen by the same score, without using the P2c vocabulary.
Frequencies come only from the TRAINING split of an approved corpus (documents with sha256(doc_id) mod 20 == 0 are the
held-out split and are skipped, exactly as in the P2c builder). Evaluation data is never read.
  P2c entries: akshara-aligned substring occurrences (an added token also matches inside longer words);
  words      : whole-word occurrences (a lower bound on matches).
Score = frequency x (base-tokenizer tokens for the candidate - 1) - row_cost; candidates are dropped if they are not
NFC-stable (the tokenizer normalizes to NFC), are already a single base token, occur fewer than min_freq times, or score <= 0.
Selection: strict K/2 per script (Devanagari, Kannada), ties broken by longer UTF-8 first, then code-point order.
New IDs are assigned after the base vocabulary: Devanagari candidates first, then Kannada, in rank order.
Usage:
  python3 -I experiments/indic_tokenizer/candidates.py --corpus A.jsonl [--corpus B.jsonl] --tokenizer qwen3.json \\
      --pool bytme --k 2048 --out-dir DIR      (DIR must be outside the repository: candidates are training-derived text)
"""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import sys
import unicodedata
from collections import Counter

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import hf_bpe  # noqa: E402
import scripts as S  # noqa: E402

CANDIDATES_VERSION = "indic-candidates-v1"
P2C_VOCABULARY = ROOT / "codec/p2c/p2c_vocabulary_v1.bin"
P2C_MANIFEST = ROOT / "codec/p2c/p2c_vocabulary_v1.manifest.json"
P2C_SHA256 = "1e12dc488beddfdf0242268fd17cdd90e93d834be0a81e6780754bcbc629dc84"
P2C_MAX_BYTES = 16
SCRIPT_OF_LANG = {"hi": "Deva", "kn": "Knda"}  # the P2c builder's run languages are script blocks


class CandidateError(Exception):
    pass


def _builder():
    spec = importlib.util.spec_from_file_location("p2c_builder_for_candidates", ROOT / "codec/p2c/build_vocabulary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_p2c(vocab=P2C_VOCABULARY, manifest=P2C_MANIFEST, expected_sha=P2C_SHA256):
    """Learned P2c entries {text: p2c_id}, after verifying the frozen file's SHA-256."""
    blob = pathlib.Path(vocab).read_bytes()
    if hashlib.sha256(blob).hexdigest() != expected_sha:
        raise CandidateError(f"P2c vocabulary {vocab} does not have the frozen SHA-256 {expected_sha}")
    m = json.loads(pathlib.Path(manifest).read_text())
    if m["sha256"] != expected_sha:
        raise CandidateError("P2c manifest does not describe the frozen vocabulary")
    entries = _builder().read_vocabulary(blob)
    out = {}
    for key in ("learned_hi", "learned_kn"):
        lo, hi = m["id_ranges"][key]
        for i in range(lo, hi + 1):
            out[entries[i].decode("utf-8")] = i
    return out


def count_training_runs(corpora, seg, B):
    """Counter of (leading_space, run) over the training split; returns (counter, documents_read, heldout_skipped)."""
    runs, seen, n, held = Counter(), set(), 0, 0
    for path in corpora:
        B.corpus_info(path)  # refuses the controlled evaluation datasets (by SHA-256 and path)
        for d in B.iter_corpus(path, seen):
            n += 1
            if B.is_heldout(d["doc_id"]):
                held += 1
                continue
            for line in d["text"].split("\n"):
                for _lang, space, run in seg.runs(line):
                    runs[(space, run)] += 1
    return runs, n, held


def p2c_substring_counts(runs, seg, p2c):
    """Akshara-aligned occurrences of each P2c entry (with/without leading space) in the training runs."""
    counts = Counter()
    for (space, run), mult in runs.items():
        ak = seg.aksharas(run)
        for i in range(len(ak)):
            acc = ""
            for j in range(i, len(ak)):
                acc += ak[j]
                if len(acc.encode("utf-8")) > P2C_MAX_BYTES:
                    break
                if acc in p2c:
                    counts[acc] += mult
                if i == 0 and space and (" " + acc) in p2c:
                    counts[" " + acc] += mult
    return counts


def starts_with_p2c(space, run, seg, p2c):
    acc = " " if space else ""
    for a in seg.aksharas(run):
        acc += a
        if len(acc.encode("utf-8")) > P2C_MAX_BYTES:
            return False
        if acc in p2c:
            return True
    return False


def build(corpora, tokenizer_path, pool, k, min_freq=20, row_cost=0, p2c=None):
    if pool not in ("bytme", "words"):
        raise CandidateError("pool must be 'bytme' or 'words'")
    if k < 2 or k % 2:
        raise CandidateError("k must be an even number >= 2 (strict 50/50 per script)")
    B = _builder()
    seg = B.Segmenter()
    tk = hf_bpe.ByteLevelBPE(tokenizer_path)
    p2c = load_p2c() if p2c is None else p2c
    runs, n_docs, n_held = count_training_runs(corpora, seg, B)
    cand = {}  # text -> (kind, freq, freq_kind, p2c_id)
    for (space, run), f in runs.items():
        if f < min_freq:
            continue
        if pool == "bytme" and not starts_with_p2c(space, run, seg, p2c):
            continue
        cand[(" " if space else "") + run] = ("word", f, "whole-word occurrences", None)
    if pool == "bytme":
        for text, f in p2c_substring_counts(runs, seg, p2c).items():
            cand[text] = ("p2c_entry", f, "akshara-aligned substring occurrences", p2c[text])  # replaces a same-text word
    excluded = Counter()
    scored = {"Deva": [], "Knda": []}
    for text, (kind, f, fk, pid) in cand.items():
        if f < min_freq:
            excluded["below_min_freq"] += 1
            continue
        if unicodedata.normalize("NFC", text) != text:
            excluded["not_nfc_stable"] += 1
            continue
        script = S.dominant(text)
        if script not in scored:
            excluded["not_single_script"] += 1
            continue
        base_ids = tk.encode(text)
        if tk.decode(base_ids) != text:
            excluded["base_round_trip_mismatch"] += 1
            continue
        if len(base_ids) < 2:
            excluded["already_single_base_token"] += 1
            continue
        score = f * (len(base_ids) - 1) - row_cost
        if score <= 0:
            excluded["no_net_saving"] += 1
            continue
        scored[script].append({"token": text, "script": script, "kind": kind, "p2c_id": pid, "frequency": f, "frequency_kind": fk,
                               "base_tokens": len(base_ids), "base_ids": base_ids, "estimated_tokens_saved": score})
    selected = []
    for script in ("Deva", "Knda"):
        ranked = sorted(scored[script], key=lambda c: (-c["estimated_tokens_saved"], -len(c["token"].encode("utf-8")), c["token"]))
        if len(ranked) < k // 2:
            raise CandidateError(f"only {len(ranked)} eligible {script} candidates for a quota of {k // 2}")
        for r, c in enumerate(ranked[:k // 2]):
            selected.append({**c, "rank_in_script": r + 1,
                             "reason": f"rank {r + 1} of {len(ranked)} eligible {script} candidates by estimated tokens saved"})
    ids = list(range(tk.base_size, tk.base_size + len(selected)))
    for c, i in zip(selected, ids):
        c["id"] = i
    corpus_meta = []
    for p in corpora:
        digest, size = B.corpus_info(p)
        corpus_meta.append({"file": pathlib.Path(p).name, "sha256": digest, "bytes": size})
    manifest = {
        "candidates_version": CANDIDATES_VERSION, "pool": pool, "k": k, "min_freq": min_freq, "row_cost": row_cost,
        "tokenizer": {"file": pathlib.Path(tokenizer_path).name, "sha256": tk.sha256, "base_size": tk.base_size, "normalizer_nfc": tk.nfc},
        "p2c_vocabulary": {"file": str(P2C_VOCABULARY.relative_to(ROOT)), "sha256": P2C_SHA256, "learned_entries": len(p2c)},
        "corpus": {"files": corpus_meta, "documents": n_docs, "heldout_documents_skipped": n_held, "split": "training split only (sha256(doc_id) mod 20 != 0)",
                   "distinct_training_runs": len(runs)},
        "pool_size": len(cand), "eligible": {s: len(v) for s, v in scored.items()}, "excluded": dict(sorted(excluded.items())),
        "selected": len(selected), "id_range": [ids[0], ids[-1]] if ids else None,
        "rules": {"score": "frequency x (base tokens - 1) - row_cost", "ties": "longer UTF-8 first, then code-point order",
                  "quota": "strict K/2 Devanagari, K/2 Kannada", "ids": "base_size.. in order Devanagari then Kannada, rank order",
                  "evaluation_data_read": False},
        "candidates": selected,
    }
    return manifest


def write(manifest, out_dir, name):
    out_dir = pathlib.Path(out_dir)
    try:
        out_dir.resolve().relative_to(ROOT)
        raise CandidateError("refusing an output directory inside the repository: candidates are training-derived text")
    except ValueError:
        pass
    out_dir.mkdir(parents=True, exist_ok=True)
    blob = (json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    (out_dir / f"{name}.json").write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    (out_dir / f"{name}.sha256").write_text(f"{digest}  {name}.json\n")
    return digest


def load_manifest(path):
    """Load a candidate manifest after checking its .sha256 sidecar and the frozen P2c reference."""
    path = pathlib.Path(path)
    blob = path.read_bytes()
    side = path.with_suffix(".sha256")
    if not side.is_file() or side.read_text().split()[0] != hashlib.sha256(blob).hexdigest():
        raise CandidateError(f"{path.name}: missing or mismatching .sha256 sidecar")
    m = json.loads(blob)
    if m.get("candidates_version") != CANDIDATES_VERSION or m["p2c_vocabulary"]["sha256"] != P2C_SHA256:
        raise CandidateError(f"{path.name}: not a {CANDIDATES_VERSION} manifest for the frozen P2c vocabulary")
    return m


def extended_tokenizer(tokenizer_path, manifest):
    """The base tokenizer plus the manifest's candidates as extension tokens; verifies the IDs match the manifest."""
    tk = hf_bpe.ByteLevelBPE(tokenizer_path)
    if tk.sha256 != manifest["tokenizer"]["sha256"]:
        raise CandidateError("candidate manifest was built for a different tokenizer file")
    ids = tk.add_tokens([c["token"] for c in manifest["candidates"]])
    if ids != [c["id"] for c in manifest["candidates"]]:
        raise CandidateError("extension IDs do not match the manifest")
    return tk


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True, action="append", type=pathlib.Path)
    ap.add_argument("--tokenizer", required=True, type=pathlib.Path)
    ap.add_argument("--pool", choices=("bytme", "words"), default="bytme")
    ap.add_argument("--k", type=int, default=2048)
    ap.add_argument("--min-freq", type=int, default=20)
    ap.add_argument("--row-cost", type=int, default=0)
    ap.add_argument("--out-dir", required=True, type=pathlib.Path)
    ap.add_argument("--name", default=None)
    args = ap.parse_args(argv)
    try:
        m = build(args.corpus, args.tokenizer, args.pool, args.k, args.min_freq, args.row_cost)
        digest = write(m, args.out_dir, args.name or f"candidates-{args.pool}-k{args.k}")
    except (CandidateError, hf_bpe.UnsupportedTokenizer) as e:
        sys.exit(f"candidate build error: {e}")
    except Exception as e:  # the P2c builder's BuildError for refused corpora
        if type(e).__name__ == "BuildError":
            sys.exit(f"candidate build error: {e}")
        raise
    print(json.dumps({"sha256": digest, "selected": m["selected"], "eligible": m["eligible"], "excluded": m["excluded"],
                      "id_range": m["id_range"], "documents": m["corpus"]["documents"], "heldout_skipped": m["corpus"]["heldout_documents_skipped"]}))


if __name__ == "__main__":
    main()
