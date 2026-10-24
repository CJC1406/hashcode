"""P2c controlled-data demo: raw vs best sgtt vs P2b vs P2c (frozen Wikipedia vocabulary), from the existing harness runs.

CONTROLLED HARNESS DATA ONLY. phase1-kn-hi-v1 and phase1-en-mixed-v1 are small, synthetic/curated, not reviewed by native
speakers, and accepted for harness validation only. These numbers do NOT establish real-world compression effectiveness and
cannot satisfy the Phase 2 success criterion, which needs an approved, independent evaluation dataset.

Usage (from the project root):
  python3 -I benchmarks/phase2/p2c_demo.py            # report from the recorded demo runs (results/phase2/p2c-demo-*-column-full-{1,2})
  python3 -I benchmarks/phase2/p2c_demo.py --fresh    # re-run the harness twice per dataset (new run ids), then report
Byte counts are the harness's own total_stored_bytes (HCC1 header + length table + codec blob); no accounting is re-implemented.
Columns: the 40 non-overlapping col-<language>-<category> columns (8 categories x hi, kn, en, en-hi, en-kn).
Shared vocabularies are static assets, reported separately and never charged per column (same rule for every method).
"""
import argparse
import csv
import datetime
import hashlib
import json
import pathlib
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks" / "phase1"))
import run_column_benchmark as rc  # noqa: E402

RAW, OA, GM, P2B, P2C = "raw_utf8_column", "sgtt_openai200k_column", "sgtt_gemma3_column", "p2b_column_id_width", "p2c_learned_column"
VOCAB = ROOT / "codec/p2c/p2c_vocabulary_v1.bin"
MANIFEST = ROOT / "codec/p2c/p2c_vocabulary_v1.manifest.json"
GROUPS = {"kn-hi-v1": ["hi", "kn"], "en-mixed-v1": ["en", "en-hi", "en-kn"]}
CATEGORIES = {"kn-hi-v1": ["short", "medium", "long", "repeated", "punct_numerals", "mixed", "edge", "tiny"],
              "en-mixed-v1": ["short", "medium", "long", "repeated", "punct_numerals", "structured", "edge", "tiny"]}
SHORT = {"kn-hi-v1": "kn-hi", "en-mixed-v1": "en-mixed"}
FROZEN = {"kn-hi-v1": [("results/phase1/column-full-1", [RAW, OA, GM]), ("results/phase2/p2b-kn-hi-column-full-1", [P2B])],
          "en-mixed-v1": [("results/phase1/en-mixed-column-full-1", [RAW, OA, GM]), ("results/phase2/p2b-en-mixed-column-full-1", [P2B])]}
BANNER = ("CONTROLLED HARNESS DATA ONLY: small synthetic/curated datasets for harness validation, not reviewed by native speakers.\n"
          "These results do NOT establish real-world compression effectiveness and cannot satisfy the Phase 2 criterion\n"
          "(>= 5% fewer bytes than the best sgtt baseline on approved, independent Hindi and Kannada evaluation data).")


def load(run_dir):
    with open(ROOT / run_dir / "measurements_column.csv", encoding="utf-8") as f:
        return {(r["column_id"], r["method"]): r for r in csv.DictReader(f)}


def pct(base, cand):
    """Size difference against base, in percent; positive = smaller than base."""
    return (base - cand) / base * 100 if base else 0.0


def fmt(p):
    return f"{p:+.1f}% {'smaller' if p > 0 else 'larger' if p < 0 else 'equal'}"


