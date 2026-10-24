#pragma once
// P2b: per-column token-ID width on top of an unchanged P1-format vocabulary (used with the frozen P2a vocabulary).
// Blob (HCC1 codec 3):
//   width u8 (1 or 2)
//   width 1 only: varint m (1..256) | m x u16 LE global IDs, strictly increasing (local ID = index in this list)
//   token stream: n x u8 local IDs (width 1) or n x u16 LE global IDs (width 2)
//   footer: "BTT2" | version u8 = 1 | table ID (8 bytes)                                  -> 13 bytes
// Width rule: width 1 iff m <= 256 and 1 + varint(m) + 2m + n < 1 + 2n; otherwise width 2. Tokenization is P1's.
#include "p1_codec.hpp"
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <span>
#include <stdexcept>
#include <vector>
//---------------------------------------------------------------------------
namespace hashcode::p2b {
//---------------------------------------------------------------------------
inline constexpr size_t footerBytes = 13;
inline constexpr uint8_t blobVersion = 1;
//---------------------------------------------------------------------------
struct Stats {
   size_t tokens = 0, fallbackTokens = 0, distinct = 0, width = 0;
   size_t mappingBytes = 0;  // width byte + varint m + 2m (width 1), or the width byte alone (width 2)
   size_t tokenBytes = 0;    // n (width 1) or 2n (width 2)
};
//---------------------------------------------------------------------------
inline size_t varintBytes(uint64_t v) {
   size_t n = 1;
   while (v >= 0x80) {
      v >>= 7;
      ++n;
   }
   return n;
}
//---------------------------------------------------------------------------
inline void putVarint(std::vector<std::byte>& out, uint64_t v) {
   do {
      uint8_t b = v & 0x7F;
      v >>= 7;
      out.push_back(static_cast<std::byte>(b | (v ? 0x80 : 0)));
   } while (v);
}
//---------------------------------------------------------------------------
inline std::vector<std::byte> encodeIds(const p1::Vocabulary& v, const std::vector<uint16_t>& ids, Stats& s) {
   std::vector<uint16_t> distinct(ids);
   std::sort(distinct.begin(), distinct.end());
   distinct.erase(std::unique(distinct.begin(), distinct.end()), distinct.end());
   s.tokens = ids.size();
   s.distinct = distinct.size();
   const size_t m = distinct.size(), n = ids.size();
   const bool narrow = m >= 1 && m <= 256 && (1 + varintBytes(m) + 2 * m + n) < (1 + 2 * n);
   std::vector<std::byte> blob;
   if (narrow) {
      s.width = 1;
      blob.push_back(std::byte{1});
      putVarint(blob, m);
      for (auto g : distinct) {
         blob.push_back(static_cast<std::byte>(g & 0xFF));
         blob.push_back(static_cast<std::byte>(g >> 8));
      }
      s.mappingBytes = blob.size();
      for (auto id : ids) blob.push_back(static_cast<std::byte>(std::lower_bound(distinct.begin(), distinct.end(), id) - distinct.begin()));
   } else {
      s.width = 2;
      blob.push_back(std::byte{2});
      s.mappingBytes = 1;
      for (auto id : ids) {
         blob.push_back(static_cast<std::byte>(id & 0xFF));
         blob.push_back(static_cast<std::byte>(id >> 8));
      }
   }
   s.tokenBytes = blob.size() - s.mappingBytes;
   for (char c : std::string_view("BTT2")) blob.push_back(static_cast<std::byte>(c));
   blob.push_back(static_cast<std::byte>(blobVersion));
   for (auto b : v.tableId()) blob.push_back(static_cast<std::byte>(b));
   return blob;
}
//---------------------------------------------------------------------------
inline std::vector<std::byte> encodeBlob(const p1::Vocabulary& v, std::span<const std::byte> data, Stats& s) {
   auto ids = v.tokenize(data, s.fallbackTokens);
   return encodeIds(v, ids, s);
}
//---------------------------------------------------------------------------
/// Global token IDs of a blob, fully validated.
inline std::vector<uint16_t> decodeIds(const p1::Vocabulary& v, std::span<const std::byte> blob) {
   if (blob.size() < 1 + footerBytes) throw std::runtime_error("P2b: blob shorter than width byte + footer");
   const auto* f = blob.data() + blob.size() - footerBytes;
   if (std::memcmp(f, "BTT2", 4) != 0) throw std::runtime_error("P2b: bad footer magic");
   if (static_cast<uint8_t>(f[4]) != blobVersion) throw std::runtime_error("P2b: unsupported blob version");
   if (std::memcmp(f + 5, v.tableId().data(), 8) != 0) throw std::runtime_error("P2b: blob was encoded with a different vocabulary");
   const size_t end = blob.size() - footerBytes;
   const auto width = static_cast<uint8_t>(blob[0]);
   size_t pos = 1;
   std::vector<uint16_t> ids;
   if (width == 1) {
      uint64_t m = 0;
      for (unsigned shift = 0;; shift += 7) {
         if (pos >= end || shift > 63) throw std::runtime_error("P2b: truncated mapping count");
         auto b = static_cast<uint8_t>(blob[pos++]);
         m |= static_cast<uint64_t>(b & 0x7F) << shift;
         if (!(b & 0x80)) break;
      }
      if (m < 1 || m > 256) throw std::runtime_error("P2b: mapping count outside 1..256");
      if (end - pos < 2 * m) throw std::runtime_error("P2b: truncated mapping");
      std::vector<uint16_t> map(m);
      for (uint64_t i = 0; i < m; ++i, pos += 2) {
         map[i] = static_cast<uint8_t>(blob[pos]) | (static_cast<uint16_t>(static_cast<uint8_t>(blob[pos + 1])) << 8);
         if (map[i] >= v.size()) throw std::runtime_error("P2b: mapped global ID outside vocabulary");
         if (i > 0 && map[i] <= map[i - 1]) throw std::runtime_error("P2b: mapping is not strictly increasing");
      }
      ids.reserve(end - pos);
      for (; pos < end; ++pos) {
         const auto local = static_cast<uint8_t>(blob[pos]);
         if (local >= m) throw std::runtime_error("P2b: local ID outside mapping");
         ids.push_back(map[local]);
      }
   } else if (width == 2) {
      if ((end - pos) % 2) throw std::runtime_error("P2b: odd 2-byte token stream");
      ids.reserve((end - pos) / 2);
      for (; pos < end; pos += 2) {
         const uint16_t g = static_cast<uint8_t>(blob[pos]) | (static_cast<uint16_t>(static_cast<uint8_t>(blob[pos + 1])) << 8);
         if (g >= v.size()) throw std::runtime_error("P2b: global ID outside vocabulary");
         ids.push_back(g);
      }
   } else {
      throw std::runtime_error("P2b: unknown ID width");
   }
   return ids;
}
//---------------------------------------------------------------------------
inline std::vector<std::byte> decodeBlob(const p1::Vocabulary& v, std::span<const std::byte> blob) {
   std::vector<std::byte> out;
   for (auto id : decodeIds(v, blob))
      for (char c : v.entry(id)) out.push_back(static_cast<std::byte>(c));
   return out;
}
//---------------------------------------------------------------------------
}
//---------------------------------------------------------------------------
