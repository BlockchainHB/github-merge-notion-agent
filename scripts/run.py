#!/usr/bin/env python3
import os
import sys
import json
import textwrap
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo
from datetime import datetime
import requests


def getenv_any(keys, default=None):
    for k in keys:
        v = os.getenv(k)
        if v:
            return v
    return default


def log(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class PRFile:
    filename: str
    additions: int
    deletions: int
    changes: int


class GitHubClient:
    def __init__(self, token: str, repo: str):
        self.base = f"https://api.github.com/repos/{repo}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "gh-merge-notion-action"
        })

    def get_pr(self, number: int) -> Dict[str, Any]:
        r = self.session.get(f"{self.base}/pulls/{number}")
        r.raise_for_status()
        return r.json()

    def get_pr_files(self, number: int, limit: int = 200) -> List[PRFile]:
        files: List[PRFile] = []
        page = 1
        per_page = 100
        while True:
            r = self.session.get(f"{self.base}/pulls/{number}/files", params={"page": page, "per_page": per_page})
            r.raise_for_status()
            batch = r.json()
            for f in batch:
                files.append(PRFile(
                    filename=f.get("filename", ""),
                    additions=f.get("additions", 0),
                    deletions=f.get("deletions", 0),
                    changes=f.get("changes", 0),
                ))
                if len(files) >= limit:
                    return files
            if len(batch) < per_page:
                break
            page += 1
        return files

    def get_pr_commits(self, number: int, limit: int = 50) -> List[str]:
        msgs: List[str] = []
        page = 1
        per_page = 100
        while True:
            r = self.session.get(f"{self.base}/pulls/{number}/commits", params={"page": page, "per_page": per_page})
            r.raise_for_status()
            batch = r.json()
            for c in batch:
                msg = (c.get("commit", {}) or {}).get("message", "")
                if msg:
                    msgs.append(msg.strip())
                if len(msgs) >= limit:
                    return msgs
            if len(batch) < per_page:
                break
            page += 1
        return msgs

    def create_issue_comment(self, number: int, body: str) -> None:
        r = self.session.post(f"{self.base}/issues/{number}/comments", json={"body": body})
        r.raise_for_status()


class NotionClient:
    def __init__(self, token: str, database_id: str, date_prop: str, title_prop: str):
        self.base = "https://api.notion.com/v1"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
            "User-Agent": "gh-merge-notion-action",
        })
        self.database_id = database_id
        self.date_prop = date_prop
        self.title_prop = title_prop
        self._resolved = False

    def _fetch_database(self) -> Dict[str, Any]:
        url = f"{self.base}/databases/{self.database_id}"
        r = self.session.get(url)
        if r.status_code >= 400:
            raise RuntimeError(f"Failed to fetch Notion database schema: {r.status_code} {r.text}")
        return r.json()

    def _resolve_props_if_needed(self) -> None:
        if self._resolved:
            return
        try:
            db = self._fetch_database()
            props = db.get("properties", {}) or {}
            title_candidates = [name for name, meta in props.items() if (meta or {}).get("type") == "title"]
            if title_candidates and self.title_prop not in props:
                self.title_prop = title_candidates[0]
            date_candidates = [name for name, meta in props.items() if (meta or {}).get("type") == "date"]
            if date_candidates and self.date_prop not in props:
                self.date_prop = date_candidates[0]
        except Exception:
            pass
        finally:
            self._resolved = True

    def find_page_for_date(self, date_str: str) -> Optional[str]:
        url = f"{self.base}/databases/{self.database_id}/query"
        if not self._resolved:
            self._resolve_props_if_needed()
        payload = {
            "filter": {
                "property": self.date_prop,
                "date": {"equals": date_str}
            },
            "page_size": 1,
        }
        r = self.session.post(url, json=payload)
        if r.status_code == 400 and not self._resolved:
            self._resolve_props_if_needed()
            payload["filter"]["property"] = self.date_prop
            r = self.session.post(url, json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"Notion query failed ({r.status_code}) for property '{self.date_prop}': {r.text}")
        res = r.json()
        results = res.get("results", [])
        if results:
            return results[0]["id"]
        return None

    def create_page_for_date(self, date_str: str, title: str) -> str:
        url = f"{self.base}/pages"
        if not self._resolved:
            self._resolve_props_if_needed()
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": {
                self.date_prop: {"date": {"start": date_str}},
                self.title_prop: {"title": [{"type": "text", "text": {"content": title}}]},
            }
        }
        r = self.session.post(url, json=payload)
        if r.status_code == 400 and not self._resolved:
            self._resolve_props_if_needed()
            payload = {
                "parent": {"database_id": self.database_id},
                "properties": {
                    self.date_prop: {"date": {"start": date_str}},
                    self.title_prop: {"title": [{"type": "text", "text": {"content": title}}]},
                }
            }
            r = self.session.post(url, json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"Failed to create Notion page ({r.status_code}) using properties title='{self.title_prop}', date='{self.date_prop}': {r.text}")
        return r.json()["id"]

    def get_children_texts(self, block_id: str) -> List[str]:
        url = f"{self.base}/blocks/{block_id}/children"
        texts: List[str] = []
        start_cursor = None
        while True:
            params = {"page_size": 100}
            if start_cursor:
                params["start_cursor"] = start_cursor
            r = self.session.get(url, params=params)
            r.raise_for_status()
            data = r.json()
            for b in data.get("results", []):
                for key in ("heading_1", "heading_2", "heading_3", "paragraph", "bulleted_list_item"):
                    if key in b:
                        rich = b[key].get("rich_text", [])
                        t = "".join(rt.get("plain_text", "") for rt in rich)
                        if t:
                            texts.append(t)
                        break
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")
        return texts

    def append_blocks(self, page_id: str, blocks: List[Dict[str, Any]]) -> None:
        url = f"{self.base}/blocks/{page_id}/children"
        payload = {"children": blocks}
        r = self.session.patch(url, json=payload)
        r.raise_for_status()

    def get_page_url(self, page_id: str) -> Optional[str]:
        url = f"{self.base}/pages/{page_id}"
        r = self.session.get(url)
        if r.status_code >= 400:
            return None
        data = r.json()
        return data.get("url")