def fresh_runs(stamp):
    runs = {}
    for k in (1, 2):
        for ds in GROUPS:
            rid = f"p2c-demo-{SHORT[ds]}-column-{stamp}-{k}"
            subprocess.run([sys.executable, "-I", str(ROOT / "benchmarks/phase1/run_column_benchmark.py"), "--dataset", ds,
                            "--results-root", str(ROOT / "results/phase2"), "--p2c-vocabulary", str(VOCAB), "--run-id", rid], check=True)
            runs.setdefault(ds, []).append(f"results/phase2/{rid}")
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fresh", action="store_true", help="re-run the harness twice per dataset first")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "results/phase2/p2c-demo")
    args = ap.parse_args()
    if args.fresh:
        runs = fresh_runs(datetime.datetime.now().strftime("%Y%m%dT%H%M%S"))
    else:
        runs = {ds: [f"results/phase2/p2c-demo-{SHORT[ds]}-column-full-{k}" for k in (1, 2)] for ds in GROUPS}
    problems = []

    # Vocabulary identity: file = .sha256 = manifest = what each run recorded.
    manifest = json.loads(MANIFEST.read_text())
    vocab_sha = hashlib.sha256(VOCAB.read_bytes()).hexdigest()
    recorded = (ROOT / "codec/p2c/p2c_vocabulary_v1.sha256").read_text().split()[0]
    if not (vocab_sha == recorded == manifest["sha256"]):
        problems.append("frozen P2c vocabulary does not match its .sha256/manifest")
    for ds, pair in runs.items():
        for run_dir in pair:
            meta = json.loads((ROOT / run_dir / "run_metadata.json").read_text())
            if (meta.get("p2c_vocabulary") or {}).get("sha256") != vocab_sha:
                problems.append(f"{run_dir}: run used a different P2c vocabulary")

    # Reproducibility, audit, frozen-baseline integrity, exact round trips.
    repro, audits = {}, {}
    for ds, (a, b) in runs.items():
        ra, rb = load(a), load(b)
        diffs = sum(1 for k in ra if any(ra[k][c] != rb.get(k, {}).get(c) for c in rc.DETERMINISTIC)) + len(set(rb) ^ set(ra))
        repro[ds] = {"run_1": a, "run_2": b, "rows": len(ra), "rows_with_differences": diffs}
        if diffs:
            problems.append(f"{ds}: the two runs differ in {diffs} rows")
        for run_dir in (a, b):
            p = subprocess.run([sys.executable, "-I", str(ROOT / "benchmarks/phase1/audit_column_results.py"), str(ROOT / run_dir)],
                               capture_output=True, text=True)
            first = p.stdout.splitlines()[0] if p.stdout else p.stderr.strip()
            audits[run_dir] = first
            if " 0 problems" not in first:
                problems.append(f"{run_dir}: audit: {first}")
        for frozen_dir, methods in FROZEN[ds]:
            old = load(frozen_dir)
            for key, r in old.items():
                if key[1] in methods and any(ra[key][c] != r[c] for c in rc.DETERMINISTIC):
                    problems.append(f"{ds}: {key} differs from the recorded {frozen_dir}")
        bad = [k for k, r in ra.items() if r["status"] != "ok" or r["roundtrip_exact"] != "true"]
        if bad:
            problems.append(f"{ds}: {len(bad)} rows not ok/exact")

    # Byte totals over the 40 non-overlapping columns.
    per_column, groups, overall = [], [], None
    methods = ("raw", "sgtt", "p2b", "p2c")

    def blank():
        return {"columns": 0, "original": 0, **{m: 0 for m in methods}, "values": 0, "exact_values": 0,
                **{f"{m}_encode_ms": 0.0 for m in ("sgtt", "p2b", "p2c")}, **{f"{m}_decode_ms": 0.0 for m in ("sgtt", "p2b", "p2c")}}
    overall = blank()
    for ds, (a, _) in runs.items():
        rows = load(a)
        for lang in GROUPS[ds]:
            g = blank()
            for cat in CATEGORIES[ds]:
                cid = f"col-{lang}-{cat}"
                t = {m: rows[(cid, m)] for m in (RAW, OA, GM, P2B, P2C)}
                tot = {m: int(t[m]["total_stored_bytes"]) for m in t}
                best = OA if tot[OA] <= tot[GM] else GM
                vals = {"raw": tot[RAW], "sgtt": tot[best], "p2b": tot[P2B], "p2c": tot[P2C]}
                per_column.append({"dataset": ds, "language": lang, "category": cat, "column_id": cid,
                                   "original_payload_bytes": int(t[RAW]["original_payload_bytes"]), **{f"{m}_total": v for m, v in vals.items()},
                                   "sgtt_best_method": best, "p2c_vs_sgtt_percent": f"{pct(vals['sgtt'], vals['p2c']):.2f}",
                                   "p2c_vs_p2b_percent": f"{pct(vals['p2b'], vals['p2c']):.2f}", "p2c_id_width": t[P2C]["token_id_bytes"],
                                   "p2c_tokens": t[P2C]["token_count"], "p2b_tokens": t[P2B]["token_count"], "sgtt_tokens": t[best]["token_count"]})
                for acc in (g, overall):
                    acc["columns"] += 1
                    acc["original"] += int(t[RAW]["original_payload_bytes"])
                    for m, v in vals.items():
                        acc[m] += v
                    acc["values"] += int(t[P2C]["value_count"])
                    acc["exact_values"] += min(int(t[m]["exact_values"]) for m in t)
                    for m, key in (("sgtt", best), ("p2b", P2B), ("p2c", P2C)):
                        acc[f"{m}_encode_ms"] += float(t[key]["column_encode_ms_median"] or 0)
                        acc[f"{m}_decode_ms"] += float(t[key]["column_decode_ms_median"] or 0)
            groups.append({"group": lang, **g})
    groups.append({"group": "all 40", **overall})

    # Output.
    lines = [BANNER, "", f"P2c vocabulary: {VOCAB.relative_to(ROOT)}  sha256 {vocab_sha}",
             f"  {manifest['entries']} entries (u16 IDs), {manifest['file_bytes']} bytes, L = {manifest['L_selected']}, "
             f"learned hi {manifest['learned_entries']['hi']} + kn {manifest['learned_entries']['kn']}; trained on Wikipedia hiwiki+knwiki 20261001",
             "", f"{'group':8}{'cols':>5}{'original':>10}{'raw':>9}{'best sgtt':>11}{'P2b':>9}{'P2c':>9}   P2c vs best sgtt     P2b vs best sgtt"]
    for g in groups:
        lines.append(f"{g['group']:8}{g['columns']:>5}{g['original']:>10}{g['raw']:>9}{g['sgtt']:>11}{g['p2b']:>9}{g['p2c']:>9}   "
                     f"{fmt(pct(g['sgtt'], g['p2c'])):20} {fmt(pct(g['sgtt'], g['p2b']))}")
    lines += ["", f"Exact round trips: {overall['exact_values']}/{overall['values']} values in the 40 columns for every method; "
              f"all {sum(len(load(p[0])) for p in runs.values())} rows ok/exact in each run.",
              "Audit: " + "; ".join(f"{pathlib.Path(k).name}: {v}" for k, v in audits.items()),
              "Reproducibility: " + "; ".join(f"{ds}: {v['rows']} rows, {v['rows_with_differences']} differences" for ds, v in repro.items()),
              f"Encode / decode time, sum of per-column medians over the 40 columns (this machine only): "
              f"sgtt {overall['sgtt_encode_ms']:.2f}/{overall['sgtt_decode_ms']:.2f} ms, P2b {overall['p2b_encode_ms']:.2f}/{overall['p2b_decode_ms']:.2f} ms, "
              f"P2c {overall['p2c_encode_ms']:.2f}/{overall['p2c_decode_ms']:.2f} ms",
              f"Integrity problems: {len(problems)}"] + [f"  PROBLEM {p}" for p in problems]
    text = "\n".join(lines)
    print(text)
    args.out.mkdir(parents=True, exist_ok=True)
    rc.pv.write_csv(args.out / "per_column.csv", per_column)
    (args.out / "summary.json").write_text(json.dumps({"data_status": BANNER, "runs": runs, "vocabulary": {"sha256": vocab_sha, **{k: manifest[k] for k in
                                                       ("entries", "file_bytes", "L_selected", "learned_entries")}},
                                                       "groups": groups, "reproducibility": repro, "audits": audits, "problems": problems}, indent=2) + "\n")
    (args.out / "summary.txt").write_text(text + "\n")
    (args.out / "group_totals.svg").write_text(svg(groups))
    return 1 if problems else 0


