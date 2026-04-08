#!/usr/bin/env python3
"""
Shared helpers for WRIT-FM content generators.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

DEFAULT_NEWS_FEEDS = (
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.npr.org/1001/rss.xml",
)
NEWS_CACHE_TTL_SECONDS = int(os.environ.get("WRIT_NEWS_CACHE_TTL", "600"))
NEWS_TIMEOUT_SECONDS = int(os.environ.get("WRIT_NEWS_TIMEOUT", "6"))

GITHUB_ORG = os.environ.get("WRIT_GITHUB_ORG", "FluidNumerics")
GITHUB_CACHE_TTL_SECONDS = int(os.environ.get("WRIT_GITHUB_CACHE_TTL", "600"))
GITHUB_TIMEOUT_SECONDS = int(os.environ.get("WRIT_GITHUB_TIMEOUT", "10"))

_NEWS_CACHE: dict[str, object] = {"timestamp": 0.0, "items": []}


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_time_of_day(hour: int | None = None, profile: str = "default") -> str:
    if hour is None:
        hour = datetime.now().hour

    if profile == "extended":
        if 6 <= hour < 10:
            return "morning"
        if 10 <= hour < 14:
            return "daytime"
        if 14 <= hour < 15:
            return "early_afternoon"
        if 15 <= hour < 18:
            return "afternoon"
        if 18 <= hour < 24:
            return "evening"
        return "late_night"

    if 6 <= hour < 10:
        return "morning"
    if 10 <= hour < 18:
        return "daytime"
    if 18 <= hour < 24:
        return "evening"
    return "late_night"


def preprocess_for_tts(text: str, *, include_cough: bool = True) -> str:
    text = text.replace("[pause]", "...")
    text = text.replace("[chuckle]", "heh...")
    if include_cough:
        text = text.replace("[cough]", "ahem...")
    text = text.replace('"', "")
    return text.strip()


def clean_claude_output(text: str, *, strip_quotes: bool = True) -> str:
    cleaned = text.replace("*", "").replace("_", "").strip()
    if strip_quotes and cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def run_claude(
    prompt: str,
    *,
    timeout: int = 60,
    model: str | None = None,
    min_length: int = 0,
    strip_quotes: bool = True,
) -> str | None:
    args = ["claude", "-p", prompt]
    if model:
        args.extend(["--model", model])

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log("Claude timed out")
        return None
    except Exception as exc:
        log(f"Claude error: {exc}")
        return None

    if result.returncode != 0 or not result.stdout.strip():
        return None

    script = clean_claude_output(result.stdout, strip_quotes=strip_quotes)
    if len(script) <= min_length:
        return None
    return script


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_child_text(elem: ET.Element, name: str) -> str:
    for child in elem:
        if _strip_namespace(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _extract_source_title(root: ET.Element, fallback: str) -> str:
    tag = _strip_namespace(root.tag)
    if tag == "rss":
        for child in root:
            if _strip_namespace(child.tag) == "channel":
                title = _find_child_text(child, "title")
                return title or fallback
    if tag == "feed":
        title = _find_child_text(root, "title")
        return title or fallback
    return fallback


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def fetch_headlines(max_items: int | None = None) -> list[dict]:
    now = time.time()
    cached_items = _NEWS_CACHE.get("items", [])
    if cached_items and now - float(_NEWS_CACHE.get("timestamp", 0.0)) < NEWS_CACHE_TTL_SECONDS:
        return list(cached_items)

    max_items = max_items or int(os.environ.get("WRIT_NEWS_MAX_ITEMS", "8"))
    feed_env = os.environ.get("WRIT_NEWS_FEEDS")
    feeds = [f.strip() for f in feed_env.split(",")] if feed_env else list(DEFAULT_NEWS_FEEDS)
    feeds = [f for f in feeds if f]

    headlines: list[dict] = []
    seen: set[str] = set()

    for feed_url in feeds:
        try:
            with urllib.request.urlopen(feed_url, timeout=NEWS_TIMEOUT_SECONDS) as response:
                content = response.read()
            root = ET.fromstring(content)
        except Exception:
            continue

        fallback = urllib.parse.urlparse(feed_url).netloc or "Unknown Source"
        source = _extract_source_title(root, fallback)

        for elem in root.iter():
            tag = _strip_namespace(elem.tag)
            if tag not in ("item", "entry"):
                continue
            title = _find_child_text(elem, "title")
            if not title:
                continue
            norm = _normalize_title(title)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            headlines.append({"title": title, "source": source})
            if len(headlines) >= max_items:
                break
        if len(headlines) >= max_items:
            break

    _NEWS_CACHE["timestamp"] = now
    _NEWS_CACHE["items"] = list(headlines)
    return headlines


def format_headlines(headlines: list[dict], max_items: int | None = None) -> str:
    if not headlines:
        return ""
    max_items = max_items or len(headlines)
    lines = []
    for item in headlines[:max_items]:
        title = item.get("title", "").strip()
        source = item.get("source", "").strip() or "Source"
        if title:
            lines.append(f"- [{source}] {title}")
    return "\n".join(lines)


# =============================================================================
# GITHUB ACTIVITY
# =============================================================================

_GITHUB_CACHE: dict[str, object] = {"timestamp": 0.0, "items": []}


def fetch_github_activity(max_items: int | None = None) -> list[dict]:
    """Fetch recent public activity from the configured GitHub org.

    Uses the GitHub Events API: /orgs/{org}/events
    No auth required for public orgs (60 req/hr unauthenticated).
    Set GITHUB_TOKEN env var for higher rate limits (5000 req/hr).
    """
    now = time.time()
    cached = _GITHUB_CACHE.get("items", [])
    if cached and now - float(_GITHUB_CACHE.get("timestamp", 0.0)) < GITHUB_CACHE_TTL_SECONDS:
        return list(cached)

    max_items = max_items or int(os.environ.get("WRIT_GITHUB_MAX_ITEMS", "15"))
    org = GITHUB_ORG

    url = f"https://api.github.com/orgs/{urllib.parse.quote(org)}/events?per_page=100"

    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "WRIT-FM/1.0")

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=GITHUB_TIMEOUT_SECONDS) as response:
            import json as _json
            events = _json.loads(response.read())
    except Exception as exc:
        log(f"GitHub API error: {exc}")
        _GITHUB_CACHE["timestamp"] = now
        _GITHUB_CACHE["items"] = []
        return []

    items: list[dict] = []
    seen: set[str] = set()

    for event in events:
        if len(items) >= max_items:
            break

        etype = event.get("type", "")
        repo_name = event.get("repo", {}).get("name", "unknown")
        actor = event.get("actor", {}).get("login", "someone")
        payload = event.get("payload", {})
        created = event.get("created_at", "")

        summary = _summarize_github_event(etype, repo_name, actor, payload)
        if not summary:
            continue

        dedup_key = f"{repo_name}:{etype}:{summary[:60]}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        items.append({
            "repo": repo_name,
            "actor": actor,
            "type": etype,
            "summary": summary,
            "created_at": created,
        })

    _GITHUB_CACHE["timestamp"] = now
    _GITHUB_CACHE["items"] = list(items)
    return items


def _summarize_github_event(etype: str, repo: str, actor: str, payload: dict) -> str | None:
    """Convert a GitHub event into a one-line summary. Returns None to skip."""
    if etype == "PushEvent":
        commits = payload.get("commits", [])
        count = len(commits)
        ref = payload.get("ref", "").replace("refs/heads/", "")
        if commits:
            last_msg = commits[-1].get("message", "").split("\n")[0][:80]
            return f"{actor} pushed {count} commit(s) to {ref} on {repo} — \"{last_msg}\""
        return f"{actor} pushed {count} commit(s) to {ref} on {repo}"

    if etype == "PullRequestEvent":
        action = payload.get("action", "")
        pr = payload.get("pull_request", {})
        title = pr.get("title", "untitled")[:80]
        merged = pr.get("merged", False)
        if action == "closed" and merged:
            return f"{actor} merged PR on {repo}: \"{title}\""
        if action in ("opened", "closed", "reopened"):
            return f"{actor} {action} PR on {repo}: \"{title}\""
        return None

    if etype == "IssuesEvent":
        action = payload.get("action", "")
        issue = payload.get("issue", {})
        title = issue.get("title", "untitled")[:80]
        if action in ("opened", "closed", "reopened"):
            return f"{actor} {action} issue on {repo}: \"{title}\""
        return None

    if etype == "CreateEvent":
        ref_type = payload.get("ref_type", "")
        ref = payload.get("ref", "")
        if ref_type == "repository":
            return f"{actor} created new repository {repo}"
        if ref_type == "branch" and ref:
            return f"{actor} created branch {ref} on {repo}"
        if ref_type == "tag" and ref:
            return f"{actor} tagged {ref} on {repo}"
        return None

    if etype == "DeleteEvent":
        ref_type = payload.get("ref_type", "")
        ref = payload.get("ref", "")
        if ref_type == "branch" and ref:
            return f"{actor} deleted branch {ref} on {repo}"
        return None

    if etype == "ReleaseEvent":
        action = payload.get("action", "")
        release = payload.get("release", {})
        tag = release.get("tag_name", "")
        if action == "published" and tag:
            return f"{actor} published release {tag} on {repo}"
        return None

    if etype == "ForkEvent":
        return f"{actor} forked {repo}"

    if etype == "WatchEvent":
        return f"{actor} starred {repo}"

    if etype == "IssueCommentEvent":
        issue = payload.get("issue", {})
        title = issue.get("title", "untitled")[:60]
        return f"{actor} commented on \"{title}\" in {repo}"

    return None


def format_github_activity(items: list[dict], max_items: int | None = None) -> str:
    """Format GitHub activity items into a text block for prompt injection."""
    if not items:
        return ""
    max_items = max_items or len(items)
    lines = []
    for item in items[:max_items]:
        lines.append(f"- {item['summary']}")
    return "\n".join(lines)
