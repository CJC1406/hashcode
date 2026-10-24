"""Tests for script detection, candidate generation, the A/B(/C) evaluator and the model-integration plan.

Uses the real frozen P2c vocabulary and Qwen3 tokenizer.json, with SYNTHETIC corpora built in temporary directories
(never real evaluation data). Run: python3 -I tests/indic_tokenizer/test_candidates_and_eval.py
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
sys.path.insert(0, str(ROOT / "experiments/indic_tokenizer"))
import candidates as C  # noqa: E402
import evaluate as EV  # noqa: E402
import hf_bpe  # noqa: E402
import model_plan as MP  # noqa: E402
import scripts as S  # noqa: E402

QWEN3 = ROOT / "external/token-vldb2026/tokenizers/qwen3.json"
spec = importlib.util.spec_from_file_location("fx_gen", ROOT / "tests/p2c/fixtures/make_synthetic_corpus.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
B = C._builder()
TMP = tempfile.TemporaryDirectory(prefix="hashcode_indic_tok_")
D = pathlib.Path(TMP.name)
FIXTURE = D / "synthetic_corpus.jsonl"
FIXTURE.write_bytes(G.generate())
DOCS = [json.loads(l) for l in FIXTURE.read_text(encoding="utf-8").splitlines()]
P2C = C.load_p2c()


def heldout_id(prefix):
    i = 0
    while not B.is_heldout(f"{prefix}-{i}"):
        i += 1
    return f"{prefix}-{i}"


def train_id(prefix):
    i = 0
    while B.is_heldout(f"{prefix}-{i}"):
        i += 1
    return f"{prefix}-{i}"


def build(pool, k=64, corpora=(FIXTURE,), min_freq=2):
    return C.build(list(corpora), QWEN3, pool, k, min_freq=min_freq, p2c=P2C)


MB, MW = build("bytme"), build("words")
C.write(MB, D, "b")
C.write(MW, D, "c")


class Scripts(unittest.TestCase):
    def test_spans_are_lossless_and_labelled(self):
        for t in ("", "नमस्ते दुनिया", "ಕನ್ನಡ ಭಾಷೆ", "Hello 123 😀", "मेरा फ़ोन 98450 call ಧನ್ಯವಾದ!", "क्‍ष", "́x"):
            self.assertEqual("".join(s for _, s in S.spans(t)), t)
        self.assertEqual([s for s, _ in S.spans("नमस्ते Hi ಕನ್ನಡ")], ["Deva", "Zyyy", "Latn", "Zyyy", "Knda"])
        self.assertEqual(S.spans("क्‍ष"), [("Deva", "क्‍ष")])  # ZWJ joins the span
        self.assertEqual(S.dominant("नमस्ते दुनिया"), "Deva")
        self.assertEqual(S.dominant("ಕನ್ನಡ"), "Knda")
        self.assertEqual(S.dominant("plain"), "Latn")
        self.assertEqual(S.dominant("नमस्ते hello world friends"), "mixed")
        self.assertEqual(S.dominant("123 !?"), "none")


class Candidates(unittest.TestCase):
    def test_frozen_p2c_checksum(self):
        self.assertEqual(len(P2C), 32768)
        bad = D / "bad.bin"
        data = bytearray(C.P2C_VOCABULARY.read_bytes())
        data[100] ^= 1
        bad.write_bytes(bytes(data))
        with self.assertRaises(C.CandidateError):
            C.load_p2c(bad)

    def test_deterministic(self):
        again = build("bytme")
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(MB, sort_keys=True))
        self.assertEqual(C.write(again, D / "again", "b"), (D / "b.sha256").read_text().split()[0])

    def test_scoring_ranking_quota_ids(self):
        tk = hf_bpe.ByteLevelBPE(QWEN3)
        for m in (MB, MW):
            c = m["candidates"]
            self.assertEqual(len(c), 64)
            self.assertEqual([x["script"] for x in c], ["Deva"] * 32 + ["Knda"] * 32)
            self.assertEqual([x["id"] for x in c], list(range(151669, 151669 + 64)))
            self.assertEqual(len({x["token"] for x in c}), 64)
            for x in c:
                self.assertEqual(x["base_ids"], tk.encode(x["token"]))
                self.assertEqual(x["base_tokens"], len(x["base_ids"]))
                self.assertGreaterEqual(x["base_tokens"], 2)
                self.assertEqual(x["estimated_tokens_saved"], x["frequency"] * (x["base_tokens"] - 1))
            for script in ("Deva", "Knda"):
                s = [x for x in c if x["script"] == script]
                keys = [(-x["estimated_tokens_saved"], -len(x["token"].encode()), x["token"]) for x in s]
                self.assertEqual(keys, sorted(keys))
        self.assertTrue(all(x["kind"] == "word" for x in MW["candidates"]))
        for x in MB["candidates"]:
            if x["kind"] == "p2c_entry":
                self.assertEqual(P2C[x["token"]], x["p2c_id"])
            else:
                self.assertTrue(C.starts_with_p2c(x["token"].startswith(" "), x["token"].lstrip(" "), B.Segmenter(), P2C))

    def test_no_heldout_or_evaluation_leakage(self):
        word = "ठठठठठठठठ"  # synthetic marker word
        held = heldout_id("leak")
        tr = train_id("ok")
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "c.jsonl"
            docs = DOCS + [{"doc_id": held, "text": " ".join([word] * 500)}]
            p.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs), encoding="utf-8")
            m = C.build([p], QWEN3, "words", 64, min_freq=2, p2c=P2C)
            self.assertNotIn(word, {x["token"] for x in m["candidates"]} | {x["token"].strip() for x in m["candidates"]})
            self.assertEqual(m["corpus"]["heldout_documents_skipped"], 13)
            docs[-1] = {"doc_id": tr, "text": " ".join([word] * 500)}
            p.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs), encoding="utf-8")
            m = C.build([p], QWEN3, "words", 64, min_freq=2, p2c=P2C)
            self.assertIn(word, {x["token"].strip() for x in m["candidates"]})
        for ds in ("datasets/phase1/kn_hi_v1.jsonl", "datasets/phase1_en_mixed/en_mixed_v1.jsonl"):
            with self.assertRaises(Exception):  # refused as a training corpus
                C.build([ROOT / ds], QWEN3, "words", 64, p2c=P2C)

    def test_nfc_unstable_excluded(self):
        self.assertGreater(MW["excluded"].get("not_nfc_stable", 0), 0)
        for x in MW["candidates"] + MB["candidates"]:
            import unicodedata
            self.assertEqual(unicodedata.normalize("NFC", x["token"]), x["token"])

    def test_fail_closed(self):
        with self.assertRaises(C.CandidateError):
            build("bytme", k=63)
        with self.assertRaises(C.CandidateError):
            build("other")
        with self.assertRaises(C.CandidateError):
            build("words", k=100000)  # not enough eligible candidates for the quota
        with self.assertRaises(C.CandidateError):
            C.write(MB, ROOT / "results", "x")
        t = D / "tampered.json"
        shutil.copy(D / "b.json", t)
        shutil.copy(D / "b.sha256", D / "tampered.sha256")
        t.write_text(t.read_text().replace('"k": 64', '"k": 66'))
        with self.assertRaises(C.CandidateError):
            C.load_manifest(t)
        with self.assertRaises(C.CandidateError):
            C.load_manifest(D / "missing.json") if (D / "missing.json").exists() else C.load_manifest(D / "b.sha256")


class Evaluate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        held = [d for d in DOCS if B.is_heldout(d["doc_id"])]  # never seen by the candidate builder
        rows = [{"group": "hi" if "deva" in d["doc_id"] else "kn" if "knda" in d["doc_id"] else "mixed", "id": d["doc_id"], "text": d["text"]} for d in held]
        rows += [{"group": "en", "id": "en-1", "text": "The quick brown fox jumps over the lazy dog, 2026!"},
                 {"group": "en", "id": "en-2", "text": ""}, {"group": "edge", "id": "x-1", "text": "😀 \t\n <|im_start|> é क़"}]
        cls.fixture = D / "eval_fixture.jsonl"
        cls.fixture.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def run_eval(self, out, *extra):
        return EV.main(["--fixture", str(self.fixture), "--tokenizer", str(QWEN3), "--candidates-b", str(D / "b.json"), "--out", str(out), *extra])

    def test_fixture_evaluation(self):
        self.assertEqual(self.run_eval(D / "e1", "--candidates-c", str(D / "c.json")), 0)
        self.assertEqual(self.run_eval(D / "e2", "--candidates-c", str(D / "c.json")), 0)
        s1, s2 = (json.loads((D / e / "summary.json").read_text()) for e in ("e1", "e2"))
        strip = lambda s: {g: {k: v for k, v in r.items()} for g, r in s["groups"].items()}  # noqa: E731
        self.assertEqual(strip(s1), strip(s2))  # deterministic counts
        self.assertIn("FIXTURE", s1["label"])
        g = s1["groups"]
        self.assertEqual(g["en"]["A_tokens"], g["en"]["B_tokens"])  # no Indic text: unchanged
        self.assertEqual(g["en"]["B_reduction_percent"], 0.0)
        for row in g.values():
            for n in ("A", "B", "C"):
                self.assertTrue(row[f"{n}_ids_valid"])
                self.assertEqual(row[f"{n}_exact_after_nfc"], row["samples"])
            self.assertEqual(row["B_reduction_percent"], round(EV.reduction(row["A_tokens"], row["B_tokens"]), 3))
        self.assertEqual(g["edge"]["A_exact_round_trip"], 0)  # non-NFC input is normalized by the model's own tokenizer
        self.assertIn("hi", s1["proposed_target"]["by_group"])

    def test_reduction_formula(self):
        self.assertEqual(EV.reduction(100, 80), 20.0)
        self.assertEqual(EV.reduction(100, 120), -20.0)
        self.assertEqual(EV.reduction(0, 0), 0.0)
        self.assertIsNone(EV.reduction(0, 3))

    def test_refusals(self):
        flores = ROOT / "datasets/external_manifests/flores_plus_devtest_e707e62e.json"
        self.assertEqual(EV.main(["--spec", str(flores), "--tokenizer", str(QWEN3), "--candidates-b", str(D / "b.json"), "--out", str(D / "r1")]), 13)
        self.assertFalse((D / "r1").exists())
        self.assertEqual(self.run_eval(D / "e1"), 2)  # never overwrite
        m = json.loads((D / "c.json").read_text())
        m["k"] = 66
        m["candidates"].append(dict(m["candidates"][-1], token="टटटट", id=151669 + 64))
        m["candidates"].append(dict(m["candidates"][-1], token="टटटटट", id=151669 + 65))
        bad = D / "c66.json"
        blob = (json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
        bad.write_bytes(blob)
        (D / "c66.sha256").write_text(hashlib.sha256(blob).hexdigest() + "  c66.json\n")
        self.assertEqual(self.run_eval(D / "r2", "--candidates-c", str(bad)), 2)  # B and C must add the same number of tokens
        other = D / "other_tokenizer.json"
        other.write_text(QWEN3.read_text().replace('"type":"NFC"', '"type": "NFC" ') + " ")
        self.assertEqual(EV.main(["--fixture", str(self.fixture), "--tokenizer", str(other), "--candidates-b", str(D / "b.json"), "--out", str(D / "r3")]), 2)


class HeldoutAndSpecModes(unittest.TestCase):
    def test_heldout_mode(self):
        out = D / "h1"
        code = EV.main(["--heldout-corpus", str(FIXTURE), "--tokenizer", str(QWEN3), "--candidates-b", str(D / "b.json"),
                        "--candidates-c", str(D / "c.json"), "--out", str(out)])
        self.assertEqual(code, 0)
        s = json.loads((out / "summary.json").read_text())
        self.assertIn("NOT independent", s["label"])
        self.assertEqual(s["source"]["kind"], "training-heldout")
        self.assertEqual(s["source"]["heldout_documents"], 12)
        held_lines = sum(1 for d in DOCS if B.is_heldout(d["doc_id"]) for l in d["text"].split("\n") if l.strip())
        self.assertEqual(s["samples"], held_lines)
        self.assertFalse((out / "per_sample.json").exists())  # aggregates only
        blob = (out / "summary.json").read_bytes()
        for d in DOCS:
            if B.is_heldout(d["doc_id"]):
                self.assertNotIn(d["text"].split("\n")[0].encode(), blob)
        self.assertEqual(list(D.glob("*.partial")), [])
        # The corpus must be exactly the candidates' own corpus.
        other = D / "other_corpus.jsonl"
        other.write_text(FIXTURE.read_text(encoding="utf-8") + json.dumps({"doc_id": "extra-1", "text": "क"}) + "\n", encoding="utf-8")
        self.assertEqual(EV.main(["--heldout-corpus", str(other), "--tokenizer", str(QWEN3), "--candidates-b", str(D / "b.json"),
                                  "--out", str(D / "h2")]), 2)
        self.assertFalse((D / "h2").exists())

    def test_spec_mode_report_only_decontamination(self):
        root = D / "spec_root"
        files = []
        held = [d for d in DOCS if B.is_heldout(d["doc_id"])]
        for g, name, rows in (("hi", "hi.jsonl", [d for d in held if "deva" in d["doc_id"]]), ("kn", "kn.jsonl", [d for d in held if "knda" in d["doc_id"]])):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = "".join(json.dumps({"id": k, "text": d["text"].split("\n")[0]}, ensure_ascii=False) + "\n" for k, d in enumerate(rows)).encode()
            path.write_bytes(data)
            files.append({"group": g, "path": name, "size": len(data), "git_blob_sha1": hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()})
        spec = {"synthetic": True, "name": "synthetic", "version_label": "0", "split": "test", "approval": {}, "decontamination": "report-only",
                "storage_root": str(root), "format": "jsonl", "text_field": "text", "id_field": "id", "column_size": 64, "files": files}
        sp = D / "spec.json"
        sp.write_text(json.dumps(spec))
        planted = D / "train_with_overlap.jsonl"
        planted.write_text(json.dumps({"doc_id": "t:1", "text": held[0]["text"].split("\n")[0]}, ensure_ascii=False) + "\n", encoding="utf-8")
        base = ["--spec", str(sp), "--tokenizer", str(QWEN3), "--candidates-b", str(D / "b.json"), "--out"]
        self.assertEqual(EV.main(base + [str(D / "s0")]), 13)  # a synthetic spec needs --synthetic-test
        self.assertEqual(EV.main(base + [str(D / "s1"), "--synthetic-test", "--training-corpus", str(planted)]), 0)
        dec = json.loads((D / "s1/summary.json").read_text())["source"]["decontamination"]
        self.assertEqual(dec["mode"], "report-only")
        self.assertGreaterEqual(dec["samples_found_whole"], 1)
        self.assertEqual(EV.main(base + [str(D / "s2"), "--training-corpus", str(planted)]), 2)  # not without --synthetic-test
        self.assertEqual(list(D.glob("*.partial")), [])


class ModelPlan(unittest.TestCase):
    def test_plan_alignment(self):
        p = MP.plan(MB, QWEN3)
        self.assertTrue(p["checks"]["ok"], p["checks"]["problems"])
        self.assertEqual(p["tokenizer"]["final_size"], 151669 + 64)
        self.assertEqual(p["embedding"]["unused_padding_rows_before"], 151936 - 151669)
        self.assertFalse(p["embedding"]["resize_needed"])
        self.assertEqual(p["embedding"]["memory_overhead_bytes"], 0)
        self.assertEqual(len(p["initialisation"]["rows"]), 64)
        small = dict(MP.QWEN3_0_6B, vocab_size=151700)
        p = MP.plan(MB, QWEN3, small)
        self.assertTrue(p["embedding"]["resize_needed"])
        self.assertEqual(p["embedding"]["memory_overhead_bytes"], (151669 + 64 - 151700) * 1024 * 2)
        untied = dict(small, tie_word_embeddings=False)
        self.assertEqual(MP.plan(MB, QWEN3, untied)["embedding"]["memory_overhead_bytes"], (151669 + 64 - 151700) * 1024 * 2 * 2)
        bad = json.loads(json.dumps(MB))
        bad["candidates"][3]["id"] += 1000
        with self.assertRaises(C.CandidateError):
            MP.plan(bad, QWEN3)


def tearDownModule():
    TMP.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=1)
