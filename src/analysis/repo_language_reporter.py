from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


_REPO_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")


@dataclass(frozen=True)
class LanguageEntry:
    language: str
    bytes_total: int
    percent: float

    def as_dict(self) -> dict[str, int | float | str]:
        return {
            "language": self.language,
            "bytes": self.bytes_total,
            "percent": round(self.percent, 2),
        }


def fetch_repo_languages(owner: str, repo: str, token: str | None = None) -> dict[str, int]:
    """Retrieve the GitHub language breakdown for a repository."""
    if not _REPO_PART.fullmatch(owner) or not _REPO_PART.fullmatch(repo):
        raise ValueError("owner and repo must be GitHub repository name components")

    # The local Qwen checkout uses a private repository. Reuse the PC's existing
    # GitHub CLI login when no credential was supplied to this read-only command.
    if token is None:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token is None:
        try:
            auth = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, check=False
            )
        except FileNotFoundError:
            auth = None
        if auth is not None and auth.returncode == 0:
            token = auth.stdout.strip() or None

    url = f"https://api.github.com/repos/{owner}/{repo}/languages"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "tim-repo-language-reporter",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise RuntimeError(
                f"GitHub could not read {owner}/{repo} (HTTP {exc.code}); "
                "check repository access with 'gh auth status' or set GH_TOKEN"
            ) from exc
        raise

    if not isinstance(payload, dict):
        raise ValueError("GitHub language response was not a JSON object")

    if any(
        not isinstance(language, str)
        or not isinstance(bytes_total, int)
        or isinstance(bytes_total, bool)
        or bytes_total < 0
        for language, bytes_total in payload.items()
    ):
        raise ValueError("GitHub language response contains invalid byte counts")
    return payload


def build_language_report(owner: str, repo: str, languages: Mapping[str, int]) -> dict[str, object]:
    total = sum(int(value) for value in languages.values())
    entries: list[dict[str, int | float | str]] = []
    for language, bytes_total in sorted(languages.items(), key=lambda item: item[1], reverse=True):
        percent = (int(bytes_total) / total * 100.0) if total else 0.0
        entries.append(LanguageEntry(language=language, bytes_total=int(bytes_total), percent=percent).as_dict())

    return {
        "owner": owner,
        "repo": repo,
        "total_bytes": total,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "languages": entries,
    }


def render_markdown(report: Mapping[str, object]) -> str:
    lines = [
        "# Repository language composition",
        "",
        f"- Repository: `{report.get('owner')}/{report.get('repo')}`",
        f"- Total bytes: {int(report.get('total_bytes', 0))}",
        f"- Generated at: {report.get('generated_at')}",
        "",
        "| Language | Bytes | Share |",
        "| --- | ---: | ---: |",
    ]

    for item in report.get("languages", []) or []:
        name = str(item["language"])
        bytes_total = int(item["bytes"])
        percent = float(item["percent"])
        lines.append(f"| {name} | {bytes_total} | {percent:.2f}% |")

    return "\n".join(lines) + "\n"


def write_report(path: str | Path, report: Mapping[str, object]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(report), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a markdown report for the repository language composition.")
    parser.add_argument("owner", help="GitHub repository owner or organization")
    parser.add_argument("repo", help="GitHub repository name")
    parser.add_argument("--token", help="Optional GitHub token for authenticated requests")
    parser.add_argument("--output", default="repo-language-report.md", help="Output path for the markdown report")
    args = parser.parse_args()

    languages = fetch_repo_languages(args.owner, args.repo, token=args.token)
    report = build_language_report(args.owner, args.repo, languages)
    output = write_report(args.output, report)
    print(json.dumps({
        "output": str(output),
        "owner": args.owner,
        "repo": args.repo,
        "total_bytes": report["total_bytes"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LanguageEntry",
    "build_language_report",
    "fetch_repo_languages",
    "render_markdown",
    "write_report",
    "main",
]
