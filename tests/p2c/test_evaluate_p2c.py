"""Tests for benchmarks/phase2/evaluate_p2c.py using SYNTHETIC evaluation files (pseudo-words; never real evaluation data).

Everything runs in temporary directories outside the repository. Results are labelled synthetic and are not an evaluation.
Run: python3 -I tests/p2c/test_evaluate_p2c.py
"""
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
EVAL = ROOT / "benchmarks/phase2/evaluate_p2c.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


E = load("p2c_eval", EVAL)
G = load("p2c_fixture_gen", ROOT / "tests/p2c/fixtures/make_synthetic_corpus.py")
TMP = tempfile.TemporaryDirectory(prefix="hashcode_p2c_eval_")
BASE = pathlib.Path(TMP.name)
N = 130  # records per file -> columns of 64, 64, 2


def sentences(script, seed):
    rng = G.Rng(seed)
    if script == "en":
        words = ["alpha", "beta", "gamma", "delta", "omega", "data", "token", "table", "1999", "x-ray"]
        return [" ".join(words[rng.skewed(len(words))] for _ in range(5 + rng.below(8))) + "." for _ in range(N)]
    lex = G.lexicon(rng, G.SCRIPTS[script], 120)
    return [" ".join(lex[rng.skewed(len(lex))] for _ in range(4 + rng.below(10))) + ("।" if script == "deva" else "") for _ in range(N)]


TEXTS = {"hi": sentences("deva", 11), "kn": sentences("knda", 12), "en": sentences("en", 13)}


def setup_root(name, **overrides):
    root = BASE / name
    files = []
    for g, path in (("hi", "test/hin_Deva.jsonl"), ("kn", "test/kan_Knda.jsonl"), ("en", "test/eng_Latn.jsonl")):
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({"id": i + 1, "text": t, "url": "synthetic", "domain": "none"}, ensure_ascii=False) for i, t in enumerate(TEXTS[g])]
        data = ("\n".join(lines) + "\n").encode("utf-8")
        p.write_bytes(data)
        files.append({"group": g, "path": path, "size": len(data), "git_blob_sha1": hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()})
    spec = {"synthetic": True, "name": "synthetic_eval", "version_label": "0", "split": "test", "source": {"revision": "synthetic"},
            "approval": {}, "decontamination": "declined", "storage_root": str(root), "format": "jsonl", "text_field": "text",
            "id_field": "id", "expected_records_per_file": N, "column_size": 64, "files": files}
    spec.update(overrides)
    sp = BASE / f"{name}.spec.json"
    sp.write_text(json.dumps(spec, ensure_ascii=False))
    return root, sp, spec


def evaluate(spec_path, out, *extra, synthetic=True):
    cmd = [sys.executable, "-I", str(EVAL), "--spec", str(spec_path), "--out", str(out), "--repetitions", "1", *map(str, extra)]
    if synthetic:
        cmd.append("--synthetic-test")
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def rewrite(spec_path, spec):
    spec_path.write_text(json.dumps(spec, ensure_ascii=False))


