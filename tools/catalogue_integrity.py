"""Portable catalogue digest: sorted JSON structure and decimal number tokens.

The Dart importer implements the same encoding. Numbers use non-exponent,
shortest round-trip decimal strings, avoiding JSON's 1 versus 1.0 distinction.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


def canonical_catalogue_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (float, int, Decimal)):
        number = format(Decimal(str(value)), "f")
        if "." in number:
            number = number.rstrip("0").rstrip(".")
        return "n" + ("0" if Decimal(number) == 0 else number)
    if isinstance(value, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T[0-9:.]+(?:Z|[+-]\d{2}:\d{2})?)?", value):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                parsed = parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(
                    timezone.utc
                )
                value = parsed.isoformat().replace("+00:00", "Z")
                value = re.sub(r"\.0+(?=Z$)", "", value)
                value = re.sub(r"(\.\d*?[1-9])0+(?=Z$)", r"\1", value)
            except ValueError:
                pass  # Ordinary text that resembles an invalid calendar date.
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(canonical_catalogue_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False) + ":" + canonical_catalogue_value(value[key])
                for key in sorted(value)
                if value[key] is not None
            )
            + "}"
        )
    raise TypeError(f"Unsupported catalogue digest value: {type(value).__name__}")


def catalogue_checksum(value: Any) -> str:
    return hashlib.sha256(canonical_catalogue_value(value).encode("utf-8")).hexdigest()
