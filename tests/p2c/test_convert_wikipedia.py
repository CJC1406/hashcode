"""Tests for codec/p2c/convert_wikipedia.py, using ONLY hand-written XML written in this file (no real dump content).

Run: python3 -I tests/p2c/test_convert_wikipedia.py
"""
import bz2
import hashlib
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unicodedata
import unittest

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("p2c_convert", ROOT / "codec" / "p2c" / "convert_wikipedia.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

NFC = unicodedata.normalize("NFC", "क़")  # U+0958 is excluded from NFC composition, so NFC keeps U+0915 U+093C
DEVA_PRECOMPOSED = "क़"            # क़ as one code point (not NFC-stable)
SITEINFO = """  <siteinfo>
    <sitename>विकिपीडिया</sitename>
    <namespaces>
      <namespace key="-2" case="first-letter">मीडिया</namespace>
      <namespace key="0" case="first-letter" />
      <namespace key="1" case="first-letter">वार्ता</namespace>
      <namespace key="6" case="first-letter">चित्र</namespace>
      <namespace key="14" case="first-letter">श्रेणी</namespace>
    </namespaces>
  </siteinfo>
"""


def page(pid, title, text, ns=0, redirect=False, text_xml=None, rev_id=None):
    body = text_xml if text_xml is not None else f"<text bytes=\"1\" xml:space=\"preserve\">{text}</text>"
    return (f"  <page>\n    <title>{title}</title>\n    <ns>{ns}</ns>\n    <id>{pid}</id>\n"
            + ("    <redirect title=\"x\" />\n" if redirect else "")
            + f"    <revision>\n      <id>{rev_id or pid * 1000}</id>\n      <contributor><username>u</username><id>77</id></contributor>\n"
            + f"      {body}\n    </revision>\n  </page>\n")


def dump_xml(pages):
    return ('<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/" version="0.11" xml:lang="hi">\n'
            + SITEINFO + "".join(pages) + "</mediawiki>\n")


ARTICLE = ("== इतिहास ==\n'''नमस्ते''' [[दुनिया|विश्व]] {{टेम्पलेट|{{अंदर}}}} पाठ&lt;ref&gt;स्रोत&lt;/ref&gt;।\n"
           "* [[चित्र:a.jpg|thumb|शीर्षक [[लिंक]]]] सूची [https://example.org बाहरी]\n"
           "{| class=&quot;wikitable&quot;\n| तालिका\n|}\n&lt;!-- टिप्पणी --&gt;\n[[श्रेणी:कुछ]] [[Category:X]] __NOTOC__\n"
           ": [[:en:Foo|अंग्रेज़ी]] ಕನ್ನಡ")
ARTICLE_EXPECTED = "इतिहास\nनमस्ते विश्व  पाठ।\nसूची बाहरी\nअंग्रेज़ी ಕನ್ನಡ"


_ENVS = []


def tearDownModule():
    for env in _ENVS:
        env.tmp.cleanup()


class Env:
    def __init__(self, pages, name="hiwiki-20261001-pages-articles.xml.bz2", compress=True):
        self.tmp = tempfile.TemporaryDirectory(prefix="hashcode_p2c_conv_")
        _ENVS.append(self)
        self.dir = pathlib.Path(self.tmp.name)
        data = dump_xml(pages).encode("utf-8")
        self.dump = self.dir / name
        self.dump.write_bytes(bz2.compress(data) if compress else data)
        self.sha1 = self.dir / "hiwiki-20261001-sha1sums.txt"
        self.sha1.write_text(f"{hashlib.sha1(self.dump.read_bytes()).hexdigest()}  {name}\n"
                             f"{'0' * 40}  hiwiki-20261001-other.xml.bz2\n")

    def run(self, out="out.jsonl", **kw):
        stats = C.convert(self.dump, "hiwiki", self.dir / out, self.dir / (out + ".stats.json"), self.sha1, **kw)
        rows = [json.loads(line) for line in (self.dir / out).read_text(encoding="utf-8").splitlines()]
        return stats, rows


class MarkupRules(unittest.TestCase):
    P = {"file", "image", "media", "category", "चित्र", "श्रेणी", "मीडिया"}

    def s(self, t):
        return C.strip_markup(t, self.P)

    def test_full_article(self):
        import html
        self.assertEqual(self.s(html.unescape(ARTICLE)), ARTICLE_EXPECTED)

    def test_templates(self):
        self.assertEqual(self.s("a{{x|{{y}}|z}}b"), "ab")
        self.assertEqual(self.s("a{{#if:1|{{y}}}}b"), "ab")
        self.assertEqual(self.s("a}}b"), "a}}b")             # stray close is text
        self.assertEqual(self.s("a{{x\nb\nc"), "a")           # unterminated drops the rest

    def test_elements_and_comments(self):
        self.assertEqual(self.s("a<ref name=\"n\" />b<REF>c</ref>d"), "abd")
        self.assertEqual(self.s("a<math>x^2</math>b<gallery>\nf.jpg\n</gallery>c"), "abc")
        self.assertEqual(self.s("a<!-- x -->b<!-- open"), "ab")
        self.assertEqual(self.s("a<ref>never closed"), "a")
        self.assertEqual(self.s("a<span style=\"x\">b</span><br/>c"), "abc")
        self.assertEqual(self.s("a <nowiki>[[x]]</nowiki>"), "a x")  # nowiki: tags removed, content kept (links then resolved)

    def test_links(self):
        self.assertEqual(self.s("[[a]] [[a|b]] [[a|b|c]]"), "a b b|c")
        self.assertEqual(self.s("[[File:x.png|thumb|cap [[y]]]]z"), "z")
        self.assertEqual(self.s("[[चित्र:x.png]] [[श्रेणी:y]] [[ Category : z]] [[मीडिया:m]]w"), "w")
        self.assertEqual(self.s("[[:श्रेणी:y|दृश्य]]"), "")  # leading colon still a category link: dropped
        self.assertEqual(self.s("[[वार्ता:x|t]]"), "t")      # other namespaces: label kept
        self.assertEqual(self.s("a [[unterminated"), "a [[unterminated")
        self.assertEqual(self.s("[[a]]s"), "as")

    def test_external_links_and_formatting(self):
        self.assertEqual(self.s("[https://x.org/p q r] [http://y] [//z.org w] [not a link]"), "q r  w [not a link]")
        self.assertEqual(self.s("''i'' '''b''' '''''bi'''''"), "i b bi")
        self.assertEqual(self.s("__TOC__x__NOEDITSECTION__"), "x")

    def test_lines(self):
        self.assertEqual(self.s("==  शीर्ष  ==\n\n\n*# सूची\n;: डी\n \t  \nअंत  "), "शीर्ष\nसूची\nडी\nअंत")
        self.assertEqual(self.s("{|\n{|\nभीतर\n|}\nअब भी\n|}\nबाहर"), "बाहर")  # nested tables
        self.assertEqual(self.s("{|\nखुली तालिका"), "")
        self.assertEqual(self.s(""), "")

    def test_no_unicode_normalization(self):
        for t in (DEVA_PRECOMPOSED, NFC, "क़", "é", "é", "क्‍ष", "क्‌ष", "\U0001F600", " x"):
            self.assertEqual(self.s(t), t.strip(" \t"))
        self.assertNotEqual(self.s(DEVA_PRECOMPOSED), self.s("क़"))


class Conversion(unittest.TestCase):
    def test_pages_ids_namespaces_redirects(self):
        import html
        pages = [page(10, "लेख", html.escape(html.unescape(ARTICLE), quote=False)),
                 page(11, "वार्ता:लेख", "बात", ns=1),
                 page(12, "चित्र:x", "चित्र", ns=6),
                 page(13, "पुनर्निर्देश", "#अनुप्रेषित [[लेख]]", redirect=True),
                 page(14, "खाली", "", text_xml="<text bytes=\"0\" />"),
                 page(15, "हटाया", "", text_xml="<text deleted=\"deleted\" />"),
                 page(16, "केवल साँचा", "{{केवल}}"),
                 page(17, "दूसरा", DEVA_PRECOMPOSED + " और क़")]
        env = Env(pages)
        stats, rows = env.run()
        self.assertEqual([r["doc_id"] for r in rows], ["hiwiki:10", "hiwiki:17"])
        self.assertEqual(rows[0]["text"], ARTICLE_EXPECTED)
        self.assertEqual(rows[1]["text"], DEVA_PRECOMPOSED + " और क़")  # both spellings preserved exactly
        self.assertEqual({k: stats[k] for k in ("pages_seen", "articles_written", "skipped_namespace", "skipped_redirect",
                                               "skipped_missing_text", "skipped_empty_after_strip")},
                         {"pages_seen": 8, "articles_written": 2, "skipped_namespace": 2, "skipped_redirect": 1,
                          "skipped_missing_text": 1, "skipped_empty_after_strip": 2})
        self.assertIn("चित्र", stats["drop_link_prefixes"])
        self.assertIn("श्रेणी", stats["drop_link_prefixes"])
        self.assertEqual(stats["input_sha1_verified"], hashlib.sha1(env.dump.read_bytes()).hexdigest())
        self.assertEqual(stats["output_sha256"], hashlib.sha256((env.dir / "out.jsonl").read_bytes()).hexdigest())
        for line in (env.dir / "out.jsonl").read_text(encoding="utf-8").splitlines():
            self.assertEqual(set(json.loads(line)), {"doc_id", "text"})

    def test_page_id_not_revision_or_contributor_id(self):
        env = Env([page(42, "a", "पाठ", rev_id=99999)])
        self.assertEqual(env.run()[1][0]["doc_id"], "hiwiki:42")

    def test_deterministic(self):
        env = Env([page(i, f"t{i}", f"पाठ {i} [[क|ख]]") for i in range(1, 30)])
        s1, r1 = env.run("a.jsonl")
        s2, r2 = env.run("b.jsonl")
        self.assertEqual(r1, r2)
        self.assertEqual(s1["output_sha256"], s2["output_sha256"])
        self.assertEqual([r["doc_id"] for r in r1], [f"hiwiki:{i}" for i in range(1, 30)])  # dump order

    def test_builder_reads_output(self):
        b_spec = importlib.util.spec_from_file_location("p2c_builder", ROOT / "codec" / "p2c" / "build_vocabulary.py")
        B = importlib.util.module_from_spec(b_spec)
        b_spec.loader.exec_module(B)
        env = Env([page(1, "a", "पाठ"), page(2, "b", "ಕನ್ನಡ")])
        env.run()
        docs = list(B.iter_corpus(env.dir / "out.jsonl"))
        self.assertEqual([d["doc_id"] for d in docs], ["hiwiki:1", "hiwiki:2"])


class Failures(unittest.TestCase):
    def test_checksum_mismatch_refused_before_parsing(self):
        env = Env([page(1, "a", "पाठ")])
        env.sha1.write_text(f"{'1' * 40}  {env.dump.name}\n")
        with self.assertRaises(C.ConvertError):
            env.run()
        self.assertFalse((env.dir / "out.jsonl").exists())

    def test_file_not_listed(self):
        env = Env([page(1, "a", "पाठ")])
        env.sha1.write_text(f"{'1' * 40}  something-else.xml.bz2\n")
        with self.assertRaises(C.ConvertError):
            env.run()

    def test_duplicate_and_bad_ids(self):
        with self.assertRaises(C.ConvertError):
            Env([page(1, "a", "x"), page(1, "b", "y")]).run()
        with self.assertRaises(C.ConvertError):
            Env([page("x1", "a", "x")]).run()

    def test_malformed_xml_and_truncated_bz2(self):
        env = Env([page(1, "a", "पाठ")])
        env.dump.write_bytes(bz2.compress(b"<mediawiki><page><ns>0</ns>"))
        env.sha1.write_text(f"{hashlib.sha1(env.dump.read_bytes()).hexdigest()}  {env.dump.name}\n")
        with self.assertRaises(Exception):
            env.run()
        self.assertFalse((env.dir / "out.jsonl").exists())  # no partial output under the final name
        env.dump.write_bytes(bz2.compress(dump_xml([page(1, "a", "पाठ")]).encode())[:-20])
        env.sha1.write_text(f"{hashlib.sha1(env.dump.read_bytes()).hexdigest()}  {env.dump.name}\n")
        with self.assertRaises(Exception):
            env.run()

    def test_cli_refuses_output_inside_repository(self):
        env = Env([page(1, "a", "पाठ")])
        p = subprocess.run([sys.executable, "-I", str(ROOT / "codec/p2c/convert_wikipedia.py"), "--dump", str(env.dump),
                            "--sha1sums", str(env.sha1), "--wiki", "hiwiki", "--out", str(ROOT / "should_not_exist.jsonl")],
                           capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse((ROOT / "should_not_exist.jsonl").exists())


if __name__ == "__main__":
    unittest.main(verbosity=1)
