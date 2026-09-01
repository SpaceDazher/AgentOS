"""Compute canonical SHA-256 of frozen artifacts and patch placeholder references."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
ARTIFACTS = {
    "revocation-contract.json": "contract_sha256",
    "rubric.json": "rubric_sha256",
}


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    hashes: dict[str, str] = {}
    for name in ARTIFACTS:
        p = BASE / name
        data = json.loads(p.read_text(encoding="utf-8"))
        canon = canonical_json(data)
        h = sha256_text(canon)
        hashes[name] = h
        print(f"{name}: canonical_sha256={h}")

    # Patch placeholders in workload-manifest.json and threat-model.json
    for fname in ("workload-manifest.json", "threat-model.json"):
        p = BASE / fname
        text = p.read_text(encoding="utf-8")
        original = text
        for placeholder, key in ARTIFACTS.items():
            ph = f"{{{{{key}}}}}"
            val = hashes[placeholder]
            text = text.replace(ph, val)
        if text != original:
            p.write_text(text, encoding="utf-8")
            print(f"  patched {fname}")

    print("\nFinal hashes:")
    for name in ARTIFACTS:
        p = BASE / name
        raw = p.read_bytes()
        print(f"  {name} file_sha256={sha256_bytes(raw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
