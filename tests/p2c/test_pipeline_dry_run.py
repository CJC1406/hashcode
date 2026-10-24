"""Dry-run tests of codec/p2c/run_wikipedia_pipeline.py on SYNTHETIC dumps (tests/p2c/fixtures/synthetic_wiki_dumps.py).

Everything runs in temporary directories; the real download directory is never touched.
Results are synthetic and say nothing about real-world compression.
Run: python3 -I tests/p2c/test_pipeline_dry_run.py
"""
import bz2
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
PIPE = ROOT / "codec/p2c/run_wikipedia_pipeline.py"
spec = importlib.util.spec_from_file_location("p2c_dumps", ROOT / "tests/p2c/fixtures/synthetic_wiki_dumps.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)
TMP = tempfile.TemporaryDirectory(prefix="hashcode_p2c_pipeline_")
BASE = pathlib.Path(TMP.name)


def fresh(name):
    d = BASE / name
    W.write(d)
    return d


def pipeline(root, *extra):
    p = subprocess.run([sys.executable, "-I", str(PIPE), "--synthetic-dry-run", "--data-root", str(root), "--shards", "3",
                        "--no-smoke", "--skip-unit-tests", *extra], capture_output=True, text=True)
    rec_path = root / "record" / "pipeline_record.json"
    rec = json.loads(rec_path.read_text()) if rec_path.exists() else None
    return p.returncode, rec, p.stdout + p.stderr


def resum(root, wiki):
    raw = root / "raw"
    name = f"{wiki}-20261001-pages-articles.xml.bz2"
    (raw / f"{wiki}-20261001-sha1sums.txt").write_text(f"{hashlib.sha1((raw / name).read_bytes()).hexdigest()}  {name}\n")


class DryRun(unittest.TestCase):
    def test_deterministic_end_to_end_and_safe_rerun(self):
        a, b = fresh("a"), fresh("b")
        ca, ra, out = pipeline(a)
        self.assertEqual(ca, 0, out)
        cb, rb, _ = pipeline(b)
        self.assertEqual(cb, 0)
        self.assertTrue(ra["synthetic"])
        self.assertEqual(ra["mode"], "synthetic-dry-run")
        self.assertEqual(ra["vocabulary"]["sha256"], rb["vocabulary"]["sha256"])
        for wiki in ("hiwiki", "knwiki"):
            self.assertEqual(ra["conversion"][wiki]["output_sha256"], rb["conversion"][wiki]["output_sha256"])
            self.assertEqual(ra["inputs"][wiki]["sha1_verified"], ra["inputs"][wiki]["sha1_published"])
            self.assertEqual(ra["conversion"][wiki]["articles_written"], 161)
            self.assertEqual(ra["conversion"][wiki]["skipped_namespace"], 2)
            self.assertEqual(ra["conversion"][wiki]["skipped_redirect"], 1)
        self.assertTrue(ra["vocabulary"]["builds_identical"])
        self.assertTrue(ra["checker"]["ok"])
        self.assertEqual(ra["checker"]["entry_round_trips"], 65536)
        self.assertEqual(ra["vocabulary"]["entries"], 65536)
        self.assertIn(ra["vocabulary"]["L_selected"], (4096, 8192, 16384, 32768))
        self.assertTrue(ra["vocabulary"]["allow_unfilled"])  # synthetic only; real mode uses --freeze
        self.assertNotIn("frozen", ra)
        # IDs are "<wiki>:<page id>" and in dump order
        ids = [json.loads(l)["doc_id"] for l in (a / "train/hiwiki-20261001-articles.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(ids[:3], ["hiwiki:1000", "hiwiki:1001", "hiwiki:1002"])
        self.assertIn("hiwiki:5006", ids)
        # re-run on the same root: conversions reused (checksums still match), same vocabulary, nothing deleted
        builds_before = sorted(p.name for p in (a / "build").iterdir())
        ca2, ra2, _ = pipeline(a)
        self.assertEqual(ca2, 0)
        self.assertTrue(all(ra2["conversion"][w]["reused_existing_output"] for w in ("hiwiki", "knwiki")))
        self.assertEqual(ra2["vocabulary"]["sha256"], ra["vocabulary"]["sha256"])
        self.assertTrue(set(builds_before) <= {p.name for p in (a / "build").iterdir()})
        # a changed conversion output is not reused
        jl = a / "train/knwiki-20261001-articles.jsonl"
        jl.write_text(jl.read_text(encoding="utf-8") + '{"doc_id": "knwiki:9", "text": "ಕ"}\n', encoding="utf-8")
        ca3, ra3, _ = pipeline(a)
        self.assertEqual(ca3, 0)
        self.assertFalse(ra3["conversion"]["knwiki"]["reused_existing_output"])
        self.assertEqual(ra3["vocabulary"]["sha256"], ra["vocabulary"]["sha256"])

    def test_partial_and_missing_inputs_refused(self):
        r = fresh("partial")
        (r / "raw/knwiki-20261001-pages-articles.xml.bz2.partial").write_bytes(b"x")
        code, rec, _ = pipeline(r)
        self.assertEqual(code, 10)
        self.assertFalse((r / "train").exists())
        m = fresh("missing")
        (m / "raw/knwiki-20261001-sha1sums.txt").unlink()
        self.assertEqual(pipeline(m)[0], 10)

    def test_checksum_failures(self):
        r = fresh("badsum")
        (r / "raw/hiwiki-20261001-sha1sums.txt").write_text(f"{'1' * 40}  hiwiki-20261001-pages-articles.xml.bz2\n")
        code, rec, _ = pipeline(r)
        self.assertEqual(code, 11)
        self.assertIn("SHA-1 mismatch", rec["status"])
        self.assertFalse((r / "train").exists())
        n = fresh("notlisted")
        (n / "raw/knwiki-20261001-sha1sums.txt").write_text(f"{'1' * 40}  other.bz2\n")
        self.assertEqual(pipeline(n)[0], 11)

    def test_unreadable_and_malformed_dumps(self):
        t = fresh("truncated")
        f = t / "raw/knwiki-20261001-pages-articles.xml.bz2"
        f.write_bytes(f.read_bytes()[:-50])
        resum(t, "knwiki")
        self.assertEqual(pipeline(t)[0], 12)
        x = fresh("badxml")
        (x / "raw/hiwiki-20261001-pages-articles.xml.bz2").write_bytes(bz2.compress("<mediawiki><page><ns>0</ns><id>1</id>".encode()))
        resum(x, "hiwiki")
        code, rec, _ = pipeline(x)
        self.assertEqual(code, 13)
        self.assertFalse((x / "train/hiwiki-20261001-articles.jsonl").exists())

    def test_usage_guards(self):
        p = subprocess.run([sys.executable, "-I", str(PIPE), "--synthetic-dry-run", "--data-root", str(ROOT / "results")],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)  # data root inside the repository
        p = subprocess.run([sys.executable, "-I", str(PIPE), "--data-root", str(BASE / "a")], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)  # real mode only for the approved root and date
        p = subprocess.run([sys.executable, "-I", str(PIPE), "--date", "20260901"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)


def tearDownModule():
    TMP.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=1)
