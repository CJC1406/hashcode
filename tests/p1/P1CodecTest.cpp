#include "catch2/catch_test_macros.hpp"
#include "column_format.hpp"
#include "p1_codec.hpp"
#include <fstream>
#include <string>
#include <vector>
//---------------------------------------------------------------------------
using namespace hashcode;
//---------------------------------------------------------------------------
namespace {
//---------------------------------------------------------------------------
const p1::Vocabulary& vocabulary() {
   static const p1::Vocabulary v(HASHCODE_P1_VOCABULARY);
   return v;
}
//---------------------------------------------------------------------------
std::span<const std::byte> bytes(const std::string& s) { return {reinterpret_cast<const std::byte*>(s.data()), s.size()}; }
//---------------------------------------------------------------------------
std::string roundTrip(const std::string& s, size_t& tokens, size_t& fallback) {
   auto blob = p1::encodeBlob(vocabulary(), bytes(s), tokens, fallback);
   REQUIRE(blob.size() == 2 * tokens + p1::footerBytes);
   auto out = p1::decodeBlob(vocabulary(), blob);
   return std::string(reinterpret_cast<const char*>(out.data()), out.size());
}
//---------------------------------------------------------------------------
std::vector<std::string> tokenStrings(const std::string& s) {
   size_t fallback = 0;
   std::vector<std::string> out;
   for (auto id : vocabulary().tokenize(bytes(s), fallback)) out.push_back(vocabulary().entry(id));
   return out;
}
//---------------------------------------------------------------------------
std::string b(const char* d, size_t n) { return std::string(d, n); }
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
TEST_CASE("P1 vocabulary loads and matches the frozen build", "[p1]") {
   const auto& v = vocabulary();
   CHECK(v.size() == 65536);
   for (unsigned i = 0; i < 256; ++i) CHECK(v.entry(static_cast<uint16_t>(i)) == std::string(1, static_cast<char>(i)));
   std::ifstream sha(HASHCODE_P1_VOCABULARY_SHA256);
   std::string hexDigest;
   sha >> hexDigest;
   REQUIRE(hexDigest.size() == 64);
   std::string idHex;
   static const char* digits = "0123456789abcdef";
   for (auto x : v.tableId()) {
      idHex.push_back(digits[x >> 4]);
      idHex.push_back(digits[x & 15]);
   }
   CHECK(idHex == hexDigest.substr(0, 16));
}
//---------------------------------------------------------------------------
TEST_CASE("P1 vocabulary entries are structural, not data-derived", "[p1]") {
   // Every multi-byte entry is pure ASCII, or 1-2 code points all inside one of U+0900-097F / U+0C80-0CFF.
   const auto& v = vocabulary();
   size_t ascii = 0, indic = 0;
   for (size_t i = 256; i < v.size(); ++i) {
      const auto& e = v.entry(static_cast<uint16_t>(i));
      bool allAscii = true;
      for (unsigned char c : e) allAscii &= c < 128;
      if (allAscii) {
         ++ascii;
         continue;
      }
      INFO("entry " << i);
      REQUIRE((e.size() == 3 || e.size() == 6));
      for (size_t k = 0; k < e.size(); k += 3) {
         const unsigned cp = ((e[k] & 0x0F) << 12) | ((e[k + 1] & 0x3F) << 6) | (e[k + 2] & 0x3F);
         CHECK(((cp >= 0x0900 && cp <= 0x097F) || (cp >= 0x0C80 && cp <= 0x0CFF)));
      }
      ++indic;
   }
   CHECK(ascii == 62784);
   CHECK(indic == 2496);
}
//---------------------------------------------------------------------------
TEST_CASE("P1 round trip is exact", "[p1]") {
   std::string all;
   for (int i = 0; i < 256; ++i) all.push_back(static_cast<char>(i));
   std::string longText;
   for (int i = 0; i < 300; ++i) longText += "ನಮಸ್ಕಾರ नमस्ते hello, world. ";
   const std::vector<std::pair<std::string, std::string>> cases = {
      {"empty", ""},
      {"ascii", "The quick brown fox jumps over the lazy dog."},
      {"hindi", "नमस्ते दुनिया।"},
      {"kannada", "ಕನ್ನಡ ನಾಡು"},
      {"mixed", "Order #A1023 का delivery status: ತಲುಪಿದೆ"},
      {"multibyte unicode (emoji, rupee, ZWJ)", "\U0001F469‍\U0001F4BB ₹350 क्‍ष"},
      {"embedded NUL", b("a\0\0\0b\0", 6)},
      {"line breaks", "line1\nline2\r\n\r\nन\n"},
      {"invalid UTF-8", "\xFF\xFE\xE0\xA4" "a\xC0\xAF\xED\xA0\x80"},
      {"decomposed and precomposed forms", "क़ क़ ಕೊ ಕೊ"},
      {"all 256 byte values", all},
      {"long", longText},
   };
   for (const auto& [name, s] : cases) {
      INFO(name);
      size_t tokens = 0, fallback = 0;
      CHECK(roundTrip(s, tokens, fallback) == s);
   }
}
//---------------------------------------------------------------------------
TEST_CASE("P1 token boundaries and fallback", "[p1]") {
   size_t tokens = 0, fallback = 0;
   // consonant + dependent vowel sign is one token; a conjunct splits after the virama.
   CHECK(tokenStrings("कि") == std::vector<std::string>{"कि"});
   CHECK(tokenStrings("क्ष") == std::vector<std::string>{"क्", "ष"});
   CHECK(tokenStrings("ನಮಸ್ಕಾರ") == std::vector<std::string>{"ನ", "ಮ", "ಸ್", "ಕಾ", "ರ"});
   // Bytes outside both blocks and outside ASCII entries fall back to one ID per byte.
   roundTrip("\U0001F600", tokens, fallback);
   CHECK(tokens == 4);
   CHECK(fallback == 4);
   roundTrip("नमस्ते", tokens, fallback);
   CHECK(fallback == 0);
   // Every prefix, including ones cut inside a multi-byte character, round-trips.
   const std::string mixed = "Meeting ನಾಳೆ 10 गे ₹\U0001F44D\n";
   for (size_t n = 0; n <= mixed.size(); ++n) {
      INFO("prefix length " << n);
      CHECK(roundTrip(mixed.substr(0, n), tokens, fallback) == mixed.substr(0, n));
   }
}
//---------------------------------------------------------------------------
TEST_CASE("P1 never reads past the input", "[p1]") {
   // Buffer holds KA + VOWEL SIGN I, but only KA is passed: the longer two-code-point entry must not be matched.
   const std::string buffer = "कि";
   size_t fallback = 0;
   auto ids = vocabulary().tokenize(std::span<const std::byte>(reinterpret_cast<const std::byte*>(buffer.data()), 3), fallback);
   REQUIRE(ids.size() == 1);
   CHECK(vocabulary().entry(ids[0]) == "क");
}
//---------------------------------------------------------------------------
TEST_CASE("P1 decoder rejects malformed blobs", "[p1]") {
   size_t tokens = 0, fallback = 0;
   auto good = p1::encodeBlob(vocabulary(), bytes("abc कि"), tokens, fallback);
   auto badMagic = good;
   badMagic[good.size() - p1::footerBytes] = std::byte{'X'};
   CHECK_THROWS(p1::decodeBlob(vocabulary(), badMagic));
   auto badVersion = good;
   badVersion[good.size() - p1::footerBytes + 4] = std::byte{9};
   CHECK_THROWS(p1::decodeBlob(vocabulary(), badVersion));
   auto otherTable = good;
   otherTable[good.size() - 1] ^= std::byte{1};
   CHECK_THROWS(p1::decodeBlob(vocabulary(), otherTable));
   auto odd = good;
   odd.insert(odd.begin(), std::byte{0});
   CHECK_THROWS(p1::decodeBlob(vocabulary(), odd));
   CHECK_THROWS(p1::decodeBlob(vocabulary(), std::span<const std::byte>(good.data(), 5)));
}
//---------------------------------------------------------------------------
TEST_CASE("P1 inside an HCC1 column keeps boundaries and empty values", "[p1][column]") {
   const std::vector<std::string> values = {"", "नमस्ते", "", b("x\0y", 3), "line\nbreak", "ಅ", ""};
   auto payload = column::concatenate(values);
   size_t tokens = 0, fallback = 0;
   auto blob = p1::encodeBlob(vocabulary(), payload.bytes(), tokens, fallback);
   column::Layout layout;
   auto container = column::serialize(column::Codec::P1, values, blob, layout);
   auto parsed = column::parse(container);
   REQUIRE(parsed.codec == column::Codec::P1);
   auto decoded = p1::decodeBlob(vocabulary(), parsed.blob);
   CHECK(column::split(decoded, parsed.lengths) == values);
   CHECK(layout.header + layout.boundary + layout.blob == container.size());
}
//---------------------------------------------------------------------------
