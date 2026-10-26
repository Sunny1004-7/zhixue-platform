from __future__ import annotations

import unicodedata


def normalize_concept_name(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        char for char in normalized
        if char.isalnum() or "\u4e00" <= char <= "\u9fff"
    )
