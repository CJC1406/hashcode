"""Independent evaluation of the FROZEN P2c vocabulary: raw vs best sgtt vs P2b vs P2c on an approved evaluation dataset.

Prerequisites (all checked; any failure stops the run before data is used):
  - an evaluation spec (datasets/external_manifests/*.json) whose approvals the project owner has set to true;
  - the spec's files present under its storage root (outside every Git repository), matching the official sizes and git
    blob SHA-1s recorded in the spec, with the expected record counts and fields;
  - the frozen vocabulary codec/p2c/p2c_vocabulary_v1.bin with the pinned SHA-256 below (never retrained, L never re-chosen);
  - the harness build (phase1_column_harness) and, for decontamination 'report-only', the frozen Wikipedia training files.
Reuses the existing runner (benchmarks/phase1/run_column_benchmark.py --external-dataset), harness, byte accounting and
auditor; nothing is re-implemented. Runs twice and requires 0 differences.
Text handling: converted samples and all harness artifacts stay in <storage_root>/runs/<stamp>/ (outside Git). Only aggregate
metrics are published to --out, after a guard checks that no evaluation sentence (or its hex encoding) appears in them.
Pre-registered criterion (docs/phase2_proposal.md §7; pinned here, not configurable): P2c succeeds only if every value
round-trips exactly, P2c stores >= 5% fewer total bytes than the per-column best sgtt baseline for Hindi AND for Kannada,
and no evaluated group is more than 5% worse.

Usage:
  python3 -I benchmarks/phase2/evaluate_p2c.py --spec datasets/external_manifests/flores_plus_devtest_e707e62e.json
  (tests only) --synthetic-test with a spec marked "synthetic": true
Exit codes: 0 ok (criterion met or not); 2 usage; 10 missing or partial file; 11 checksum mismatch; 12 incomplete or malformed
data; 13 spec not approved or invalid; 14 overlap check failed; 15 vocabulary mismatch; 16 benchmark failed or runs differ;
17 audit failed; 18 text-suppression guard tripped (nothing published).
"""
import argparse
import csv
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import statistics
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks" / "phase1"))
import run_column_benchmark as rc  # noqa: E402

P2C_VOCABULARY = ROOT / "codec/p2c/p2c_vocabulary_v1.bin"
P2C_SHA256 = "1e12dc488beddfdf0242268fd17cdd90e93d834be0a81e6780754bcbc629dc84"  # frozen 2026-10-25 (report §11.2)
P2A_SHA256 = "c99ff52fa92fa7c8be541c0358c10acd678aeaa98764bb474ef06077faa7face"
TRAINING_DIR = pathlib.Path("/Users/Shared/hashcode-data/wikipedia/20261001/train")
RAW, OA, GM, P2B, P2C = "raw_utf8_column", "sgtt_openai200k_column", "sgtt_gemma3_column", "p2b_column_id_width", "p2c_learned_column"
REQUIRED_GROUPS = ("hi", "kn")       # criterion languages (pinned)
ALLOWED_GROUPS = ("hi", "kn", "en")  # en is a regression check
THRESHOLD = 5.0                      # percent (pinned)
APPROVALS = ("gate_accepted_by_owner", "evaluation_only_use_approved", "storage_approved", "aggregate_only_publication_approved")
INDIC_RUN = re.compile("[ऀ-ॿಀ-೿]{3,}")


