"""P2c Wikipedia pipeline: verify -> convert -> overlap check -> build twice -> compare -> check -> freeze -> smoke/audit.

Approved inputs (docs/phase2_p2c_report.md §10): hiwiki + knwiki, dump 20261001, in /Users/Shared/hashcode-data/wikipedia/20261001/raw/.
It STOPS before any evaluation: no FLORES+, no real-data compression results.

Layout under --data-root (outside every Git repository):
  raw/      <wiki>-<date>-pages-articles.xml.bz2 and <wiki>-<date>-sha1sums.txt (as downloaded; never modified)
  train/    <wiki>-<date>-articles.jsonl (+ .stats.json): converter output, the training corpus
  build/<timestamp>/  stage1/, stage2/ (two independent builds), check1/, check2/ (held-out check files: contain training text)
  smoke/    harness smoke runs with the built vocabulary on the controlled datasets (round-trip validation only)
Repository outputs (no text): codec/p2c/p2c_vocabulary_v1.{bin,sha256,manifest.json} (real mode only) and the record
directory (default results/phase2/p2c-wikipedia-<date>-build/): pipeline_record.json, pipeline.log, converter stats,
overlap report, checker output.

Modes:
  real (default)        approved date and root only; builder runs with --freeze (all D1-D8 guards); the vocabulary is
                        copied into codec/p2c only after both builds are identical and the checker passes.
  --synthetic-dry-run   for tests on hand-written XML: any data root outside the repository, test-only --allow-unfilled,
                        nothing is written to codec/; everything is labelled synthetic.
Re-running is safe: verified inputs are re-verified, existing conversions are reused only if their recorded checksums match,
builds go to fresh time-stamped directories (nothing is deleted), and an existing frozen vocabulary is never overwritten with different content.
Exit codes: 0 ok; 2 usage; 10 missing or partial input; 11 checksum failure; 12 unreadable dump; 13 conversion failure;
14 overlap check failure; 15 build failure; 16 builds differ; 17 checker failure; 18 frozen output conflict;
19 post-build tests or smoke/audit failed.
"""
import argparse
import bz2
import datetime
import filecmp
import hashlib
import json
import os
import pathlib
import resource
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
APPROVED_DATE = "20261001"
APPROVED_ROOT = pathlib.Path("/Users/Shared/hashcode-data/wikipedia/20261001")
WIKIS = ("hiwiki", "knwiki")
URL = "https://dumps.wikimedia.org/{wiki}/{date}/{name}"
VOCAB_NAME = "p2c_vocabulary_v1"
REAL_LABEL = "Wikipedia hiwiki + knwiki dump 20261001 (CC BY-SA 4.0 / GFDL text; vocabulary released under CC BY-SA 4.0)"
SYNTHETIC_LABEL = "synthetic dry-run fixture (hand-written XML; not a real corpus)"
DEFAULT_CHECKER = ROOT / "external/token-vldb2026/build-arm64/hashcode_tools/hashcode_p2c_check_vocabulary"
DEFAULT_HARNESS = ROOT / "external/token-vldb2026/build-arm64/hashcode_benchmarks/phase1_column_harness"


