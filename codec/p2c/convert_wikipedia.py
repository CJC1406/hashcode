"""Converts one approved Wikipedia pages-articles dump into the P2c builder's JSONL training format.

Approved source (docs/phase2_p2c_report.md §10): hiwiki and knwiki, dump 20261001. Licence of the text: CC BY-SA 4.0 + GFDL.
Input:  <wiki>-<date>-pages-articles.xml.bz2, verified against the official <wiki>-<date>-sha1sums.txt BEFORE any parsing.
Output: JSONL, one article per line, {"doc_id": "<wiki>:<page id>", "text": "<plain text>"}, in dump order, plus a stats JSON.
Write outputs OUTSIDE every Git repository (e.g. /Users/Shared/hashcode-data/wikipedia/20261001/train/).

Page rule: keep a page only if its namespace is 0 (articles), it has no <redirect/>, it has a <text> element, and its stripped
text is non-empty. Everything else is counted, not emitted.
Unicode: no normalization, no case folding, no entity decoding. XML-level decoding by the XML parser is the only change
(XML entities such as &lt; become "<", and XML line-end handling applies).
Markup rule "wikitext-strip-v1" (applied in this order; deterministic):
  1. drop HTML comments <!-- ... --> (an unterminated comment drops the rest of the page);
  2. drop the whole element, contents included, for: ref, references, math, chem, ce, score, syntaxhighlight, source, gallery,
     timeline, graph, templatedata, hiero, mapframe, maplink (paired or self-closing; an unterminated one drops the rest);
  3. drop templates and parser functions {{ ... }} with nesting (an unterminated "{{" drops the rest of the page; a stray "}}"
     outside any template is kept as text);
  4. drop tables: from a line starting with "{|" to its matching line starting with "|}" (nested; unterminated drops the rest);
  5. internal links [[...]] with nesting: if the target's namespace prefix (before the first ":", case-insensitive, after an
     optional leading ":") is a File, Media or Category namespace name of this wiki (from <siteinfo>, plus the canonical
     "File", "Image", "Media", "Category"), drop the link; otherwise replace it by the text after its first "|", or by the
     target when there is no "|"; an unterminated "[[" is kept as literal text;
  6. external links: "[scheme://... label]" -> "label", "[scheme://...]" -> "" (schemes http, https, ftp, //);
  7. remove runs of two or more apostrophes (bold/italic);
  8. remove behaviour switches __WORD__;
  9. remove any remaining HTML/extension tag markup <tag ...>, </tag>, <tag/> (keep the text between tags);
 10. per line: headings "=+ X =+" -> "X"; strip a leading run of list markers [*#:;] and the spaces after it; strip
     leading and trailing spaces and tabs (spaces inside a line are kept as they are); drop lines that are then empty.
     Lines are joined with "\n".
Run: python3 -I codec/p2c/convert_wikipedia.py --dump D.xml.bz2 --sha1sums S.txt --wiki hiwiki --out O.jsonl --stats O.stats.json
"""
import argparse
import bz2
import hashlib
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True

CONVERTER_VERSION = "p2c-wikipedia-converter-v1"
MARKUP_RULE = "wikitext-strip-v1"
WIKIS = ("hiwiki", "knwiki")
DROP_ELEMENTS = ("ref", "references", "math", "chem", "ce", "score", "syntaxhighlight", "source", "gallery", "timeline",
                 "graph", "templatedata", "hiero", "mapframe", "maplink")
CANONICAL_DROP_NAMESPACES = ("file", "image", "media", "category")
DROP_NAMESPACE_IDS = ("-2", "6", "14")  # Media, File, Category


class ConvertError(Exception):
    pass


# ---------------------------------------------------------------------------- verification
def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_sha1(sha1sums_path, file_name):
    for line in pathlib.Path(sha1sums_path).read_text(encoding="ascii").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == file_name:
            if not re.fullmatch(r"[0-9a-f]{40}", parts[0]):
                raise ConvertError(f"malformed SHA-1 for {file_name} in {sha1sums_path}")
            return parts[0]
    raise ConvertError(f"{file_name} is not listed in {sha1sums_path}")


