"""Model-integration plan for an extended tokenizer: vocabulary alignment, embedding resize and initialisation mapping.

This does NOT create, load or train any model. No weights, torch or GPU are available or approved. It computes and checks what
an adapted model needs, from the model's public config (recorded below with its source) and a candidate manifest:
  - final tokenizer size = base tokenizer IDs + K extension IDs; every new ID unique, contiguous and above all existing IDs
    (including special tokens), so it cannot collide with a control token;
  - embedding rows needed vs the model's vocab_size (rows beyond the tokenizer are unused padding); resize if exceeded;
  - tied input/output embeddings: one shared matrix is resized (untied models would need both resized consistently);
  - memory overhead = new rows x hidden_size x bytes per parameter (x 2 if untied);
  - initialisation: each new row = mean of the embeddings of the base tokens that the candidate replaces (the base
    tokenizer's IDs for the candidate text), which are listed per new ID.
"""
import argparse
import json
import pathlib
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import candidates as C  # noqa: E402

# Public config of Qwen/Qwen3-0.6B at revision c1899de289a04d12100db370d81485cdf75e47ca (config.json, read 2026-10-25).
QWEN3_0_6B = {"model": "Qwen/Qwen3-0.6B", "revision": "c1899de289a04d12100db370d81485cdf75e47ca", "licence": "apache-2.0 (model card metadata)",
              "vocab_size": 151936, "hidden_size": 1024, "tie_word_embeddings": True, "torch_dtype": "bfloat16",
              "bos_token_id": 151643, "eos_token_id": 151645, "weights_bytes": 1503300328, "weights_downloaded": False}
DTYPE_BYTES = {"bfloat16": 2, "float16": 2, "float32": 4}


def plan(manifest, tokenizer_path, config=QWEN3_0_6B):
    tk = C.extended_tokenizer(tokenizer_path, manifest)  # verifies the manifest IDs against the tokenizer
    new = [c["id"] for c in manifest["candidates"]]
    problems = []
    if new != list(range(tk.base_size, tk.base_size + len(new))):
        problems.append("extension IDs are not contiguous from the base size")
    if set(new) & set(tk.id_to_token):
        problems.append("an extension ID collides with an existing token or special token")
    if any(i < 0 or i >= tk.size() for i in new):
        problems.append("an extension ID is out of range")
    for c in manifest["candidates"]:
        if tk.encode(c["token"]) != [c["id"]]:
            problems.append(f"candidate {c['id']} does not encode to its own ID")
            break
        if any(b >= tk.base_size for b in c["base_ids"]):
            problems.append(f"candidate {c['id']} initialisation refers to a non-base ID")
            break
    final = tk.size()
    rows = max(config["vocab_size"], final)
    per_row = config["hidden_size"] * DTYPE_BYTES[config["torch_dtype"]] * (1 if config["tie_word_embeddings"] else 2)
    return {
        "model": {k: config[k] for k in ("model", "revision", "licence", "vocab_size", "hidden_size", "tie_word_embeddings", "torch_dtype",
                                         "weights_downloaded")},
        "tokenizer": {"base_size": tk.base_size, "extension_tokens": len(new), "final_size": final},
        "embedding": {"model_rows": config["vocab_size"], "unused_padding_rows_before": config["vocab_size"] - tk.base_size,
                      "rows_required": final, "resize_needed": final > config["vocab_size"], "rows_after_resize": rows,
                      "tied": config["tie_word_embeddings"],
                      "memory_overhead_bytes": max(0, final - config["vocab_size"]) * per_row,
                      "note": "rows past the tokenizer's last ID are unused padding; up to that many new tokens fit without a resize"},
        "initialisation": {"method": "mean of the base-token embeddings the candidate replaces",
                           "rows": [{"id": c["id"], "base_ids": c["base_ids"]} for c in manifest["candidates"]]},
        "checks": {"problems": problems, "ok": not problems},
        "not_done": "no model loaded, resized, initialised or trained; needs weights, torch and compute (not available or approved)",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--candidates", required=True, type=pathlib.Path)
    ap.add_argument("--tokenizer", required=True, type=pathlib.Path)
    ap.add_argument("--out", type=pathlib.Path, default=None)
    args = ap.parse_args(argv)
    try:
        p = plan(C.load_manifest(args.candidates), args.tokenizer)
    except C.CandidateError as e:
        print(f"STOP: {e}", file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(json.dumps(p, indent=1) + "\n")
    print(json.dumps({k: p[k] for k in ("tokenizer", "embedding", "checks")}, indent=1))
    return 0 if p["checks"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
