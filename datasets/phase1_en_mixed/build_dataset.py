"""Builds the frozen Phase 1 English / mixed-language dataset (en_mixed_v1.jsonl) and its SHA-256.

Same record schema as datasets/phase1/kn_hi_v1.jsonl. `utf8_hex` is authoritative; `text` is the same string.
No Unicode normalization. Language labels: en (English only), en-hi (English + Hindi/Devanagari),
en-kn (English + Kannada). Run: python3 -I datasets/phase1_en_mixed/build_dataset.py
"""
import hashlib
import json
import pathlib
import sys

DATASET_VERSION = "phase1-en-mixed-v1"
PROVENANCE = "authored for this project (Token Tables for Bharat), 2026-10-24; original text, not copied from any source"
CATEGORIES = ["short", "medium", "long", "repeated", "punct_numerals", "structured", "edge", "tiny"]

EN_PARAGRAPH = (
    "The warehouse receives new stock every Monday and Thursday. Each delivery is counted, labelled and entered "
    "into the inventory system before noon, so that orders placed in the afternoon can be packed the same day. "
    "When an item is out of stock, customers are offered a restock alert or a similar product, and the support "
    "team follows up within two working days."
)
EN_HI_PARAGRAPH = (
    "हमारी team हर Monday को weekly review करती है। इस meeting में पिछले हफ़्ते के orders, pending deliveries और "
    "customer feedback पर बात होती है। अगर कोई issue urgent हो, तो उसी दिन ticket बनाकर support को assign कर दिया जाता है, "
    "ताकि customer को ज़्यादा wait न करना पड़े।"
)
EN_KN_PARAGRAPH = (
    "ನಮ್ಮ team ಪ್ರತಿ Monday weekly review ಮಾಡುತ್ತದೆ. ಈ meeting ನಲ್ಲಿ ಹಿಂದಿನ ವಾರದ orders, pending deliveries ಮತ್ತು "
    "customer feedback ಬಗ್ಗೆ ಚರ್ಚೆ ಆಗುತ್ತದೆ. ಯಾವುದಾದರೂ issue urgent ಆಗಿದ್ದರೆ, ಅದೇ ದಿನ ticket ಮಾಡಿ support ಗೆ assign ಮಾಡಲಾಗುತ್ತದೆ, "
    "ಇದರಿಂದ customer ಹೆಚ್ಚು ಸಮಯ wait ಮಾಡಬೇಕಾಗಿಲ್ಲ."
)