def verify_dump(dump, sha1sums):
    dump = pathlib.Path(dump)
    want = expected_sha1(sha1sums, dump.name)
    got = sha1_file(dump)
    if got != want:
        raise ConvertError(f"SHA-1 mismatch for {dump.name}: file {got}, published {want}")
    return want


# ---------------------------------------------------------------------------- markup stripping (wikitext-strip-v1)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_ELEMENT_OPEN = re.compile(r"<(" + "|".join(DROP_ELEMENTS) + r")\b([^>]*)>", re.I)
_EXT_LINK = re.compile(r"\[(?:https?:|ftp:)?//[^\s\]]*(?:\s+([^\]]*))?\]")
_APOSTROPHES = re.compile(r"'{2,}")
_SWITCH = re.compile(r"__[A-Z]+__")
_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>")
_HEADING = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$")
_LIST = re.compile(r"^[*#:;]+[ \t]*")


def _drop_comments(t):
    t = _COMMENT.sub("", t)
    i = t.find("<!--")
    return t if i < 0 else t[:i]


def _drop_elements(t):
    out, pos = [], 0
    while True:
        m = _ELEMENT_OPEN.search(t, pos)
        if not m:
            out.append(t[pos:])
            return "".join(out)
        out.append(t[pos:m.start()])
        if m.group(2).rstrip().endswith("/"):  # self-closing
            pos = m.end()
            continue
        close = re.compile(r"</" + re.escape(m.group(1)) + r"\s*>", re.I).search(t, m.end())
        if not close:
            return "".join(out)  # unterminated: drop the rest
        pos = close.end()


_BRACES = re.compile(r"\{\{|\}\}")
_BRACKETS = re.compile(r"\[\[|\]\]")


def _drop_templates(t):
    """Remove balanced {{ ... }} spans (with nesting). An unterminated span drops the rest of the text; a stray "}}" outside
    any template is kept as text."""
    out, depth, start = [], 0, 0
    for m in _BRACES.finditer(t):
        if m.group() == "{{":
            if depth == 0:
                out.append(t[start:m.start()])
            depth += 1
        elif depth:
            depth -= 1
            if depth == 0:
                start = m.end()
    if depth == 0:
        out.append(t[start:])
    return "".join(out)


def _drop_tables(t):
    out, depth = [], 0
    lines = t.split("\n")
    for line in lines:
        s = line.lstrip(" \t")
        if s.startswith("{|"):
            depth += 1
            continue
        if depth:
            if s.startswith("|}"):
                depth -= 1
            continue
        out.append(line)
    return "\n".join(out)  # an unterminated table has dropped every following line


def _links(t, drop_prefixes):
    out, i, n = [], 0, len(t)
    while i < n:
        j = t.find("[[", i)
        if j < 0:
            out.append(t[i:])
            break
        out.append(t[i:j])
        depth, k = 0, None
        for m in _BRACKETS.finditer(t, j):
            depth += 1 if m.group() == "[[" else -1
            if depth == 0:
                k = m.end()
                break
        if k is None:  # unterminated: keep literally
            out.append(t[j:])
            break
        inner = t[j + 2:k - 2]
        target = inner.split("|", 1)[0].lstrip(":").strip()
        prefix = target.split(":", 1)[0].strip().casefold() if ":" in target else None
        if prefix is not None and prefix in drop_prefixes:
            pass
        else:
            label = inner.split("|", 1)[1] if "|" in inner else inner.lstrip(":")
            out.append(_links(label, drop_prefixes))  # a label may itself contain links
        i = k
    return "".join(out)


