#!/usr/bin/env python3
"""Discover remixes/covers of the song "I'm Upping My P(doom)".

Sources:
  * YouTube      -- yt-dlp ytsearch (no API key)
  * SoundCloud   -- yt-dlp scsearch (no API key)
  * Suno         -- public search API, needs a bearer token (optional)

The dataset in data/videos.json is APPEND-ONLY: a video that has been
seen once is never dropped, even if it disappears from search results.
Manual decisions live in data/curation.json.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "videos.json"
CURATION_FILE = ROOT / "data" / "curation.json"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

# --------------------------------------------------------------------------
# What counts as the song
# --------------------------------------------------------------------------

# Strong, unambiguous references to the song itself.
STRONG_PHRASES = [
    r"up+ing\s+my\s+p",             # upping my p(doom) / pdoom
    r"up\s+my\s+p",
    r"lower\w*\s+my\s+p",           # lower/lowering my p(doom)
    r"lower\s+the\s+p",
    r"rais\w*\s+my\s+p",
    r"answer\s+to\s+p\s*[\(\[{]?\s*do+m",  # answer to P(doom)
]

# Tokens that name the song but also name the AI-risk meme; they only count
# when the item also looks like music (otherwise they are podcasts/interviews).
SONG_TOKEN = re.compile(
    r"p\s*[\(\[{]\s*do+m\s*[\)\]}]|\bpdo+m\b|\bp\s*/\s*do+m\b"
)

# Words that mean "this is a piece of music / a rendition".
MUSIC_SIGNALS = [
    r"\bremix", r"\bcover", r"\bversion\b", r"\bmix\b", r"\bre-?mix",
    r"\bsong\b", r"\bmusic\b", r"\bmusical\b", r"\bremake\b", r"\brebuild\b",
    r"\bremaster", r"\bslowed\b", r"\bsped[ -]?up\b", r"\breverb",
    r"\b8-?bit\b", r"\bchip-?tune\b", r"\bmetal\b", r"\brock\b", r"\bjazz\b",
    r"\bpop\b", r"\bjungle\b", r"\btrance\b", r"\bpunk\b", r"\bphonk\b",
    r"\blo-?fi\b", r"\borchestral\b", r"\binstrumental\b", r"\bparody\b",
    r"\bakapella\b", r"\bkaraoke\b", r"\bnightcore\b", r"\bopera\b",
    r"\banime\b", r"\bvocaloid\b", r"\bacoustic\b", r"\bpiano\b",
]

# Talk formats that mention p(doom) but are not renditions of the song.
TALK_PATTERNS = [
    r"\bpodcast\b", r"\binterview\b", r"\blex fridman\b", r"\bbill maher\b",
    r"\breal time with\b", r"\bexplained\b", r"\bdocumentary\b",
    r"\bpanel\b", r"\bwill ai destroy\b", r"\bmost disturbing number\b",
    r"\bwarns\b", r"\bprobability that ai\b", r"\bdebate\b",
]


def norm(text: str) -> str:
    return (text or "").lower()


def song_related(*texts: str) -> bool:
    """True when the text looks like a rendition of *this* song."""
    title = norm(texts[0] if texts else "")
    whole = norm(" ".join(t or "" for t in texts))

    if any(re.search(p, title) for p in STRONG_PHRASES):
        return True
    # A bare p(doom)-style token only counts alongside a music signal.
    if SONG_TOKEN.search(whole) and any(
        re.search(p, whole) for p in MUSIC_SIGNALS
    ):
        if any(re.search(p, title) for p in TALK_PATTERNS):
            return False
        return True
    return False


def has_audio_cover_signal(*texts: str) -> bool:
    blob = norm(" ".join(t or "" for t in texts))
    return any(re.search(p, blob) for p in AUDIO_COVER_PATTERNS)


# Visual-style words like "retro", "pixel", "anime", "blender" are NOT signals,
# because a new music video for the same audio is a re-upload, not a remix.
AUDIO_COVER_PATTERNS = [
    r"\bremix", r"\bcover", r"\bmashup", r"\bmash-up", r"\bbootleg",
    r"\brework", r"\breimagined", r"\brearrangement", r"\bremake",
    r"\bre-?made\b", r"\bedit\b", r"\bflip\b", r"\bremaster", r"\bredux\b",
    r"\binstrumental", r"\bkaraoke", r"\bacoustic", r"\bpiano\b",
    r"\borchestral", r"\bsymphonic",
    r"\bmetal\b", r"\brock\b", r"\bjazz\b", r"\blo-?fi\b", r"\bphonk\b",
    r"\bchip-?tune\b", r"\b8-?bit\b", r"\bchiptune\b", r"\bhardstyle\b",
    r"\btechno\b", r"\bedm\b", r"\bsynthwave\b", r"\bnightcore\b",
    r"\bsped[ -]?up\b", r"\bslowed\b", r"\breverb\b", r"\bvocaloid\b",
    r"\bai cover\b", r"\bsung by\b", r"\bperformed by\b", r"\btype beat\b",
    r"in the style of", r"\barrangement\b", r"\bmedley\b", r"\bparody\b",
    r"\brussian\b", r"\bjapanese\b", r"\bkorean\b", r"\bspanish\b",
    r"\bfrench\b", r"\bgerman\b", r"\bpolish\b", r"\bportuguese\b",
    r"\bitalian\b", r"\bhindi\b", r"\bmandarin\b", r"\bchinese\b",
    r"\bj-?rock\b", r"\bk-?pop\b", r"\bj-?pop\b", r"\brap\b", r"\bhip-?hop\b",
    r"\bcountry\b", r"\bballad\b", r"\bchoir\b", r"\b8d\b",
]

# Durations (seconds) of the canonical recordings. A video of canonical
# length with no audio-cover signal is treated as a re-upload / new visuals
# for existing audio and is excluded under "strict" mode.
CANONICAL_DURATIONS = [132, 157]
DURATION_TOLERANCE = 4


def near_canonical(duration) -> bool:
    if not duration:
        return False
    return any(abs(duration - c) <= DURATION_TOLERANCE for c in CANONICAL_DURATIONS)


def classify(meta: dict) -> str:
    """Return one of: original | remix | cover | version | visual | unknown."""
    title = meta.get("title") or ""
    desc = meta.get("description") or ""
    blob = norm(title + " " + desc)
    duration = meta.get("duration")

    # Seed/curated originals win.
    if meta.get("kind"):
        return meta["kind"]

    if re.search(r"\bremix", blob):
        return "remix"
    if re.search(r"\bcover", blob):
        return "cover"
    if has_audio_cover_signal(title, desc):
        return "cover"
    if duration and not near_canonical(duration):
        # A different recording length almost always means a re-recording.
        return "version"
    if duration is None:
        return "unknown"
    # Canonical length, no musical signal: new moving pictures on old audio.
    return "visual"


# --------------------------------------------------------------------------
# Search backends
# --------------------------------------------------------------------------

YT_QUERIES = [
    "I'm Upping My P(doom)",
    "Upping My P(doom) remix",
    "Upping My P(doom) cover",
    "Upping My P(doom) instrumental",
    "Upping My P(doom) version",
    "P(doom) song",
    "P(doom) Claude Pop",
    "pdoom song cover",
    "I'm Upping My Pdoom",
    "P/doom song",
    "Upping My P(doom) Russian",
    "Upping My P(doom) AI",
]

SC_QUERIES = [
    "I'm Upping My P(doom)",
    "Upping My P(doom) remix",
    "Upping My P(doom) cover",
    "p(doom) song",
]


def yt_dlp(args: list[str], timeout: int = 180) -> list[dict]:
    cmd = ["yt-dlp", "--no-warnings", "--ignore-errors", *args]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"[yt-dlp] {exc}", file=sys.stderr)
        return []
    items = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return items


def youtube_search(query: str, limit: int = 50) -> list[dict]:
    return yt_dlp(
        [f"ytsearch{limit}:{query}", "--flat-playlist", "--dump-json"]
    )


def soundcloud_search(query: str, limit: int = 40) -> list[dict]:
    return yt_dlp(
        [f"scsearch{limit}:{query}", "--flat-playlist", "--dump-json"]
    )


def fetch_details(url: str) -> dict:
    """Full metadata for one item (upload date, description, thumbnails)."""
    items = yt_dlp(["-J", url], timeout=120)
    return items[0] if items else {}


def suno_search(query: str, token: str, limit: int = 50) -> list[dict]:
    """Best-effort Suno search. Requires SUNO_TOKEN (bearer JWT / __session)."""
    url = "https://studio-api-prod.suno.com/api/search/"
    body = {
        "search_queries": [
            {
                "name": "public_song",
                "search_type": "public_song",
                "term": query,
                "from_index": 0,
                "size": limit,
                "is_public": True,
            }
        ]
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": UA,
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[suno] search failed: {exc}", file=sys.stderr)
        return []
    results = []
    for group in (payload.get("search_queries") or payload.get("results") or []):
        for song in group.get("results", group.get("songs", [])) or []:
            results.append(
                {
                    "id": song.get("id"),
                    "title": song.get("title") or song.get("name"),
                    "uploader": (song.get("display_name")
                                 or song.get("handle") or "Suno"),
                    "audiopath": song.get("audio_url"),
                    "image": song.get("image_url") or song.get("image_large_url"),
                    "created": song.get("created_at") or song.get("created"),
                }
            )
    return results


# --------------------------------------------------------------------------
# Normalisation / store
# --------------------------------------------------------------------------

def yt_thumb(vid: str) -> str:
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"


def from_youtube(item: dict) -> dict:
    vid = item.get("id")
    return {
        "key": f"youtube:{vid}",
        "platform": "youtube",
        "id": vid,
        "url": item.get("url") or f"https://www.youtube.com/watch?v={vid}",
        "title": item.get("title"),
        "channel": item.get("uploader") or item.get("channel"),
        "channel_url": item.get("channel_url"),
        "duration": item.get("duration"),
        "thumbnail": yt_thumb(vid) if vid else None,
        "views": item.get("view_count"),
    }


def from_soundcloud(item: dict) -> dict:
    sid = item.get("id")
    return {
        "key": f"soundcloud:{sid}",
        "platform": "soundcloud",
        "id": str(sid),
        "url": item.get("url") or item.get("webpage_url"),
        "title": item.get("title"),
        "channel": item.get("uploader") or item.get("channel"),
        "channel_url": item.get("channel_url") or item.get("uploader_url"),
        "duration": item.get("duration"),
        "thumbnail": item.get("thumbnail") or item.get("image"),
        "views": item.get("view_count"),
    }


def from_suno(item: dict) -> dict:
    sid = item.get("id")
    return {
        "key": f"suno:{sid}",
        "platform": "suno",
        "id": str(sid),
        "url": f"https://suno.com/song/{sid}",
        "title": item.get("title"),
        "channel": item.get("uploader") or "Suno",
        "channel_url": None,
        "duration": None,
        "thumbnail": item.get("image"),
        "views": None,
    }


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text())
    return default


def _published(details: dict) -> str | None:
    ts = details.get("timestamp") or details.get("release_timestamp")
    if ts:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    upload = details.get("upload_date")
    if upload:
        return f"{upload[0:4]}-{upload[4:6]}-{upload[6:8]}"
    return None


def enrich(entry: dict, details: dict | None = None) -> dict:
    """Fetch richer metadata for a candidate before classification."""
    if details is None:
        try:
            details = fetch_details(entry["url"])
        except Exception:  # noqa: BLE001 - enrichment is best effort
            details = {}
    if details:
        entry["description"] = details.get("description")
        entry["duration"] = details.get("duration") or entry.get("duration")
        entry["views"] = details.get("view_count") or entry.get("views")
        entry["channel"] = (
            details.get("uploader") or details.get("channel") or entry.get("channel")
        )
        entry["channel_url"] = (
            details.get("channel_url") or entry.get("channel_url")
        )
        ts = details.get("timestamp") or details.get("release_timestamp")
        upload = details.get("upload_date")
        if ts:
            entry["published"] = datetime.fromtimestamp(
                ts, tz=timezone.utc
            ).strftime("%Y-%m-%d")
        elif upload:
            entry["published"] = (
                f"{upload[0:4]}-{upload[4:6]}-{upload[6:8]}"
            )
        thumbs = details.get("thumbnails") or []
        if thumbs:
            entry["thumbnail"] = thumbs[-1].get("url") or entry.get("thumbnail")
        entry["tags"] = details.get("tags")
    return entry


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    store = load_json(DATA_FILE, {"videos": []})
    curation = load_json(
        CURATION_FILE,
        {"seed_urls": [], "force_include": [], "force_exclude": [], "kind_overrides": {}},
    )
    known = {v["key"]: v for v in store.get("videos", [])}
    force_include = set(curation.get("force_include", []))
    force_exclude = set(curation.get("force_exclude", []))
    kind_overrides = curation.get("kind_overrides", {})

    candidates: dict[str, dict] = {}

    print("Searching YouTube ...")
    for q in YT_QUERIES:
        for item in youtube_search(q):
            if item.get("id"):
                cand = from_youtube(item)
                candidates.setdefault(cand["key"], cand)

    print("Searching SoundCloud ...")
    for q in SC_QUERIES:
        for item in soundcloud_search(q):
            if item.get("id") is not None:
                cand = from_soundcloud(item)
                candidates.setdefault(cand["key"], cand)

    token = os.environ.get("SUNO_TOKEN", "").strip()
    if token:
        print("Searching Suno ...")
        for q in ["upping my p(doom)", "p(doom)", "claude pop pdoom"]:
            for item in suno_search(q, token):
                if item.get("id"):
                    cand = from_suno(item)
                    candidates.setdefault(cand["key"], cand)
    else:
        print("SUNO_TOKEN not set - skipping Suno.")

    # Curated seeds are fetched directly so they survive even if search misses.
    for url in curation.get("seed_urls", []):
        details = fetch_details(url)
        if not details:
            print(f"  ! seed unavailable: {url}", file=sys.stderr)
            continue
        is_sc = "soundcloud" in (details.get("extractor_key", "") + url).lower()
        entry = from_soundcloud(details) if is_sc else from_youtube(details)
        entry.update(description=details.get("description"),
                     published=_published(details))
        entry = enrich(entry, details)
        entry["_seed"] = True
        candidates[entry["key"]] = entry

    new_keys = [k for k in candidates if k not in known]
    print(f"{len(candidates)} candidates, {len(new_keys)} new.")

    added = 0
    for key in new_keys:
        entry = candidates[key]
        seed = entry.pop("_seed", False)
        if key in force_exclude and not seed:
            continue
        if not seed and not song_related(entry.get("title")):
            continue

        # Classify from the cheap search metadata first; only spend a full
        # metadata fetch on items that plausibly belong on the page.
        pre_kind = kind_overrides.get(key) or classify(entry)
        if not seed and key not in force_include and pre_kind not in (
            "remix", "cover", "version"
        ):
            continue

        if not seed:
            entry = enrich(entry)
            if not song_related(entry.get("title"), entry.get("description")):
                continue

        kind = kind_overrides.get(key) or classify(entry)
        entry["kind"] = kind
        entry["first_seen"] = today
        entry["last_seen"] = today

        # Strict mode: only keep genuine new renditions.
        if (kind in ("visual", "unknown")
                and key not in force_include and not seed):
            continue

        known[key] = entry
        store["videos"].append(entry)
        added += 1
        print(f"  + [{kind}] {entry.get('title')} ({key})")

    # Update last_seen for everything seen in this run.
    for key, entry in known.items():
        if key in candidates:
            entry["last_seen"] = today

    store["videos"] = sorted(
        known.values(),
        key=lambda v: (v.get("published") or v.get("first_seen") or "", v["key"]),
        reverse=True,
    )
    store["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.setdefault("song", {
        "title": "I'm Upping My P(doom)",
        "original": "https://www.youtube.com/watch?v=uEB5E67vcPA",
        "about": "https://docs.osmarks.net/hypha/p%28doom%29_song_objectively_correct_interpretation",
    })

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(store, indent=2, ensure_ascii=False) + "\n")
    print(f"Added {added}; dataset now has {len(store['videos'])} videos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
