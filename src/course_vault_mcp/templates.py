from __future__ import annotations

from datetime import datetime, timezone
import json


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _bullets(values: list[str], empty: str = "- 待补充") -> str:
    cleaned = [value.strip() for value in values if value.strip()]
    return "\n".join(f"- {value}" for value in cleaned) if cleaned else empty


def render_lesson_card(
    *,
    project_id: str,
    lesson_id: str,
    title: str,
    source_url: str,
    summary: str,
    key_concepts: list[str],
    decision_rules: list[str],
    counterexamples: list[str],
    open_questions: list[str],
    source_refs: list[str],
    tags: list[str],
    source_hash: str | None,
    source_language: str,
    transcript_coverage_complete: bool,
    visual_evidence: str,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    frontmatter_tags = "\n".join(f"  - {_yaml_string(tag)}" for tag in tags) or "  - course-note"
    frontmatter_refs = "\n".join(f"  - {_yaml_string(ref)}" for ref in source_refs)
    if not frontmatter_refs:
        frontmatter_refs = "  - source-reference-required"
    return f"""---
project_id: {_yaml_string(project_id)}
lesson_id: {_yaml_string(lesson_id)}
title: {_yaml_string(title)}
source_url: {_yaml_string(source_url)}
source_hash: {_yaml_string(source_hash or 'unknown')}
source_language: {_yaml_string(source_language)}
transcript_coverage: {_yaml_string('complete' if transcript_coverage_complete else 'incomplete')}
visual_evidence: {_yaml_string(visual_evidence)}
generated_at: {_yaml_string(generated_at)}
workflow_state: see-local-ledger
artifact_kind: lesson-card
tags:
{frontmatter_tags}
source_refs:
{frontmatter_refs}
---

# {title}

## 一句话结论

{summary.strip()}

## 核心概念

{_bullets(key_concepts)}

## 决策规则候选

{_bullets(decision_rules)}

## 反例与失效边界

{_bullets(counterexamples)}

## 待验证问题

{_bullets(open_questions)}

## 来源定位

{_bullets(source_refs, empty='- 必须补充课程编号与时间点后才能通过校验')}

## 证据边界

- 本笔记是对授权课程内容的原创结构化归纳，不是课程逐字稿。
- 课程直接结论、系统代理变量与研究假设必须分开标记。
- 未经图表复核、独立验证和成本后测试，不得升级为盈利或自动执行结论。
"""
