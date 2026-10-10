"""Collect recent public repository commits and releases with GitHub CLI."""

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime, timedelta


def gh_json(endpoint: str):
    result = subprocess.run(
        ["gh", "api", endpoint], stdout=subprocess.PIPE, text=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)


def collect(repo: str, days: int, limit: int) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("repo must be owner/repository")
    if not 1 <= days <= 30 or not 1 <= limit <= 100:
        raise ValueError("days must be 1..30 and limit must be 1..100")
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
    commits = gh_json(f"repos/{repo}/commits?since={since}&per_page={limit}")
    releases = gh_json(f"repos/{repo}/releases?per_page={limit}")
    return {
        "repository": repo, "window_start_utc": since, "window_days": days,
        "commits": [
            {"sha": item["sha"], "message": item["commit"]["message"][:1200],
             "at": item["commit"]["committer"]["date"], "url": item["html_url"]}
            for item in commits
        ],
        "releases": [
            {"tag": item["tag_name"], "name": item["name"], "at": item["published_at"],
             "prerelease": item["prerelease"], "body": (item["body"] or "")[:2500],
             "url": item["html_url"]}
            for item in releases
            if item["published_at"] and datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(since)
        ],
        "coverage": {"per_page": limit, "commit_page_full": len(commits) == limit,
                     "release_page_full": len(releases) == limit,
                     "note": "One page per endpoint; commit messages and release notes are excerpts, not code review."},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=30)
    arguments = parser.parse_args()
    print(json.dumps(collect(arguments.repo, arguments.days, arguments.limit), ensure_ascii=False))
