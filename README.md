# P(doom) Remixes

A static, self-updating index of remixes, covers and alternate renditions of the
song **"I'm Upping My P(doom)"** (lyrics by [osmarks](https://docs.osmarks.net/hypha/p%28doom%29_song_objectively_correct_interpretation),
opening verse/chorus by MusicPerson, original generated with Udio, November 2024).

- **Live site:** https://brainwagon.github.io/pdoom-remixes/
- **Raw data:** `data/videos.json` (served as `videos.json` on the site)

## How it works

A GitHub Action (`.github/workflows/update.yml`) runs **once a day**, and can also
be triggered manually from the Actions tab. It:

1. searches YouTube (via `yt-dlp`), SoundCloud (via `yt-dlp`) and — when a
   `SUNO_TOKEN` secret is configured — Suno, for renditions of the song;
2. classifies each hit as a genuine new rendition (`remix` / `cover` / `version`),
   an original, or merely a new music video for the existing audio (`visual`);
3. **appends** the genuine renditions to `data/videos.json`;
4. rebuilds `public/index.html` and commits both;
5. deploys `public/` to GitHub Pages.

### Append-only guarantee

`data/videos.json` is **append-only**. Once a video is listed it is never
removed: if it later disappears from search results, is made private, or is
pulled from the platform, it stays on the page (with its original `first_seen`
date). The only exception is an explicit `force_exclude` entry in
`data/curation.json` — a human decision applied before a video is ever added.

## Manual curation

Edit `data/curation.json`:

```jsonc
{
  // URLs fetched directly on every run (e.g. the canonical originals),
  // so they are present even if search never returns them.
  "seed_urls": ["https://www.youtube.com/watch?v=uEB5E67vcPA"],

  // Keys never to add. Keys look like "youtube:<id>", "soundcloud:<id>",
  // "suno:<id>".
  "force_exclude": [],

  // Keys to add even if the classifier would drop them (e.g. an unusual
  // cover it mistook for a re-upload).
  "force_include": [],

  // Force the type: original | remix | cover | version | visual.
  "kind_overrides": { "youtube:uEB5E67vcPA": "original" }
}
```

Keys for anything already on the page can be read from `data/videos.json`.

## Classification

"Strict remixes and covers only" means: a new *music video* for the exact same
recording is **not** included, but anything that is a genuinely different
rendition is. The classifier looks at the title/description for musical signals
(remix, cover, a language, a genre, instrumental, slowed, …) and compares the
duration against the canonical recordings (132 s and 157 s). A same-length item
with no musical signal is treated as a re-upload and skipped.

Because this is a heuristic, a few items will inevitably be misjudged — fix them
with `kind_overrides` or `force_exclude`.

## Local development

```bash
pip install yt-dlp
python scripts/scrape.py     # update data/videos.json (append-only)
python scripts/build.py      # write public/index.html
python -m http.server -d public
```

## Suno (optional)

Suno's search API needs a bearer token. Export `SUNO_TOKEN` (the `__session`
cookie value, or a JWT from the network tab) and the daily run will include
Suno results. Store it as the repository secret `SUNO_TOKEN`. If it is absent,
Suno is skipped and everything else still works.

## Credits

Not affiliated with the song's authors. The song and lyrics belong to their
authors; this project only indexes public performances of it.
