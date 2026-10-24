// Phase 1 column-mode harness: raw UTF-8 vs upstream sgtt (OpenAI200K, Gemma3) inside the HCC1 column container.
// Input TSV:  "C<TAB>column_id<TAB>value_count" followed by value_count lines "V<TAB>sample_id<TAB>utf8_hex".
// Outputs: column measurements CSV, containers TSV (encoded column hex), decoded-values TSV (per value).
// Usage: phase1_column_harness <columns.tsv> <measurements.csv> <containers.tsv> <decoded_values.tsv> <repetitions>
#include "column_format.hpp"
#include "p1_codec.hpp"
#include "p2b_codec.hpp"
#include "tokenizer/TokenizerConfig.hpp"
#include <memory>
#include <set>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
//---------------------------------------------------------------------------
using namespace sgtt;
using namespace hashcode;
using Clock = std::chrono::steady_clock;
//---------------------------------------------------------------------------
namespace {
//---------------------------------------------------------------------------
struct Method {
   std::string name, configuration;
   column::Codec codec;
   std::optional<compressor::CompressorConfig> config;
   const char* vocabulary = nullptr;  // P1-format vocabulary file for Codec::P1 methods
};
//---------------------------------------------------------------------------
std::vector<Method> methods() {
   auto sgtt = [](const char* name, tokenizer::TokenizerType type) {
      tokenizer::TokenizerConfig tc{.tokenizer = type, .tokenIdEncoding = tokenizer::DenseIds};
      std::string configuration = "container=HCC1v1 compressor=sgtt tokenizer=" + tokenizer::toString(type) +
         " token_id_encoding=dense max_token_size=default(16) token_compression=identity hash_map=default simd=scalar";
      return Method{name, configuration, column::Codec::Sgtt, compressor::CompressorConfig{compressor::parseCompressor("sgtt"), std::nullopt, compressor::OnPairConfig{false, false}, tc}};
   };
   std::vector<Method> list = {
      {"raw_utf8_column", "container=HCC1v1 codec=raw (concatenated value bytes)", column::Codec::Raw, std::nullopt},
      sgtt("sgtt_openai200k_column", tokenizer::OpenAI200K),
      sgtt("sgtt_gemma3_column", tokenizer::Gemma3),
      {"p1_akshara_column", "container=HCC1v1 codec=p1 vocabulary=codec/p1/p1_vocabulary_v1.bin token_ids=u16 footer=BTT1v1+table_id(13B)", column::Codec::P1, std::nullopt, HASHCODE_P1_VOCABULARY},
      {"p2a_space_akshara_column", "container=HCC1v1 codec=p1 vocabulary=codec/p2a/p2a_vocabulary_v1.bin token_ids=u16 footer=BTT1v1+table_id(13B)", column::Codec::P1, std::nullopt, HASHCODE_P2A_VOCABULARY},
      {"p2b_column_id_width", "container=HCC1v1 codec=p2b vocabulary=codec/p2a/p2a_vocabulary_v1.bin token_ids=u8_local_with_sorted_u16_map|u16_global footer=BTT2v1+table_id(13B)", column::Codec::P2b, std::nullopt, HASHCODE_P2A_VOCABULARY},
   };
   // P2c (optional): the unchanged P2b codec with a P2c-layout vocabulary given at run time. Without the variable the method
   // list, and so every output, is exactly as before. The runner records the vocabulary's path and SHA-256.
   static const std::string p2cVocabulary = [] {
      const char* p = std::getenv("HASHCODE_P2C_VOCABULARY");
      return std::string(p ? p : "");
   }();
   if (!p2cVocabulary.empty())
      list.push_back({"p2c_learned_column", "container=HCC1v1 codec=p2b vocabulary=$HASHCODE_P2C_VOCABULARY token_ids=u8_local_with_sorted_u16_map|u16_global footer=BTT2v1+table_id(13B)",
                      column::Codec::P2b, std::nullopt, p2cVocabulary.c_str()});
   return list;
}
//---------------------------------------------------------------------------
uint64_t fnvUpdate(uint64_t h, const void* data, size_t size) {
   auto* p = static_cast<const uint8_t*>(data);
   for (size_t i = 0; i < size; ++i) {
      h ^= p[i];
      h *= 0x100000001b3ull;
   }
   return h;
}
//---------------------------------------------------------------------------
/// Fingerprint of an ordered value sequence: FNV-1a over (u64 little-endian length, bytes) per value, so order, boundaries and empties all count.
uint64_t sequenceFingerprint(const std::vector<std::string>& values) {
   uint64_t h = 0xcbf29ce484222325ull;
   for (const auto& v : values) {
      uint64_t len = v.size();
      uint8_t le[8];
      for (int i = 0; i < 8; ++i) le[i] = static_cast<uint8_t>(len >> (8 * i));
      h = fnvUpdate(h, le, 8);
      h = fnvUpdate(h, v.data(), v.size());
   }
   return h;
}
//---------------------------------------------------------------------------
std::string hex(const void* data, size_t size) {
   static const char* digits = "0123456789abcdef";
   auto* p = static_cast<const uint8_t*>(data);
   std::string s;
   s.reserve(2 * size);
   for (size_t i = 0; i < size; ++i) {
      s.push_back(digits[p[i] >> 4]);
      s.push_back(digits[p[i] & 15]);
   }
   return s;
}
//---------------------------------------------------------------------------
std::string unhex(const std::string& s) {
   if (s.size() % 2) throw std::runtime_error("odd-length hex");
   std::string out(s.size() / 2, '\0');
   for (size_t i = 0; i < out.size(); ++i) out[i] = static_cast<char>(std::stoul(s.substr(2 * i, 2), nullptr, 16));
   return out;
}
//---------------------------------------------------------------------------
std::optional<uint64_t> infoField(const std::string& info, const std::string& key) {
   auto pos = info.find(key + ": ");
   if (pos == std::string::npos) return std::nullopt;
   return std::stoull(info.substr(pos + key.size() + 2));
}
//---------------------------------------------------------------------------
double ms(Clock::duration d) { return std::chrono::duration<double, std::milli>(d).count(); }
//---------------------------------------------------------------------------
std::string median(std::vector<double> v) {
   if (v.empty()) return "";
   std::sort(v.begin(), v.end());
   double m = v.size() % 2 ? v[v.size() / 2] : (v[v.size() / 2 - 1] + v[v.size() / 2]) / 2;
   char buffer[64];
   std::snprintf(buffer, sizeof(buffer), "%.6f", m);
   return buffer;
}
//---------------------------------------------------------------------------
std::string quote(const std::string& s) {
   std::string out = "\"";
   for (char c : s) out += (c == '"') ? std::string("\"\"") : std::string(1, c);
   return out + "\"";
}
//---------------------------------------------------------------------------
struct Column {
   std::string id;
   std::vector<std::string> sampleIds, values;
};
//---------------------------------------------------------------------------
std::vector<Column> readColumns(const char* path) {
   std::ifstream in(path);
   if (!in) throw std::runtime_error("cannot open column input");
   std::vector<Column> columns;
   std::string line;
   size_t expected = 0;
   while (std::getline(in, line)) {
      std::vector<std::string> f;
      size_t start = 0;
      for (size_t tab; (tab = line.find('\t', start)) != std::string::npos; start = tab + 1) f.push_back(line.substr(start, tab - start));
      f.push_back(line.substr(start));
      if (f.size() == 3 && f[0] == "C") {
         if (!columns.empty() && columns.back().values.size() != expected) throw std::runtime_error("value count mismatch in " + columns.back().id);
         columns.push_back({f[1], {}, {}});
         expected = std::stoull(f[2]);
      } else if (f.size() == 3 && f[0] == "V" && !columns.empty()) {
         columns.back().sampleIds.push_back(f[1]);
         columns.back().values.push_back(unhex(f[2]));
      } else {
         throw std::runtime_error("malformed column input line");
      }
   }
   if (!columns.empty() && columns.back().values.size() != expected) throw std::runtime_error("value count mismatch in " + columns.back().id);
   return columns;
}
//---------------------------------------------------------------------------
struct Result {
   std::string status = "ok", error;
   uint64_t inputFingerprint = 0;
   size_t originalPayload = 0;
   std::optional<uint64_t> tokens, tokenIdBytes, usedTokens, fallbackTokens, mappingBytes;
   size_t header = 0, boundary = 0, blob = 0, encodedPayload = 0, bitmap = 0, footer = 0, total = 0;
   uint64_t containerHash = 0, decodedFingerprint = 0;
   bool consistent = true, exact = false;
   size_t decodedCount = 0, exactValues = 0;
   std::vector<double> codecInit, encode, decoderInit, decode;
   std::vector<std::byte> container;
   std::vector<std::string> decoded;
};
//---------------------------------------------------------------------------
void measure(const Method& m, const Column& c, unsigned repetitions, Result& r) {
   r.inputFingerprint = sequenceFingerprint(c.values);
   for (unsigned rep = 0; rep < repetitions; ++rep) {
      // Encode: codec init | concatenate + codec + container serialization.
      auto t0 = Clock::now();
      std::unique_ptr<compressor::Compressor> encoder;
      std::unique_ptr<p1::Vocabulary> encoderVocabulary;
      if (m.codec == column::Codec::Sgtt) encoder = compressor::Compressor::create(*m.config);
      if (m.codec == column::Codec::P1 || m.codec == column::Codec::P2b) encoderVocabulary = std::make_unique<p1::Vocabulary>(m.vocabulary);
      auto t1 = Clock::now();
      auto payload = column::concatenate(c.values);
      std::vector<std::byte> blob;
      size_t p1Tokens = 0, p1Fallback = 0;
      p2b::Stats p2bStats;
      if (payload.size > 0) {
         if (m.codec == column::Codec::Raw) {
            blob.assign(payload.buffer.begin(), payload.buffer.begin() + payload.size);
         } else if (m.codec == column::Codec::P1) {
            blob = p1::encodeBlob(*encoderVocabulary, payload.bytes(), p1Tokens, p1Fallback);
         } else if (m.codec == column::Codec::P2b) {
            blob = p2b::encodeBlob(*encoderVocabulary, payload.bytes(), p2bStats);
         } else {
            blob.resize(10 * payload.size + 64);
            encoder->compress(payload.bytes(), blob);
         }
      }
      column::Layout layout;
      auto container = column::serialize(m.codec, c.values, blob, layout);
      auto t2 = Clock::now();
      std::string info = (encoder && payload.size > 0) ? encoder->getInfo() : "";

      // Decode: parse + decoder init | codec decode + split.
      auto t3 = Clock::now();
      auto parsed = column::parse(container);
      std::vector<std::byte> owned(parsed.blob.begin(), parsed.blob.end());
      std::unique_ptr<compressor::Compressor> decoder;
      std::unique_ptr<p1::Vocabulary> decoderVocabulary;
      std::vector<std::byte> decodedPayload;
      if (m.codec == column::Codec::Sgtt && !owned.empty()) {
         decoder = compressor::Compressor::create(*m.config, owned);
         decodedPayload.resize(2 * decoder->getUncompressedSize(owned));
      }
      if ((m.codec == column::Codec::P1 || m.codec == column::Codec::P2b) && !owned.empty()) decoderVocabulary = std::make_unique<p1::Vocabulary>(m.vocabulary);
      auto t4 = Clock::now();
      if (decoder) {
         std::vector<std::vector<std::byte>> temporaryBuffers;
         decoder->decompress(owned, decodedPayload, temporaryBuffers);
      } else if (decoderVocabulary && m.codec == column::Codec::P2b) {
         decodedPayload = p2b::decodeBlob(*decoderVocabulary, owned);
      } else if (decoderVocabulary) {
         decodedPayload = p1::decodeBlob(*decoderVocabulary, owned);
      } else if (m.codec == column::Codec::Raw) {
         decodedPayload = owned;
      }
      auto values = column::split(decodedPayload, parsed.lengths);
      auto t5 = Clock::now();

      if (m.codec == column::Codec::Sgtt || m.codec == column::Codec::P1 || m.codec == column::Codec::P2b) {
         r.codecInit.push_back(ms(t1 - t0));
         r.decoderInit.push_back(ms(t4 - t3));
      }
      r.encode.push_back(ms(t2 - t1));
      r.decode.push_back(ms(t5 - t4));

      const uint64_t containerHash = fnvUpdate(0xcbf29ce484222325ull, container.data(), container.size());
      if (rep == 0) {
         r.originalPayload = payload.size;
         r.header = layout.header;
         r.boundary = layout.boundary;
         r.blob = layout.blob;
         r.total = container.size();
         r.containerHash = containerHash;
         if (m.codec == column::Codec::Raw) {
            r.encodedPayload = blob.size();
         } else if (m.codec == column::Codec::P2b && !blob.empty()) {
            // Mapping (width byte + varint m + 2m, or the width byte alone) is per-column metadata: reported as bitmap_bytes,
            // the slot sgtt uses for its used-token bitmap, and separately as mapping_bytes.
            r.tokens = p2bStats.tokens;
            r.tokenIdBytes = p2bStats.width;
            r.usedTokens = p2bStats.distinct;
            r.fallbackTokens = p2bStats.fallbackTokens;
            r.mappingBytes = p2bStats.mappingBytes;
            r.encodedPayload = p2bStats.tokenBytes;
            r.bitmap = p2bStats.mappingBytes;
            r.footer = p2b::footerBytes;
            if (blob.size() != r.encodedPayload + r.bitmap + r.footer) throw std::runtime_error("P2b blob size != mapping + token IDs + footer");
         } else if (m.codec == column::Codec::P1 && !blob.empty()) {
            r.tokens = p1Tokens;
            r.tokenIdBytes = 2;
            r.fallbackTokens = p1Fallback;
            std::set<uint16_t> distinct;
            for (size_t i = 0; i < 2 * p1Tokens; i += 2) distinct.insert(static_cast<uint16_t>(static_cast<uint8_t>(blob[i]) | (static_cast<uint8_t>(blob[i + 1]) << 8)));
            r.usedTokens = distinct.size();
            r.encodedPayload = 2 * p1Tokens;
            r.footer = p1::footerBytes;
            if (blob.size() != r.encodedPayload + r.footer) throw std::runtime_error("P1 blob size != token IDs + footer");
         } else if (m.codec == column::Codec::Sgtt && !blob.empty()) {
            r.tokens = infoField(info, "tokens");
            auto bits = infoField(info, "token_id_size");
            if (bits) r.tokenIdBytes = *bits / 8;
            r.usedTokens = infoField(info, "used_tokens");
            if (!r.tokens || !r.tokenIdBytes) throw std::runtime_error("upstream getInfo() lacks tokens/token_id_size");
            r.encodedPayload = *r.tokens * *r.tokenIdBytes;
            r.footer = column::sgttFooterBytes;
            if (blob.size() < r.encodedPayload + r.footer) throw std::runtime_error("sgtt blob smaller than token IDs + footer");
            r.bitmap = blob.size() - r.encodedPayload - r.footer;
         }
         r.decoded = values;
         r.decodedCount = values.size();
         r.decodedFingerprint = sequenceFingerprint(values);
         r.exactValues = 0;
         for (size_t i = 0; i < std::min(values.size(), c.values.size()); ++i) r.exactValues += values[i] == c.values[i];
         r.exact = values == c.values;
         r.container = std::move(container);
      } else if (containerHash != r.containerHash || container.size() != r.total) {
         r.consistent = false;
      }
   }
   if (!r.exact) r.status = "roundtrip_mismatch";
   else if (!r.consistent) r.status = "nondeterministic_encoding";
   else if (r.header + r.boundary + r.encodedPayload + r.bitmap + r.footer != r.total) r.status = "accounting_mismatch";
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
int main(int argc, char** argv) {
   if (argc != 6) {
      std::cerr << "usage: phase1_column_harness <columns.tsv> <measurements.csv> <containers.tsv> <decoded_values.tsv> <repetitions>\n";
      return 2;
   }
   const unsigned repetitions = std::max(1ul, std::stoul(argv[5]));
   std::vector<Column> columns;
   try {
      columns = readColumns(argv[1]);
   } catch (const std::exception& e) {
      std::cerr << "input error: " << e.what() << "\n";
      return 2;
   }
   std::ofstream csv(argv[2]), containers(argv[3]), decodedOut(argv[4]);
   csv << "column_id,method,value_count,original_payload_bytes,input_sequence_fnv1a64,token_count,token_id_bytes,used_tokens,"
          "header_bytes,boundary_metadata_bytes,codec_blob_bytes,encoded_payload_bytes,bitmap_bytes,footer_bytes,total_stored_bytes,"
          "container_fnv1a64,encoded_consistent_across_reps,decoded_value_count,decoded_sequence_fnv1a64,exact_values,roundtrip_exact,"
          "codec_init_ms_median,column_encode_ms_median,decoder_init_ms_median,column_decode_ms_median,timed_repetitions,status,error_message,configuration,"
          "fallback_tokens,mapping_bytes\n";
   containers << "column_id\tmethod\tcontainer_hex\n";
   decodedOut << "column_id\tmethod\tvalue_index\tsample_id\tdecoded_hex\n";

   size_t failures = 0;
   for (const auto& c : columns) {
      for (const auto& m : methods()) {
         Result r;
         try {
            measure(m, c, repetitions, r);
         } catch (const std::exception& e) {
            r.status = "error";
            r.error = e.what();
         }
         if (r.status != "ok") ++failures;
         csv << c.id << ',' << m.name << ',' << c.values.size() << ',' << r.originalPayload << ',' << r.inputFingerprint << ','
             << (r.tokens ? std::to_string(*r.tokens) : "") << ',' << (r.tokenIdBytes ? std::to_string(*r.tokenIdBytes) : "") << ','
             << (r.usedTokens ? std::to_string(*r.usedTokens) : "") << ',' << r.header << ',' << r.boundary << ',' << r.blob << ','
             << r.encodedPayload << ',' << r.bitmap << ',' << r.footer << ',' << r.total << ',' << r.containerHash << ',' << (r.consistent ? "true" : "false") << ','
             << r.decodedCount << ',' << r.decodedFingerprint << ',' << r.exactValues << ',' << (r.exact ? "true" : "false") << ','
             << median(r.codecInit) << ',' << median(r.encode) << ',' << median(r.decoderInit) << ',' << median(r.decode) << ',' << r.encode.size() << ','
             << r.status << ',' << quote(r.error) << ',' << quote(m.configuration) << ',' << (r.fallbackTokens ? std::to_string(*r.fallbackTokens) : "") << ','
             << (r.mappingBytes ? std::to_string(*r.mappingBytes) : "") << '\n';
         containers << c.id << '\t' << m.name << '\t' << hex(r.container.data(), r.container.size()) << '\n';
         for (size_t i = 0; i < r.decoded.size(); ++i)
            decodedOut << c.id << '\t' << m.name << '\t' << i << '\t' << (i < c.sampleIds.size() ? c.sampleIds[i] : "") << '\t' << hex(r.decoded[i].data(), r.decoded[i].size()) << '\n';
      }
   }
   std::cerr << "column failures: " << failures << "\n";
   return failures == 0 ? 0 : 1;
}
