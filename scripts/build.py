#!/usr/bin/env python3
"""Render the static site into public/ from data/videos.json."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "videos.json"
TEMPLATE = ROOT / "scripts" / "template.html"
OUT_DIR = ROOT / "public"

PLATFORM_LABEL = {
    "youtube": "YouTube",
    "soundcloud": "SoundCloud",
    "suno": "Suno",
}
KIND_LABEL = {
    "original": "Original",
    "remix": "Remix",
    "cover": "Cover",
    "version": "Version",
    "visual": "Visual",
    "unknown": "Other",
}
PLATFORM_ORDER = {"youtube": 0, "soundcloud": 1, "suno": 2}


def fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def card_html(v: dict) -> str:
    platform = v.get("platform", "youtube")
    kind = v.get("kind", "unknown")
    title = v.get("title") or "(untitled)"
    channel = v.get("channel") or ""
    url = v.get("url") or "#"
    thumb = v.get("thumbnail") or ""
    duration = fmt_duration(v.get("duration"))
    published = v.get("published") or ""
    first_seen = v.get("first_seen") or ""
    date = published or first_seen
    search = f"{title} {channel}".lower()

    thumb_tag = (
        f'<img loading="lazy" src="{esc(thumb)}" alt="" '
        f'referrerpolicy="no-referrer" '
        f"onerror=\"this.style.display='none'\">"
        if thumb
        else ""
    )

    return f"""    <article class="card" data-platform="{esc(platform)}"
      data-kind="{esc(kind)}" data-title="{esc(title.lower())}"
      data-channel="{esc(channel.lower())}" data-search="{esc(search)}"
      data-date="{esc(date)}" data-sort-title="{esc(title.lower())}">
      <a class="thumb" href="{esc(url)}" target="_blank" rel="noopener">
        {thumb_tag}
        <span class="play" aria-hidden="true">&#9654;</span>
        {f'<span class="dur">{esc(duration)}</span>' if duration else ''}
      </a>
      <div class="body">
        <div class="badges">
          <span class="badge plat-{esc(platform)}">{esc(PLATFORM_LABEL.get(platform, platform))}</span>
          <span class="badge kind-{esc(kind)}">{esc(KIND_LABEL.get(kind, kind))}</span>
        </div>
        <h3 class="title"><a href="{esc(url)}" target="_blank" rel="noopener">{esc(title)}</a></h3>
        <p class="channel">{esc(channel)}</p>
        <p class="meta">
          {f'<span>{esc(date)}</span>' if date else ''}
          {f'<span class="seen" title="first added to this list">added {esc(first_seen)}</span>' if first_seen else ''}
        </p>
      </div>
    </article>"""


def sort_key(v: dict):
    return (
        v.get("published") or v.get("first_seen") or "",
        PLATFORM_ORDER.get(v.get("platform", ""), 9),
        (v.get("title") or "").lower(),
    )


def main() -> int:
    store = json.loads(DATA_FILE.read_text())
    videos = store.get("videos", [])
    song = store.get("song", {})

    originals = sorted(
        [v for v in videos if v.get("kind") == "original"], key=sort_key, reverse=True
    )
    rest = sorted(
        [v for v in videos if v.get("kind") != "original"], key=sort_key, reverse=True
    )

    cards = "\n".join(card_html(v) for v in rest)
    origin_cards = "\n".join(card_html(v) for v in originals)

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = json.dumps(
        {
            "generated": store.get("generated"),
            "count": len(videos),
            "videos": [
                {
                    "key": v.get("key"),
                    "title": v.get("title"),
                    "channel": v.get("channel"),
                    "url": v.get("url"),
                    "platform": v.get("platform"),
                    "kind": v.get("kind"),
                    "duration": v.get("duration"),
                    "published": v.get("published"),
                    "first_seen": v.get("first_seen"),
                }
                for v in videos
            ],
        },
        ensure_ascii=False,
    )

    template = TEMPLATE.read_text()
    page = (
        template.replace("__CARDS__", cards)
        .replace("__ORIGINAL_CARDS__", origin_cards)
        .replace("__COUNT__", str(len(videos)))
        .replace("__REMIX_COUNT__", str(len(rest)))
        .replace("__UPDATED__", updated)
        .replace("__SONG_TITLE__", esc(song.get("title", "I'm Upping My P(doom)")))
        .replace("__SONG_URL__", esc(song.get("original", "#")))
        .replace("__ABOUT_URL__", esc(song.get("about", "#")))
        .replace("__DATA_JSON__", payload)
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(page)
    (OUT_DIR / "videos.json").write_text(
        json.dumps(store, indent=2, ensure_ascii=False) + "\n"
    )
    (OUT_DIR / ".nojekyll").write_text("")
    print(f"Wrote {OUT_DIR/'index.html'} ({len(rest)} remixes, {len(originals)} originals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
