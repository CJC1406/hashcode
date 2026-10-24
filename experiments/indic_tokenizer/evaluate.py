"""Tokenizer-only A/B(/C) evaluation: NATIVE model input-token counts, base tokenizer vs extended tokenizers.

  A  the model's original tokenizer (baseline)
  B  A + ByteME-derived Indic candidates (candidates.py --pool bytme)
  C  A + the same number of candidates chosen without ByteME (candidates.py --pool words)   [optional ablation]
All counts are native token IDs of the model tokenizer (via hf_bpe.py), never ByteME storage IDs or sgtt dictionary matches.
Data:
  --spec SPEC      an approved evaluation spec (as for benchmarks/phase2/evaluate_p2c.py); refused unless the owner has set
                   every approval; files verified (size, git blob SHA-1, counts) before use; aggregates only are published,
                   after the same text guard.
  --fixture FILE   JSONL {"group", "id", "text"} of SYNTHETIC or hand-written fixture sentences, for tests and demos; the
                   output is labelled FIXTURE and is not evidence of real-world token reduction.
  --heldout-corpus FILE (repeat)  the HELD-OUT split (sha256(doc_id) mod 20 == 0) of the very corpus files the candidates
                   were selected from (checked by SHA-256 against candidate manifest B; documents in the split must equal
                   the manifest's skipped count). Every non-empty line is a sample, grouped by dominant script. Same source
                   as the training data: labelled TRAINING-SOURCE HELD-OUT, NOT independent evaluation. Aggregates only.
With --spec and decontamination 'report-only', evaluation sentences are checked for exact overlap with the frozen training
files (counts only). Results are staged outside the repository and moved into --out only after the text guard.
Metric: token_reduction_percent = 100 x (base - extended) / base (negative = more tokens); with base = 0 it is 0.0 if
extended = 0, otherwise undefined (reported as null).
Proposed engineering target (NOT an approved criterion): >= 20% fewer native tokens than A for Hindi and for Kannada.
"""
import argparse
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import candidates as C  # noqa: E402
import hf_bpe  # noqa: E402
import scripts as S  # noqa: E402

TARGET_PERCENT = 20.0
TARGET_GROUPS = ("hi", "kn")


