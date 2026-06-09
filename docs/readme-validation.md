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
