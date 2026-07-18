# Instagram Scroll

A self-hosted reel player for the pile of Instagram reels your wife (or
anyone) sends you. Import a Meta "Download your information" export, and it
picks up right where you left off, auto-advancing to the next reel when one
ends. Built to be cast to a TV and driven from your phone.

## How it works

- **Import**: drop your Meta export (zip, or the individual
  `message_*.json` files) into the app. It scans your messages for shared
  Instagram reel/post links, along with who sent them and when.
- **Fetch**: a background worker resolves each reel to an actual video file
  using [yt-dlp](https://github.com/yt-dlp/yt-dlp) (no login, no OAuth — this
  works for any public reel). It keeps the next handful of reels ready ahead
  of your current position, and works through the rest of the backlog in the
  background at a polite pace.
- **Play**: a plain `<video>` element gives you real control — auto-advance
  when a reel ends, scrubbing, and actual 2x playback — which Instagram's
  official embed widget can't offer (it's a cross-origin iframe with no
  "ended" event and no programmatic speed control).
- **Resume**: your position (which reel + how many seconds into it) is saved
  continuously to a small SQLite file, so reopening the app - on your phone,
  on the TV, wherever - jumps right back to where you stopped.

### Why not fully automatic, no-export ingestion?

I looked at this and it isn't something to build safely: Meta's official
APIs (Graph API / Instagram API) don't expose the content of your personal
DMs at all, for any account type — that data simply isn't reachable through
a legitimate API, OAuth or not. The only way to pull it "automatically"
would be to script your own logged-in Instagram session (an unofficial,
ToS-violating private-API integration), which is exactly the fragile,
account-risking approach you said you wanted to avoid. So the manual export
stays, but importing it is a single drag-and-drop.

## Requirements

- A Docker-capable home server (Raspberry Pi, NAS, mini PC, etc.)
- An existing reverse proxy (nginx, Caddy, Cloudflare Tunnel, ...) if you
  want a clean URL / access away from home — the container just exposes
  plain HTTP on port 8000.

## Quick start

```bash
git clone <this repo> instagram-scroll
cd instagram-scroll
docker compose up -d --build
```

The app is now on `http://<server-ip>:8000`. Point your reverse proxy at
that port (e.g. `reverse_proxy instagram-scroll:8000` in a Caddyfile, or an
nginx `proxy_pass http://127.0.0.1:8000;`), and put it behind a login if
your proxy supports it (Caddy `basicauth`, an nginx `auth_basic`, or your
Cloudflare Tunnel/Access policy) since the app itself has no auth of its
own — it's a single-user tool.

Data (the SQLite DB and downloaded videos) lives in `./data` next to the
compose file, so it survives rebuilds/updates.

## Getting a Meta export

1. Instagram app/site → your profile → **Settings** → **Accounts Center** →
   **Your information and permissions** → **Download your information**.
2. Choose **Some of your information** → **Messages** (select just the
   thread with the person who sends you reels, to keep the export small).
3. **Format: JSON** (important — the HTML export is parsed on a best-effort
   basis and can't recover reliable timestamps for ordering).
4. Date range: pick "since [last export date]" if you remember it, or "all
   time" the first time. Re-importing is safe — duplicates are skipped
   automatically.
5. Once Meta emails you the export, drop the `.zip` straight into the app
   via the **+** button (or unzip and drop the `message_1.json`,
   `message_2.json`, ... files directly — both work).

## Using the player

- **Play/pause**: tap the button, or `space`
- **Seek**: drag the progress bar, or `←`/`→` for ±10s
- **Prev/next reel**: buttons, or `↑`/`↓`
- **Speed**: cycles 1x → 1.25x → 1.5x → 2x, or `s`
- **Fullscreen**: useful before casting, or `f`
- **Auto: On/Off**: turn off if you want to stay on one reel (e.g. to show
  someone) without it jumping away when it ends
- Reels that fail to fetch (deleted, private, blocked) are skipped
  automatically after a few seconds, with a **Retry** button in case it was
  a transient block

### Casting to the TV

This is just a normal web page, so any of these work:

- Open it in the TV's own browser (works well on smart TVs with a browser)
- Cast/mirror a Chrome tab from your phone or laptop to a Chromecast/Fire TV
- AirPlay the browser tab to an Apple TV

Hit fullscreen (`f`) first so there's no browser chrome on screen. Your
phone stays fully usable as a remote — the resume position is shared
through the server, so if you also open the app on your phone it reads the
same "currently watching" state (last save wins if you have both open at
once, so avoid actively scrubbing on two devices at the same time).

## Configuration

Environment variables (set in `docker-compose.yml`):

| Variable | Default | Meaning |
|---|---|---|
| `PREFETCH_WINDOW` | `6` | How many reels ahead to always keep pre-fetched |
| `FETCH_DELAY_SECONDS` | `3` | Delay between downloads (politeness/rate-limit avoidance) |
| `CACHE_KEEP_BEHIND` | `30` | Delete cached video files more than N reels behind your current position (re-fetched on demand if you scroll back) |
| `MAX_FETCH_ATTEMPTS` | `3` | Retries before marking a reel "failed" |
| `COOKIES_FILE` | unset | Path to a Netscape-format `cookies.txt` exported from your own logged-in browser, only needed for reels from private accounts. Optional, not OAuth. |

## Limitations

- Reels from private accounts you don't follow (or that get rate-limited)
  will fail to fetch; a personal `cookies.txt` can unblock those, but it's
  entirely optional.
- Instagram can change its site layout; `yt-dlp`'s Instagram extractor is
  actively maintained, but if fetching breaks entirely, `docker compose
  pull && docker compose up -d --build` to grab a newer yt-dlp usually fixes
  it (bump the version pin in `backend/requirements.txt` if needed).
- This is a single-user tool with no authentication built in — put it
  behind your reverse proxy's auth if it's reachable from outside your home
  network.
