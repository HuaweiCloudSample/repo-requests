#!/usr/bin/env python3
"""Validate repository README files against the organization README standard."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


HEADING_RE = re.compile(r"^\\?(#{1,6})\s+(.+?)\s*$")
ANCHOR_RE = re.compile(r"\s*\[[^\]]+\]\([^)]*\)\s*$")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
MERMAID_FENCE_RE = re.compile(r"```mermaid.*?```", re.DOTALL | re.IGNORECASE)


@dataclass
class Finding:
    level: str
    message: str


def normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_heading(title: str) -> str:
    title = title.replace("\\_", "_")
    title = title.replace("\\", "")
    title = ANCHOR_RE.sub("", title)
    title = re.sub(r"\[(CRITICAL|MINOR)\]\s*$", "", title, flags=re.IGNORECASE)
    title = title.replace("/", " / ")
    title = re.sub(r"\s+", " ", title)
    return title.strip(" #：:")


def compact_heading(title: str) -> str:
    return re.sub(r"[\s/_-]+", "", normalize_heading(title)).lower()


def strip_placeholder_noise(text: str) -> str:
    text = HTML_COMMENT_RE.sub("", text)
    text = MERMAID_FENCE_RE.sub("", text)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]+\]\([^)]*\)", "", text)
    text = re.sub(r"[-*`>#|:()\[\]{}\\_/~\s]", "", text)
    return text


def extract_sections(readme: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in readme.splitlines():
        match = HEADING_RE.match(line)
        if match:
            current = compact_heading(match.group(2))
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)

    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def has_section(sections: dict[str, str], expected: str) -> bool:
    expected_key = compact_heading(expected)
    if expected_key in sections:
        return True
    return any(expected_key in key or key in expected_key for key in sections)


def section_body(sections: dict[str, str], expected: str) -> str:
    expected_key = compact_heading(expected)
    if expected_key in sections:
        return sections[expected_key]
    for key, value in sections.items():
        if expected_key in key or key in expected_key:
            return value
    return ""


def regex_found(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE) is not None


def iter_rule_items(rules: dict, key: str) -> Iterable[dict]:
    for item in rules.get(key, []):
        if isinstance(item, dict) and item.get("pattern"):
            yield item


def validate(readme_path: Path, rules_path: Path) -> tuple[list[Finding], list[Finding]]:
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    errors: list[Finding] = []
    warnings: list[Finding] = []

    if not readme_path.exists():
        errors.append(Finding("error", f"未找到 {readme_path.name}。"))
        return errors, warnings

    readme = normalize_text(readme_path.read_text(encoding="utf-8"))
    sections = extract_sections(readme)

    for section in rules.get("critical_sections", []):
        if not has_section(sections, section):
            errors.append(Finding("error", f"缺少 CRITICAL 章节：{section}。"))

    for section in rules.get("recommended_sections", []):
        if not has_section(sections, section):
            warnings.append(Finding("warning", f"建议补充 MINOR 章节：{section}。"))

    for name, min_chars in rules.get("section_min_chars", {}).items():
        body = strip_placeholder_noise(section_body(sections, name))
        if has_section(sections, name) and len(body) < int(min_chars):
            errors.append(Finding("error", f"CRITICAL 章节内容过少：{name} 至少需要 {min_chars} 个有效字符。"))

    for item in iter_rule_items(rules, "required_patterns"):
        if not regex_found(item["pattern"], readme):
            errors.append(Finding("error", item.get("message") or f"缺少必需内容：{item.get('name', item['pattern'])}。"))

    for item in iter_rule_items(rules, "forbidden_patterns"):
        if regex_found(item["pattern"], readme):
            errors.append(Finding("error", item.get("message") or f"包含禁止内容：{item.get('name', item['pattern'])}。"))

    return errors, warnings


def render_markdown(errors: list[Finding], warnings: list[Finding], rules: dict) -> str:
    max_errors = int(rules.get("max_errors_to_show", 50))
    max_warnings = int(rules.get("max_warnings_to_show", 50))
    lines: list[str] = ["## README 规范审核结果", ""]

    if not errors and not warnings:
        lines.append("通过。README 符合当前组织模板规范。")
        return "\n".join(lines) + "\n"

    if errors:
        lines.extend(["### 必须修复", ""])
        for finding in errors[:max_errors]:
            lines.append(f"- {finding.message}")
        if len(errors) > max_errors:
            lines.append(f"- 另有 {len(errors) - max_errors} 项错误未展示。")
        lines.append("")

    if warnings:
        lines.extend(["### 建议优化", ""])
        for finding in warnings[:max_warnings]:
            lines.append(f"- {finding.message}")
        if len(warnings) > max_warnings:
            lines.append(f"- 另有 {len(warnings) - max_warnings} 项建议未展示。")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate README.md against organization rules.")
    parser.add_argument("--readme", default="README.md", help="Path to README.md.")
    parser.add_argument("--rules", default="readme-rules.json", help="Path to readme-rules.json.")
    parser.add_argument("--report", default="", help="Optional markdown report output path.")
    parser.add_argument("--warnings-as-errors", action="store_true", help="Fail when MINOR warnings exist.")
    args = parser.parse_args()

    readme_path = Path(args.readme)
    rules_path = Path(args.rules)
    if not rules_path.exists():
        print(f"规则文件不存在：{rules_path}", file=sys.stderr)
        return 2

    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    errors, warnings = validate(readme_path, rules_path)
    report = render_markdown(errors, warnings, rules)
    print(report)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

    if errors or (args.warnings_as_errors and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