class HappyPath(unittest.TestCase):
    def test_deterministic_aggregates_and_no_text_published(self):
        root, sp, _ = setup_root("ok")
        c1, o1 = evaluate(sp, BASE / "pub1")
        self.assertEqual(c1, 0, o1)
        c2, o2 = evaluate(sp, BASE / "pub2")
        self.assertEqual(c2, 0, o2)
        s1, s2 = (json.loads((BASE / d / "summary.json").read_text()) for d in ("pub1", "pub2"))
        self.assertEqual(s1["groups"], s2["groups"])
        self.assertEqual((BASE / "pub1/per_column.csv").read_text(), (BASE / "pub2/per_column.csv").read_text())
        self.assertEqual((BASE / "pub1/groups.csv").read_text(), (BASE / "pub2/groups.csv").read_text())
        self.assertTrue(s1["synthetic"])
        self.assertIn("SYNTHETIC", s1["label"])
        self.assertEqual(s1["criterion"]["criterion_met"], "not applicable (synthetic test data)")
        self.assertTrue(s1["criterion"]["exact_round_trip_all_values"])
        self.assertTrue(s1["runs_identical"])
        self.assertEqual([g["group"] for g in s1["groups"]], ["hi", "kn", "en"])
        self.assertEqual([g["columns"] for g in s1["groups"]], [3, 3, 3])
        self.assertEqual(sum(g["values"] for g in s1["groups"]), 3 * N)
        self.assertEqual(s1["vocabulary"]["sha256"], E.P2C_SHA256)
        for g in s1["groups"]:
            self.assertEqual(g["exact_columns"], g["columns"])
        # No evaluation sentence, hex encoding or Indic text in anything published.
        blob = b"".join(p.read_bytes() for p in (BASE / "pub1").rglob("*") if p.is_file())
        for texts in TEXTS.values():
            for t in texts:
                self.assertNotIn(t.encode(), blob)
                self.assertNotIn(t.encode().hex()[:48].encode(), blob)
        self.assertIsNone(E.INDIC_RUN.search(blob.decode()))
        # All text-bearing artifacts stayed under the storage root.
        self.assertTrue(any((root / "runs").rglob("containers.tsv")))
        self.assertFalse(any((BASE / "pub1").rglob("containers.tsv")))
        # Published results are never overwritten.
        self.assertEqual(evaluate(sp, BASE / "pub1")[0], 2)

    def test_report_only_overlap_check(self):
        root, sp, spec = setup_root("decon", decontamination="report-only")
        train = BASE / "train.jsonl"
        train.write_text(json.dumps({"doc_id": "x:1", "text": "before\n" + TEXTS["hi"][5] + "\nafter"}, ensure_ascii=False) + "\n",
                         encoding="utf-8")
        code, out = evaluate(sp, BASE / "pub_decon", "--training-corpus", train)
        self.assertEqual(code, 0, out)
        d = json.loads((BASE / "pub_decon/summary.json").read_text())["decontamination"]
        self.assertEqual(d["mode"], "report-only")
        self.assertGreaterEqual(d["samples_found_whole"], 1)