class Stop(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def inside_repo(p):
    try:
        pathlib.Path(p).resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def git_blob_sha1(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def pct(base, cand):
    return (base - cand) / base * 100 if base else 0.0


def check_spec(spec, synthetic_test):
    if bool(spec.get("synthetic")) != synthetic_test:
        raise Stop(13, "synthetic specs run only with --synthetic-test, and --synthetic-test runs only synthetic specs")
    if not synthetic_test:
        missing = [k for k in APPROVALS if spec.get("approval", {}).get(k) is not True]
        if missing or not spec["approval"].get("approved_by") or not spec["approval"].get("approved_on"):
            raise Stop(13, f"spec not approved by the project owner (pending: {missing or ['approved_by/approved_on']})")
    if spec.get("decontamination") not in ("report-only", "declined"):
        raise Stop(13, "decontamination decision is pending: set 'report-only' or 'declined'")
    groups = [f["group"] for f in spec["files"]]
    if len(groups) != len(set(groups)) or not set(REQUIRED_GROUPS) <= set(groups) or not set(groups) <= set(ALLOWED_GROUPS):
        raise Stop(13, f"spec must have one file per group, include {REQUIRED_GROUPS}, and only {ALLOWED_GROUPS}")
    for f in spec["files"]:
        if not re.fullmatch(r"[0-9a-f]{40}", str(f.get("git_blob_sha1"))) or not isinstance(f.get("size"), int):
            raise Stop(13, f"{f.get('path')}: the spec needs the official size and git blob SHA-1")
    if spec.get("format") != "jsonl":
        raise Stop(13, "only the jsonl format is supported")
    if not isinstance(spec.get("column_size"), int) or spec["column_size"] < 1:
        raise Stop(13, "column_size must be a positive integer")


def read_files(spec, root):
    """Verify every file against the spec, then parse it. Returns [(group, [(id, text)])]."""
    if any(root.rglob("*.partial")):
        raise Stop(10, "partial download present under the storage root")
    out, info = [], []
    for f in spec["files"]:
        path = root / f["path"]
        if not path.is_file():
            raise Stop(10, f"missing evaluation file {f['path']}")
        data = path.read_bytes()
        if len(data) != f["size"] or git_blob_sha1(data) != f["git_blob_sha1"]:
            raise Stop(11, f"{f['path']}: size/git blob SHA-1 {len(data)}/{git_blob_sha1(data)} != official {f['size']}/{f['git_blob_sha1']}")
        records, seen = [], set()
        try:
            lines = data.decode("utf-8").split("\n")
        except UnicodeDecodeError:
            raise Stop(12, f"{f['path']}: not valid UTF-8") from None
        for k, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                raise Stop(12, f"{f['path']} line {k + 1}: not JSON") from None
            t, i = r.get(spec["text_field"]) if isinstance(r, dict) else None, r.get(spec["id_field"]) if isinstance(r, dict) else None
            if not isinstance(t, str) or not isinstance(i, (str, int)) or isinstance(i, bool):
                raise Stop(12, f"{f['path']} line {k + 1}: missing '{spec['text_field']}' (string) or '{spec['id_field']}'")
            if str(i) in seen:
                raise Stop(12, f"{f['path']}: duplicate id {i}")
            seen.add(str(i))
            try:
                t.encode("utf-8")
            except UnicodeEncodeError:
                raise Stop(12, f"{f['path']} line {k + 1}: text not encodable as UTF-8") from None
            records.append((str(i), t))
        want = spec.get("expected_records_per_file")
        if want is not None and len(records) != want:
            raise Stop(12, f"{f['path']}: {len(records)} records, expected {want} (incomplete or wrong file)")
        out.append((f["group"], records))
        info.append({"group": f["group"], "path": f["path"], "size": len(data), "git_blob_sha1_verified": f["git_blob_sha1"],
                     "sha256": hashlib.sha256(data).hexdigest(), "records": len(records)})
    return out, info


def write_samples(groups, path, version):
    """Shared sample schema (as the controlled datasets), in spec file order; no normalization."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for g, records in groups:
            for i, t in records:
                b = t.encode("utf-8")
                f.write(json.dumps({"sample_id": f"{g}-{i}", "language": g, "category": "eval", "dataset_version": version,
                                    "text": t, "utf8_hex": b.hex(), "utf8_bytes": len(b)}, ensure_ascii=False) + "\n")
    return sha256(path)


def run(cmd, code, what):
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if p.returncode:
        raise Stop(code, f"{what} failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-800:]}")
    return p.stdout


def text_guard(directory, groups):
    """Raise if any evaluation sentence (>= 12 bytes), its hex encoding, or any Indic text run appears in a file to publish."""
    needles = []
    for _, records in groups:
        for _, t in records:
            b = t.encode("utf-8")
            if len(b) >= 12:
                needles += [b, b.hex()[:48].encode(), json.dumps(t)[1:-1].encode()]
    for p in sorted(pathlib.Path(directory).rglob("*")):
        if p.is_file():
            data = p.read_bytes()
            if INDIC_RUN.search(data.decode("utf-8", errors="replace")) or any(n in data for n in needles):
                raise Stop(18, f"text-suppression guard: evaluation text found in {p.name}; nothing was published")


def aggregate(rows, groups_order, synthetic):
    per_column, totals = [], {}
    for (cid, m), r in sorted(rows.items()):
        if m != RAW:
            continue
        g = cid.split("-")[1]
        t = {x: rows[(cid, x)] for x in (RAW, OA, GM, P2B, P2C)}
        tot = {x: int(t[x]["total_stored_bytes"]) for x in t}
        best = OA if tot[OA] <= tot[GM] else GM
        exact = all(t[x]["status"] == "ok" and t[x]["roundtrip_exact"] == "true" for x in t)
        per_column.append({"column_id": cid, "group": g, "values": int(t[RAW]["value_count"]), "original_payload_bytes": int(t[RAW]["original_payload_bytes"]),
                           "raw": tot[RAW], "sgtt_best_method": best, "sgtt_best": tot[best], "p2b": tot[P2B], "p2c": tot[P2C],
                           "p2c_vs_sgtt_percent": f"{pct(tot[best], tot[P2C]):.4f}", "all_methods_exact": exact})
        a = totals.setdefault(g, {"columns": 0, "values": 0, "original": 0, "raw": 0, "sgtt_best": 0, "p2b": 0, "p2c": 0, "exact_columns": 0, "reds": []})
        a["columns"] += 1
        a["values"] += int(t[RAW]["value_count"])
        a["original"] += int(t[RAW]["original_payload_bytes"])
        for k, v in (("raw", tot[RAW]), ("sgtt_best", tot[best]), ("p2b", tot[P2B]), ("p2c", tot[P2C])):
            a[k] += v
        a["exact_columns"] += exact
        a["reds"].append(pct(tot[best], tot[P2C]))
    groups = []
    for g in groups_order:
        a = totals[g]
        groups.append({"group": g, **{k: v for k, v in a.items() if k != "reds"},
                       "p2c_vs_sgtt_bytes_percent": round(pct(a["sgtt_best"], a["p2c"]), 4),
                       "p2b_vs_sgtt_bytes_percent": round(pct(a["sgtt_best"], a["p2b"]), 4),
                       "p2c_vs_p2b_bytes_percent": round(pct(a["p2b"], a["p2c"]), 4),
                       "median_p2c_vs_sgtt_percent": round(statistics.median(a["reds"]), 4)})
    all_exact = all(c["all_methods_exact"] for c in per_column)
    by = {g["group"]: g for g in groups}
    decision = {
        "rule": "exact round trip on 100% of values; P2c >= 5% fewer total stored bytes than the per-column best sgtt for hi AND kn; "
                "no evaluated group more than 5% worse (docs/phase2_proposal.md §7, unchanged)",
        "exact_round_trip_all_values": all_exact,
        "hi_reduction_percent": by["hi"]["p2c_vs_sgtt_bytes_percent"], "kn_reduction_percent": by["kn"]["p2c_vs_sgtt_bytes_percent"],
        "hi_at_least_5_percent": by["hi"]["p2c_vs_sgtt_bytes_percent"] >= THRESHOLD,
        "kn_at_least_5_percent": by["kn"]["p2c_vs_sgtt_bytes_percent"] >= THRESHOLD,
        "no_group_more_than_5_percent_worse": all(g["p2c_vs_sgtt_bytes_percent"] >= -THRESHOLD for g in groups),
    }
    met = all(decision[k] for k in ("exact_round_trip_all_values", "hi_at_least_5_percent", "kn_at_least_5_percent", "no_group_more_than_5_percent_worse"))
    decision["criterion_met"] = "not applicable (synthetic test data)" if synthetic else met
    return per_column, groups, decision


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True, type=pathlib.Path)
    ap.add_argument("--storage-root", type=pathlib.Path, default=None, help="default: the spec's storage_root")
    ap.add_argument("--out", type=pathlib.Path, default=None, help="published aggregates (default results/phase2/p2c-eval-<name>-<split>-<stamp>)")
    ap.add_argument("--repetitions", type=int, default=None)
    ap.add_argument("--harness", type=pathlib.Path, default=rc.COLUMN_HARNESS)
    ap.add_argument("--vocabulary", type=pathlib.Path, default=P2C_VOCABULARY, help="must have the pinned SHA-256")
    ap.add_argument("--training-corpus", type=pathlib.Path, action="append", default=None,
                    help="synthetic tests only: training files for the report-only overlap check")
    ap.add_argument("--synthetic-test", action="store_true")
    args = ap.parse_args(argv)
    try:
        spec = json.loads(args.spec.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read spec: {e}", file=sys.stderr)
        return 2
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    try:
        check_spec(spec, args.synthetic_test)
        root = (args.storage_root or pathlib.Path(spec["storage_root"])).resolve()
        if inside_repo(root):
            raise Stop(2, "the storage root must be outside the repository")
        if not args.synthetic_test and root != pathlib.Path(spec["storage_root"]).resolve():
            raise Stop(13, "the storage root must be the approved one in the spec")
        if args.training_corpus and not args.synthetic_test:
            raise Stop(2, "--training-corpus is for synthetic tests only")
        out = (args.out or ROOT / f"results/phase2/p2c-eval-{spec['name']}-{spec['split']}-{stamp[:15]}").resolve()
        if out.exists():
            raise Stop(2, f"{out} already exists; published results are never overwritten")
        # Vocabulary (pinned; never retrained here).
        vocab = args.vocabulary.resolve()
        if not vocab.is_file() or sha256(vocab) != P2C_SHA256:
            raise Stop(15, f"vocabulary {vocab.name} does not have the frozen SHA-256 {P2C_SHA256}")
        if sha256(ROOT / rc.P2A_VOCABULARY) != P2A_SHA256:
            raise Stop(15, "P2a/P2b vocabulary does not match its frozen SHA-256")
        # Data: verified before any use.
        groups, files = read_files(spec, root)
        work = root / "runs" / stamp
        work.mkdir(parents=True)
        version = f"{spec['name']}-{spec.get('version_label', '?').split()[0]}-{spec['split']}@{spec.get('source', {}).get('revision', 'synthetic')[:12]}"
        samples = work / "eval_samples.jsonl"
        samples_sha = write_samples(groups, samples, version)
        record = {"evaluation": "p2c-independent-evaluation-v1", "synthetic": bool(spec.get("synthetic")), "spec_file": args.spec.name,
                  "spec_sha256": sha256(args.spec), "spec": {k: spec[k] for k in spec if k not in ("files",)}, "files": files,
                  "samples_sha256": samples_sha, "samples": sum(len(r) for _, r in groups), "column_size": spec["column_size"],
                  "vocabulary": {"file": str(P2C_VOCABULARY.relative_to(ROOT)), "sha256": P2C_SHA256}, "p2a_sha256": P2A_SHA256,
                  "conversion": "records in spec file order; sample_id '<group>-<id>'; text unchanged (no normalization); columns of "
                                f"{spec['column_size']} consecutive sentences per group (col-<group>-NNN), non-overlapping"}
        # Decontamination (report-only): evaluation sentences against the frozen training text; never changes the vocabulary.
        if spec["decontamination"] == "report-only":
            if args.training_corpus:
                train = args.training_corpus
            else:
                manifest = json.loads((ROOT / "codec/p2c/p2c_vocabulary_v1.manifest.json").read_text())
                train = []
                for f in manifest["corpus"]["files"]:
                    p = TRAINING_DIR / f["file"]
                    if not p.is_file() or sha256(p) != f["sha256"]:
                        raise Stop(14, f"training file {f['file']} missing or not the frozen one")
                    train.append(p)
            cmd = [sys.executable, "-I", ROOT / "codec/p2c/check_eval_overlap.py", "--out", work / "overlap.json", "--eval", f"evaluation={samples}"]
            for t in train:
                cmd += ["--train", t]
            run(cmd, 14, "overlap check")
            ov = json.loads((work / "overlap.json").read_text())["datasets"]["evaluation"]
            record["decontamination"] = {"mode": "report-only", "probes_checked": ov["probes_checked"],
                                         "samples_found_whole": len(ov["samples_found_whole"]),
                                         "samples_with_a_line_found": len(ov["samples_with_a_line_found"])}
        else:
            record["decontamination"] = {"mode": "declined", "note": "no overlap check against the training text (limitation)"}
        # Two runs with the existing runner, then compare and audit.
        runs = []
        for k in (1, 2):
            cmd = [sys.executable, "-I", ROOT / "benchmarks/phase1/run_column_benchmark.py", "--external-dataset", samples,
                   "--external-sha256", samples_sha, "--column-size", str(spec["column_size"]), "--results-root", work,
                   "--run-id", f"eval-run-{k}", "--harness", args.harness, "--p2c-vocabulary", vocab]
            if args.repetitions:
                cmd += ["--repetitions", str(args.repetitions)]
            run(cmd, 16, f"benchmark run {k}")
            runs.append(work / f"eval-run-{k}")
        cmp = run([sys.executable, "-I", ROOT / "benchmarks/phase1/run_column_benchmark.py", "--compare", runs[0], runs[1]], 16, "run comparison")
        if " 0 differences" not in cmp:
            raise Stop(16, f"the two runs differ: {cmp.strip().splitlines()[-1]}")
        audits = []
        for r in runs:
            a = run([sys.executable, "-I", ROOT / "benchmarks/phase1/audit_column_results.py", r, "--dataset-path", samples], 17, "audit")
            first = a.splitlines()[0]
            if " 0 problems" not in first:
                raise Stop(17, f"audit: {first}")
            audits.append(first)
        with open(runs[0] / "measurements_column.csv", encoding="utf-8") as f:
            rows = {(r["column_id"], r["method"]): r for r in csv.DictReader(f)}
        per_column, group_rows, decision = aggregate(rows, [g for g, _ in groups], bool(spec.get("synthetic")))
        timing = {}
        for m in (OA, GM, P2B, P2C):
            sel = [r for (c, mm), r in rows.items() if mm == m]
            timing[m] = {"sum_column_encode_ms_median": round(sum(float(r["column_encode_ms_median"] or 0) for r in sel), 4),
                         "sum_column_decode_ms_median": round(sum(float(r["column_decode_ms_median"] or 0) for r in sel), 4)}
        record.update({"runs_identical": True, "audits": audits, "timing_this_machine": timing, "groups": group_rows, "criterion": decision})
        # Publish aggregates only, after the text guard.
        stage = work / "publish"
        stage.mkdir()
        label = "SYNTHETIC TEST DATA: not an evaluation" if spec.get("synthetic") else "independent evaluation (approved dataset)"
        (stage / "summary.json").write_text(json.dumps({"label": label, **record}, indent=2) + "\n")
        rc.pv.write_csv(stage / "groups.csv", group_rows)
        rc.pv.write_csv(stage / "per_column.csv", per_column)
        lines = [f"P2c evaluation: {label}", f"vocabulary {P2C_SHA256[:16]} (frozen; L and entries unchanged)", "",
                 f"{'group':6}{'cols':>5}{'values':>8}{'raw':>10}{'best sgtt':>11}{'P2b':>10}{'P2c':>10}  P2c vs best sgtt"]
        for g in group_rows:
            lines.append(f"{g['group']:6}{g['columns']:>5}{g['values']:>8}{g['raw']:>10}{g['sgtt_best']:>11}{g['p2b']:>10}{g['p2c']:>10}  {g['p2c_vs_sgtt_bytes_percent']:+.2f}%")
        lines += ["", f"exact round trips: {decision['exact_round_trip_all_values']}; runs identical; audits: {'; '.join(audits)}",
                  f"criterion met: {decision['criterion_met']}"]
        (stage / "summary.txt").write_text("\n".join(lines) + "\n")
        text_guard(stage, groups)
        shutil.copytree(stage, out)
        print("\n".join(lines))
        print(f"published (aggregates only): {out}")
        return 0
    except Stop as e:
        print(f"STOP (exit {e.code}): {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
