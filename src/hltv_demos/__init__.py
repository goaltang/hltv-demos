
"""HLTV demo fetcher for CS2: event -> matches -> played-map filter -> download -> extract.

Call via `await hltv_demos(...)` (see run() docstring) or CLI `hltv_demos`.
Hardened from real runs: Cloudflare needs curl_cffi chrome impersonation at
every hop (plain requests/curl/cloudscraper get 403); archives resume via
.part + Range; a manifest in ~/tools/hltv-demos prevents re-downloads; big
downloads validate byte size; HLTV map lists include unplayed veto maps, so
played-state must be checked per match page.
"""
import glob
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

BASE = "https://www.hltv.org"
WORK = os.path.expanduser("~/tools/hltv-demos")
MANIFEST = os.path.join(WORK, "manifest.json")
SEVENZ = os.path.join(WORK, "7zz")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# Chinese -> HLTV display names (case-insensitive lookup also covers English)
MAP_ALIASES = {
    "mirage": "Mirage", "nuke": "Nuke", "dust2": "Dust2",
    "ancient": "Ancient", "anubis": "Anubis", "cache": "Cache", "overpass": "Overpass",
    "train": "Train", "vertigo": "Vertigo", "inferno": "Inferno",
    "mills": "Mills", "grail": "Grail", "pool": "Pool",
    "荒漠迷城": "Mirage", "炼狱小镇": "Inferno", "核子危机": "Nuke",
    "炙热沙城ii": "Dust2", "炙热沙城2": "Dust2", "炙热沙城": "Dust2",
    "远古遗迹": "Ancient", "阿努比斯": "Anubis", "死亡游乐园": "Overpass",
    "列车停放站": "Train", "殒命大厦": "Vertigo", "币厂": "Cache", "加币": "Cache",
}


def resolve_maps(maps: str) -> list[str]:
    out = []
    for token in re.split(r"[,，、\s]+", (maps or "").strip()):
        if not token:
            continue
        name = MAP_ALIASES.get(token.lower().strip())
        if name is None:
            # allow de_mirage style and case variants
            key = token.lower().removeprefix("de_").strip()
            name = MAP_ALIASES.get(key)
        if name is None:
            raise ValueError(f"unknown map name: {token!r} (known: Mirage/Inferno/Nuke/... or 荒漠迷城/炼狱小镇/核子危机...)")
        if name not in out:
            out.append(name)
    return out


def _get(url: str, stream: bool = False, headers: dict | None = None, timeout=30, tries: int = 3):
    last = None
    for i in range(tries):
        try:
            r = cr.get(url, impersonate="chrome", timeout=timeout, stream=stream,
                       allow_redirects=not headers, headers=headers)
            if r.status_code == 200:
                return r
            last = f"http {r.status_code}"
            r.close()
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:80]}"
        time.sleep(2 + 3 * i)
    raise RuntimeError(f"GET failed after {tries} tries ({last}): {url}")


def _head_size(url: str) -> int:
    try:
        h = cr.head(url, impersonate="chrome", timeout=30)
        return int(h.headers.get("content-length") or 0)
    except Exception:
        return 0


def ensure_7zz() -> str:
    if os.path.exists(SEVENZ) and os.access(SEVENZ, os.X_OK):
        return SEVENZ
    os.makedirs(WORK, exist_ok=True)
    url = "https://www.7-zip.org/a/7z2501-linux-x64.tar.xz"
    tar = os.path.join(WORK, "7z.tar.xz")
    r = _get(url)
    with open(tar, "wb") as f:
        f.write(r.content)
    r.close()
    subprocess.run(["tar", "-xf", tar, "-C", WORK, "7zz"], check=True)
    os.chmod(SEVENZ, 0o755)
    return SEVENZ


def discover_csgo(explicit: str = "") -> str:
    cands = []
    if explicit:
        cands.append(explicit)
    env = os.environ.get("HLTV_DEMOS_CSGO_DIR")
    if env:
        cands.append(env)
    cands += [
        "/mnt/d/steam/steamapps/common/Counter-Strike Global Offensive",
        "/mnt/c/Program Files (x86)/Steam/steamapps/common/Counter-Strike Global Offensive",
        os.path.expanduser("~/.steam/steam/steamapps/common/Counter-Strike Global Offensive"),
        os.path.expanduser("~/.local/share/Steam/steamapps/common/Counter-Strike Global Offensive"),
    ]
    for root in glob.glob("/mnt/*/steamapps/common/Counter-Strike Global Offensive"):
        cands.append(root)
    for c in cands:
        demo_dir = os.path.join(c.rstrip("/"), "game", "csgo")
        if os.path.isdir(demo_dir) and os.access(demo_dir, os.W_OK):
            return demo_dir
    raise RuntimeError(
        "CS2 game/csgo dir not found (or not writable). Pass csgo_dir='<CS2 root>' "
        "or set env HLTV_DEMOS_CSGO_DIR to the 'Counter-Strike Global Offensive' root.")


