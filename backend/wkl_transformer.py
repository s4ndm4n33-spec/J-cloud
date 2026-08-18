"""Weighted Key Language (WKL) Transformer.

Provides bijective (lossless) encoding and decoding of high-frequency substrate
tokens and reserved engineering terminology to reduce prompt bloat over the wire.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Tuple


class WKLTransformer:
    """Bijective encoder/decoder utilizing WKL schema mappings."""

    def __init__(self, schema_path: str | None = None) -> None:
        self.schema_path = self._resolve_schema_path(schema_path)
        self.encode_map: Dict[str, str] = {}
        self.decode_map: Dict[str, str] = {}
        self._load_schema()
        self._compile_regex()

    def _resolve_schema_path(self, provided_path: str | None) -> Path:
        """Resolve schema path using absolute pathing to prevent path traps."""
        if provided_path:
            p = Path(provided_path).resolve()
            if p.exists():
                return p

        # Environment variable override
        env_path = os.environ.get("WKL_SCHEMA_PATH")
        if env_path:
            p = Path(env_path).resolve()
            if p.exists():
                return p

        # Root backend directory relative to file location
        base_dir = Path(__file__).parent.resolve()
        default_path = base_dir / "wkl_schema.json"
        if default_path.exists():
            return default_path

        # Canonical pod fallback
        canonical_path = Path("/app/backend/wkl_schema.json")
        if canonical_path.exists():
            return canonical_path

        raise FileNotFoundError(
            f"WKL Schema not found. Attempted provided path: {provided_path}, "
            f"default: {default_path}, canonical: {canonical_path}"
        )

    def _load_schema(self) -> None:
        """Load schema JSON and build full forward/reverse mappings."""
        with open(self.schema_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        std_keys: Dict[str, str] = data.get("std_keys", {})
        eng_keys: Dict[str, str] = data.get("engineering_block", {})

        # Decode map: Key -> Original Token
        self.decode_map.update(std_keys)
        self.decode_map.update(eng_keys)

        # Encode map: Original Token -> Key
        for key, value in self.decode_map.items():
            self.encode_map[value] = key

    def _compile_regex(self) -> None:
        """Compile regex patterns sorting keys by length descending to prevent partial match overwrites."""
        # Encode regex: match longer words first
        sorted_tokens = sorted(self.encode_map.keys(), key=len, reverse=True)
        escaped_tokens = [re.escape(tok) for tok in sorted_tokens]
        self.encode_regex = re.compile("|".join(escaped_tokens))

        # Decode regex: match keys ($00-$99, E00-E09)
        sorted_keys = sorted(self.decode_map.keys(), key=len, reverse=True)
        escaped_keys = [re.escape(k) for k in sorted_keys]
        self.decode_regex = re.compile("|".join(escaped_keys))

    def encode(self, text: str) -> str:
        """Compress text by substituting known tokens with WKL short-keys."""
        if not text:
            return text

        def _replacer(match: re.Match[str]) -> str:
            token = match.group(0)
            return self.encode_map.get(token, token)

        return self.encode_regex.sub(_replacer, text)

    def decode(self, compressed_text: str) -> str:
        """Restore original text by substituting WKL short-keys with original tokens."""
        if not compressed_text:
            return compressed_text

        def _replacer(match: re.Match[str]) -> str:
            key = match.group(0)
            return self.decode_map.get(key, key)

        return self.decode_regex.sub(_replacer, compressed_text)


if __name__ == "__main__":
    # Self-test integrity check
    transformer = WKLTransformer()
    sample = "The gauntlet backend runtime failed over the tunnel with torque and tensile stress."
    encoded = transformer.encode(sample)
    decoded = transformer.decode(encoded)

    print(f"Original:  {sample}")
    print(f"Encoded:   {encoded}")
    print(f"Decoded:   {decoded}")
    assert decoded == sample, "Integrity Check Failed: Bijective encoding mismatch!"
    print("Self-test passed: Lossless integrity verified.")