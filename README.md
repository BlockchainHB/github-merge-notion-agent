# GitHub Merge → Notion Changelog
Turn merged PRs into a polished daily Notion changelog with one click.

Summarize each merged pull request using GPT, append it to a single Notion page per day (timezone‑aware), and automatically comment back on the PR with the Notion link. Idempotent per PR and schema‑aware (auto‑detects Title/Date properties).

## 2) Why You’ll Want It
Keeping changelogs current is hard. This Action automatically turns merged PRs into clear, actionable entries in Notion. It uses OpenAI (GPT) to produce concise summaries, groups everything into a single page per day (configurable timezone), and avoids duplicates with idempotent markers. It’s database‑schema aware (auto‑detects your Date/Title property names), posts the Notion link on the PR, and works out‑of‑the‑box with just three secrets. Keywords: “GitHub Action Notion changelog,” “auto changelog,” “OpenAI GPT PR summary,” “daily Notion journal,” “merge to changelog”.

## 3) Visuals

![Flow diagram: GitHub → GPT → Notion](docs/images/flow.png)
![Daily Notion page example](docs/images/notion-daily.png)
![PR comment with Notion link](docs/images/pr-comment.png)

## 4) Installation (User)
Requirements:
- Notion integration: create one and invite it to your target database.
- Notion database: has a Date property (e.g., `Date`) and a Title property (e.g., `Title`).
- Repository secrets:
  - `NOTION_TOKEN`
  - `NOTION_DATABASE_ID`
  - `OPENAI_API_KEY`

Add this workflow to your repo (works on merged PRs and supports manual runs):

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
        uses: BlockchainHB/github-merge-notion-agent@v1
        with:
          timezone: America/New_York
          date_property: Date
          title_property: Title
          llm_model: gpt-4o
        env:
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

## 5) Developer Setup (Contributing)
- Clone this repo and make changes under `scripts/` or `action.yml`.
- Local run (optional): the script can be executed directly with env vars set (`NOTION_TOKEN`, `NOTION_DATABASE_ID`, `OPENAI_API_KEY`, `GITHUB_TOKEN`) and pointing to a PR number. For safer tests, use a future `date_override` (e.g., `2099-01-01`).
- Testing in a sample repo: add the example workflow and point `uses:` to your branch or fork (e.g., `@feature-branch`).
- Keep changes minimal, focused, and well‑described.

## 6) Expectations for Contributors
- Find a bug? Open an issue with clear steps to reproduce and logs (omit secrets).
- Want a feature? Propose the interface (inputs/env) and rationale before coding.
- Submit small PRs, include a brief test plan (e.g., manual dispatch with `pr_number`).
- Be kind, concise, and security‑minded (no secrets in logs or examples).

## Inputs
- `timezone`: timezone for daily page buckets (default `America/New_York`)
- `date_property`: Notion Date property name (default `Date`)
- `title_property`: Notion Title property name (default `Title`)
- `llm_model`: OpenAI model ID (default `gpt-4o`)
- `pr_number`: PR number when using manual dispatch
- `date_override`: write into a specific date (YYYY‑MM‑DD) for testing

## Behavior
- Comments on PR: enabled by default; set `COMMENT_ON_PR=false` to disable
- Idempotency: adds a hidden marker `[LOGGED-PR-ID:<number>]` and checks headings to avoid duplicates
- Schema detection: fetches DB schema and auto‑selects the first Title/Date props if names differ

## Troubleshooting
- Notion 400 Bad Request: invite the integration to the database; confirm Date/Title property names or set custom names via inputs
- Model access: ensure your OpenAI key can use the chosen `llm_model`
- Forked PRs: for public repos receiving fork PRs, consider `pull_request_target` with caution (secrets exposure)

## 7) Connect
Developed by Hasaam Bhatti — hasaamb.com · x.com/automatingwork

If this Action helps you ship cleaner changelogs, please star the repo and share it with your team.

## License
MIT — see `LICENSE` for details.
