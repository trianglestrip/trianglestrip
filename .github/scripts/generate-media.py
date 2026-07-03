#!/usr/bin/env python3
"""Generate dalindev-style terminal SVGs from recent GitHub code activity."""

from __future__ import annotations

import json
import os
import re
import urllib.request
import xml.sax.saxutils as xml
from datetime import datetime, timezone

MONO = (
    "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace"
)
LANG_COLORS = {
    "C++": "#f34b7d",
    "HTML": "#e34c26",
    "Cuda": "#3A4E3A",
    "CUDA": "#3A4E3A",
    "Python": "#3572A5",
    "TypeScript": "#3178c6",
    "C": "#555555",
    "JavaScript": "#f1e05a",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Shell": "#89e051",
    "CMake": "#064f8c",
}


def esc(text: object) -> str:
    return xml.escape(str(text))


def trunc(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def gh_request(url: str, token: str) -> dict | list:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "trianglestrip-media-generator",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def parse_time(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def clock(iso: str) -> str:
    return parse_time(iso).strftime("%H:%M:%S")


def ago(iso: str) -> str:
    delta = datetime.now(timezone.utc) - parse_time(iso)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def lang_color(name: str | None) -> str:
    if not name:
        return "#8b949e"
    return LANG_COLORS.get(name, "#60a5fa")


def fetch_activity(username: str, token: str) -> dict:
    events = gh_request(
        f"https://api.github.com/users/{username}/events/public?per_page=30",
        token,
    )
    repos = gh_request(
        f"https://api.github.com/users/{username}/repos?sort=pushed&per_page=12",
        token,
    )

    stream_lines: list[dict] = []
    commit_rows: list[dict] = []
    repo_cards: list[dict] = []
    seen_repos: set[str] = set()
    lang_counts: dict[str, int] = {}

    for event in events:
        if event.get("type") != "PushEvent":
            continue

        repo_full = event["repo"]["name"]
        repo = repo_full.split("/")[-1]
        ref = event["payload"]["ref"].replace("refs/heads/", "")
        head = event["payload"]["head"][:7]
        created = event["created_at"]
        commits = event["payload"].get("commits") or []
        size = event["payload"].get("size") or len(commits) or 1

        if not commits:
            try:
                commit_data = gh_request(
                    f"https://api.github.com/repos/{repo_full}/commits/{event['payload']['head']}",
                    token,
                )
                commits = [
                    {
                        "message": commit_data["commit"]["message"],
                        "sha": event["payload"]["head"],
                    }
                ]
            except Exception:
                commits = [{"message": f"update {ref}", "sha": event["payload"]["head"]}]

        stream_lines.append(
            {
                "time": clock(created),
                "tag": "git.push",
                "msg": f"{repo} · {ref} · {head} · {size} commit(s)",
                "accent": "#4ade80",
            }
        )

        for commit in commits[:3]:
            message = trunc(commit.get("message", "update"), 52)
            sha = commit.get("sha", event["payload"]["head"])[:7]
            commit_rows.append(
                {
                    "repo": repo,
                    "sha": sha,
                    "message": message,
                    "time": clock(created),
                }
            )
            stream_lines.append(
                {
                    "time": clock(created),
                    "tag": "commit.msg",
                    "msg": f"{repo} · {sha} · {message}",
                    "accent": "#c9d1d9",
                }
            )

        if repo in seen_repos:
            continue
        seen_repos.add(repo)

        repo_meta = next((item for item in repos if item["name"] == repo), None)
        language = (repo_meta or {}).get("language") or "Mixed"
        lang_counts[language] = lang_counts.get(language, 0) + max(size, 1)
        top_message = (
            trunc(commits[0].get("message", f"{ref}@{head}"), 36)
            if commits
            else f"{ref}@{head}"
        )

        repo_cards.append(
            {
                "name": trunc(repo, 16).upper(),
                "lang": language,
                "branch": ref,
                "sha": head,
                "message": top_message,
                "time": ago(created),
                "active": True,
            }
        )

        if len(stream_lines) >= 12:
            break

    for repo_meta in repos:
        name = repo_meta["name"]
        if name in seen_repos:
            continue
        seen_repos.add(name)
        language = repo_meta.get("language") or "Mixed"
        repo_cards.append(
            {
                "name": trunc(name, 16).upper(),
                "lang": language,
                "branch": repo_meta.get("default_branch") or "main",
                "sha": "idle",
                "message": trunc(repo_meta.get("description") or "no recent push", 36),
                "time": ago(repo_meta["pushed_at"]),
                "active": False,
            }
        )
        if len(repo_cards) >= 8:
            break

    if not stream_lines:
        stream_lines = [
            {
                "time": "--:--:--",
                "tag": "git.idle",
                "msg": "waiting for next push event",
                "accent": "#6e7681",
            }
        ]
    if not commit_rows:
        commit_rows = [
            {
                "repo": username,
                "sha": "0000000",
                "message": "no recent commits in public feed",
                "time": "--:--",
            }
        ]

    total_lang = sum(lang_counts.values()) or 1
    lang_rows = sorted(lang_counts.items(), key=lambda item: item[1], reverse=True)[:6]
    languages = [
        (name, round(count * 100 / total_lang, 1), lang_color(name))
        for name, count in lang_rows
    ]

    active = sum(1 for card in repo_cards[:8] if card["active"])
    idle = max(0, min(8, len(repo_cards)) - active)

    return {
        "login": username,
        "stream_lines": stream_lines[:12],
        "commit_rows": commit_rows[:6],
        "repo_cards": repo_cards[:8],
        "languages": languages,
        "push_count": len({line["msg"].split(" · ")[0] for line in stream_lines if line["tag"] == "git.push"}),
        "active": active,
        "idle": idle,
    }


def render_term_stream(data: dict) -> str:
    lines = data["stream_lines"]
    while len(lines) < 12:
        lines = lines + lines
    lines = lines[:12]

    log_lines = []
    y = 60
    for line in lines:
        accent = line.get("accent", "#c9d1d9")
        log_lines.append(
            f'      <text x="24" y="{y}"><tspan fill="#4b5563">[{esc(line["time"])}]</tspan> '
            f'<tspan fill="{accent}">{esc(line["tag"])}</tspan>  · {esc(line["msg"])}</text>'
        )
        y += 18

    scroll_steps = min(6, max(1, len(lines) - 7))
    values = "; ".join(f"0,-{18 * step}" for step in range(scroll_steps + 1))
    key_times = "; ".join(f"{idx / scroll_steps:.3f}" for idx in range(scroll_steps + 1))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 180" width="800" height="180" role="img" aria-label="recent git push activity stream">
  <defs>
    <clipPath id="streamWindow">
      <rect x="0" y="46" width="800" height="128"/>
    </clipPath>
  </defs>
  <rect width="800" height="180" rx="10" fill="#0d1117" stroke="#30363d"/>
  <path d="M 0,10 A 10,10 0 0 1 10,0 L 790,0 A 10,10 0 0 1 800,10 L 800,36 L 0,36 Z" fill="#161b22"/>
  <line x1="0" y1="36" x2="800" y2="36" stroke="#30363d"/>
  <circle cx="22" cy="18" r="6" fill="#ff5f57"/>
  <circle cx="42" cy="18" r="6" fill="#febc2e"/>
  <circle cx="62" cy="18" r="6" fill="#28c840"/>
  <text x="400" y="22" text-anchor="middle" font-family="{MONO}" font-size="11" fill="#6e7681" letter-spacing="1">{esc(data['login'])}@github — recent pushes</text>
  <g transform="translate(700, 22)" font-family="{MONO}" font-size="11" letter-spacing="1">
    <circle cx="-12" cy="-4" r="4" fill="#4ade80">
      <animate attributeName="opacity" values="1;0.3;1" dur="1.8s" repeatCount="indefinite"/>
    </circle>
    <text x="0" y="0" fill="#4ade80">LIVE</text>
  </g>
  <g clip-path="url(#streamWindow)" font-family="{MONO}" font-size="12" fill="#c9d1d9">
    <g>
      <animateTransform attributeName="transform" type="translate"
        values="{values}"
        keyTimes="{key_times}"
        calcMode="discrete"
        dur="9s" repeatCount="indefinite"/>
{chr(10).join(log_lines)}
    </g>
  </g>
</svg>
"""


def render_term_build(data: dict) -> str:
    commits = data["commit_rows"]
    langs = data["languages"] or [("Mixed", 100.0, "#8b949e")]
    top = langs[0][0]
    push_count = max(1, data["push_count"])
    pct = min(95, 40 + push_count * 12)

    rows = []
    y = 64
    for name, share, color in langs[:4]:
        bar_w = max(8, int(420 * share / 100))
        rows.append(f'    <text x="24" y="{y}"><tspan fill="#6e7681">{esc(name.upper())}</tspan></text>')
        rows.append(f'    <rect x="120" y="{y - 9}" width="420" height="11" fill="#21262d" rx="2"/>')
        rows.append(
            f'    <rect x="120" y="{y - 9}" width="{bar_w}" height="11" fill="{color}" rx="2">'
            f'<animate attributeName="width" values="{max(4, bar_w - 8)};{bar_w};{max(4, bar_w - 4)}" dur="6s" repeatCount="indefinite"/>'
            f"</rect>"
        )
        rows.append(
            f'    <text x="560" y="{y}"><tspan fill="#c9d1d9" font-weight="700">{share:.1f}%</tspan></text>'
        )
        y += 24

    log_y = max(176, y + 12)
    log_lines = []
    for idx, commit in enumerate(commits[:3]):
        log_lines.append(
            f'    <text x="24" y="{log_y + idx * 18}" font-size="11" fill="#4b5563">'
            f"[{esc(commit['time'])}] {esc(commit['repo'])} · {esc(commit['sha'])} · {esc(commit['message'])}"
            f"</text>"
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 240" width="800" height="240" role="img" aria-label="recent commit activity monitor">
  <rect width="800" height="240" rx="10" fill="#0d1117" stroke="#30363d"/>
  <path d="M 0,10 A 10,10 0 0 1 10,0 L 790,0 A 10,10 0 0 1 800,10 L 800,36 L 0,36 Z" fill="#161b22"/>
  <line x1="0" y1="36" x2="800" y2="36" stroke="#30363d"/>
  <circle cx="22" cy="18" r="6" fill="#ff5f57"/>
  <circle cx="42" cy="18" r="6" fill="#febc2e"/>
  <circle cx="62" cy="18" r="6" fill="#28c840"/>
  <text x="400" y="22" text-anchor="middle" font-family="{MONO}" font-size="11" fill="#6e7681" letter-spacing="1">recent-edits — active languages · {esc(top)}</text>
  <g transform="translate(710, 22)" font-family="{MONO}" font-size="11" letter-spacing="1">
    <circle cx="-12" cy="-4" r="4" fill="#4ade80">
      <animate attributeName="opacity" values="1;0.3;1" dur="1.8s" repeatCount="indefinite"/>
    </circle>
    <text x="0" y="0" fill="#4ade80">ACTIVE</text>
  </g>
  <g font-family="{MONO}" font-size="12" fill="#c9d1d9">
    <text x="24" y="64"><tspan fill="#6e7681">PUSHES</tspan> <tspan fill="#c9d1d9" font-weight="700">{push_count}</tspan>  ·  <tspan fill="#6e7681">ACTIVITY</tspan></text>
    <rect x="260" y="55" width="200" height="11" fill="#21262d" rx="2"/>
    <rect x="260" y="55" height="11" fill="#4ade80" rx="2" width="{int(200 * pct / 100)}">
      <animate attributeName="width" values="{int(200 * max(20, pct - 8) / 100)};{int(200 * pct / 100)};{int(200 * max(20, pct - 4) / 100)}" dur="9s" repeatCount="indefinite"/>
    </rect>
    <text x="472" y="64" font-weight="700" fill="#fbbf24">{pct}%</text>
    <line x1="24" y1="78" x2="776" y2="78" stroke="#21262d"/>
{chr(10).join(rows)}
    <line x1="24" y1="{log_y - 12}" x2="776" y2="{log_y - 12}" stroke="#21262d"/>
{chr(10).join(log_lines)}
  </g>
</svg>
"""


def render_dev_floor(data: dict) -> str:
    positions = [
        (10, 46),
        (208, 46),
        (406, 46),
        (604, 46),
        (10, 154),
        (208, 154),
        (406, 154),
        (604, 154),
    ]
    cards = data["repo_cards"]
    while len(cards) < 8:
        cards.append(
            {
                "name": "NO REPO",
                "lang": "Mixed",
                "branch": "main",
                "sha": "idle",
                "message": "waiting for activity",
                "time": "n/a",
                "active": False,
            }
        )

    card_svg = []
    for idx, ((x, y), card) in enumerate(zip(positions, cards[:8])):
        color = lang_color(card["lang"]) if card["active"] else "#6e7681"
        if not card["active"] and card["sha"] == "idle":
            color = "#6e7681"
        dot = (
            f'<circle cx="20" cy="20" r="4" fill="{color}">'
            f'<animate attributeName="opacity" values="1;0.3;1" dur="1.8s" repeatCount="indefinite" begin="{idx * 0.2}s"/>'
            "</circle>"
            if card["active"]
            else f'<circle cx="20" cy="20" r="4" fill="none" stroke="#6e7681" stroke-width="1.5"/>'
        )
        card_svg.append(
            f"""    <g transform="translate({x}, {y})">
      <rect width="186" height="96" rx="6" fill="#161b22" stroke="#30363d"{'' if card['active'] else ''}/>
      {dot}
      <text x="32" y="24" fill="{color}" font-size="11" font-weight="700" letter-spacing="0.6">{esc(card['name'])}</text>
      <text x="12" y="44" fill="#6e7681" font-size="10">{esc(card['lang'])} · {esc(card['branch'])}@{esc(card['sha'])}</text>
      <text x="12" y="68" fill="#c9d1d9" font-size="11">{esc(card['message'])}</text>
      <text x="12" y="84" fill="#8b949e" font-size="11">{esc(card['time'])}</text>
    </g>"""
        )

    title = f"repo-floor — {data['active']} active · {data['idle']} idle · recent edits"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 260" width="800" height="260" role="img" aria-label="recently active repositories">
  <rect width="800" height="260" rx="10" fill="#0d1117" stroke="#30363d"/>
  <path d="M 0,10 A 10,10 0 0 1 10,0 L 790,0 A 10,10 0 0 1 800,10 L 800,36 L 0,36 Z" fill="#161b22"/>
  <line x1="0" y1="36" x2="800" y2="36" stroke="#30363d"/>
  <circle cx="22" cy="18" r="6" fill="#ff5f57"/>
  <circle cx="42" cy="18" r="6" fill="#febc2e"/>
  <circle cx="62" cy="18" r="6" fill="#28c840"/>
  <text x="400" y="22" text-anchor="middle" font-family="{MONO}" font-size="11" fill="#6e7681" letter-spacing="1">{esc(title)}</text>
  <g font-family="{MONO}">
{chr(10).join(card_svg)}
  </g>
</svg>
"""


def main() -> None:
    username = os.environ.get("GITHUB_USER", "trianglestrip")
    token = os.environ.get("GITHUB_TOKEN", "")
    data = fetch_activity(username, token)

    os.makedirs("media", exist_ok=True)
    files = {
        "media/term-stream.svg": render_term_stream(data),
        "media/term-build.svg": render_term_build(data),
        "media/dev-floor.svg": render_dev_floor(data),
    }
    for path, content in files.items():
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
