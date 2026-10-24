// ASan/UBSan driver: P2b codec with the P2c fixture vocabulary. Round trips, every truncation, and random byte mutations.
#include "p2b_codec.hpp"
#include <cstdio>
#include <random>
using namespace hashcode;
static std::span<const std::byte> B(const std::string& s) { return {reinterpret_cast<const std::byte*>(s.data()), s.size()}; }
int main(int, char** argv) {
   const p1::Vocabulary v(argv[1]);
   std::mt19937_64 rng(42);
   std::vector<std::string> inputs = {"", "a", std::string(1, '\0'), "\xff\xfe\x80", "नमस्ते ಕನ್ನಡ mixed \U0001F600\r\n\t"};
   for (int k = 0; k < 6; ++k) { std::string s; for (int i = 0; i < 40; ++i) s += v.entry(static_cast<uint16_t>(5248 + rng() % 2989)) + (rng() % 3 ? " " : ""); inputs.push_back(s); }
   { std::string s; for (int i = 0; i < 3000; ++i) s += v.entry(static_cast<uint16_t>(rng() % 65536)); inputs.push_back(s); }
   size_t ok = 0, rejected = 0, accepted = 0;
   for (const auto& s : inputs) {
      p2b::Stats st;
      auto blob = p2b::encodeBlob(v, B(s), st);
      auto back = p2b::decodeBlob(v, blob);
      if (std::string(reinterpret_cast<const char*>(back.data()), back.size()) != s) { std::puts("ROUNDTRIP MISMATCH"); return 1; }
      ++ok;
      for (size_t n = 0; n < blob.size(); ++n) {
         try { p2b::decodeBlob(v, std::span<const std::byte>(blob.data(), n)); ++accepted; } catch (const std::exception&) { ++rejected; }
      }
      for (int t = 0; t < 4000; ++t) {
         auto m = blob;
         for (int j = 0, k = 1 + rng() % 3; j < k; ++j) m[rng() % m.size()] = static_cast<std::byte>(rng());
         if (rng() % 4 == 0 && m.size() > 14) m.erase(m.begin() + 1 + rng() % (m.size() - 14));
         try { p2b::decodeBlob(v, m); ++accepted; } catch (const std::exception&) { ++rejected; }
      }
   }
   std::printf("roundtrips %zu, malformed rejected %zu, malformed accepted (decoded without error) %zu\n", ok, rejected, accepted);
}
