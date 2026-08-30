"""
Pulls fresh CCU / visits / group-member stats from the Roblox API for every
game in PLACE_IDS and regenerates ../cartridge_wall.html in place.

Run standalone: py scripts/refresh.py
Then republish with the Artifact tool using the same URL to push the update live.
"""
import json, os, time, base64, urllib.request, urllib.error, html, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

PLACE_IDS = [
    136680208905701, 140340279062020, 105215477731035, 109422846863419,
    104963759267884, 129768383418466, 130361766615221, 118403629519701,
    135787657971346, 98693477169705, 93268804142717, 124082555806669,
    6924758805, 116681772517483, 86223718444028, 92082396510209,
    76290649647929, 96899409615001, 86806930109334, 75433208977335,
]

UA = {"User-Agent": "Mozilla/5.0"}

def get_json(url, retries=6, backoff=5):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  429 rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if attempt == retries - 1:
                raise
            time.sleep(backoff)
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
            time.sleep(backoff)
    return None

def main():
    print(f"Resolving {len(PLACE_IDS)} places -> universes...")
    universe_by_place = {}
    for p in PLACE_IDS:
        d = get_json(f"https://apis.roblox.com/universes/v1/places/{p}/universe")
        universe_by_place[p] = d["universeId"]

    ids = ",".join(str(u) for u in universe_by_place.values())

    print("Fetching game stats...")
    games = get_json(f"https://games.roblox.com/v1/games?universeIds={ids}")["data"]

    print("Fetching icons...")
    icons_data = get_json(
        f"https://thumbnails.roblox.com/v1/games/icons?universeIds={ids}"
        "&size=512x512&format=Png&isCircular=false"
    )["data"]
    icon_url_by_universe = {x["targetId"]: x["imageUrl"] for x in icons_data}

    # reuse cached icon bytes when present so we don't re-download 20 images every run
    cache_path = "scripts/icon_cache.json"
    icon_cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}

    group_ids = sorted({g["creator"]["id"] for g in games})
    print(f"Fetching {len(group_ids)} group member counts (rate-limited, be patient)...")
    group_by_id = {}
    for i, gid in enumerate(group_ids):
        d = get_json(f"https://groups.roblox.com/v1/groups/{gid}")
        group_by_id[gid] = d
        time.sleep(6)

    out = []
    for g in games:
        uid = g["id"]
        creator = g["creator"]
        group_info = group_by_id.get(creator["id"], {})
        icon_b64 = icon_cache.get(str(uid))
        icon_url = icon_url_by_universe.get(uid)
        if icon_url and not icon_b64:
            try:
                req = urllib.request.Request(icon_url, headers=UA)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    icon_b64 = "data:image/png;base64," + base64.b64encode(resp.read()).decode("ascii")
                icon_cache[str(uid)] = icon_b64
            except Exception as e:
                print("icon fetch failed for", uid, e)

        out.append({
            "placeId": g["rootPlaceId"],
            "name": g["name"],
            "playing": g["playing"],
            "visits": g["visits"],
            "favorites": g.get("favoritedCount", 0),
            "groupId": creator["id"],
            "groupName": creator["name"],
            "groupMembers": group_info.get("memberCount", 0),
            "groupVerified": creator.get("hasVerifiedBadge", False),
            "icon": icon_b64,
        })

    json.dump(icon_cache, open(cache_path, "w", encoding="utf-8"))
    json.dump(out, open("scripts/combined.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("Fetched stats for", len(out), "games.")
    render(out)

def fmt(n):
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)

def fmt_exact(n):
    return f"{int(n):,}"

def render(games):
    from datetime import datetime, timezone
    games = sorted(games, key=lambda g: g["playing"], reverse=True)

    total_ccu = sum(g["playing"] for g in games)
    total_visits = sum(g["visits"] for g in games)
    total_members = sum(g["groupMembers"] for g in games)
    total_games = len(games)
    snapshot_label = datetime.now(timezone.utc).strftime("%b %-d, %Y %H:%M UTC") if os.name != "nt" \
        else datetime.now(timezone.utc).strftime("%b %d, %Y %H:%M UTC").replace(" 0", " ")

    card_tpl = """
      <article class="cart">
        <a class="cart-art" href="https://www.roblox.com/games/{place_id}" target="_blank" rel="noopener">
          <img src="{icon}" alt="{name_attr} box art" loading="lazy" width="512" height="512">
          <span class="cart-notch" aria-hidden="true"></span>
          {live_badge}
        </a>
        <div class="cart-body">
          <h3 class="cart-title">{name}</h3>
          <a class="cart-studio" href="https://www.roblox.com/communities/{group_id}" target="_blank" rel="noopener">
            {studio}{verified}
            <span class="cart-studio-members">{members} members</span>
          </a>
          <dl class="cart-stats">
            <div class="stat">
              <dt>Playing now</dt>
              <dd title="{playing_exact}">{playing}</dd>
            </div>
            <div class="stat">
              <dt>Visits</dt>
              <dd title="{visits_exact}">{visits}</dd>
            </div>
          </dl>
          <a class="cart-play" href="https://www.roblox.com/games/{place_id}" target="_blank" rel="noopener">
            <span>Play</span>
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2.5v11l9-5.5-9-5.5z" fill="currentColor"/></svg>
          </a>
        </div>
      </article>"""

    cards_html = []
    for g in games:
        verified = ' <svg class="verify" viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M8 0l1.8 1.2 2.1-.4 1 1.9 1.9 1-.4 2.1L15.6 8l-1.2 1.8.4 2.1-1.9 1-1 1.9-2.1-.4L8 16l-1.8-1.2-2.1.4-1-1.9-1.9-1 .4-2.1L.4 8l1.2-1.8-.4-2.1 1.9-1 1-1.9 2.1.4z" fill="currentColor"/><path d="M6.5 8.3l1.3 1.3 2.7-3" stroke="var(--surface)" stroke-width="1.3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>' if g["groupVerified"] else ""
        live_badge = '<span class="live-badge"><span class="live-dot"></span>Live</span>' if g["playing"] > 0 else ""
        cards_html.append(card_tpl.format(
            place_id=g["placeId"],
            group_id=g["groupId"],
            icon=g["icon"] or "",
            name=html.escape(g["name"]),
            name_attr=html.escape(g["name"], quote=True),
            studio=html.escape(g["groupName"]),
            verified=verified,
            members=fmt(g["groupMembers"]),
            playing=fmt(g["playing"]),
            playing_exact=fmt_exact(g["playing"]),
            visits=fmt(g["visits"]),
            visits_exact=fmt_exact(g["visits"]),
            live_badge=live_badge,
        ))

    cards_joined = "\n".join(cards_html)

    page = f"""<title>Cartridge Wall</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bungee&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap');

  :root {{
    --bg: #F1F2F6;
    --surface: #FFFFFF;
    --surface-2: #F7F8FB;
    --border: #DEE2EC;
    --text: #171B26;
    --text-muted: #5B6478;
    --accent: #B36A00;
    --accent-strong: #8F5500;
    --accent-on: #FFFFFF;
    --live: #16874F;
    --live-bg: rgba(22,135,79,0.10);
    --shadow: rgba(20,24,38,0.10);
  }}

  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #0B0E14;
      --surface: #12161F;
      --surface-2: #181D29;
      --border: #242A3A;
      --text: #EDEFF4;
      --text-muted: #8B93A7;
      --accent: #FFB020;
      --accent-strong: #FFC658;
      --accent-on: #1A1206;
      --live: #3DDC84;
      --live-bg: rgba(61,220,132,0.14);
      --shadow: rgba(0,0,0,0.45);
    }}
  }}

  :root[data-theme="dark"] {{
    --bg: #0B0E14;
    --surface: #12161F;
    --surface-2: #181D29;
    --border: #242A3A;
    --text: #EDEFF4;
    --text-muted: #8B93A7;
    --accent: #FFB020;
    --accent-strong: #FFC658;
    --accent-on: #1A1206;
    --live: #3DDC84;
    --live-bg: rgba(61,220,132,0.14);
    --shadow: rgba(0,0,0,0.45);
  }}

  * {{ box-sizing: border-box; }}
  html {{ color-scheme: light dark; }}

  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'IBM Plex Sans', system-ui, -apple-system, Segoe UI, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}

  a {{ color: inherit; text-decoration: none; }}
  a:focus-visible, button:focus-visible {{ outline: 3px solid var(--accent); outline-offset: 2px; }}

  .wrap {{
    max-width: 1180px;
    margin: 0 auto;
    padding: 0 24px 96px;
  }}

  .marquee {{
    position: relative;
    padding: 72px 24px 48px;
    text-align: center;
    overflow: hidden;
    background:
      radial-gradient(60% 100% at 50% 0%, color-mix(in srgb, var(--accent) 12%, transparent), transparent 70%),
      var(--bg);
    border-bottom: 1px solid var(--border);
  }}

  .marquee-eyebrow {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--text-muted);
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }}
  .marquee-eyebrow .dot {{
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--live);
    box-shadow: 0 0 0 3px var(--live-bg);
  }}

  h1.marquee-title {{
    font-family: 'Bungee', 'Segoe UI', sans-serif;
    font-weight: 400;
    font-size: clamp(34px, 6vw, 64px);
    line-height: 1.05;
    letter-spacing: 0.01em;
    margin: 18px 0 12px;
    text-wrap: balance;
    color: var(--text);
  }}
  h1.marquee-title span {{ color: var(--accent); }}

  .marquee-sub {{
    max-width: 560px;
    margin: 0 auto;
    color: var(--text-muted);
    font-size: 16px;
    line-height: 1.6;
    text-wrap: balance;
  }}

  .scoreboard {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1px;
    max-width: 880px;
    margin: 40px auto 0;
    background: var(--border);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }}
  .score {{
    background: var(--surface);
    padding: 20px 12px;
  }}
  .score dt {{
    font-size: 11px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin: 0 0 8px;
  }}
  .score dd {{
    margin: 0;
    font-family: 'IBM Plex Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    font-size: clamp(18px, 3vw, 26px);
    color: var(--text);
  }}
  .score.accent dd {{ color: var(--accent-strong); }}

  .shelf-heading {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin: 56px 0 20px;
    flex-wrap: wrap;
  }}
  .shelf-heading h2 {{
    font-family: 'Bungee', sans-serif;
    font-weight: 400;
    font-size: 20px;
    letter-spacing: 0.02em;
    margin: 0;
  }}
  .shelf-heading p {{
    margin: 0;
    color: var(--text-muted);
    font-size: 13px;
    font-family: 'IBM Plex Mono', monospace;
  }}

  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 20px;
  }}

  .cart {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    box-shadow: 0 1px 2px var(--shadow);
    transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
  }}
  .cart:hover {{
    transform: translateY(-3px);
    box-shadow: 0 12px 28px var(--shadow);
    border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  }}
  @media (prefers-reduced-motion: reduce) {{
    .cart {{ transition: none; }}
    .cart:hover {{ transform: none; }}
  }}

  .cart-art {{
    position: relative;
    display: block;
    aspect-ratio: 1 / 1;
    background: var(--surface-2);
  }}
  .cart-art img {{
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }}
  .cart-notch {{
    position: absolute;
    left: 0; right: 0; bottom: 0;
    height: 6px;
    background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 40%, transparent));
  }}
  .live-badge {{
    position: absolute;
    top: 10px; left: 10px;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: color-mix(in srgb, var(--bg) 70%, transparent);
    backdrop-filter: blur(4px);
    border: 1px solid var(--live-bg);
    color: var(--live);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 4px 8px 4px 6px;
    border-radius: 999px;
  }}
  .live-dot {{
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--live);
    animation: pulse 1.8s ease-in-out infinite;
  }}
  @media (prefers-reduced-motion: reduce) {{ .live-dot {{ animation: none; }} }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.35; }}
  }}

  .cart-body {{
    padding: 14px 16px 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    flex: 1;
  }}

  .cart-title {{
    margin: 0;
    font-family: 'IBM Plex Sans', sans-serif;
    font-weight: 700;
    font-size: 14.5px;
    line-height: 1.3;
    color: var(--text);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 2.6em;
  }}

  .cart-studio {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: 12px;
    color: var(--text-muted);
  }}
  .cart-studio:hover {{ color: var(--accent-strong); }}
  .cart-studio .verify {{ color: var(--accent); vertical-align: -1px; margin-left: 3px; }}
  .cart-studio-members {{
    font-family: 'IBM Plex Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-size: 11px;
    white-space: nowrap;
    color: var(--text-muted);
  }}

  .cart-stats {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin: 2px 0 0;
    padding: 10px 0;
    border-top: 1px dashed var(--border);
    border-bottom: 1px dashed var(--border);
  }}
  .cart-stats dt {{
    font-size: 10px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin: 0 0 3px;
  }}
  .cart-stats dd {{
    margin: 0;
    font-family: 'IBM Plex Mono', monospace;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    font-size: 15px;
    color: var(--text);
  }}

  .cart-play {{
    margin-top: auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    background: var(--accent);
    color: var(--accent-on);
    font-weight: 600;
    font-size: 13px;
    padding: 9px 14px;
    border-radius: 8px;
    transition: filter 0.12s ease;
  }}
  .cart-play:hover {{ filter: brightness(1.08); }}

  footer.page-footer {{
    text-align: center;
    color: var(--text-muted);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    padding: 40px 24px 0;
  }}
</style>

<div class="marquee">
  <span class="marquee-eyebrow"><span class="dot"></span>Snapshot &middot; {snapshot_label}</span>
  <h1 class="marquee-title">The <span>Cartridge</span> Wall</h1>
  <p class="marquee-sub">{total_games} Roblox titles shipped across {total_games} independent studios &mdash; live player counts, lifetime visits, and community size for each.</p>

  <dl class="scoreboard">
    <div class="score accent">
      <dt>Games shipped</dt>
      <dd>{total_games}</dd>
    </div>
    <div class="score">
      <dt>Playing right now</dt>
      <dd>{fmt_exact(total_ccu)}</dd>
    </div>
    <div class="score">
      <dt>Lifetime visits</dt>
      <dd>{fmt(total_visits)}</dd>
    </div>
    <div class="score">
      <dt>Combined community</dt>
      <dd>{fmt(total_members)}</dd>
    </div>
  </dl>
</div>

<div class="wrap">
  <div class="shelf-heading">
    <h2>All titles</h2>
    <p>sorted by players online</p>
  </div>
  <div class="grid">
{cards_joined}
  </div>

  <footer class="page-footer">Stats pulled live from the Roblox API at publish time &middot; tap a cartridge to play</footer>
</div>
"""
    open("cartridge_wall.html", "w", encoding="utf-8").write(page)
    print("Rendered cartridge_wall.html:", os.path.getsize("cartridge_wall.html"), "bytes")

if __name__ == "__main__":
    main()
