#!/usr/bin/env python3
"""Audit README files across an organization without installing workflows in target repos."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_readme import validate  # noqa: E402


ISSUE_TITLE = "README 规范巡检未通过"
ISSUE_MARKER = "<!-- readme-audit-bot -->"


@dataclass
class RepoResult:
    name: str
    full_name: str
    html_url: str
    default_branch: str
    status: str
    errors: list[str]
    warnings: list[str]


class GitHubClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith("https://") else f"https://api.github.com{path}"
        body = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "repo-requests-readme-audit",
        }
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API {method} {url} failed: HTTP {exc.code} {raw}") from exc

    def paginate(self, path: str) -> list[Any]:
        items: list[Any] = []
        separator = "&" if "?" in path else "?"
        page = 1
        while True:
            page_path = f"{path}{separator}per_page=100&page={page}"
            chunk = self.request("GET", page_path)
            if not chunk:
                break
            items.extend(chunk)
            if len(chunk) < 100:
                break
            page += 1
        return items


def load_repo_readme(client: GitHubClient, owner: str, repo: str, ref: str) -> str | None:
    encoded_path = urllib.parse.quote("README.md")
    try:
        data = client.request("GET", f"/repos/{owner}/{repo}/contents/{encoded_path}?ref={urllib.parse.quote(ref)}")
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise
    if not isinstance(data, dict) or data.get("encoding") != "base64":
        return None
    content = data.get("content", "")
    return base64.b64decode(content).decode("utf-8", errors="replace")


def audit_readme_text(readme: str, rules_path: Path) -> tuple[list[str], list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        readme_path = Path(tmp) / "README.md"
        readme_path.write_text(readme, encoding="utf-8")
        errors, warnings = validate(readme_path, rules_path)
        return [item.message for item in errors], [item.message for item in warnings]


def render_report(results: list[RepoResult], org: str, mode: str) -> str:
    failed = [item for item in results if item.status == "failed"]
    missing = [item for item in results if item.status == "missing"]
    passed = [item for item in results if item.status == "passed"]

    lines = [
        "# 组织 README 规范巡检报告",
        "",
        f"- 组织：`{org}`",
        f"- 模式：`{mode}`",
        f"- 扫描仓库数：{len(results)}",
        f"- 通过：{len(passed)}",
        f"- 不通过：{len(failed)}",
        f"- 缺少 README：{len(missing)}",
        "",
    ]

    if failed or missing:
        lines.extend(["## 需要处理", ""])
        for item in failed + missing:
            lines.append(f"### [{item.full_name}]({item.html_url})")
            lines.append("")
            if item.status == "missing":
                lines.append("- 未找到 `README.md`。")
            for message in item.errors:
                lines.append(f"- {message}")
            if item.warnings:
                lines.append("")
                lines.append("建议项：")
                for message in item.warnings[:20]:
                    lines.append(f"- {message}")
            lines.append("")
    else:
        lines.extend(["## 结果", "", "全部仓库 README 均符合当前硬性规范。", ""])

    return "\n".join(lines)


def find_existing_issue(client: GitHubClient, owner: str, repo: str) -> dict[str, Any] | None:
    issues = client.paginate(f"/repos/{owner}/{repo}/issues?state=open")
    for issue in issues:
        if "pull_request" in issue:
            continue
        if issue.get("title") == ISSUE_TITLE:
            return issue
    return None


def upsert_issue(client: GitHubClient, result: RepoResult) -> None:
    owner, repo = result.full_name.split("/", 1)
    body_lines = [
        ISSUE_MARKER,
        "本仓库 README 未通过组织模板规范巡检，请按标准模板修复。",
        "",
        "## 必须修复",
        "",
    ]
    if result.status == "missing":
        body_lines.append("- 未找到 `README.md`。")
    else:
        body_lines.extend(f"- {message}" for message in result.errors)
    if result.warnings:
        body_lines.extend(["", "## 建议优化", ""])
        body_lines.extend(f"- {message}" for message in result.warnings[:30])

    body = "\n".join(body_lines) + "\n"
    issue = find_existing_issue(client, owner, repo)
    if issue:
        client.request("PATCH", f"/repos/{owner}/{repo}/issues/{issue['number']}", {"body": body})
    else:
        client.request(
            "POST",
            f"/repos/{owner}/{repo}/issues",
            {"title": ISSUE_TITLE, "body": body},
        )


def close_existing_issue(client: GitHubClient, result: RepoResult) -> None:
    owner, repo = result.full_name.split("/", 1)
    issue = find_existing_issue(client, owner, repo)
    if issue:
        client.request("PATCH", f"/repos/{owner}/{repo}/issues/{issue['number']}", {"state": "closed"})


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit README files across a GitHub organization.")
    parser.add_argument("--org", required=True, help="GitHub organization login.")
    parser.add_argument("--rules", default="readme-rules.json", help="Path to validation rules.")
    parser.add_argument("--mode", choices=["report-only", "issue"], default="report-only")
    parser.add_argument("--include-archived", action="store_true")
    parser.add_argument("--include-forks", action="store_true")
    parser.add_argument("--fail-on-violations", action="store_true", help="Exit 1 when any repo fails the audit.")
    parser.add_argument("--report", default="readme-audit-report.md")
    parser.add_argument("--json-report", default="readme-audit-report.json")
    args = parser.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("缺少 GH_TOKEN 或 GITHUB_TOKEN。", file=sys.stderr)
        return 2

    rules_path = Path(args.rules)
    client = GitHubClient(token)
    repos = client.paginate(f"/orgs/{urllib.parse.quote(args.org)}/repos?type=all&sort=full_name")
    results: list[RepoResult] = []

    for repo in repos:
        if repo.get("archived") and not args.include_archived:
            continue
        if repo.get("fork") and not args.include_forks:
            continue

        full_name = repo["full_name"]
        owner, name = full_name.split("/", 1)
        readme = load_repo_readme(client, owner, name, repo.get("default_branch") or "main")
        if readme is None:
            result = RepoResult(
                name=name,
                full_name=full_name,
                html_url=repo.get("html_url", ""),
                default_branch=repo.get("default_branch") or "",
                status="missing",
                errors=["未找到 README.md。"],
                warnings=[],
            )
        else:
            errors, warnings = audit_readme_text(readme, rules_path)
            result = RepoResult(
                name=name,
                full_name=full_name,
                html_url=repo.get("html_url", ""),
                default_branch=repo.get("default_branch") or "",
                status="failed" if errors else "passed",
                errors=errors,
                warnings=warnings,
            )

        results.append(result)
        if args.mode == "issue":
            if result.status in {"failed", "missing"}:
                upsert_issue(client, result)
            else:
                close_existing_issue(client, result)

    report = render_report(results, args.org, args.mode)
    Path(args.report).write_text(report, encoding="utf-8")
    Path(args.json_report).write_text(
        json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(report)
    failed_count = sum(1 for item in results if item.status in {"failed", "missing"})
    return 1 if args.fail_on_violations and failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