def _p2c_eval():
    spec = importlib.util.spec_from_file_location("p2c_eval_for_tokenizer", ROOT / "benchmarks/phase2/evaluate_p2c.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def reduction(base, ext):
    if base == 0:
        return 0.0 if ext == 0 else None
    return 100.0 * (base - ext) / base


GROUP_OF_SCRIPT = {"Deva": "hi", "Knda": "kn", "Latn": "en", "mixed": "mixed"}


def load_heldout(paths, manifest):
    """Non-empty lines of the held-out documents of the candidates' own training corpus files (verified by SHA-256)."""
    B = C._builder()
    want = {(f["file"], f["sha256"]) for f in manifest["corpus"]["files"]}
    got = set()
    for p in paths:
        digest, _ = B.corpus_info(p)
        got.add((pathlib.Path(p).name, digest))
    if got != want:
        raise C.CandidateError("--heldout-corpus files are not exactly the corpus files the candidates were selected from")
    samples, docs, seen = [], 0, set()
    for p in paths:
        for d in B.iter_corpus(p, seen):
            if not B.is_heldout(d["doc_id"]):
                continue
            docs += 1
            for k, line in enumerate(d["text"].split("\n")):
                if line.strip():
                    samples.append((GROUP_OF_SCRIPT.get(S.dominant(line), "other"), f"{d['doc_id']}#{k}", line))
    if docs != manifest["corpus"]["heldout_documents_skipped"]:
        raise C.CandidateError(f"held-out documents read ({docs}) != documents the candidate builder skipped "
                               f"({manifest['corpus']['heldout_documents_skipped']})")
    files = [{"file": n, "sha256": h} for n, h in sorted(got)]
    return samples, {"kind": "training-heldout", "files": files, "heldout_documents": docs,
                     "split": "sha256(doc_id) mod 20 == 0 (excluded from candidate selection)"}


def decontamination(spec, samples, args, work):
    """Spec mode: act on the owner's decontamination decision (report-only overlap check against the frozen training text)."""
    if spec["decontamination"] != "report-only":
        return {"mode": spec["decontamination"], "note": "no overlap check against the training text (limitation)"}
    E = _p2c_eval()
    groups = {}
    for g, i, t in samples:
        groups.setdefault(g, []).append((i, t))
    path = work / "eval_samples.jsonl"
    E.write_samples(list(groups.items()), path, "tokenizer-eval")
    if args.training_corpus:
        train = args.training_corpus
    else:
        manifest = json.loads((ROOT / "codec/p2c/p2c_vocabulary_v1.manifest.json").read_text())
        train = []
        for f in manifest["corpus"]["files"]:
            p = E.TRAINING_DIR / f["file"]
            if not p.is_file() or E.sha256(p) != f["sha256"]:
                raise E.Stop(14, f"training file {f['file']} missing or not the frozen one")
            train.append(p)
    cmd = [sys.executable, "-I", str(ROOT / "codec/p2c/check_eval_overlap.py"), "--out", str(work / "overlap.json"), "--eval", f"evaluation={path}"]
    for t in train:
        cmd += ["--train", str(t)]
    if subprocess.run(cmd, capture_output=True, text=True).returncode:
        raise E.Stop(14, "overlap check failed")
    ov = json.loads((work / "overlap.json").read_text())["datasets"]["evaluation"]
    return {"mode": "report-only", "probes_checked": ov["probes_checked"], "samples_found_whole": len(ov["samples_found_whole"]),
            "samples_with_a_line_found": len(ov["samples_with_a_line_found"])}


def load_samples(args, manifest_b=None):
    if args.heldout_corpus:
        return load_heldout(args.heldout_corpus, manifest_b)
    if args.fixture:
        rows = [json.loads(l) for l in pathlib.Path(args.fixture).read_text(encoding="utf-8").splitlines() if l.strip()]
        for r in rows:
            if not isinstance(r.get("group"), str) or not isinstance(r.get("text"), str) or "id" not in r:
                raise C.CandidateError("fixture lines need group, id and text")
        return [(r["group"], str(r["id"]), r["text"]) for r in rows], {"kind": "fixture", "file": pathlib.Path(args.fixture).name}
    E = _p2c_eval()
    spec = json.loads(args.spec.read_text())
    E.check_spec(spec, synthetic_test=bool(spec.get("synthetic")) and args.synthetic_test)
    root = pathlib.Path(spec["storage_root"]).resolve()
    if E.inside_repo(root):
        raise E.Stop(2, "storage root must be outside the repository")
    groups, files = E.read_files(spec, root)
    samples = [(g, i, t) for g, recs in groups for i, t in recs]
    work = pathlib.Path(tempfile.mkdtemp(prefix="indic_tok_eval_", dir=root))
    return samples, {"kind": "approved-spec" if not spec.get("synthetic") else "synthetic-spec", "spec_file": args.spec.name,
                     "files": files, "decontamination": decontamination(spec, samples, args, work)}


def measure(tk, samples):
    """Per-sample native token counts (cold cache timing), round-trip checks and ID validity."""
    tk._cache.clear()
    t0 = time.perf_counter()
    encoded = [tk.encode(t) for _, _, t in samples]
    secs = time.perf_counter() - t0
    size = tk.size()
    special = set(tk.special)
    out = []
    for (g, i, t), ids in zip(samples, encoded):
        dec = tk.decode_bytes(ids)
        out.append({"group": g, "id": i, "tokens": len(ids), "added_tokens": sum(1 for x in ids if x in tk.added_ids),
                    "exact": dec == t.encode("utf-8"), "exact_after_nfc": dec == unicodedata.normalize("NFC", t).encode("utf-8") if tk.nfc else dec == t.encode("utf-8"),
                    "ids_valid": all(0 <= x < size and x not in special for x in ids)})
    return out, secs


def aggregate(samples, results, secs):
    groups = {}
    for (g, _, t), r in zip(samples, results["A"]):
        groups.setdefault(g, {"samples": 0, "chars": 0})
        groups[g]["samples"] += 1
        groups[g]["chars"] += len(t)
    report = {}
    for g, info in groups.items():
        row = {"group": g, **info}
        base = [r for r in results["A"] if r["group"] == g]
        a = sum(r["tokens"] for r in base)
        for name, res in results.items():
            rs = [r for r in res if r["group"] == g]
            n = sum(r["tokens"] for r in rs)
            row[f"{name}_tokens"] = n
            row[f"{name}_tokens_per_sentence"] = round(n / info["samples"], 3)
            row[f"{name}_tokens_per_1000_chars"] = round(1000 * n / info["chars"], 3) if info["chars"] else None
            row[f"{name}_exact_round_trip"] = sum(r["exact"] for r in rs)
            row[f"{name}_exact_after_nfc"] = sum(r["exact_after_nfc"] for r in rs)
            row[f"{name}_ids_valid"] = all(r["ids_valid"] for r in rs)
            if name != "A":
                red = reduction(a, n)
                row[f"{name}_reduction_percent"] = None if red is None else round(red, 3)
                row[f"{name}_samples_improved"] = sum(1 for x, b in zip(rs, base) if x["tokens"] < b["tokens"])
                row[f"{name}_samples_worse"] = sum(1 for x, b in zip(rs, base) if x["tokens"] > b["tokens"])
                row[f"{name}_samples_using_added_tokens"] = sum(1 for x in rs if x["added_tokens"])
                row[f"{name}_added_token_share_percent"] = round(100 * sum(x["added_tokens"] for x in rs) / n, 3) if n else None
        report[g] = row
    total_chars = sum(len(t) for _, _, t in samples)
    throughput = {k: {"seconds": round(v, 4), "chars_per_second": round(total_chars / v) if v else None} for k, v in secs.items()}
    return report, throughput


def run(samples, tokenizer, manifests):
    tks = {"A": hf_bpe.ByteLevelBPE(tokenizer)}
    for name, m in manifests.items():
        tks[name] = C.extended_tokenizer(tokenizer, m)
    if len({m["k"] for m in manifests.values()}) > 1:
        raise C.CandidateError("B and C must add the same number of tokens")
    results, secs = {}, {}
    for name, tk in tks.items():
        results[name], secs[name] = measure(tk, samples)
    groups, throughput = aggregate(samples, results, secs)
    target = {g: {"B_reduction_percent": groups[g].get("B_reduction_percent"),
                  "met": (groups[g].get("B_reduction_percent") or -1e9) >= TARGET_PERCENT} for g in TARGET_GROUPS if g in groups}
    return {"groups": groups, "throughput_python_prototype": throughput,
            "tokenizer": {"file": pathlib.Path(tokenizer).name, "sha256": tks["A"].sha256, "base_size": tks["A"].base_size},
            "extensions": {n: {"pool": m["pool"], "k": m["k"], "id_range": m["id_range"], "corpus": m["corpus"]["files"]} for n, m in manifests.items()},
            "proposed_target": {"rule": f">= {TARGET_PERCENT}% fewer native tokens than A for hi and kn (proposed, not approved)", "by_group": target}}, results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--spec", type=pathlib.Path)
    src.add_argument("--fixture", type=pathlib.Path)
    src.add_argument("--heldout-corpus", type=pathlib.Path, action="append")
    ap.add_argument("--training-corpus", type=pathlib.Path, action="append", default=None, help="synthetic tests only (report-only overlap)")
    ap.add_argument("--synthetic-test", action="store_true")
    ap.add_argument("--tokenizer", required=True, type=pathlib.Path)
    ap.add_argument("--candidates-b", required=True, type=pathlib.Path)
    ap.add_argument("--candidates-c", type=pathlib.Path, default=None)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    args = ap.parse_args(argv)
    E = None
    try:
        manifests = {"B": C.load_manifest(args.candidates_b)}
        if args.candidates_c:
            manifests["C"] = C.load_manifest(args.candidates_c)
        if args.training_corpus and not args.synthetic_test:
            raise C.CandidateError("--training-corpus is for synthetic tests only")
        samples, source = load_samples(args, manifests["B"])
        report, per_sample = run(samples, args.tokenizer, manifests)
        label = {"approved-spec": "INDEPENDENT EVALUATION (approved dataset)",
                 "training-heldout": "TRAINING-SOURCE HELD-OUT SPLIT (Wikipedia; documents excluded from candidate selection; same source, "
                                     "NOT independent evaluation)"}.get(source["kind"], "FIXTURE (synthetic or hand-written): not evidence of real-world token reduction")
        report = {"label": label, "source": source, "samples": len(samples), **report}
        if args.out.exists():
            raise C.CandidateError(f"{args.out} exists; results are never overwritten")
        stage = pathlib.Path(tempfile.mkdtemp(prefix="indic_tok_publish_"))  # outside the repository
        (stage / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        if source["kind"] in ("approved-spec", "synthetic-spec", "training-heldout"):
            E = _p2c_eval()
            groups = {}
            for g, i, t in samples:
                groups.setdefault(g, []).append((i, t))
            E.text_guard(stage, list(groups.items()))  # aggregates only; nothing is moved if evaluation text appears
        else:
            (stage / "per_sample.json").write_text(json.dumps([{k: v for k, v in r.items()} for r in per_sample["A"]], indent=1) + "\n")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stage), str(args.out))
        for g, row in report["groups"].items():
            print(f"{g:6} A {row['A_tokens']:>7}  B {row.get('B_tokens', ''):>7} ({row.get('B_reduction_percent')}%)"
                  + (f"  C {row['C_tokens']:>7} ({row['C_reduction_percent']}%)" if "C_tokens" in row else "")
                  + f"  exact A/B {row['A_exact_after_nfc']}/{row.get('B_exact_after_nfc')} of {row['samples']}")
        print(f"label: {label}")
        return 0
    except (C.CandidateError, hf_bpe.UnsupportedTokenizer) as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        if type(e).__name__ == "Stop":
            print(f"STOP (exit {e.code}): {e}", file=sys.stderr)
            return e.code
        raise


if __name__ == "__main__":
    sys.exit(main())
