"""
LLM-as-a-judge: автоматическая оценка качества перевода по Microsoft MQM.

Возвращает структурированный отчёт со списком ошибок, Quality Score и решением PASS/FAIL.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from llm_clients import call_llm, parse_json_response

REFERENCE_DIR = Path(__file__).resolve().parent.parent / "reference"


def _load_criteria() -> dict:
    with open(REFERENCE_DIR / "qa_criteria.json", encoding="utf-8") as f:
        return json.load(f)


def _build_criteria_prompt(criteria: dict) -> str:
    lines = []
    for cat in criteria["categories"]:
        lines.append(f"\n### {cat['name']}")
        for et in cat["error_types"]:
            lines.append(f"  - {et['code']} ({et['name']}, default={et['default_severity']}): {et['description']}")
    return "\n".join(lines)


SYSTEM_JUDGE = """You are a senior translation quality auditor applying the Microsoft Quality Framework (MQM-based).

You will receive segment pairs (source + translation). For EACH error you find, output one entry.

Severity levels and weights:
  - Critical (10): meaning broken, security/legal risk, unintelligible, encoding broken, inappropriate content
  - Major (5):    significant comprehension impact, wrong term, missing tag, wrong locale format
  - Minor (1):    small style/grammar/punctuation issue, formatting glitch
  - Neutral (0):  preference comment, not an error

Error types (use these CODES exactly):
{criteria_list}

For each error return:
  - "segment_id"
  - "source"        (snippet from original)
  - "target"        (snippet from translation)
  - "category"      (e.g. "accuracy")
  - "error_type"    (CODE from list above)
  - "severity"      ("Critical"|"Major"|"Minor"|"Neutral")
  - "weight"        (10|5|1|0)
  - "comment"       (1-2 sentences explaining the issue + recommended fix, in {comment_lang})

Be precise: do not report the same issue twice. If a segment is correct, don't include it.

Return JSON: {{"errors": [...], "summary": {{"notes": "<1-3 sentence overall impression in {comment_lang}>"}}}}
"""


def _classify_decision(quality_score: float, has_critical: bool, criteria: dict) -> dict:
    if has_critical:
        return {"decision": "FAIL", "label": "Critical errors present", "color": "red"}
    th = criteria["pass_fail_thresholds"]
    if quality_score < 10:
        return {"decision": "PASS", "label": "Excellent", "color": "green"}
    elif quality_score < 20:
        return {"decision": "PASS", "label": "Good", "color": "green"}
    elif quality_score < 30:
        return {"decision": "PASS_CONDITIONAL", "label": "Acceptable", "color": "yellow"}
    elif quality_score < 50:
        return {"decision": "FAIL", "label": "Poor", "color": "red"}
    else:
        return {"decision": "FAIL", "label": "Unacceptable", "color": "red"}


def evaluate(segments: list[dict], translations: dict[str, str],
             provider: str, model_id: str,
             src_lang: str, tgt_lang: str,
             comment_lang: str = "Russian",
             batch_size: int = 25) -> dict:
    """
    Возвращает:
        {
          "errors": [...],
          "score_breakdown": {by_category: {...}, by_severity: {...}},
          "total_score": 42,
          "word_count": 1000,
          "quality_score": 42.0,    # на 1000 слов
          "decision": {...},
          "summary_notes": "...",
          "judge_model": "..."
        }
    """
    criteria = _load_criteria()
    system = SYSTEM_JUDGE.format(
        criteria_list=_build_criteria_prompt(criteria),
        comment_lang=comment_lang,
    )

    all_errors: list[dict] = []
    summary_notes: list[str] = []

    for i in range(0, len(segments), batch_size):
        batch = segments[i:i + batch_size]
        payload = {
            "language_pair": f"{src_lang} → {tgt_lang}",
            "segments": [
                {"id": s["id"], "source": s["text"], "target": translations.get(s["id"], "")}
                for s in batch
            ],
        }
        user = json.dumps(payload, ensure_ascii=False, indent=2)

        raw = call_llm(provider, model_id, system, user,
                       max_tokens=8192, json_mode=True)
        try:
            parsed = parse_json_response(raw)
        except Exception as e:
            print(f"[qa_judge] JSON parse error: {e}")
            continue

        for err in parsed.get("errors", []):
            all_errors.append(err)
        if parsed.get("summary", {}).get("notes"):
            summary_notes.append(parsed["summary"]["notes"])

    # подсчёт
    word_count = sum(len(t.split()) for t in translations.values())
    if word_count == 0:
        word_count = 1
    total_score = sum(e.get("weight", 0) for e in all_errors)
    quality_score = total_score / (word_count / 1000.0)
    has_critical = any(e.get("severity") == "Critical" for e in all_errors)

    by_cat: dict[str, dict] = {}
    by_sev: dict[str, int] = {"Critical": 0, "Major": 0, "Minor": 0, "Neutral": 0}
    for e in all_errors:
        cat = e.get("category", "unknown")
        sev = e.get("severity", "Minor")
        by_cat.setdefault(cat, {"count": 0, "score": 0})
        by_cat[cat]["count"] += 1
        by_cat[cat]["score"] += e.get("weight", 0)
        by_sev[sev] = by_sev.get(sev, 0) + 1

    decision = _classify_decision(quality_score, has_critical, criteria)

    return {
        "judge_model": f"{provider}/{model_id}",
        "language_pair": f"{src_lang} → {tgt_lang}",
        "errors": all_errors,
        "score_breakdown": {"by_category": by_cat, "by_severity": by_sev},
        "total_score": total_score,
        "word_count": word_count,
        "quality_score": round(quality_score, 2),
        "decision": decision,
        "summary_notes": " ".join(summary_notes),
    }