# (language, category, text, note)
SAMPLES = [
    # --- English only ------------------------------------------------------------------------------------------
    ("en", "short", "Thank you", ""),
    ("en", "short", "Order confirmed", ""),
    ("en", "short", "Please wait.", ""),
    ("en", "short", "Good morning", ""),
    ("en", "medium", "Your package has been shipped and should arrive within three working days.", ""),
    ("en", "medium", "The library will remain closed on Sunday for annual maintenance.", ""),
    ("en", "medium", "Please update your password before the end of this month.", ""),
    ("en", "medium", "The train to the city centre departs every fifteen minutes.", ""),
    ("en", "long", EN_PARAGRAPH, ""),
    ("en", "long",
     "Residents are requested to separate dry and wet waste before collection. Dry waste includes paper, plastic, "
     "glass and metal, while wet waste includes vegetable peels, food scraps and garden leaves. Collection vans visit "
     "each lane between seven and nine in the morning, and any missed pickup can be reported through the helpline.", ""),
    ("en", "long",
     "This release improves search speed, fixes a crash when exporting large reports, and adds support for dark mode. "
     "Users upgrading from an older version should back up their settings first. A full list of changes is available "
     "in the release notes, and known issues will be addressed in the next maintenance update.", ""),
    ("en", "repeated", " ".join(["data"] * 8), "one word repeated 8 times"),
    ("en", "repeated", "yes, yes, yes", ""),
    ("en", "repeated", "Please try again later. " * 10, "one sentence repeated 10 times"),
    ("en", "repeated", " ".join([EN_PARAGRAPH] * 10), "long paragraph repeated 10 times"),
    ("en", "punct_numerals", "Total: $1,250.50 (incl. 18% tax)", ""),
    ("en", "punct_numerals", "Date: 2025-08-15, Time: 10:30 IST", "ISO date"),
    ("en", "punct_numerals", "Version 3.14.159-rc.2 (build #4821)", ""),
    ("en", "punct_numerals", "Score: 98.6/100; rank 3 of 1,024.", ""),
    ("en", "structured", "order_id=ORD-2025-000123;status=shipped;qty=3", "fictional identifier"),
    ("en", "structured", '{"id": 1042, "city": "Bengaluru", "active": true}', "JSON-like record, fictional"),
    ("en", "structured", "INV/2025-26/00042,2025-08-15,1250.50,INR", "CSV-like row, fictional invoice number"),
    ("en", "structured", "3f2b9c1e-7a4d-4e8b-9c2a-5d6e7f8a9b0c", "UUID-shaped identifier, made up"),
    ("en", "structured", "support@example.com", "reserved example domain (RFC 2606), not a real mailbox"),
    ("en", "edge", "tab\tseparated\tvalues", "horizontal tabs"),
    ("en", "edge", "line one\nline two", "embedded LF"),
    ("en", "edge", "CRLF line\r\n", "trailing CR LF"),
    ("en", "edge", "  leading and trailing  ", "leading/trailing spaces"),
    ("en", "edge", "“Smart quotes” – en dash … ellipsis", "typographic punctuation"),
    ("en", "edge", "Great job \U0001F44D\U0001F3FD", "emoji with skin-tone modifier"),
    ("en", "edge", "no break space", "no-break spaces"),
    ("en", "tiny", "", "empty input"),
    ("en", "tiny", "a", "single letter"),
    ("en", "tiny", "7", "single digit"),
    ("en", "tiny", " ", "single space"),
    # --- English + Hindi (Devanagari) ---------------------------------------------------------------------------
    ("en-hi", "short", "OK, धन्यवाद", ""),
    ("en-hi", "short", "Payment done है", ""),
    ("en-hi", "short", "Meeting cancel हो गई", ""),
    ("en-hi", "medium", "कल की meeting में project का final update share करना है।", ""),
    ("en-hi", "medium", "मेरा order अभी तक deliver नहीं हुआ, please check करें।", ""),
    ("en-hi", "medium", "Office का Wi-Fi password बदल गया है।", ""),
    ("en-hi", "long", EN_HI_PARAGRAPH, ""),
    ("en-hi", "long",
     "इस app के नए version में search fast हो गई है और dark mode भी आ गया है। पुराने version से upgrade करने से पहले "
     "अपनी settings का backup ज़रूर लें। पूरी list release notes में दी गई है, और बाकी issues अगले update में ठीक होंगे।", ""),
    ("en-hi", "repeated", "OK हाँ OK हाँ OK हाँ", ""),
    ("en-hi", "repeated", "Please wait करें। " * 5, "one sentence repeated 5 times"),
    ("en-hi", "repeated", " ".join([EN_HI_PARAGRAPH] * 10), "long paragraph repeated 10 times"),
    ("en-hi", "punct_numerals", "Bill amount ₹2,499 है, due date 15/08/2025.", ""),
    ("en-hi", "punct_numerals", "Train 12627 platform 3 पर आएगी, ETA 10:45।", "fictional train number"),
    ("en-hi", "punct_numerals", "Discount 20% तक — offer सिर्फ़ आज।", ""),
    ("en-hi", "structured", "item=चाय;qty=2;price=40", ""),
    ("en-hi", "structured", '{"product": "किताब", "price": 350, "currency": "INR"}', "JSON-like record"),
    ("en-hi", "structured", "SKU-HI-0042,दूध 1L,2025-08-15", "CSV-like row, fictional SKU"),
    ("en-hi", "edge", "हाँ\tनहीं\tok", "horizontal tabs"),
    ("en-hi", "edge", "पहली line\nदूसरी line", "embedded LF"),
    ("en-hi", "edge", "Hello \U0001F44B नमस्ते", "emoji"),
    ("en-hi", "tiny", "", "empty input"),
    ("en-hi", "tiny", "OK", "English only (tiny values are exempt from the mixed-script rule)"),
    ("en-hi", "tiny", "है", "Hindi only (tiny values are exempt from the mixed-script rule)"),
    # --- English + Kannada --------------------------------------------------------------------------------------
    ("en-kn", "short", "OK, ಧನ್ಯವಾದ", ""),
    ("en-kn", "short", "Payment ಆಯ್ತು", ""),
    ("en-kn", "short", "Meeting cancel ಆಗಿದೆ", ""),
    ("en-kn", "medium", "ನಾಳೆ meeting ನಲ್ಲಿ project final update share ಮಾಡಬೇಕು.", ""),
    ("en-kn", "medium", "ನನ್ನ order ಇನ್ನೂ deliver ಆಗಿಲ್ಲ, please check ಮಾಡಿ.", ""),
    ("en-kn", "medium", "Office Wi-Fi password ಬದಲಾಗಿದೆ.", ""),
    ("en-kn", "long", EN_KN_PARAGRAPH, ""),
    ("en-kn", "long",
     "ಈ app ನ ಹೊಸ version ನಲ್ಲಿ search fast ಆಗಿದೆ ಮತ್ತು dark mode ಕೂಡ ಬಂದಿದೆ. ಹಳೆಯ version ನಿಂದ upgrade ಮಾಡುವ ಮೊದಲು "
     "ನಿಮ್ಮ settings ನ backup ತೆಗೆದುಕೊಳ್ಳಿ. ಪೂರ್ಣ list release notes ನಲ್ಲಿ ಇದೆ, ಮತ್ತು ಉಳಿದ issues ಮುಂದಿನ update ನಲ್ಲಿ ಸರಿಯಾಗುತ್ತವೆ.", ""),
    ("en-kn", "repeated", "OK ಸರಿ OK ಸರಿ OK ಸರಿ", ""),
    ("en-kn", "repeated", "Please wait ಮಾಡಿ. " * 5, "one sentence repeated 5 times"),
    ("en-kn", "repeated", " ".join([EN_KN_PARAGRAPH] * 10), "long paragraph repeated 10 times"),
    ("en-kn", "punct_numerals", "Bill amount ₹2,499, due date 15/08/2025 ಆಗಿದೆ.", ""),
    ("en-kn", "punct_numerals", "Bus 500D platform 3 ಗೆ ಬರುತ್ತದೆ, ETA 10:45.", "fictional bus route"),
    ("en-kn", "punct_numerals", "Discount 20% ವರೆಗೆ — offer ಇಂದು ಮಾತ್ರ.", ""),
    ("en-kn", "structured", "item=ಕಾಫಿ;qty=2;price=40", ""),
    ("en-kn", "structured", '{"product": "ಪುಸ್ತಕ", "price": 350, "currency": "INR"}', "JSON-like record"),
    ("en-kn", "structured", "SKU-KN-0042,ಹಾಲು 1L,2025-08-15", "CSV-like row, fictional SKU"),
    ("en-kn", "edge", "ಹೌದು\tಇಲ್ಲ\tok", "horizontal tabs"),
    ("en-kn", "edge", "ಮೊದಲ line\nಎರಡನೇ line", "embedded LF"),
    ("en-kn", "edge", "Hello \U0001F44B ನಮಸ್ಕಾರ", "emoji"),
    ("en-kn", "tiny", "", "empty input"),
    ("en-kn", "tiny", "OK", "English only (tiny values are exempt from the mixed-script rule)"),
    ("en-kn", "tiny", "ಹೌದು", "Kannada only (tiny values are exempt from the mixed-script rule)"),
]


