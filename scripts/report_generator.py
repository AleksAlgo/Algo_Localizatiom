"""
Генератор Markdown-отчёта QA по результатам qa_judge.evaluate().
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


_DECISION_BADGE = {
    "PASS":             "🟢 **PASS**",
    "PASS_CONDITIONAL": "🟡 **PASS (условный)**",
    "FAIL":             "🔴 **FAIL**",
}


def render_report(qa_result: dict, *, stage: str, source_file: str,
                  output_file: str, source_lang: str, target_lang: str,
                  domain: str, translation_model: str,
                  changes_log: list[dict] | None = None) -> str:
    """
    stage: 'v1' (после первичного перевода) | 'v2' (после ревью Opus)
    """
    d = qa_result["decision"]
    badge = _DECISION_BADGE.get(d["decision"], d["decision"])
    md = []
    md.append(f"# Отчёт оценки качества перевода — этап `{stage}`")
    md.append("")
    md.append(f"**Дата:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    md.append(f"**Файл:** `{source_file}` → `{output_file}`  ")
    md.append(f"**Языковая пара:** {source_lang} → {target_lang}  ")
    md.append(f"**Домен:** {domain}  ")
    md.append(f"**Модель перевода:** `{translation_model}`  ")
    md.append(f"**Модель-судья:** `{qa_result['judge_model']}`  ")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## Итоговое решение")
    md.append("")
    md.append(f"| Метрика | Значение |")
    md.append(f"|---|---|")
    md.append(f"| Решение | {badge} ({d['label']}) |")
    md.append(f"| Quality Score (на 1000 слов) | **{qa_result['quality_score']}** |")
    md.append(f"| Σ штрафных баллов | {qa_result['total_score']} |")
    md.append(f"| Объём перевода (слов) | {qa_result['word_count']} |")
    md.append(f"| Количество ошибок | {len(qa_result['errors'])} |")
    md.append("")

    # сводка по серьёзности
    sev = qa_result["score_breakdown"]["by_severity"]
    md.append("### Распределение по серьёзности")
    md.append("")
    md.append("| Severity | Вес | Кол-во | Σ баллов |")
    md.append("|---|---|---|---|")
    for s, w in [("Critical", 10), ("Major", 5), ("Minor", 1), ("Neutral", 0)]:
        cnt = sev.get(s, 0)
        md.append(f"| {s} | {w} | {cnt} | {cnt * w} |")
    md.append("")

    # сводка по категориям
    by_cat = qa_result["score_breakdown"]["by_category"]
    if by_cat:
        md.append("### Распределение по категориям")
        md.append("")
        md.append("| Категория | Кол-во ошибок | Σ баллов | % от общего |")
        md.append("|---|---|---|---|")
        total = qa_result["total_score"] or 1
        for cat, data in sorted(by_cat.items(), key=lambda x: -x[1]["score"]):
            pct = round(data["score"] / total * 100, 1)
            md.append(f"| {cat} | {data['count']} | {data['score']} | {pct}% |")
        md.append("")

    # резюме
    if qa_result.get("summary_notes"):
        md.append("### Общий комментарий судьи")
        md.append("")
        md.append(f"> {qa_result['summary_notes']}")
        md.append("")

    # изменения после ревью (только для v2)
    if changes_log is not None and stage == "v2":
        md.append(f"### Изменения, внесённые ревьюером ({len(changes_log)} сегментов)")
        md.append("")
        if not changes_log:
            md.append("Ревьюер не внёс изменений — первичный перевод признан финальным.")
            md.append("")
        else:
            md.append("| ID | До ревью | После ревью | Причина |")
            md.append("|---|---|---|---|")
            for c in changes_log[:50]:  # до 50 строк
                before = (c.get("before") or "").replace("|", "\\|").replace("\n", " ")[:80]
                after = (c.get("after") or "").replace("|", "\\|").replace("\n", " ")[:80]
                reason = (c.get("reason") or "").replace("|", "\\|").replace("\n", " ")[:80]
                md.append(f"| `{c['id']}` | {before} | {after} | {reason} |")
            if len(changes_log) > 50:
                md.append(f"\n_(показаны первые 50 из {len(changes_log)} изменений)_")
            md.append("")

    # подробный список ошибок
    md.append("---")
    md.append("")
    md.append(f"## Журнал ошибок ({len(qa_result['errors'])})")
    md.append("")
    if not qa_result["errors"]:
        md.append("Ошибок не обнаружено.")
    else:
        md.append("| # | Segment | Категория | Тип | Sev. | Вес | Source → Target | Комментарий |")
        md.append("|---|---|---|---|---|---|---|---|")
        for i, e in enumerate(qa_result["errors"], start=1):
            sid = e.get("segment_id", "—")
            cat = e.get("category", "—")
            etype = e.get("error_type", "—")
            sev_v = e.get("severity", "—")
            w = e.get("weight", 0)
            src = (e.get("source") or "").replace("|", "\\|").replace("\n", " ")[:60]
            tgt = (e.get("target") or "").replace("|", "\\|").replace("\n", " ")[:60]
            cm = (e.get("comment") or "").replace("|", "\\|").replace("\n", " ")[:120]
            md.append(f"| {i} | `{sid}` | {cat} | `{etype}` | **{sev_v}** | {w} | {src} → {tgt} | {cm} |")
    md.append("")

    # шкала PASS/FAIL
    md.append("---")
    md.append("")
    md.append("## Справочно: шкала PASS/FAIL")
    md.append("")
    md.append("| Quality Score | Оценка | Решение |")
    md.append("|---|---|---|")
    md.append("| 0–9   | Excellent      | 🟢 PASS |")
    md.append("| 10–19 | Good           | 🟢 PASS |")
    md.append("| 20–29 | Acceptable     | 🟡 PASS (условный) |")
    md.append("| 30–49 | Poor           | 🔴 FAIL |")
    md.append("| ≥ 50  | Unacceptable   | 🔴 FAIL |")
    md.append("| Любая Critical-ошибка | — | 🔴 FAIL (override) |")
    md.append("")

    return "\n".join(md)


def write_report(qa_result: dict, out_path: Path, **kwargs) -> Path:
    out_path = Path(out_path)
    md = render_report(qa_result, **kwargs)
    out_path.write_text(md, encoding="utf-8")
    return out_path


def write_json_log(qa_v1: dict, qa_v2: dict, model_selection: dict,
                   changes: list[dict], out_path: Path) -> Path:
    out_path = Path(out_path)
    payload = {
        "model_selection": model_selection,
        "v1": {
            "quality_score": qa_v1["quality_score"],
            "decision": qa_v1["decision"],
            "errors_total": len(qa_v1["errors"]),
            "by_severity": qa_v1["score_breakdown"]["by_severity"],
        },
        "v2": {
            "quality_score": qa_v2["quality_score"],
            "decision": qa_v2["decision"],
            "errors_total": len(qa_v2["errors"]),
            "by_severity": qa_v2["score_breakdown"]["by_severity"],
        },
        "improvement": {
            "score_delta": round(qa_v1["quality_score"] - qa_v2["quality_score"], 2),
            "errors_delta": len(qa_v1["errors"]) - len(qa_v2["errors"]),
            "segments_changed_in_review": len(changes),
        },
        "generated_at": datetime.now().isoformat(),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path