def find_event(query: str) -> tuple[str, str]:
    r = _get(f"{BASE}/search?query={query.strip().replace(' ', '+')}")
    slugs = re.findall(r'href="/events/(\d+)/([a-z0-9-]+)"', r.text)
    r.close()
    if not slugs:
        raise RuntimeError(f"no HLTV event found for {query!r}")
    want = re.sub(r"[^a-z0-9]", "", query.lower())
    for eid, slug in slugs:
        if want and want in re.sub(r"[^a-z0-9]", "", slug):
            return eid, slug
    return slugs[0]


def list_results(event_id: str) -> list[dict]:
    r = _get(f"{BASE}/results?event={event_id}")
    soup = BeautifulSoup(r.text, "lxml")
    r.close()
    out = []
    for div in soup.select("div.result-con"):
        a = div.select_one("a.a-reset")
        if not a:
            continue
        t1 = div.select_one("div.team1")
        t2 = div.select_one("div.team2")
        sc = div.select_one("td.result-score")
        out.append({
            "teams": f"{t1.get_text(' ', strip=True) if t1 else '?'} vs {t2.get_text(' ', strip=True) if t2 else '?'}",
            "score": sc.get_text(" ", strip=True) if sc else "?",
            "path": a.get("href", ""),
        })
    return out


def fetch_match_page(match_path: str) -> tuple[list[str], str | None]:
    """Return (played map names, demo download path) from one match page (single fetch)."""
    r = _get(BASE + match_path)
    played = []
    for holder in BeautifulSoup(r.text, "lxml").select("div.mapholder"):
        nm = holder.select_one("div.mapname")
        res = holder.select_one("div.results")
        if nm and res and "played" in (res.get("class") or []):
            played.append(nm.get_text(strip=True))
    mm = re.search(r'href="(/download/demo[^"]+)"', r.text)
    r.close()
    return played, (mm.group(1) if mm else None)


def resolve_demo(demo_path: str) -> dict:
    r = cr.get(BASE + demo_path, impersonate="chrome", timeout=30, allow_redirects=False)
    loc = r.headers.get("location", "")
    r.close()
    if not loc:
        raise RuntimeError(f"demo {demo_path}: no redirect (HLTV may require login now)")
    return {"r2": loc, "name": loc.rsplit("/", 1)[-1], "size": _head_size(loc)}


def _manifest() -> dict:
    try:
        return json.load(open(MANIFEST))
    except Exception:
        return {}


def _save_manifest(m: dict) -> None:
    os.makedirs(WORK, exist_ok=True)
    json.dump(m, open(MANIFEST, "w"), indent=1, ensure_ascii=False)


def download(r2: str, size: int, dest: str) -> str:
    part = dest + ".part"
    offset = os.path.getsize(part) if os.path.exists(part) else 0
    if size and offset == size:
        os.replace(part, dest)
        return "resumed-complete"
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    t0 = time.time()
    r = cr.get(r2, impersonate="chrome", timeout=(30, 3600), stream=True, headers=headers)
    try:
        if r.status_code not in (200, 206):
            raise RuntimeError(f"download http {r.status_code}")
        mode = "ab" if (offset and r.status_code == 206) else "wb"
        got = offset if mode == "ab" else 0
        with open(part, mode) as f:
            for chunk in r.iter_content(1024 * 512):
                f.write(chunk)
                got += len(chunk)
    finally:
        r.close()
    if size and got != size:
        raise RuntimeError(f"size mismatch: got {got} want {size} (part kept for resume)")
    os.replace(part, dest)
    return f"downloaded {got/1e6:.0f}MB in {time.time()-t0:.0f}s"


def archive_demos(rar: str) -> list[str]:
    out = subprocess.run([ensure_7zz(), "l", "-ba", rar], capture_output=True, text=True, timeout=300)
    names = []
    for line in out.stdout.splitlines():
        parts_ = line.split()
        if parts_ and parts_[-1].lower().endswith(".dem"):
            names.append(parts_[-1])
    return names


def extract(rar: str, maps_wanted: list[str], csgo: str) -> list[dict]:
    done = []
    for name in archive_demos(rar):
        low = name.lower()
        for mp in maps_wanted:
            if low.endswith(f"-{mp.lower()}.dem"):
                dest = os.path.join(csgo, name)
                if os.path.exists(dest) and os.path.getsize(dest) > 0:
                    done.append({"file": name, "playdemo": name[:-4], "note": "already-extracted"})
                    break
                res = subprocess.run([ensure_7zz(), "x", "-y", rar, "-o" + csgo, name],
                                     capture_output=True, text=True, timeout=900)
                ok = "Everything is Ok" in (res.stdout + res.stderr)
                if ok:
                    done.append({"file": name, "playdemo": name[:-4], "note": "extracted"})
                else:
                    done.append({"file": name, "note": f"extract-failed: {res.stderr[-80:]}"})
                break
    return done