def iso_date_for_timezone(now_utc: Optional[datetime], tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    now = now_utc or datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    local = now.astimezone(tz)
    return local.date().isoformat()


def build_context(pr: Dict[str, Any], files: List[PRFile], commits: List[str], repo: str) -> str:
    title = pr.get("title", "")
    body = pr.get("body") or ""
    number = pr.get("number")
    user = ((pr.get("user") or {}).get("login") or "?")
    merged_by = ((pr.get("merged_by") or {}).get("login") or "?")
    labels = [l.get("name") for l in pr.get("labels", []) if l.get("name")]
    additions = pr.get("additions", 0)
    deletions = pr.get("deletions", 0)
    changed_files = pr.get("changed_files", 0)

    sorted_files = sorted(files, key=lambda f: f.changes, reverse=True)
    top_files = sorted_files[:30]
    file_lines = [f"- {f.filename} (+{f.additions}/-{f.deletions})" for f in top_files]
    if len(files) > len(top_files):
        file_lines.append(f"- … and {len(files) - len(top_files)} more")

    commit_lines = [f"- {m.splitlines()[0][:200]}" for m in commits[:20]]
    if len(commits) > 20:
        commit_lines.append(f"- … and {len(commits) - 20} more")

    ctx = f"""
    Repository: {repo}
    PR #{number} by {user}, merged by {merged_by}
    Title: {title}
    Labels: {', '.join(labels) if labels else 'none'}
    Stats: +{additions} / -{deletions} across {changed_files} files

    PR Description:\n{textwrap.dedent(body).strip() or '(no description)'}

    Changed files (top):
    {os.linesep.join(file_lines)}

    Commit messages (top):
    {os.linesep.join(commit_lines) if commit_lines else '(none)'}
    """.strip()
    return ctx


def build_prompt(context: str) -> List[Dict[str, str]]:
    system = (
        "You are a senior release engineer. Produce a concise, detailed, and actionable changelog entry suitable for a daily Notion changelog page. "
        "Focus on user-visible changes, API/DB migrations, risk/rollback notes, and follow-ups. Use clear bullets; avoid code diffs."
    )
    user = f"""
    From the following PR context, write a changelog section with:
    - What changed (grouped by area or feature)
    - Why it changed (intent)
    - Impact and risks (perf, UX, reliability)
    - Migration/ops notes if relevant
    - Link text: include the PR number and title in the heading

    Keep it crisp (6-12 bullets). If context is sparse, infer carefully but do not hallucinate.

    Context:
    ---
    {context}
    ---

    Output format:
    - Start with a one-line summary.
    - Then a bullet list (one point per line).
    """.strip()
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def call_openai(messages: List[Dict[str, str]], model: Optional[str] = None) -> str:
    api_key = getenv_any(["OPENAI_API_KEY"]) or ""
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY env var")
    model = model or os.getenv("LLM_MODEL", "gpt-4o")

    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(model=model, messages=messages)
    return resp.choices[0].message.content.strip()


def lines_to_notion_bullets(text: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return blocks
    first = lines[0]
    blocks.append({
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": first}}]},
    })
    for l in lines[1:]:
        clean = l
        for prefix in ("- ", "* ", "• "):
            if clean.startswith(prefix):
                clean = clean[len(prefix):].strip()
                break
        blocks.append({
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": clean}}]},
        })
    return blocks


def make_pr_section_blocks(repo: str, pr_number: int, pr_title: str, pr_url: str, body_text: str) -> List[Dict[str, Any]]:
    heading_text = f"{repo} • PR #{pr_number}: {pr_title}"
    blocks: List[Dict[str, Any]] = [
        {"type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading_text}}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [
            {"type": "text", "text": {"content": "Link: ", "link": None}},
            {"type": "text", "text": {"content": pr_url, "link": {"url": pr_url}}}
        ]}},
    ]
    blocks.extend(lines_to_notion_bullets(body_text))
    blocks.append({"type": "divider", "divider": {}})
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": f"[LOGGED-PR-ID:{pr_number}]"}}]}})
    return blocks


