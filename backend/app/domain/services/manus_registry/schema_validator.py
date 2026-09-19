"""JSON Schema validation for registry tool arguments.

Uses the ``jsonschema`` library (already a dependency) with explicit
draft-2020 mapping. Validation failures return a structured, actionable
details dict so the model can repair its arguments in ONE round instead of
retrying the same broken call.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

import jsonschema

from app.domain.services.manus_registry.errors import VALIDATION_ERROR


def _iter_validation_errors(
    schema: Dict[str, Any], arguments: Dict[str, Any]
):
    """Yield validation errors, supporting allOf+oneOf compositions.

    The registry's browser_click uses allOf:[{brief...},{oneOf:[index|coords]}].
    jsonschema handles this natively; we just surface the best error.
    """
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    yield from validator.iter_errors(arguments)


def _describe_error(err: jsonschema.ValidationError) -> Dict[str, Any]:
    """Human/LLM-readable detail for one validation error."""
    path = "$" + "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in err.absolute_path
    )
    detail: Dict[str, Any] = {"path": path, "message": err.message}
    if err.validator == "required":
        missing = list(err.message.split("'")[1::2])
        detail["missing_fields"] = missing
    elif err.validator == "enum":
        detail["allowed_values"] = list(err.validator_value)
    elif err.validator == "type":
        detail["expected_type"] = err.validator_value
    elif err.validator in ("minItems", "maxItems"):
        detail["limit"] = err.validator_value
    elif err.validator in ("minimum", "maximum"):
        detail["limit"] = err.validator_value
    elif err.validator == "pattern":
        detail["pattern"] = err.validator_value
    return detail


def validate_arguments(
    tool_name: str,
    schema: Dict[str, Any],
    arguments: Dict[str, Any],
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Validate ``arguments`` against the tool's input_schema.

    Returns (ok, error_details) where error_details (when not ok) carries:
      - code: VALIDATION_ERROR
      - message: one-line summary
      - details.errors: per-error path/message/fix hints
      - details.provided: sorted list of argument names the model sent
    """
    if not isinstance(arguments, dict):
        return False, {
            "code": VALIDATION_ERROR,
            "message": f"{tool_name}: arguments must be a JSON object, "
                       f"got {type(arguments).__name__}",
            "details": {"provided": []},
        }

    errors = sorted(_iter_validation_errors(schema, arguments), key=lambda e: list(e.absolute_path))
    if not errors:
        return True, None

    details = [_describe_error(e) for e in errors[:5]]
    first = details[0]
    message = (
        f"{tool_name}: {first['message']} (at {first['path']}). "
        "This call was NOT executed — fix the highlighted fields and call again."
    )
    return False, {
        "code": VALIDATION_ERROR,
        "message": message,
        "details": {
            "errors": details,
            "provided": sorted(arguments.keys()),
        },
    }


def schema_summary(schema: Dict[str, Any]) -> str:
    """Compact one-line schema description for error-repair hints."""
    try:
        return json.dumps(schema, ensure_ascii=False)[:600]
    except Exception:  # pragma: no cover
        return ""


# ── model-friendliness helpers ────────────────────────────────────────────────
# Live sessions showed sloppy-but-correctable calls: numeric fields sent as
# strings ("index": "23"), and `brief` (a NARRATION field) omitted even though
# it is required. Rejecting those produced multi-step VALIDATION_ERROR loops
# where the model kept retrying the same call. Both are repaired HERE, before
# validation, so the operational contract (url, index, query, argv, …) stays
# strict while narration/cosmetic slips get fixed automatically.

def _iter_subschemas(schema: Dict[str, Any]):
    """Yield the schema itself and every subschema (allOf/anyOf/oneOf/items)."""
    yield schema
    for key in ("allOf", "anyOf", "oneOf"):
        for sub in schema.get(key) or []:
            if isinstance(sub, dict):
                yield from _iter_subschemas(sub)
    for sub in (schema.get("items") or []):
        if isinstance(sub, dict):
            yield from _iter_subschemas(sub)
    for sub in (schema.get("properties") or {}).values():
        if isinstance(sub, dict):
            yield from _iter_subschemas(sub)


def schema_mentions_brief(schema: Dict[str, Any]) -> bool:
    """True when ``brief`` appears anywhere in the schema (top-level required,
    allOf branches, oneOf branches, or as a property).

    The registry's browser_click nests ``brief`` inside allOf[0].required —
    a top-level ``schema.get("required")`` check never sees it, which is why
    browser_click calls were rejected 4x in a live session while the same
    auto-fill worked for browser_navigate.
    """
    for sub in _iter_subschemas(schema):
        if "brief" in (sub.get("properties") or {}):
            return True
        if "brief" in (sub.get("required") or []):
            return True
    return False


def coerce_arguments(schema: Dict[str, Any], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce scalar argument types to what the schema declares.

    Only lossless, unambiguous conversions are applied:
      - "23" → 23 when the schema declares integer
      - "4.5" → 4.5 when the schema declares number
      - "true"/"false" → bool when the schema declares boolean
    Anything else passes through untouched (jsonschema reports it and the
    model gets the repair hint as before).
    """
    if not isinstance(arguments, dict):
        return arguments

    # Collect declared types per property across all composition branches.
    types: Dict[str, set] = {}
    for sub in _iter_subschemas(schema):
        props = sub.get("properties") or {}
        if not isinstance(props, dict):
            continue
        for name, spec in props.items():
            if not isinstance(spec, dict):
                continue
            declared = spec.get("type")
            if isinstance(declared, str):
                types.setdefault(name, set()).add(declared)

    coerced = dict(arguments)
    for name, value in coerced.items():
        declared = types.get(name) or set()
        if not declared:
            continue
        if isinstance(value, str):
            text = value.strip()
            if "integer" in declared or "number" in declared:
                # A JSON int string never contains "." / exponent.
                if "integer" in declared and text.lstrip("+-").isdigit():
                    try:
                        coerced[name] = int(text)
                        continue
                    except ValueError:  # pragma: no cover
                        pass
                if "number" in declared:
                    try:
                        coerced[name] = float(text) if any(c in text for c in ".eE") else int(text)
                        continue
                    except ValueError:
                        pass
            if "boolean" in declared and text.lower() in ("true", "false"):
                coerced[name] = text.lower() == "true"
    return coerced
