"""
Перевод сегментов выбранной LLM с батчингом и сохранением плейсхолдеров.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from llm_clients import call_llm, parse_json_response

PLACEHOLDER_PATTERNS = [
    r"\{[^}]+\}",          # {0}, {name}
    r"%\w",                # %s, %d
    r"%\([^)]+\)\w",       # %(name)s
    r"<[^>]+>",            # HTML/XML теги
    r"\$\{[^}]+\}",        # ${var}
]


def _extract_placeholders(text: str) -> list[str]:
    out = []
    for pat in PLACEHOLDER_PATTERNS:
        out.extend(re.findall(pat, text))
    return out


def _check_placeholders_preserved(src: str, tgt: str) -> tuple[bool, list[str]]:
    src_ph = sorted(_extract_placeholders(src))
    tgt_ph = sorted(_extract_placeholders(tgt))
    if src_ph != tgt_ph:
        missing = [p for p in src_ph if tgt_ph.count(p) < src_ph.count(p)]
        return False, missing
    return True, []


SYSTEM_TRANSLATOR = """You are a professional translator specialized in {domain} content.
Translate from {src_lang} to {tgt_lang}.

CRITICAL RULES:
1. Preserve ALL placeholders, tags and variables EXACTLY: {{0}}, {{name}}, %s, %(var)s, <b>, ${{var}}
2. Preserve original formatting: line breaks, spacing, punctuation around placeholders
3. Adapt locale conventions (numbers, dates, currencies, units) to {tgt_lang}
4. Use natural, idiomatic {tgt_lang} — not literal calque
5. Maintain consistent terminology across all segments
{glossary_block}
6. Match register: {register}
7. Do NOT translate proper nouns, brand names, code identifiers
8. Output ONLY the translation. No explanations, no quotes, no markdown.

Return JSON: {{"translations": [{{"id": "<segment_id>", "text": "<translated_text>"}}]}}
"""


def translate_segments(segments: list[dict], provider: str, model_id: str,
                       src_lang: str, tgt_lang: str, domain: str = "general",
                       glossary: Optional[dict[str, str]] = None,
                       register: str = "neutral",
                       batch_size: int = 20) -> dict[str, str]:
    """
    segments: [{"id": "...", "text": "...", "ctx": {...}}, ...]
    Возвращает {segment_id: translated_text}.
    """
    glossary_block = ""
    if glossary:
        items = "\n".join(f"  - {k} → {v}" for k, v in glossary.items())
        glossary_block = f"5a. STRICT GLOSSARY (must use):\n{items}"

    system = SYSTEM_TRANSLATOR.format(
        domain=domain, src_lang=src_lang, tgt_lang=tgt_lang,
        glossary_block=glossary_block, register=register,
    )

    results: dict[str, str] = {}

    for i in range(0, len(segments), batch_size):
        batch = segments[i:i + batch_size]
        user_payload = {"segments": [{"id": s["id"], "text": s["text"]} for s in batch]}
        user = json.dumps(user_payload, ensure_ascii=False, indent=2)

        raw = call_llm(provider, model_id, system, user,
                       max_tokens=8192, json_mode=True)
        try:
            parsed = parse_json_response(raw)
        except Exception as e:
            print(f"[translator] JSON parse error in batch {i}: {e}")
            print(f"[translator] raw: {raw[:300]}")
            continue

        for item in parsed.get("translations", []):
            sid = item.get("id")
            txt = item.get("text", "")
            if sid:
                results[sid] = txt

        # проверка плейсхолдеров
        for s in batch:
            tr = results.get(s["id"])
            if tr is None:
                continue
            ok, missing = _check_placeholders_preserved(s["text"], tr)
            if not ok:
                print(f"[translator] WARN: placeholders missing in {s['id']}: {missing}")

    return results
