# README 规范审核接入说明

本仓库集中维护组织 README 模板、审核规则和可复用 GitHub Actions workflow。

## 新仓库自动接入

`auto-create-repo.yml` 会在仓库创建后写入 `.github/workflows/validate-readme.yml`，新仓库后续提交或 PR 修改 `README.md` 时会自动调用本仓库的集中式审核流程。

## 已有仓库手动接入

在目标仓库添加以下文件：`.github/workflows/validate-readme.yml`

```yaml
name: README 规范审核

on:
  pull_request:
    paths:
      - README.md
  push:
    branches:
      - main
    paths:
      - README.md
  workflow_dispatch:

permissions:
  contents: read
  pull-requests: write

jobs:
  validate-readme:
    uses: HuaweiCloudSample/repo-requests/.github/workflows/validate-readme.yml@main
    with:
      readme-path: README.md
      warnings-as-errors: false
```

## 规则维护

- `readme-rules.json`：维护必填章节、建议章节、必需内容和禁止占位符。
- `scripts/validate_readme.py`：无第三方依赖的校验器。
- `readme模板.md`：组织标准 README 模板。

默认策略：`CRITICAL` 项失败会阻止合并，`MINOR` 项只给出建议。若需要让 `MINOR` 也阻止合并，将 `warnings-as-errors` 设置为 `true`。

## 组织级定期巡检

如果不希望在业务仓库中放置 workflow，可以使用集中式巡检：

- `.github/workflows/audit-org-readmes.yml`：每周一运行，也支持手动触发。
- `scripts/audit_org_readmes.py`：扫描组织仓库，读取 `README.md` 并复用同一套规则校验。

巡检模式：

- `report-only`：只生成巡检报告，不修改业务仓库。
- `issue`：对不合规仓库创建或更新 `README 规范巡检未通过` Issue；合规后会关闭已有巡检 Issue。

`ORG_ADMIN_TOKEN` 至少需要：

- `Contents: Read-only`
- `Metadata: Read-only`
- `Issues: Read and write`（仅 `issue` 模式需要）
