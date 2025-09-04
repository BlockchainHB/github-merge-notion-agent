# GitHub Merge → Notion Changelog Action

Turn merged PRs into a daily Notion changelog. On merge, this Action summarizes the PR with GPT and upserts a single Notion page per day (timezone‑aware). It then comments on the PR with the Notion link. Idempotent per PR and schema‑aware (auto‑detects Title/Date).

## Quick Start

1) Create a Notion integration and share it with your target database.
2) Add repo secrets:
- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`
- `OPENAI_API_KEY`

3) Add a workflow to your repo (example below).

## Example Workflow

```yaml
name: PR → Notion Changelog

on:
  pull_request:
    types: [closed]
  workflow_dispatch:
    inputs:
      pr_number:
        description: "PR number to summarize (for manual runs)"
        required: false
      date_override:
        description: "Optional date (YYYY-MM-DD)"
        required: false

permissions:
  contents: read
  pull-requests: write
  issues: write

jobs:
  changelog:
    if: >-
      ${{ (github.event_name == 'pull_request' && github.event.pull_request.merged == true) ||
          (github.event_name == 'workflow_dispatch') }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: PR → Notion Changelog
        uses: BlockchainHB/github-merge-notion-agent@main
        with:
          timezone: America/New_York
          date_property: Date
          title_property: Title
          llm_model: gpt-4o
          pr_number: ${{ inputs.pr_number }}
          date_override: ${{ inputs.date_override }}
        env:
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## Notes
- Idempotent: won’t duplicate entries for the same PR on the same date.
- Schema‑aware: auto‑detects Title/Date if your property names differ.
- Commenting: posts the Notion link as a comment on the PR (can be disabled by setting `COMMENT_ON_PR=false`).
- Costs: each run calls an LLM; set `llm_model` as you prefer.

## Troubleshooting
- 400 from Notion: ensure the integration is invited to the database and property names match; try the defaults `Date`/`Title` or set custom names.
- Model errors: ensure your key has access to the specified `llm_model`.
- Forked PRs: consider `pull_request_target` with care; review security implications.