def has_range(text, lo, hi):
    return any(lo <= ord(ch) <= hi for ch in text)


def check_labels(language, category, text, sample_id):
    deva, kann, latin = has_range(text, 0x0900, 0x097F), has_range(text, 0x0C80, 0x0CFF), any("A" <= ch <= "Z" or "a" <= ch <= "z" for ch in text)
    if language == "en" and (deva or kann):
        sys.exit(f"{sample_id}: English-only sample contains Indic script")
    if language == "en-hi" and (kann or (category != "tiny" and not (deva and latin))):
        sys.exit(f"{sample_id}: en-hi sample must mix Latin and Devanagari and contain no Kannada")
    if language == "en-kn" and (deva or (category != "tiny" and not (kann and latin))):
        sys.exit(f"{sample_id}: en-kn sample must mix Latin and Kannada and contain no Devanagari")
    if category not in CATEGORIES:
        sys.exit(f"{sample_id}: unknown category {category}")


def main():
    out_dir = pathlib.Path(__file__).resolve().parent
    counters, lines = {}, []
    for language, category, text, note in SAMPLES:
        key = (language, category)
        counters[key] = counters.get(key, 0) + 1
        sample_id = f"{language}-{category}-{counters[key]:03d}"
        check_labels(language, category, text, sample_id)
        data = text.encode("utf-8")
        lines.append(json.dumps({
            "sample_id": sample_id, "dataset_version": DATASET_VERSION, "language": language, "category": category,
            "utf8_bytes": len(data), "code_points": len(text), "utf8_hex": data.hex(), "text": text, "note": note,
            "provenance": PROVENANCE,
        }, ensure_ascii=False, sort_keys=True))
    ids = [json.loads(l)["sample_id"] for l in lines]
    assert len(ids) == len(set(ids)), "duplicate sample ids"
    content = ("\n".join(lines) + "\n").encode("utf-8")
    (out_dir / "en_mixed_v1.jsonl").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (out_dir / "en_mixed_v1.sha256").write_text(f"{digest}  en_mixed_v1.jsonl\n")
    print(f"wrote {len(lines)} samples, sha256 {digest}")


if __name__ == "__main__":
    main()
