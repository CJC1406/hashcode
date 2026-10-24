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
const p1::Vocabulary& p2a() {
   static const p1::Vocabulary v(HASHCODE_P2A_VOCABULARY);
   return v;
}
//---------------------------------------------------------------------------
const p1::Vocabulary& p1v() {
   static const p1::Vocabulary v(HASHCODE_P1_VOCABULARY);
   return v;
}
//---------------------------------------------------------------------------
std::span<const std::byte> bytes(const std::string& s) { return {reinterpret_cast<const std::byte*>(s.data()), s.size()}; }
//---------------------------------------------------------------------------
std::string roundTrip(const p1::Vocabulary& v, const std::string& s, size_t& tokens, size_t& fallback) {
   auto blob = p1::encodeBlob(v, bytes(s), tokens, fallback);
   REQUIRE(blob.size() == 2 * tokens + p1::footerBytes);
   auto out = p1::decodeBlob(v, blob);
   return std::string(reinterpret_cast<const char*>(out.data()), out.size());
}
//---------------------------------------------------------------------------
std::vector<std::string> tokenStrings(const std::string& s) {
   size_t fallback = 0;
   std::vector<std::string> out;
   for (auto id : p2a().tokenize(bytes(s), fallback)) out.push_back(p2a().entry(id));
   return out;
}
//---------------------------------------------------------------------------
std::string hexId(const p1::Vocabulary& v) {
   static const char* digits = "0123456789abcdef";
   std::string s;
   for (auto x : v.tableId()) {
      s.push_back(digits[x >> 4]);
      s.push_back(digits[x & 15]);
   }
   return s;
}
//---------------------------------------------------------------------------
std::string b(const char* d, size_t n) { return std::string(d, n); }
//---------------------------------------------------------------------------
constexpr uint16_t aksharaBegin = 256, spacedBegin = 2752, asciiBegin = 5248;
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
TEST_CASE("P2a vocabulary is frozen P1 plus space+akshara entries only", "[p2a]") {
   const auto& v = p2a();
   const auto& p = p1v();
   REQUIRE(v.size() == 65536);
   std::ifstream sha(HASHCODE_P2A_VOCABULARY_SHA256);
   std::string digest;
   sha >> digest;
   CHECK(hexId(v) == digest.substr(0, 16));
   CHECK(hexId(v) != hexId(p));
   // Single bytes and akshara entries are P1's, ID for ID.
   for (uint32_t i = 0; i < spacedBegin; ++i) CHECK(v.entry(static_cast<uint16_t>(i)) == p.entry(static_cast<uint16_t>(i)));
   // Each new entry is a space followed by the akshara entry at the same offset.
   for (uint32_t i = 0; i < spacedBegin - aksharaBegin; ++i)
      CHECK(v.entry(static_cast<uint16_t>(spacedBegin + i)) == " " + p.entry(static_cast<uint16_t>(aksharaBegin + i)));
   // ASCII entries are P1's ASCII entries in the same order, truncated.
   for (uint32_t i = 0; i < 65536 - asciiBegin; ++i) CHECK(v.entry(static_cast<uint16_t>(asciiBegin + i)) == p.entry(static_cast<uint16_t>(spacedBegin + i)));
}
//---------------------------------------------------------------------------
TEST_CASE("P2a round trip is exact", "[p2a]") {
   std::string all;
   for (int i = 0; i < 256; ++i) all.push_back(static_cast<char>(i));
   std::string longText;
   for (int i = 0; i < 200; ++i) longText += "ನಮಸ್ಕಾರ नमस्ते hello,\tworld.\r\n";
   const std::vector<std::pair<std::string, std::string>> cases = {
      {"empty", ""},
      {"ascii", "The quick brown fox jumps over the lazy dog."},
      {"hindi", "आज मौसम बहुत सुहावना है।"},
      {"kannada", "ಇಂದು ಹವಾಮಾನ ತುಂಬಾ"},
      {"mixed", "Meeting नाळे 10 गे Zoom ನಲ್ಲಿ"},
      {"multibyte", "\U0001F469‍\U0001F4BB ₹350 क्‌ष"},
      {"NUL", b("\0 \0\0a\0", 6)},
      {"LF CR tab", "a\nb\rc\td\r\n न\n"},
      {"leading, trailing and repeated spaces", "   न  न "},
      {"invalid UTF-8 and lone space before continuation bytes", " \xA4\xFF \xE0\xA4"},
      {"all 256 byte values", all},
      {"long", longText},
   };
   for (const auto& [name, s] : cases) {
      INFO(name);
      size_t tokens = 0, fallback = 0;
      CHECK(roundTrip(p2a(), s, tokens, fallback) == s);
   }
}
//---------------------------------------------------------------------------
TEST_CASE("P2a longest match uses space+akshara entries", "[p2a]") {
   // " कि" is one token; "नमस्ते दुनिया" keeps the space with the next akshara.
   CHECK(tokenStrings(" कि") == std::vector<std::string>{" कि"});
   CHECK(tokenStrings("नमस्ते दुनिया") ==
         std::vector<std::string>{"न", "म", "स्", "ते", " दु", "नि", "या"});
   // ASCII words with a leading space still prefer the longest ASCII entry.
   CHECK(tokenStrings(" the")[0] == " the");
   // Greedy, not optimal: at position 0 the longest entry is the two-space ASCII entry "  ", which consumes both
   // spaces, so KA is left without a space (an optimal split would be " " + " KA"). Known limitation of greedy matching.
   CHECK(tokenStrings("  क") == std::vector<std::string>{"  ", "क"});
   size_t tokens = 0, fallback = 0;
   // A space followed by a non-Indic, non-entry byte is still a single-byte fallback.
   roundTrip(p2a(), " \U0001F600", tokens, fallback);
   CHECK(fallback == 5);
   // Fallback on spaces disappears for space-separated Indic words.
   roundTrip(p2a(), "नमस्ते दुनिया ಕನ್ನಡ", tokens, fallback);
   CHECK(fallback == 0);
   roundTrip(p1v(), "नमस्ते दुनिया ಕನ್ನಡ", tokens, fallback);
   CHECK(fallback == 2);
}
//---------------------------------------------------------------------------
TEST_CASE("P2a every prefix cut round-trips and never reads past the input", "[p2a]") {
   const std::string s = "Order #42 का ₹ ನಾಳೆ \U0001F44D\n";
   size_t tokens = 0, fallback = 0;
   for (size_t n = 0; n <= s.size(); ++n) {
      INFO("prefix " << n);
      CHECK(roundTrip(p2a(), s.substr(0, n), tokens, fallback) == s.substr(0, n));
   }
   // Buffer holds " कि" but only " क" is passed: the 7-byte entry must not be matched.
   const std::string buffer = " कि";
   auto ids = p2a().tokenize(std::span<const std::byte>(reinterpret_cast<const std::byte*>(buffer.data()), 4), fallback);
   REQUIRE(ids.size() == 1);
   CHECK(p2a().entry(ids[0]) == " क");
}
//---------------------------------------------------------------------------
TEST_CASE("P2a blobs carry their own table ID and are rejected by P1", "[p2a]") {
   size_t tokens = 0, fallback = 0;
   auto blob = p1::encodeBlob(p2a(), bytes("abc कि"), tokens, fallback);
   CHECK(blob.size() == 2 * tokens + p1::footerBytes);
   for (size_t i = 0; i + p1::footerBytes < blob.size(); i += 2) {
      const uint16_t id = static_cast<uint8_t>(blob[i]) | (static_cast<uint8_t>(blob[i + 1]) << 8);
      CHECK(id < p2a().size());
   }
   CHECK_NOTHROW(p1::decodeBlob(p2a(), blob));
   CHECK_THROWS(p1::decodeBlob(p1v(), blob));
}
//---------------------------------------------------------------------------
TEST_CASE("P2a inside HCC1 keeps boundaries; reported sizes equal serialized sizes", "[p2a][column]") {
   const std::vector<std::string> values = {"", " नमस्ते", "", b("x\0 y", 4), "line\n ನ", " ", ""};
   auto payload = column::concatenate(values);
   size_t tokens = 0, fallback = 0;
   auto blob = p1::encodeBlob(p2a(), payload.bytes(), tokens, fallback);
   column::Layout layout;
   auto container = column::serialize(column::Codec::P1, values, blob, layout);
   CHECK(layout.header + layout.boundary + 2 * tokens + p1::footerBytes == container.size());
   auto parsed = column::parse(container);
   CHECK(column::split(p1::decodeBlob(p2a(), parsed.blob), parsed.lengths) == values);
}
//---------------------------------------------------------------------------
