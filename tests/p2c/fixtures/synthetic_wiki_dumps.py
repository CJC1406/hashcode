"""SYNTHETIC Wikipedia-style dumps for pipeline dry runs. NOT real Wikipedia content.

Writes <wiki>-<date>-pages-articles.xml.bz2 and <wiki>-<date>-sha1sums.txt for hiwiki and knwiki into <dir>/raw/.
Article text is meaningless pseudo-words from tests/p2c/fixtures/make_synthetic_corpus.py's generator, wrapped in the
MediaWiki export XML structure, plus pages that exercise the converter's rules (namespaces, redirects, empty text, markup).
Run: python3 -I tests/p2c/fixtures/synthetic_wiki_dumps.py <dir> [--date 20261001]
"""
import bz2
import hashlib
import importlib.util
import pathlib
import sys
from xml.sax.saxutils import escape

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("p2c_fixture_gen", HERE / "make_synthetic_corpus.py")
G = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(G)

NAMESPACES = {"hiwiki": {"-2": "मीडिया", "1": "वार्ता", "6": "चित्र", "14": "श्रेणी"},
              "knwiki": {"-2": "ಮೀಡಿಯಾ", "1": "ಚರ್ಚೆಪುಟ", "6": "ಚಿತ್ರ", "14": "ವರ್ಗ"}}
SCRIPT = {"hiwiki": "deva", "knwiki": "knda"}


def _page(pid, title, text, ns=0, redirect=False, text_xml=None):
    body = text_xml if text_xml is not None else f'<text bytes="{len(text.encode())}" xml:space="preserve">{escape(text)}</text>'
    return (f"  <page>\n    <title>{escape(title)}</title>\n    <ns>{ns}</ns>\n    <id>{pid}</id>\n"
            + ('    <redirect title="x" />\n' if redirect else "")
            + f"    <revision>\n      <id>{pid * 10 + 7}</id>\n      <contributor><username>u</username><id>5</id></contributor>\n"
            + f"      {body}\n    </revision>\n  </page>\n")


def dump_xml(wiki, n_articles=160, seed=1):
    rng = G.Rng(seed + (0 if wiki == "hiwiki" else 99))
    lex = G.lexicon(rng, G.SCRIPTS[SCRIPT[wiki]], 200)
    ns = NAMESPACES[wiki]
    pages = []
    for i in range(n_articles):
        lines = [" ".join(lex[rng.skewed(len(lex))] for _ in range(6 + rng.below(6))) for _ in range(3)]
        cat = ns["14"]
        text = (f"== {lex[i % len(lex)]} ==\n'''{lines[0]}''' {{{{साँचा|x={lines[1][:5]}}}}} [[{lex[1]}|{lex[2]}]]\n"
                f"* {lines[1]}<ref>{lex[3]}</ref>\n{lines[2]}\n[[{cat}:{lex[4]}]]")
        pages.append(_page(1000 + i, f"लेख {i}", text))
    pages += [_page(5000, f"{ns['1']}:x", "बात", ns=1), _page(5001, f"{ns['6']}:y.png", "चित्र", ns=6),
              _page(5002, "पुनर्निर्देश", "#REDIRECT [[x]]", redirect=True), _page(5003, "खाली", "", text_xml='<text bytes="0" />'),
              _page(5004, "हटाया", "", text_xml='<text deleted="deleted" />'), _page(5005, "साँचा", "{{केवल}}"),
              _page(5006, "यूनिकोड", "क़ क़ é é क्‍ष \U0001F600")]
    head = (f'<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/" version="0.11">\n  <siteinfo>\n    <sitename>{wiki}</sitename>\n'
            "    <namespaces>\n" + "".join(f'      <namespace key="{k}" case="first-letter">{v}</namespace>\n' for k, v in ns.items())
            + '      <namespace key="0" case="first-letter" />\n    </namespaces>\n  </siteinfo>\n')
    return head + "".join(pages) + "</mediawiki>\n"


def write(dir_, date="20261001", n_articles=160):
    raw = pathlib.Path(dir_) / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for wiki in ("hiwiki", "knwiki"):
        name = f"{wiki}-{date}-pages-articles.xml.bz2"
        blob = bz2.compress(dump_xml(wiki, n_articles).encode("utf-8"), 9)
        (raw / name).write_bytes(blob)
        (raw / f"{wiki}-{date}-sha1sums.txt").write_text(f"{hashlib.sha1(blob).hexdigest()}  {name}\n{'0' * 40}  {wiki}-{date}-other.xml.bz2\n")
    return raw


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: synthetic_wiki_dumps.py <dir> [--date D]")
    date = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else "20261001"
    print(write(sys.argv[1], date))
