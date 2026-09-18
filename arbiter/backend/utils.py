"""
utils.py — shared utilities for all Arbiter agents
"""
from __future__ import annotations

import json
import re
import logging

logger = logging.getLogger(__name__)


def strip_llm_response(text: str) -> str:
    """Clean raw LLM text to extract pure JSON.

    Handles:
    - <think>...</think> blocks from qwen/qwen3.8-27b
    - Markdown code fences (```json ... ```)
    - Leading/trailing prose before/after the JSON object
    """
    text = text.strip()

    # 1. Strip <think>...</think> reasoning tokens (qwen outputs these)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.strip()

    # 2. Strip markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    # 3. Extract first JSON object — use non-greedy to pick the outermost
    #    correctly balanced object, not a greedy match that overshoots.
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == '{':
            if start is None:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                return text[start:i+1]

    # Fallback: if no balanced object found, return the raw text
    return text.strip()


def _repair_truncated_json(text: str) -> str:
    """Best-effort repair for truncated JSON: close open brackets/braces."""
    # Remove trailing comma before attempting to close
    text = text.rstrip().rstrip(',')
    # Close any open string literal (find odd number of unescaped quotes)
    # Simple heuristic: count unescaped quotes
    in_string = False
    i = 0
    while i < len(text):
        if text[i] == '\\' and in_string:
            i += 2
            continue
        if text[i] == '"':
            in_string = not in_string
        i += 1
    if in_string:
        text += '"'  # close the open string
    # Count open braces/brackets
    open_braces = text.count('{') - text.count('}')
    open_brackets = text.count('[') - text.count(']')
    text += (']' * max(0, open_brackets)) + ('}' * max(0, open_braces))
    return text


def parse_llm_json(text: str) -> dict:
    """Parse LLM output to JSON, with best-effort cleaning."""
    cleaned = strip_llm_response(text)
    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        pass

    # Attempt 1: Remove trailing commas before closing braces/brackets
    fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(fixed, strict=False)
    except json.JSONDecodeError:
        pass

    # Attempt 2: Replace Unicode non-breaking hyphens and similar chars
    fixed2 = fixed.replace('\u2011', '-').replace('\u2013', '-').replace('\u2014', '-')
    try:
        return json.loads(fixed2, strict=False)
    except json.JSONDecodeError:
        pass

    # Attempt 3: Try to repair truncation
    fixed3 = _repair_truncated_json(fixed2)
    try:
        return json.loads(fixed3, strict=False)
    except json.JSONDecodeError as exc:
        logger.warning("parse_llm_json: all repair attempts failed: %s | snippet: %.200s", exc, cleaned[:200])
        # Return empty dict instead of raising — callers handle missing keys gracefully
        return {}
