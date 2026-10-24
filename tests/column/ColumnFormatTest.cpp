#include "catch2/catch_test_macros.hpp"
#include "column_format.hpp"
#include "tokenizer/TokenizerConfig.hpp"
#include <optional>
#include <string>
#include <vector>
//---------------------------------------------------------------------------
using namespace sgtt;
using namespace hashcode;
//---------------------------------------------------------------------------
namespace {
//---------------------------------------------------------------------------
struct Method {
   std::string name;
   column::Codec codec;
   std::optional<compressor::CompressorConfig> config;
};
//---------------------------------------------------------------------------
std::vector<Method> methods() {
   auto sgtt = [](const char* name, tokenizer::TokenizerType type) {
      tokenizer::TokenizerConfig tc{.tokenizer = type, .tokenIdEncoding = tokenizer::DenseIds};
      return Method{name, column::Codec::Sgtt, compressor::CompressorConfig{compressor::parseCompressor("sgtt"), std::nullopt, compressor::OnPairConfig{false, false}, tc}};
   };
   return {{"raw_utf8_column", column::Codec::Raw, std::nullopt}, sgtt("sgtt_openai200k_column", tokenizer::OpenAI200K), sgtt("sgtt_gemma3_column", tokenizer::Gemma3)};
}
//---------------------------------------------------------------------------
struct Case {
   std::string name;
   std::vector<std::string> values;
};
//---------------------------------------------------------------------------
std::string b(const char* data, size_t size) { return std::string(data, size); }
//---------------------------------------------------------------------------
std::vector<Case> cases() {
   const std::string kn = "ನಮಸ್ಕಾರ";
   const std::string hi = "नमस्ते";
   const std::string paragraph = std::string(
      "ಕರ್ನಾಟಕ ದಕ್ಷಿಣ ಭಾರತದ ಒಂದು ರಾಜ್ಯವಾಗಿದೆ. "
      "भारत एक विशाल देश है। ");
   std::string longParagraph;
   for (int i = 0; i < 40; ++i) longParagraph += paragraph;
   return {
      {"zero values", {}},
      {"one empty value", {""}},
      {"multiple empty values", {"", "", ""}},
      {"empty values between non-empty values", {kn, "", "", hi}},
      {"final value empty", {kn, hi, ""}},
      {"first value empty", {"", kn}},
      {"one-byte values", {"a", "7", "\n", " "}},
      {"short Kannada and Hindi", {kn, hi, "ಅ", "क"}},
      {"long paragraph", {longParagraph}},
      {"mixed Kannada, Hindi and English", {"Order #A1023 " + kn, "laptop " + hi + " slow", kn + " / " + hi}},
      {"embedded NUL bytes", {b("a\0b", 3), b("\0\0\0", 3), b("x\0", 2), kn}},
      {"value containing only NULs then text", {b("\0", 1), "tail"}},
      {"newlines inside values", {"line1\nline2", "\n\n", hi + "\n" + kn}},
      {"combining marks and zero-width characters", {"क्‍ष", "क्‌ष", "ಕೊ", "ಕೊ", "ि", "क़", "क़"}},
      {"repeated values", {kn, kn, kn, hi, hi, kn}},
      {"values that concatenate ambiguously", {"ab", "c", "a", "bc"}},
   };
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
TEST_CASE("HCC1 column container round trip", "[column]") {
   for (const auto& m : methods()) {
      for (const auto& c : cases()) {
         DYNAMIC_SECTION(m.name << ": " << c.name) {
            column::Layout layout;
            auto encoded = column::encodeColumn(m.codec, m.config, c.values, layout);
            auto decoded = column::decodeColumn(m.config, encoded);

            REQUIRE(decoded.size() == c.values.size());
            for (size_t i = 0; i < c.values.size(); ++i) {
               INFO("value index " << i);
               CHECK(decoded[i].size() == c.values[i].size());
               CHECK(decoded[i] == c.values[i]);
            }

            auto parsed = column::parse(encoded);
            CHECK(parsed.codec == m.codec);
            CHECK(parsed.lengths.size() == c.values.size());
            CHECK(layout.header == column::headerBytes);
            CHECK(layout.header + layout.boundary + layout.blob == encoded.size());
            CHECK(parsed.layout.boundary == layout.boundary);
            CHECK(parsed.layout.blob == layout.blob);

            size_t payload = 0;
            for (const auto& v : c.values) payload += v.size();
            if (payload == 0) CHECK(layout.blob == 0);
            if (m.codec == column::Codec::Raw) CHECK(layout.blob == payload);
            if (m.codec == column::Codec::Sgtt && payload > 0) CHECK(layout.blob >= column::sgttFooterBytes);
         }
      }
   }
}
//---------------------------------------------------------------------------
TEST_CASE("HCC1 rejects malformed containers", "[column]") {
   column::Layout layout;
   auto good = column::encodeColumn(column::Codec::Raw, std::nullopt, {"abc", ""}, layout);

   auto badMagic = good;
   badMagic[0] = std::byte{'X'};
   CHECK_THROWS(column::parse(badMagic));

   auto truncated = good;
   truncated.pop_back();
   CHECK_THROWS(column::parse(truncated));

   auto badVersion = good;
   badVersion[4] = std::byte{2};
   CHECK_THROWS(column::parse(badVersion));

   CHECK_THROWS(column::parse(std::span<const std::byte>(good.data(), 3)));
}
//---------------------------------------------------------------------------
