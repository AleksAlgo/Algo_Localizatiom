"""
Ревью перевода в Claude Opus.

На вход — исходные сегменты + первичный перевод. Opus возвращает улучшенную версию
с пометкой, какие сегменты были изменены и почему.
"""
from __future__ import annotations

import json
from typing import Optional

from llm_clients import call_llm, parse_json_response

SYSTEM_REVIEWER = """You are a senior {tgt_lang} translation editor reviewing a draft {domain} translation from {src_lang}.

Your job:
1. Check each segment for: accuracy, terminology, fluency, style, locale conventions, tags/placeholders.
2. If a segment can be improved — provide a better version. If it's already good — keep it as-is.
3. Preserve all placeholders/tags exactly as in source: {{0}}, %s, <b>, ${{var}}.
4. Do NOT translate brand names or code identifiers.
5. Maintain consistency across segments (terminology, register, style).
{glossary_block}

For EACH segment return:
  - "id": segment id
  - "text": final reviewed translation
  - "changed": true/false
  - "reason": short reason for change (only if changed)

Return JSON: {{"reviews": [{{"id":"...", "text":"...", "changed":true, "reason":"..."}}]}}
"""


def review_segments(segments: list[dict], draft: dict[str, str],
                    provider: str, model_id: str,
                    src_lang: str, tgt_lang: str, domain: str = "general",
                    glossary: Optional[dict[str, str]] = None,
                    batch_size: int = 15) -> tuple[dict[str, str], list[dict]]:
    """
    Возвращает (final_translations, changes_log).
    """
    glossary_block = ""
    if glossary:
        items = "\n".join(f"  - {k} → {v}" for k, v in glossary.items())
        glossary_block = f"6. STRICT GLOSSARY (must use):\n{items}"

    system = SYSTEM_REVIEWER.format(
        domain=domain, src_lang=src_lang, tgt_lang=tgt_lang,
        glossary_block=glossary_block,
    )

    final: dict[str, str] = {}
    changes: list[dict] = []

    for i in range(0, len(segments), batch_size):
        batch = segments[i:i + batch_size]
        payload = {"segments": [
            {"id": s["id"], "source": s["text"], "draft_translation": draft.get(s["id"], "")}
            for s in batch
        ]}
        user = json.dumps(payload, ensure_ascii=False, indent=2)

        raw = call_llm(provider, model_id, system, user,
                       max_tokens=8192, json_mode=True)
        try:
            parsed = parse_json_response(raw)
        except Exception as e:
            print(f"[reviewer] JSON parse error in batch {i}: {e}")
            # fallback: оставить draft без изменений
            for s in batch:
                final[s["id"]] = draft.get(s["id"], "")
            continue

        for r in parsed.get("reviews", []):
            sid = r.get("id")
            if not sid:
                continue
            final[sid] = r.get("text", draft.get(sid, ""))
            if r.get("changed"):
                changes.append({
                    "id": sid,
                    "before": draft.get(sid, ""),
                    "after": r.get("text", ""),
                    "reason": r.get("reason", ""),
                })

    # на случай если модель что-то пропустила
    for s in segments:
        final.setdefault(s["id"], draft.get(s["id"], ""))

    return final, changes