class Guards(unittest.TestCase):
    def test_text_guard_trips(self):
        groups = [("hi", [("1", TEXTS["hi"][0])]), ("en", [("1", TEXTS["en"][0])])]
        for name, content in (("plain.txt", TEXTS["en"][0].encode()), ("hex.txt", TEXTS["en"][0].encode().hex().encode()),
                              ("indic.txt", "कमल".encode())):
            d = BASE / f"guard_{name}"
            d.mkdir()
            (d / name).write_bytes(b"x " + content + b" y")
            with self.assertRaises(E.Stop) as cm:
                E.text_guard(d, groups)
            self.assertEqual(cm.exception.code, 18)
        clean = BASE / "guard_clean"
        clean.mkdir()
        (clean / "a.json").write_text('{"group": "hi", "p2c": 123}')
        E.text_guard(clean, groups)

    def test_missing_partial_and_checksum(self):
        root, sp, _ = setup_root("missing")
        (root / "test/kan_Knda.jsonl").unlink()
        self.assertEqual(evaluate(sp, BASE / "o1")[0], 10)
        root, sp, _ = setup_root("partial")
        (root / "test/x.jsonl.partial").write_bytes(b"x")
        self.assertEqual(evaluate(sp, BASE / "o2")[0], 10)
        root, sp, _ = setup_root("badsum")
        p = root / "test/hin_Deva.jsonl"
        data = bytearray(p.read_bytes())
        data[10] ^= 1
        p.write_bytes(bytes(data))
        code, out = evaluate(sp, BASE / "o3")
        self.assertEqual(code, 11, out)
        self.assertFalse((root / "runs").exists())  # nothing processed
        self.assertFalse((BASE / "o3").exists())

    def test_incomplete_or_malformed_data(self):
        root, sp, spec = setup_root("count")
        spec["expected_records_per_file"] = N + 1
        rewrite(sp, spec)
        self.assertEqual(evaluate(sp, BASE / "o4")[0], 12)
        spec["expected_records_per_file"] = N
        spec["text_field"] = "body"
        rewrite(sp, spec)
        self.assertEqual(evaluate(sp, BASE / "o5")[0], 12)
        root, sp, spec = setup_root("dup")
        p = root / "test/eng_Latn.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[0]
        data = ("\n".join(lines) + "\n").encode()
        p.write_bytes(data)
        spec["files"][2].update(size=len(data), git_blob_sha1=hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest())
        rewrite(sp, spec)
        self.assertEqual(evaluate(sp, BASE / "o6")[0], 12)

    def test_vocabulary_mismatch(self):
        root, sp, _ = setup_root("vocab")
        self.assertEqual(evaluate(sp, BASE / "o7", "--vocabulary", ROOT / "codec/p2a/p2a_vocabulary_v1.bin")[0], 15)

    def test_approval_and_spec_guards(self):
        real = ROOT / "datasets/external_manifests/flores_plus_devtest_e707e62e.json"
        code, out = evaluate(real, BASE / "o8", synthetic=False)
        self.assertEqual(code, 13, out)  # not approved: refused before any file access
        self.assertIn("not approved", out)
        self.assertEqual(evaluate(real, BASE / "o9")[0], 13)  # --synthetic-test cannot bypass approval for a real spec
        root, sp, spec = setup_root("synthreal")
        self.assertEqual(evaluate(sp, BASE / "o10", synthetic=False)[0], 13)  # synthetic spec without --synthetic-test
        spec["decontamination"] = "pending"
        rewrite(sp, spec)
        self.assertEqual(evaluate(sp, BASE / "o11")[0], 13)
        spec["decontamination"] = "declined"
        spec["files"] = spec["files"][:1]  # Kannada missing
        rewrite(sp, spec)
        self.assertEqual(evaluate(sp, BASE / "o12")[0], 13)
        root, sp, spec = setup_root("inrepo")
        self.assertEqual(evaluate(sp, BASE / "o13", "--storage-root", ROOT / "results")[0], 2)

    def test_criterion_constants_are_pinned(self):
        self.assertEqual(E.THRESHOLD, 5.0)
        self.assertEqual(E.REQUIRED_GROUPS, ("hi", "kn"))
        rows = []
        # A hand-built aggregate: hi -6%, kn +10%, en -4% -> not met (hi below 5%).
        def col(g, sg, p2c):
            base = {"status": "ok", "roundtrip_exact": "true", "value_count": "1", "original_payload_bytes": "10"}
            return {(f"col-{g}-001", m): {**base, "total_stored_bytes": str(v)} for m, v in
                    ((E.RAW, 100), (E.OA, sg), (E.GM, sg + 1), (E.P2B, 100), (E.P2C, p2c))}
        table = {**col("hi", 100, 106), **col("kn", 100, 90), **col("en", 100, 104)}
        _, groups, decision = E.aggregate(table, ["hi", "kn", "en"], synthetic=False)
        self.assertFalse(decision["criterion_met"])
        self.assertFalse(decision["hi_at_least_5_percent"])
        table = {**col("hi", 100, 95), **col("kn", 100, 90), **col("en", 100, 105)}
        self.assertTrue(E.aggregate(table, ["hi", "kn", "en"], synthetic=False)[2]["criterion_met"])  # exactly 5% / -5%: met
        table = {**col("hi", 100, 95), **col("kn", 100, 90), **col("en", 100, 106)}
        self.assertFalse(E.aggregate(table, ["hi", "kn", "en"], synthetic=False)[2]["criterion_met"])  # en 6% worse


def tearDownModule():
    TMP.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=1)
