"""Script-span detection: routing metadata for candidate selection and reporting.

Scripts, not languages: Devanagari text may be Hindi, Marathi, Nepali, Sanskrit, ...; Kannada script may contain other
languages or loanwords. Labels are therefore scripts ("Deva", "Knda", "Latn"), plus "Zyyy" (common: spaces, punctuation,
digits, symbols, emoji) and "Zzzz" (anything else). Combining marks and ZWJ/ZWNJ ("inherited") join the preceding span.
Detection never changes the text: concatenating the spans gives the input back exactly.
"""
import unicodedata

BLOCKS = {"Deva": [(0x0900, 0x097F), (0xA8E0, 0xA8FF), (0x1CD0, 0x1CFF), (0x11B00, 0x11B5F)],
          "Knda": [(0x0C80, 0x0CFF)]}
INHERITED = {0x200C, 0x200D}


def script_of(ch):
    cp = ord(ch)
    for name, ranges in BLOCKS.items():
        if any(lo <= cp <= hi for lo, hi in ranges):
            return name
    cat = unicodedata.category(ch)
    if cp in INHERITED or cat in ("Mn", "Me"):
        return "Zinh"
    if cat.startswith("L") and "LATIN" in unicodedata.name(ch, ""):
        return "Latn"
    if cat[0] in "PSZN" or cat in ("Cc", "Cf"):
        return "Zyyy"
    return "Zzzz"


def spans(text):
    """[(script, substring)], adjacent characters of the same script merged; inherited characters join the previous span."""
    out = []
    for ch in text:
        s = script_of(ch)
        if s == "Zinh":
            s = out[-1][0] if out else "Zyyy"
        if out and out[-1][0] == s:
            out[-1][1].append(ch)
        else:
            out.append((s, [ch]))
    return [(s, "".join(c)) for s, c in out]


def letter_counts(text):
    counts = {"Deva": 0, "Knda": 0, "Latn": 0}
    for s, sub in spans(text):
        if s in counts:
            counts[s] += sum(1 for c in sub if unicodedata.category(c)[0] in "LM")
    return counts


def dominant(text, mixed_threshold=0.2):
    """'Deva', 'Knda', 'Latn', 'mixed' (a second script has >= threshold of letters), or 'none'."""
    c = letter_counts(text)
    total = sum(c.values())
    if not total:
        return "none"
    ranked = sorted(c.items(), key=lambda kv: -kv[1])
    if ranked[1][1] / total >= mixed_threshold:
        return "mixed"
    return ranked[0][0]