class Stop(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


class Log:
    def __init__(self, path):
        self.path = path

    def __call__(self, msg):
        line = f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def sha(path, algo):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inside_repo(p):
    try:
        pathlib.Path(p).resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def run(cmd, log, code, what, **kw):
    log("$ " + " ".join(str(c) for c in cmd))
    t = time.monotonic()
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if p.stdout.strip():
        log("  stdout: " + p.stdout.strip()[-2000:].replace("\n", "\n  "))
    if p.returncode:
        log("  stderr: " + p.stderr.strip()[-2000:].replace("\n", "\n  "))
        raise Stop(code, f"{what} failed (exit {p.returncode})")
    return p, round(time.monotonic() - t, 2)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", type=pathlib.Path, default=APPROVED_ROOT)
    ap.add_argument("--date", default=APPROVED_DATE)
    ap.add_argument("--record-dir", type=pathlib.Path, default=None)
    ap.add_argument("--checker", type=pathlib.Path, default=DEFAULT_CHECKER)
    ap.add_argument("--harness", type=pathlib.Path, default=DEFAULT_HARNESS)
    ap.add_argument("--shards", type=int, default=16)
    ap.add_argument("--no-smoke", action="store_true", help="skip the harness smoke runs and audit")
    ap.add_argument("--skip-unit-tests", action="store_true", help="skip re-running the Python unit tests at the end")
    ap.add_argument("--synthetic-dry-run", action="store_true")
    args = ap.parse_args(argv)
    data = args.data_root.resolve()
    if inside_repo(data):
        print("refusing a data root inside the repository", file=sys.stderr)
        return 2
    if args.synthetic_dry_run:
        record = (args.record_dir or data / "record").resolve()
        if inside_repo(record):
            print("synthetic dry run: the record directory must be outside the repository", file=sys.stderr)
            return 2
        label = SYNTHETIC_LABEL
    else:
        if args.date != APPROVED_DATE or data != APPROVED_ROOT:
            print(f"real mode only runs the approved dump {APPROVED_DATE} in {APPROVED_ROOT}", file=sys.stderr)
            return 2
        record = (args.record_dir or ROOT / f"results/phase2/p2c-wikipedia-{args.date}-build").resolve()
        label = REAL_LABEL
    record.mkdir(parents=True, exist_ok=True)
    log = Log(record / "pipeline.log")
    rec = {"pipeline": "p2c-wikipedia-pipeline-v1", "mode": "synthetic-dry-run" if args.synthetic_dry_run else "real",
           "synthetic": args.synthetic_dry_run, "dump_date": args.date, "started": datetime.datetime.now().isoformat(timespec="seconds"),
           "steps": {}, "inputs": {}, "conversion": {}, "status": "running"}
    if args.synthetic_dry_run:
        rec["note"] = "SYNTHETIC hand-written XML; says nothing about real-world compression"

    def save():
        (record / "pipeline_record.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    def step(name, seconds, **info):
        rec["steps"][name] = {"seconds": seconds, **info}
        save()

    try:
        log(f"mode={rec['mode']} data_root={data} date={args.date}")
        raw, train, build = data / "raw", data / "train", data / "build"
        # 1. inputs present and complete, then official checksums
        t = time.monotonic()
        partial = sorted(p.name for p in raw.glob("*.partial")) if raw.exists() else []
        if partial:
            raise Stop(10, f"partial download(s) present, refusing to run: {partial}")
        for wiki in WIKIS:
            dump, sums = raw / f"{wiki}-{args.date}-pages-articles.xml.bz2", raw / f"{wiki}-{args.date}-sha1sums.txt"
            for p in (dump, sums):
                if not p.is_file() or p.stat().st_size == 0:
                    raise Stop(10, f"missing input {p}")
            want = None
            for line in sums.read_text(encoding="ascii").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == dump.name:
                    want = parts[0]
            if want is None:
                raise Stop(11, f"{dump.name} is not listed in {sums.name}")
            got = sha(dump, "sha1")
            if got != want:
                raise Stop(11, f"SHA-1 mismatch for {dump.name}: file {got}, published {want}")
            rec["inputs"][wiki] = {"dump_url": URL.format(wiki=wiki, date=args.date, name=dump.name),
                                   "sha1sums_url": URL.format(wiki=wiki, date=args.date, name=sums.name),
                                   "dump_file": dump.name, "dump_bytes": dump.stat().st_size, "sha1_published": want,
                                   "sha1_verified": got, "sha256": sha(dump, "sha256"), "sha1sums_sha256": sha(sums, "sha256")}
            log(f"verified {dump.name}: sha1 {got} matches the published value")
        step("verify_checksums", round(time.monotonic() - t, 2))
        # 2. readable and complete bz2 streams
        t = time.monotonic()
        for wiki in WIKIS:
            dump = raw / f"{wiki}-{args.date}-pages-articles.xml.bz2"
            n = 0
            try:
                with bz2.open(dump, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 22), b""):
                        n += len(chunk)
            except (OSError, EOFError) as e:
                raise Stop(12, f"{dump.name} is not a complete, readable bz2 stream: {e}") from None
            rec["inputs"][wiki]["uncompressed_bytes"] = n
            log(f"{dump.name}: bz2 stream complete, {n} bytes uncompressed")
        step("bz2_integrity", round(time.monotonic() - t, 2))
        # 3. conversion (reused only when the recorded checksums still match)
        train.mkdir(parents=True, exist_ok=True)
        corpora = []
        for wiki in WIKIS:
            t = time.monotonic()
            dump = raw / f"{wiki}-{args.date}-pages-articles.xml.bz2"
            out, stats_path = train / f"{wiki}-{args.date}-articles.jsonl", train / f"{wiki}-{args.date}-articles.stats.json"
            reuse = False
            if out.is_file() and stats_path.is_file():
                st = json.loads(stats_path.read_text())
                reuse = (st.get("input_sha256") == rec["inputs"][wiki]["sha256"] and st.get("output_sha256") == sha(out, "sha256")
                         and st.get("converter_version") == _converter_version())
            if not reuse:
                run([sys.executable, "-I", HERE / "convert_wikipedia.py", "--dump", dump, "--sha1sums", raw / f"{wiki}-{args.date}-sha1sums.txt",
                     "--wiki", wiki, "--out", out, "--stats", stats_path], log, 13, f"conversion of {wiki}")
            st = json.loads(stats_path.read_text())
            if st["output_sha256"] != sha(out, "sha256"):
                raise Stop(13, f"{out.name} does not match its recorded SHA-256")
            shutil.copyfile(stats_path, record / stats_path.name)
            rec["conversion"][wiki] = {**{k: st[k] for k in ("converter_version", "markup_rule", "pages_seen", "articles_written",
                                                             "skipped_namespace", "skipped_redirect", "skipped_missing_text",
                                                             "skipped_empty_after_strip", "output_file", "output_bytes", "output_sha256")},
                                       "reused_existing_output": reuse}
            corpora.append(out)
            step(f"convert_{wiki}", round(time.monotonic() - t, 2), reused=reuse)
            log(f"{wiki}: {st['articles_written']} articles -> {out.name} ({st['output_bytes']} bytes, sha256 {st['output_sha256']})")
        # 4. exact-overlap check against the controlled evaluation datasets (read only; reported, not used to build)
        cmd = [sys.executable, "-I", HERE / "check_eval_overlap.py"]
        for c in corpora:
            cmd += ["--train", c]
        cmd += ["--out", record / "eval_overlap.json"]
        _, secs = run(cmd, log, 14, "overlap check")
        rec["eval_overlap"] = json.loads((record / "eval_overlap.json").read_text())["datasets"]
        step("overlap_check", secs)
        # 5. two independent builds
        stages = []
        run_dir = build / datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
        if run_dir.exists():
            raise Stop(15, f"build directory {run_dir} already exists")
        rec["build_dir"] = str(run_dir)
        for k in (1, 2):
            stage, check = run_dir / f"stage{k}", run_dir / f"check{k}"
            cmd = [sys.executable, "-I", HERE / "build_vocabulary.py", "--corpus-label", label, "--out-dir", stage, "--name", VOCAB_NAME,
                   "--check-dir", check, "--shards", str(args.shards)]
            for c in corpora:
                cmd += ["--corpus", c]
            cmd += ["--allow-unfilled"] if args.synthetic_dry_run else ["--freeze"]
            before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
            _, secs = run(cmd, log, 15, f"build {k}")
            rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
            step(f"build_{k}", secs, max_rss_bytes_children=max(rss, before))
            stages.append((stage, check))
        names = [f"{VOCAB_NAME}.bin", f"{VOCAB_NAME}.sha256", f"{VOCAB_NAME}.manifest.json"]
        for n in names:
            if not filecmp.cmp(stages[0][0] / n, stages[1][0] / n, shallow=False):
                raise Stop(16, f"the two builds differ in {n}")
        if not filecmp.cmp(stages[0][1] / f"{VOCAB_NAME}.heldout_check.tsv", stages[1][1] / f"{VOCAB_NAME}.heldout_check.tsv", shallow=False):
            raise Stop(16, "the two builds differ in the held-out check file")
        manifest = json.loads((stages[0][0] / names[2]).read_text())
        rec["vocabulary"] = {k: manifest[k] for k in ("vocabulary", "builder_version", "entries", "file_bytes", "sha256", "table_id_hex",
                                                     "L_selected", "L_selection", "learned_entries", "learned_slots_returned_to_ascii",
                                                     "allow_unfilled", "id_ranges", "candidates_ranked", "candidates_with_positive_score",
                                                     "distinct_training_runs", "shards")}
        rec["vocabulary"]["corpus"] = {k: v for k, v in manifest["corpus"].items() if k != "label"}
        rec["vocabulary"]["builds_identical"] = True
        log(f"builds identical: sha256 {manifest['sha256']}, L = {manifest['L_selected']}, learned {manifest['learned_entries']}")
        # 6. C++ checker (format, layout against P2a, every entry and mixed round trips, Python size model on held-out columns)
        if not args.checker.exists():
            raise Stop(17, f"checker binary not found: {args.checker} (build target hashcode_p2c_check_vocabulary)")
        p = subprocess.run([str(args.checker), str(stages[0][0] / names[0]), "--sha256-file", str(stages[0][0] / names[1]),
                            "--p2a", str(ROOT / "codec/p2a/p2a_vocabulary_v1.bin"),
                            "--heldout-check", str(stages[0][1] / f"{VOCAB_NAME}.heldout_check.tsv")], capture_output=True, text=True)
        (record / "checker.json").write_text(p.stdout)
        try:
            chk = json.loads(p.stdout)
        except json.JSONDecodeError:
            raise Stop(17, f"checker produced no JSON (exit {p.returncode}): {p.stderr.strip()}") from None
        if p.returncode or not chk["ok"]:
            raise Stop(17, f"checker failed: {chk.get('failures') or chk.get('error')}")
        agree = (chk["sha256"] == manifest["sha256"] and chk["file_bytes"] == manifest["file_bytes"] and chk["entries"] == 65536
                 and chk["learned_hi"] == manifest["learned_entries"]["hi"] and chk["learned_kn"] == manifest["learned_entries"]["kn"])
        if not agree:
            raise Stop(17, "checker and builder manifest disagree")
        rec["checker"] = {k: chk[k] for k in ("ok", "entries", "file_bytes", "sha256", "learned_hi", "learned_kn", "ascii_entries",
                                              "entry_round_trips", "mixed_round_trips", "heldout_rows_checked")}
        step("checker", None)
        # 7. freeze (real mode): copy into codec/p2c; never overwrite different content
        vocab_for_smoke = stages[0][0] / names[0]
        if not args.synthetic_dry_run:
            dest = HERE
            for n in names:
                target = dest / n
                if target.exists():
                    if not filecmp.cmp(target, stages[0][0] / n, shallow=False):
                        raise Stop(18, f"{target} exists with different content; not overwriting")
                else:
                    shutil.copyfile(stages[0][0] / n, target)
            rec["frozen"] = {n: str((dest / n).relative_to(ROOT)) for n in names}
            vocab_for_smoke = dest / names[0]
            log(f"frozen into {dest.relative_to(ROOT)}")
        # 8. smoke round trips in the HCC1 harness on the controlled datasets + independent audit (validation only)
        if not args.no_smoke:
            smoke = data / "smoke"
            smoke.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S%f")
            rec["smoke"] = {}
            for ds in ("kn-hi-v1", "en-mixed-v1"):
                rid = f"p2c-{'synthetic' if args.synthetic_dry_run else 'wikipedia'}-{ds}-smoke-{stamp}"
                run([sys.executable, "-I", ROOT / "benchmarks/phase1/run_column_benchmark.py", "--dataset", ds, "--smoke",
                     "--results-root", smoke, "--run-id", rid, "--harness", args.harness, "--p2c-vocabulary", vocab_for_smoke],
                    log, 19, f"smoke run {ds}")
                a, _ = run([sys.executable, "-I", ROOT / "benchmarks/phase1/audit_column_results.py", smoke / rid], log, 19, f"audit {ds}")
                first = a.stdout.splitlines()[0]
                if " 0 problems" not in first:
                    raise Stop(19, f"audit of {ds}: {first}")
                rec["smoke"][ds] = {"run_id": rid, "audit": first, "note": "round-trip validation on controlled data; not an evaluation"}
            step("smoke_and_audit", None)
        # 9. unit tests of the builder, converter and checker
        if not args.skip_unit_tests:
            for test in ("test_build_vocabulary.py", "test_convert_wikipedia.py", "test_check_vocabulary.py", "test_check_eval_overlap.py",
                         "test_pipeline_dry_run.py"):
                _, secs = run([sys.executable, "-I", ROOT / "tests/p2c" / test], log, 19, test, env={**os.environ, "HASHCODE_P2C_CHECKER": str(args.checker)})
                rec["steps"].setdefault("unit_tests", {})[test] = "ok"
            save()
        rec["status"] = "ok"
        rec["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
        save()
        log("pipeline finished: OK. Stopped before evaluation (FLORES+ not approved).")
        return 0
    except Stop as e:
        rec["status"] = f"stopped (exit {e.code}): {e}"
        save()
        log(f"STOP (exit {e.code}): {e}")
        return e.code


def _converter_version():
    import importlib.util
    spec = importlib.util.spec_from_file_location("p2c_convert_v", HERE / "convert_wikipedia.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CONVERTER_VERSION


if __name__ == "__main__":
    sys.exit(main())