def svg(groups):
    """Grouped bar chart of total stored bytes per group (raw, best sgtt, P2b, P2c), drawn from the summary data."""
    colors = {"raw": "#9aa0a6", "sgtt": "#4c78a8", "p2b": "#f58518", "p2c": "#54a24b"}
    names = {"raw": "raw HCC1", "sgtt": "best sgtt", "p2b": "P2b", "p2c": "P2c"}
    gs = [g for g in groups if g["group"] != "all 40"]
    top = max(g["raw"] for g in gs)
    W, H, left, bottom, gw = 720, 360, 60, 300, 120
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif" font-size="11">',
           '<rect width="100%" height="100%" fill="#ffffff"/>',
           f'<text x="{left}" y="18" font-size="13">Total stored bytes per group (controlled harness data; not a real-world evaluation)</text>']
    for i, g in enumerate(gs):
        x0 = left + i * gw
        for j, m in enumerate(("raw", "sgtt", "p2b", "p2c")):
            h = g[m] / top * (bottom - 40)
            out.append(f'<rect x="{x0 + j * 24}" y="{bottom - h:.1f}" width="20" height="{h:.1f}" fill="{colors[m]}"><title>{names[m]}: {g[m]} B</title></rect>')
        out.append(f'<text x="{x0 + 46}" y="{bottom + 16}" text-anchor="middle">{g["group"]}</text>')
    out.append(f'<line x1="{left - 5}" y1="{bottom}" x2="{left + len(gs) * gw}" y2="{bottom}" stroke="#333"/>')
    for j, m in enumerate(("raw", "sgtt", "p2b", "p2c")):
        out.append(f'<rect x="{left + j * 110}" y="{bottom + 30}" width="12" height="12" fill="{colors[m]}"/>'
                   f'<text x="{left + j * 110 + 16}" y="{bottom + 40}">{names[m]}</text>')
    out.append("</svg>\n")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
