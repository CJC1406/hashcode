"""Builds the frozen Phase 1 Kannada/Hindi dataset (kn_hi_v1.jsonl) and its SHA-256.

Every record stores the authoritative bytes as `utf8_hex`; `text` is the same string for readability.
No Unicode normalization is applied anywhere. Run: python3 -I datasets/phase1/build_dataset.py
"""
import hashlib
import json
import pathlib

DATASET_VERSION = "phase1-kn-hi-v1"
PROVENANCE = "authored for this project (Token Tables for Bharat), 2026-10-24; original text, not copied from any source"

HI_PARAGRAPH = (
    "भारत एक विशाल देश है जहाँ अनेक भाषाएँ बोली जाती हैं। हर राज्य की अपनी संस्कृति, खान-पान और त्योहार हैं। "
    "गाँवों में आज भी लोग खेती पर निर्भर हैं, जबकि शहरों में उद्योग और सेवाएँ तेज़ी से बढ़ रही हैं। "
    "शिक्षा और तकनीक के प्रसार से नई पीढ़ी के सामने अवसरों के नए द्वार खुल रहे हैं।"
)
KN_PARAGRAPH = (
    "ಕರ್ನಾಟಕ ದಕ್ಷಿಣ ಭಾರತದ ಒಂದು ರಾಜ್ಯವಾಗಿದ್ದು, ಇಲ್ಲಿ ಕನ್ನಡ ಮುಖ್ಯ ಭಾಷೆಯಾಗಿದೆ. "
    "ರಾಜ್ಯದಲ್ಲಿ ಕರಾವಳಿ, ಮಲೆನಾಡು ಮತ್ತು ಬಯಲುಸೀಮೆ ಎಂಬ ವಿಭಿನ್ನ ಪ್ರದೇಶಗಳಿವೆ. "
    "ಹಳ್ಳಿಗಳಲ್ಲಿ ಜನರು ಇಂದಿಗೂ ಕೃಷಿಯನ್ನು ಅವಲಂಬಿಸಿದ್ದಾರೆ, ಆದರೆ ನಗರಗಳಲ್ಲಿ ಉದ್ಯಮ ಮತ್ತು ಸೇವಾ ಕ್ಷೇತ್ರಗಳು ವೇಗವಾಗಿ ಬೆಳೆಯುತ್ತಿವೆ. "
    "ಶಿಕ್ಷಣ ಮತ್ತು ತಂತ್ರಜ್ಞಾನದ ಹರಡುವಿಕೆಯಿಂದ ಹೊಸ ತಲೆಮಾರಿಗೆ ಹೊಸ ಅವಕಾಶಗಳು ತೆರೆದುಕೊಳ್ಳುತ್ತಿವೆ."
)

