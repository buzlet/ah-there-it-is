# tokenizer_benchmark.py
"""Exact text-token counts using published vocabularies; optional vendor API counts."""
from pathlib import Path
import hashlib
import json
import os
import traceback
import requests

ROOT = Path(__file__).parent
INPUTS = {"en": ROOT / "samples/en.txt", "ru": ROOT / "samples/ru.txt"}
EXPECTED = {
    "en": ("19ff97cee3eaf82374e28d32cbe8546432756d559c2d31102d2d99a4338a2b2b", 10240),
    "ru": ("2429095870289824ae3a0bbb28e348cc7d72eb9b03f9fe2bc788c74fe7e273c0", 21198),
}
MODELS = {
    "Qwen3.8-27B": "Qwen/Qwen3.8-27B",
    "Qwen3.5-35B-A3B": "Qwen/Qwen3.5-35B-A3B",
    "Qwen3-235B-A22B": "Qwen/Qwen3-235B-A22B",
    "DeepSeek-V4.1-Flash": "deepseek-ai/DeepSeek-V4.1-Flash",
    "DeepSeek-V4-Pro-0813": "deepseek-ai/DeepSeek-V4-Pro-0813",
    "DeepSeek-V3.2": "deepseek-ai/DeepSeek-V3.2",
}


def validated_inputs():
    values = {}
    for lang, path in INPUTS.items():
        data = path.read_bytes()
        digest, size = EXPECTED[lang]
        assert (hashlib.sha256(data).hexdigest(), len(data)) == (digest, size), lang
        values[lang] = data.decode("utf-8")
    return values


def count_local(values, output):
    import tiktoken
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    enc = tiktoken.get_encoding("o200k_base")
    output["gpt-oss-120b"] = {
        "source": "o200k_harmony (ordinary text; same merges as o200k_base)",
        "method": "local-exact",
        "en": len(enc.encode(values["en"])),
        "ru": len(enc.encode(values["ru"])),
    }
    for model, repo in MODELS.items():
        try:
            path = hf_hub_download(repo_id=repo, filename="tokenizer.json")
            tok = Tokenizer.from_file(path)
            result = {
                "source": repo,
                "method": "local-exact",
                "en": len(tok.encode(values["en"], add_special_tokens=False).ids),
                "ru": len(tok.encode(values["ru"], add_special_tokens=False).ids),
            }
            output[model] = result
        except Exception as exc:
            output[model] = {"source": repo, "method": "unavailable",
                             "error": f"{type(exc).__name__}: {exc}"[:600]}
        print("MODEL", model, json.dumps(output[model], ensure_ascii=False), flush=True)


def count_vendor_api(values, output):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = "claude-opus-5-5"
    entry = {"source": model, "method": "official-api"}
    if key:
        for lang, text in values.items():
            try:
                resp = requests.post("https://api.anthropic.com/v1/messages/count_tokens",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": model, "messages": [
                        {"role": "user", "content": [{"type": "text", "text": text}]}
                    ]}, timeout=60)
                resp.raise_for_status()
                entry[lang] = int(resp.json()["input_tokens"])
            except Exception as exc:
                entry[lang + "_error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
    else:
        entry["method"] = "key-required"
    output["Claude-Opus-5.5"] = entry

    key = os.environ.get("GEMINI_API_KEY", "")
    for model in ("gemini-3.1-pro-preview", "gemini-3.8-flash"):
        entry = {"source": model, "method": "official-api"}
        if key:
            for lang, text in values.items():
                try:
                    resp = requests.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:countTokens",
                        headers={"x-goog-api-key": key, "content-type": "application/json"},
                        json={"contents": [{"role": "user", "parts": [{"text": text}]}]},
                        timeout=60)
                    resp.raise_for_status()
                    entry[lang] = int(resp.json()["totalTokens"])
                except Exception as exc:
                    entry[lang + "_error"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        else:
            entry["method"] = "key-required"
        output["Gemini-" + model] = entry


def main():
    values = validated_inputs()
    output = {}
    count_local(values, output)
    count_vendor_api(values, output)
    target = ROOT / "token_counts.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("RESULT_JSON_BEGIN")
    print(target.read_text())
    print("RESULT_JSON_END")


if __name__ == "__main__":
    main()