async def run(event: str = "", maps: str = "", latest: int = 0, keep_rars: bool = True,
              dry_run: bool = False, csgo_dir: str = "") -> dict:
    """Download HLTV CS2 demos for an event and install selected maps into the CS2 game/csgo dir.

    Args:
        event: HLTV event name/slug, e.g. "blast-open-porto-2026".
        maps: map filter, English or Chinese, comma separated, e.g. "炼狱小镇" or "Mirage,Nuke". Empty = all maps (rars only).
        latest: keep only the N most recent matching matches (0 = all).
        keep_rars: keep downloaded archive files in the downloads folder.
        dry_run: resolve and report the plan (matches, played maps, sizes) without downloading.
        csgo_dir: optional path to the 'Counter-Strike Global Offensive' root (overrides auto-discovery).

    Returns:
        dict with extracted demos (each with a ready `playdemo` command), downloaded/skipped
        archives, per-match map info and any errors.
    """
    if not event:
        return {"error": "event is required, e.g. event='blast-open-porto-2026'"}
    wanted = resolve_maps(maps) if maps else []
    csgo = discover_csgo(csgo_dir)
    dl_dir = os.environ.get("HLTV_DEMOS_DL_DIR") or next(
        (p for p in sorted(glob.glob("/mnt/*/Downloads")) if os.path.isdir(p)),
        os.path.expanduser("~/Downloads"))
    os.makedirs(dl_dir, exist_ok=True)
    man = _manifest()

    eid, slug = find_event(event)
    results = list_results(eid)

    selected = []
    for m in results:
        played, demo_path = fetch_match_page(m["path"]) if wanted else ([], None)
        m["played"], m["demo_path"] = played, demo_path
        if wanted:
            hit = [w for w in wanted if w in played]
            if hit:
                m["hit"] = hit
                selected.append(m)
        else:
            selected.append(m)
        time.sleep(0.4)
        if wanted and latest and len(selected) >= latest:
            break
    if latest and not wanted:
        selected = selected[:latest]

    plan = []
    for m in selected:
        demo_path = None
        entry = {}
        try:
            demo_path = m.get("demo_path")
            if demo_path is None:
                _, demo_path = fetch_match_page(m["path"])
            if demo_path:
                info = resolve_demo(demo_path)
                entry.update(info)
                entry["demo_id"] = demo_path.rsplit("/", 1)[-1]
            else:
                entry["error"] = "no demo link on match page"
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)[:120]
        plan.append({**m, **entry})

    if not wanted and not latest and not dry_run:
        return {
            "event": f"{eid}/{slug}", "mode": "refused",
            "note": "maps= is empty and latest=0: this would download EVERY match archive. "
                    "Pass maps='...' and/or latest=N, or dry_run=True to inspect first.",
            "all_matches": [m["teams"] for m in results],
        }

    if dry_run:
        return {
            "event": f"{eid}/{slug}", "csgo_dir": csgo, "mode": "dry-run",
            "maps": wanted, "matches": [
                {k: v for k, v in p.items() if k in ("teams", "score", "played", "hit", "name", "size", "demo_id", "error")}
                for p in plan
            ],
            "total_mb": round(sum(p.get("size", 0) for p in plan) / 1e6, 1),
        }

    extracted, downloaded, skipped, errors = [], [], [], []
    for p in plan:
        if not p.get("r2"):
            errors.append({"teams": p["teams"], "error": p.get("error", "no demo url")})
            continue
        dest = os.path.join(dl_dir, p["name"])
        p["dl_dir"] = dl_dir
        hit_maps = [w for w in wanted if w in p.get("played", [])] if wanted else []
        try:
            if os.path.exists(dest) and p["size"] and os.path.getsize(dest) == p["size"]:
                skipped.append(f"{p['teams']} (archive on disk)")
            else:
                adopted = None
                if p["size"]:
                    for cand in glob.glob(os.path.join(p["dl_dir"], "*.rar")):
                        if os.path.getsize(cand) == p["size"]:
                            adopted = cand
                            break
                if adopted:
                    dest = adopted
                    skipped.append(f"{p['teams']} (adopted same-size archive {os.path.basename(adopted)})")
                else:
                    note = download(p["r2"], p["size"], dest)
                    downloaded.append(f"{p['teams']}: {note}")
            got = extract(dest, hit_maps or wanted, csgo)
            for g in got:
                g["teams"] = p["teams"]
            extracted += got
            ent = man.get(p.get("demo_id", "?"), {})
            ent.update({"teams": p["teams"], "rar": dest, "size": p["size"],
                        "maps_extracted": sorted({g["file"] for g in got}),
                        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            man[p.get("demo_id", "?")] = ent
            _save_manifest(man)
            if not keep_rars and os.path.basename(dest) == p["name"] and os.path.exists(dest):
                os.remove(dest)
        except Exception as e:  # noqa: BLE001
            errors.append({"teams": p["teams"], "error": str(e)[:160]})

    return {
        "event": f"{eid}/{slug}", "csgo_dir": csgo, "maps": wanted,
        "selected_matches": [p["teams"] for p in plan],
        "downloaded": downloaded, "skipped": skipped,
        "extracted": extracted,
        "playdemo_commands": [g["playdemo"] for g in extracted if "playdemo" in g],
        "errors": errors,
        "total_demos_in_csgo": len([f for f in os.listdir(csgo) if f.endswith(".dem")]),
    }