def derive_pr_number_from_event(event_path: Optional[str]) -> Optional[int]:
    if not event_path or not os.path.isfile(event_path):
        return None
    try:
        with open(event_path, "r", encoding="utf-8") as f:
            ev = json.load(f)
        n = ((ev.get("pull_request") or {}).get("number"))
        return int(n) if n is not None else None
    except Exception:
        return None


def main(argv: List[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Summarize merged PR to Notion daily changelog")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--pr", required=False, help="PR number (optional; derived from event if missing)")
    parser.add_argument("--timezone", required=False, default=os.getenv("TIMEZONE", "America/New_York"))
    parser.add_argument("--date", required=False, help="Override date (YYYY-MM-DD) for Notion page")
    parser.add_argument("--notion-page-id", required=False, help="Append to this Notion page id instead of date upsert")
    args = parser.parse_args(argv)

    repo = str(args.repo)
    tz_name = str(args.timezone)

    notion_token = os.getenv("NOTION_TOKEN")
    notion_db = os.getenv("NOTION_DATABASE_ID")
    if not notion_token or not notion_db:
        raise SystemExit("Missing NOTION_TOKEN or NOTION_DATABASE_ID")

    notion_date_prop = os.getenv("NOTION_DATE_PROPERTY", "Date")
    notion_title_prop = os.getenv("NOTION_TITLE_PROPERTY", "Title")

    notion = NotionClient(notion_token, notion_db, notion_date_prop, notion_title_prop)

    pr_number = int(args.pr) if args.pr else (derive_pr_number_from_event(os.getenv("GITHUB_EVENT_PATH")) or 0)
    if not pr_number:
        raise SystemExit("PR number not provided and could not be derived from event")

    gh_token = getenv_any(["GITHUB_TOKEN"]) or ""
    if not gh_token:
        raise SystemExit("Missing GITHUB_TOKEN for GitHub API access")
    gh = GitHubClient(gh_token, repo)

    log(f"Fetching PR #{pr_number} from {repo}…")
    pr = gh.get_pr(pr_number)
    if not pr.get("merged_at"):
        log("PR is not merged; skipping.")
        return 0

    pr_url = pr.get("html_url")
    pr_title = pr.get("title", f"PR #{pr_number}")
    files = gh.get_pr_files(pr_number)
    commits = gh.get_pr_commits(pr_number)
    context = build_context(pr, files, commits, repo)

    log("Calling OpenAI to generate changelog entry…")
    messages = build_prompt(context)
    model = os.getenv("LLM_MODEL") or None
    summary = call_openai(messages, model=model)

    blocks = make_pr_section_blocks(repo, pr_number, pr_title, pr_url, summary)

    # Resolve target page
    if args.notion_page_id:
        page_id = args.notion_page_id
        log(f"Appending to provided Notion page id: {page_id}…")
        target_date = None
    else:
        date_str = args.date or iso_date_for_timezone(None, tz_name)
        target_date = date_str
        title_text = f"Changelog {date_str}"
        log(f"Upserting Notion page for {date_str}…")
        page_id = notion.find_page_for_date(date_str)
        if not page_id:
            page_id = notion.create_page_for_date(date_str, title_text)
        # Idempotency check
        texts = notion.get_children_texts(page_id)
        marker = f"PR #{pr_number}"
        hidden_marker = f"[LOGGED-PR-ID:{pr_number}]"
        if any(marker in t or hidden_marker in t for t in texts):
            log("Entry already exists. Exiting.")
            return 0

    log("Appending new section to Notion page…")
    notion.append_blocks(page_id, blocks)

    # Comment back on the PR (optional)
    comment_on_pr = (os.getenv("COMMENT_ON_PR", "true").lower() != "false")
    if comment_on_pr:
        page_url = None
        try:
            page_url = notion.get_page_url(page_id)
        except Exception:
            page_url = None
        if args.notion_page_id:
            comment = f"Changelog entry added to Notion page: {page_url}" if page_url else "Changelog entry added to Notion (page URL unavailable)."
        else:
            if page_url:
                comment = f"Changelog entry added to Notion daily page for {target_date} ({tz_name}):\n{page_url}"
            else:
                comment = f"Changelog entry added to Notion daily page for {target_date} (URL unavailable)."
        gh.create_issue_comment(pr_number, comment)

    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