# (language, category, text, note)
SAMPLES = [
    # --- Hindi -------------------------------------------------------------------------------------------------
    ("hi", "short", "नमस्ते", ""),
    ("hi", "short", "धन्यवाद", ""),
    ("hi", "short", "आप कैसे हैं?", ""),
    ("hi", "short", "शुभ प्रभात", ""),
    ("hi", "short", "कृपया बैठिए", ""),
    ("hi", "medium", "आज मौसम बहुत सुहावना है और हल्की बारिश हो रही है।", ""),
    ("hi", "medium", "मैं हर सुबह पार्क में टहलने जाता हूँ।", ""),
    ("hi", "medium", "इस पुस्तकालय में बच्चों के लिए कई नई किताबें आई हैं।", ""),
    ("hi", "medium", "रेलगाड़ी समय पर स्टेशन पहुँच गई।", ""),
    ("hi", "long", HI_PARAGRAPH, ""),
    ("hi", "long",
     "हमारे मोहल्ले में एक छोटी सी दुकान है जहाँ दूध, सब्ज़ियाँ और रोज़मर्रा का सामान मिलता है। "
     "दुकानदार सुबह छह बजे दुकान खोलता है और रात नौ बजे बंद करता है। "
     "त्योहारों के दिनों में वहाँ बहुत भीड़ रहती है, इसलिए लोग पहले से ही अपनी सूची बनाकर जाते हैं।", ""),
    ("hi", "repeated", " ".join(["पानी"] * 8), "one word repeated 8 times"),
    ("hi", "repeated", "जल्दी आओ, जल्दी आओ, जल्दी आओ।", ""),
    ("hi", "repeated", "सड़क पर सावधानी से चलें। " * 10, "one sentence repeated 10 times"),
    ("hi", "repeated", " ".join([HI_PARAGRAPH] * 10), "long paragraph repeated 10 times"),
    ("hi", "punct_numerals", "कुल राशि: ₹1,250.50 (एक हज़ार दो सौ पचास रुपये पचास पैसे)।", ""),
    ("hi", "punct_numerals", "दिनांक: १५/०८/२०२५, समय: १०:३० बजे", "Devanagari digits"),
    ("hi", "punct_numerals", "क्रमांक 42-अ; पिन कोड 110001।", "generic postal code, not an address"),
    ("hi", "mixed", "मेरा laptop बहुत slow चल रहा है, कृपया check करें।", ""),
    ("hi", "mixed", "Meeting कल सुबह 10 बजे Zoom पर होगी।", ""),
    ("hi", "mixed", "Order #A1023 का delivery status: पहुँच गया", "fictional order number"),
    ("hi", "edge", "ज़रूरी", "nukta precomposed (U+095B)"),
    ("hi", "edge", "ज़रूरी", "nukta decomposed (U+091C U+093C); canonically equivalent to previous, different bytes"),
    ("hi", "edge", "क्‍ष", "virama + ZWJ"),
    ("hi", "edge", "क्‌ष", "virama + ZWNJ"),
    ("hi", "edge", "हँसी दुःख", "candrabindu and visarga"),
    ("hi", "edge", "ि", "isolated dependent vowel sign (valid UTF-8, defective cluster)"),
    ("hi", "edge", "नमस्ते जी", "no-break space"),
    ("hi", "tiny", "", "empty input"),
    ("hi", "tiny", "क", "single consonant"),
    ("hi", "tiny", "अ", "single vowel"),
    ("hi", "tiny", "।", "danda only"),
    # --- Kannada -----------------------------------------------------------------------------------------------
    ("kn", "short", "ನಮಸ್ಕಾರ", ""),
    ("kn", "short", "ಧನ್ಯವಾದಗಳು", ""),
    ("kn", "short", "ಹೇಗಿದ್ದೀರಾ?", ""),
    ("kn", "short", "ಶುಭೋದಯ", ""),
    ("kn", "short", "ದಯವಿಟ್ಟು ಕುಳಿತುಕೊಳ್ಳಿ", ""),
    ("kn", "medium", "ಇಂದು ಹವಾಮಾನ ತುಂಬಾ ಚೆನ್ನಾಗಿದೆ ಮತ್ತು ಸ್ವಲ್ಪ ಮಳೆ ಬರುತ್ತಿದೆ.", ""),
    ("kn", "medium", "ನಾನು ಪ್ರತಿದಿನ ಬೆಳಿಗ್ಗೆ ಉದ್ಯಾನವನದಲ್ಲಿ ನಡೆಯಲು ಹೋಗುತ್ತೇನೆ.", ""),
    ("kn", "medium", "ಈ ಗ್ರಂಥಾಲಯದಲ್ಲಿ ಮಕ್ಕಳಿಗಾಗಿ ಹಲವು ಹೊಸ ಪುಸ್ತಕಗಳು ಬಂದಿವೆ.", ""),
    ("kn", "medium", "ರೈಲು ಸಮಯಕ್ಕೆ ಸರಿಯಾಗಿ ನಿಲ್ದಾಣವನ್ನು ತಲುಪಿತು.", ""),
    ("kn", "long", KN_PARAGRAPH, ""),
    ("kn", "long",
     "ನಮ್ಮ ಬಡಾವಣೆಯಲ್ಲಿ ಒಂದು ಸಣ್ಣ ಅಂಗಡಿ ಇದೆ, ಅಲ್ಲಿ ಹಾಲು, ತರಕಾರಿ ಮತ್ತು ದಿನನಿತ್ಯದ ವಸ್ತುಗಳು ಸಿಗುತ್ತವೆ. "
     "ಅಂಗಡಿಯವರು ಬೆಳಿಗ್ಗೆ ಆರು ಗಂಟೆಗೆ ಅಂಗಡಿ ತೆರೆಯುತ್ತಾರೆ ಮತ್ತು ರಾತ್ರಿ ಒಂಬತ್ತು ಗಂಟೆಗೆ ಮುಚ್ಚುತ್ತಾರೆ. "
     "ಹಬ್ಬದ ದಿನಗಳಲ್ಲಿ ಅಲ್ಲಿ ತುಂಬಾ ಜನಸಂದಣಿ ಇರುತ್ತದೆ, ಆದ್ದರಿಂದ ಜನರು ಮೊದಲೇ ಪಟ್ಟಿ ಮಾಡಿಕೊಂಡು ಹೋಗುತ್ತಾರೆ.", ""),
    ("kn", "repeated", " ".join(["ನೀರು"] * 8), "one word repeated 8 times"),
    ("kn", "repeated", "ಬೇಗ ಬನ್ನಿ, ಬೇಗ ಬನ್ನಿ, ಬೇಗ ಬನ್ನಿ.", ""),
    ("kn", "repeated", "ರಸ್ತೆಯಲ್ಲಿ ಎಚ್ಚರಿಕೆಯಿಂದ ನಡೆಯಿರಿ. " * 10, "one sentence repeated 10 times"),
    ("kn", "repeated", " ".join([KN_PARAGRAPH] * 10), "long paragraph repeated 10 times"),
    ("kn", "punct_numerals", "ಒಟ್ಟು ಮೊತ್ತ: ₹1,250.50 (ಒಂದು ಸಾವಿರದ ಇನ್ನೂರ ಐವತ್ತು ರೂಪಾಯಿ ಐವತ್ತು ಪೈಸೆ).", ""),
    ("kn", "punct_numerals", "ದಿನಾಂಕ: ೧೫/೦೮/೨೦೨೫, ಸಮಯ: ೧೦:೩೦", "Kannada digits"),
    ("kn", "punct_numerals", "ಕ್ರಮ ಸಂಖ್ಯೆ 42-ಅ; ಪಿನ್ ಕೋಡ್ 560001.", "generic postal code, not an address"),
    ("kn", "mixed", "ನನ್ನ laptop ತುಂಬಾ slow ಆಗಿದೆ, ದಯವಿಟ್ಟು check ಮಾಡಿ.", ""),
    ("kn", "mixed", "Meeting ನಾಳೆ ಬೆಳಿಗ್ಗೆ 10 ಗಂಟೆಗೆ Zoom ನಲ್ಲಿ ಇರುತ್ತದೆ.", ""),
    ("kn", "mixed", "Order #A1023 ರ delivery status: ತಲುಪಿದೆ", "fictional order number"),
    ("kn", "edge", "ಕೊ", "two-part vowel sign O precomposed (U+0CCA)"),
    ("kn", "edge", "ಕೊ", "two-part vowel sign O decomposed (U+0CC6 U+0CC2); canonically equivalent to previous, different bytes"),
    ("kn", "edge", "ಕ್ಷ", "conjunct KSSA via virama"),
    ("kn", "edge", "ರ್‍ಕ", "virama + ZWJ"),
    ("kn", "edge", "ಕ್‌ಷ", "virama + ZWNJ"),
    ("kn", "edge", "ಜ಼", "nukta (U+0CBC)"),
    ("kn", "edge", "ಿ", "isolated dependent vowel sign (valid UTF-8, defective cluster)"),
    ("kn", "edge", "ನಮಸ್ಕಾರ ಸರ್", "no-break space"),
    ("kn", "tiny", "", "empty input"),
    ("kn", "tiny", "ಕ", "single consonant"),
    ("kn", "tiny", "ಅ", "single vowel"),
    ("kn", "tiny", "ಃ", "visarga only (combining mark)"),
]


def main():
    out_dir = pathlib.Path(__file__).resolve().parent
    counters = {}
    lines = []
    for language, category, text, note in SAMPLES:
        key = (language, category)
        counters[key] = counters.get(key, 0) + 1
        sample_id = f"{language}-{category}-{counters[key]:03d}"
        data = text.encode("utf-8")
        record = {
            "sample_id": sample_id,
            "dataset_version": DATASET_VERSION,
            "language": language,
            "category": category,
            "utf8_bytes": len(data),
            "code_points": len(text),
            "utf8_hex": data.hex(),
            "text": text,
            "note": note,
            "provenance": PROVENANCE,
        }
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    ids = [json.loads(l)["sample_id"] for l in lines]
    assert len(ids) == len(set(ids)), "duplicate sample ids"
    content = ("\n".join(lines) + "\n").encode("utf-8")
    (out_dir / "kn_hi_v1.jsonl").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (out_dir / "kn_hi_v1.sha256").write_text(f"{digest}  kn_hi_v1.jsonl\n")
    print(f"wrote {len(lines)} samples, sha256 {digest}")


if __name__ == "__main__":
    main()