def strip_markup(text, drop_prefixes):
    t = _drop_comments(text)
    t = _drop_elements(t)
    t = _drop_templates(t)
    t = _drop_tables(t)
    t = _links(t, drop_prefixes)
    t = _EXT_LINK.sub(lambda m: m.group(1) or "", t)
    t = _APOSTROPHES.sub("", t)
    t = _SWITCH.sub("", t)
    t = _TAG.sub("", t)
    lines = []
    for line in t.split("\n"):
        h = _HEADING.match(line)
        if h:
            line = h.group(2)
        line = _LIST.sub("", line).strip(" \t")
        if line:
            lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------- XML streaming
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def convert(dump_path, wiki, out_path, stats_path=None, sha1sums=None):
    if wiki not in WIKIS:
        raise ConvertError(f"wiki must be one of {WIKIS}")
    stats = {"converter_version": CONVERTER_VERSION, "markup_rule": MARKUP_RULE, "wiki": wiki,
             "input_file": pathlib.Path(dump_path).name, "pages_seen": 0, "articles_written": 0,
             "skipped_namespace": 0, "skipped_redirect": 0, "skipped_missing_text": 0, "skipped_empty_after_strip": 0}
    if sha1sums is not None:
        stats["input_sha1_verified"] = verify_dump(dump_path, sha1sums)
    stats["input_sha256"] = sha256_file(dump_path)
    drop_prefixes = set(CANONICAL_DROP_NAMESPACES)
    seen_ids = set()
    out_path = pathlib.Path(out_path)
    tmp = out_path.with_suffix(out_path.suffix + ".partial")
    opener = bz2.open if str(dump_path).endswith(".bz2") else open
    with opener(dump_path, "rb") as src, open(tmp, "w", encoding="utf-8", newline="\n") as dst:
        page = None
        for event, el in ET.iterparse(src, events=("start", "end")):
            name = _local(el.tag)
            if event == "start":
                if name == "page":
                    page = {"ns": None, "id": None, "redirect": False, "text": None}
                continue
            if name == "namespace" and page is None:
                alias = (el.text or "").strip()
                if el.get("key") in DROP_NAMESPACE_IDS and alias:
                    drop_prefixes.add(alias.casefold())
            elif page is not None and name == "ns" and page["ns"] is None:
                page["ns"] = (el.text or "").strip()
            elif page is not None and name == "id" and page["id"] is None:
                page["id"] = (el.text or "").strip()  # the first <id> in a page is the page ID (revision IDs come later)
            elif page is not None and name == "redirect":
                page["redirect"] = True
            elif page is not None and name == "text":
                page["text"] = el.text if el.text is not None else ("" if el.get("deleted") is None else None)
            elif name == "page":
                stats["pages_seen"] += 1
                if not page["id"] or not page["id"].isdigit():
                    raise ConvertError(f"page without a numeric page ID (page #{stats['pages_seen']})")
                if page["id"] in seen_ids:
                    raise ConvertError(f"duplicate page ID {page['id']}")
                seen_ids.add(page["id"])
                if page["ns"] != "0":
                    stats["skipped_namespace"] += 1
                elif page["redirect"]:
                    stats["skipped_redirect"] += 1
                elif page["text"] is None:
                    stats["skipped_missing_text"] += 1
                else:
                    text = strip_markup(page["text"], drop_prefixes)
                    if not text:
                        stats["skipped_empty_after_strip"] += 1
                    else:
                        dst.write(json.dumps({"doc_id": f"{wiki}:{page['id']}", "text": text}, ensure_ascii=False, sort_keys=True) + "\n")
                        stats["articles_written"] += 1
                page = None
                el.clear()
            if event == "end" and name in ("page", "siteinfo"):
                el.clear()
    tmp.replace(out_path)
    stats["drop_link_prefixes"] = sorted(drop_prefixes)
    stats["output_file"] = out_path.name
    stats["output_bytes"] = out_path.stat().st_size
    stats["output_sha256"] = sha256_file(out_path)
    if stats_path:
        pathlib.Path(stats_path).write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n")
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", required=True, type=pathlib.Path)
    ap.add_argument("--sha1sums", required=True, type=pathlib.Path, help="official <wiki>-<date>-sha1sums.txt; verified before parsing")
    ap.add_argument("--wiki", required=True, choices=WIKIS)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--stats", type=pathlib.Path, default=None)
    args = ap.parse_args(argv)
    root = pathlib.Path(__file__).resolve().parents[2]
    for p in (args.out, args.stats):
        if p is not None:
            try:
                p.resolve().relative_to(root)
                sys.exit(f"refusing to write {p} inside the repository: training text must stay outside every Git repository")
            except ValueError:
                pass
    try:
        stats = convert(args.dump, args.wiki, args.out, args.stats, args.sha1sums)
    except (ConvertError, ET.ParseError, OSError, EOFError) as e:
        sys.exit(f"conversion error: {e}")
    print(json.dumps({k: stats[k] for k in ("wiki", "pages_seen", "articles_written", "output_sha256")}))


if __name__ == "__main__":
    main()
