"""HLTV demo fetcher for CS2: event -> matches -> played-map filter -> download -> extract.

Call via `await hltv_demos(...)` (see run() docstring) or CLI `hltv_demos`.
Hardened from real runs: Cloudflare needs curl_cffi chrome impersonation at
every hop (plain requests/curl/cloudscraper get 403); archives resume via
.part + Range; a manifest in ~/tools/hltv-demos prevents re-downloads; big
downloads validate byte size; HLTV map lists include unplayed veto maps, so
played-state must be checked per match page.
"""
import asyncio
import glob
import json
import os
import re
import subprocess
import tempfile
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
    """List every event result, following HLTV's 100-result pagination."""
    out = []
    seen = set()
    for offset in range(0, 10_000, 100):
        suffix = f"&offset={offset}" if offset else ""
        r = _get(f"{BASE}/results?event={event_id}{suffix}")
        soup = BeautifulSoup(r.text, "lxml")
        r.close()
        rows = soup.select("div.result-con")
        added = 0
        for div in rows:
            a = div.select_one("a.a-reset")
            path = a.get("href", "") if a else ""
            if not path or path in seen:
                continue
            seen.add(path)
            added += 1
            t1 = div.select_one("div.team1")
            t2 = div.select_one("div.team2")
            sc = div.select_one("td.result-score")
            out.append({
                "teams": f"{t1.get_text(' ', strip=True) if t1 else '?'} vs {t2.get_text(' ', strip=True) if t2 else '?'}",
                "score": sc.get_text(" ", strip=True) if sc else "?",
                "path": path,
            })
        if len(rows) < 100 or not added:
            break
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
        with open(MANIFEST, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_manifest(m: dict) -> None:
    """Atomically save the manifest so interruption cannot corrupt it."""
    os.makedirs(WORK, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="manifest-", suffix=".tmp", dir=WORK)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, MANIFEST)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def download(r2: str, size: int, dest: str) -> str:
    part = dest + ".part"
    offset = os.path.getsize(part) if os.path.exists(part) else 0
    if size and offset == size:
        os.replace(part, dest)
        return "resumed-complete"
    if size and offset > size:
        os.remove(part)
        offset = 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    t0 = time.time()
    r = cr.get(r2, impersonate="chrome", timeout=(30, 3600), stream=True, headers=headers)
    try:
        if r.status_code not in (200, 206):
            raise RuntimeError(f"download http {r.status_code}")
        if offset and r.status_code == 206:
            content_range = r.headers.get("content-range", "")
            if not re.match(rf"bytes\s+{offset}-\d+/", content_range, re.I):
                raise RuntimeError(f"invalid resume response: {content_range!r}")
        mode = "ab" if (offset and r.status_code == 206) else "wb"
        got = offset if mode == "ab" else 0
        with open(part, mode) as f:
            for chunk in r.iter_content(1024 * 512):
                if chunk:
                    f.write(chunk)
                    got += len(chunk)
    finally:
        r.close()
    if size and got != size:
        raise RuntimeError(f"size mismatch: got {got} want {size} (part kept for resume)")
    os.replace(part, dest)
    return f"downloaded {got/1e6:.0f}MB in {time.time()-t0:.0f}s"


def archive_demos(rar: str) -> list[dict]:
    """List demo members and their uncompressed sizes using 7-Zip's stable format."""
    out = subprocess.run(
        [ensure_7zz(), "l", "-slt", rar], capture_output=True, text=True, timeout=300
    )
    if out.returncode != 0:
        raise RuntimeError(f"cannot list archive: {(out.stderr or out.stdout)[-160:]}")
    demos = []
    current = {}
    for line in out.stdout.splitlines() + [""]:
        if not line.strip():
            path = current.get("Path", "")
            if path.lower().endswith(".dem") and current.get("Folder", "-") != "+":
                normalized = path.replace("\\", "/")
                parts = normalized.split("/")
                if normalized.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", normalized):
                    raise RuntimeError(f"unsafe demo member path: {path!r}")
                try:
                    member_size = int(current.get("Size", "0"))
                except ValueError:
                    member_size = 0
                demos.append({"member": path, "file": os.path.basename(normalized),
                              "size": member_size})
            current = {}
        elif " = " in line:
            key, value = line.split(" = ", 1)
            current[key] = value
    return demos


def test_archive(rar: str) -> None:
    result = subprocess.run([ensure_7zz(), "t", rar], capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"archive integrity test failed: {(result.stderr or result.stdout)[-160:]}")


def _wanted_members(members: list[dict], maps_wanted: list[str]) -> list[dict]:
    if not maps_wanted:
        return members
    return [m for m in members if any(
        m["file"].lower().endswith(f"-{mp.lower()}.dem") for mp in maps_wanted
    )]


def extract(rar: str, maps_wanted: list[str], csgo: str) -> list[dict]:
    """Extract through a temp dir, validate size, then atomically install each demo."""
    done = []
    for item in _wanted_members(archive_demos(rar), maps_wanted):
        name, member, expected = item["file"], item["member"], item["size"]
        if not name or name in (".", ".."):
            continue
        dest = os.path.join(csgo, name)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            actual_existing = os.path.getsize(dest)
            if not expected or actual_existing == expected:
                done.append({"file": name, "playdemo": name[:-4], "note": "already-extracted",
                             "size": actual_existing})
                continue
            raise RuntimeError(
                f"existing demo conflict for {name}: size {actual_existing}, expected {expected}; "
                "existing file was preserved"
            )
        with tempfile.TemporaryDirectory(prefix="hltv-demo-", dir=csgo) as tmp:
            # `e` discards archive paths, preventing path traversal outside tmp.
            res = subprocess.run([ensure_7zz(), "e", "-y", rar, "-o" + tmp, member],
                                 capture_output=True, text=True, timeout=900)
            candidate = os.path.join(tmp, name)
            actual = os.path.getsize(candidate) if os.path.isfile(candidate) else 0
            if res.returncode != 0 or actual == 0 or (expected and actual != expected):
                detail = (res.stderr or res.stdout)[-120:]
                raise RuntimeError(
                    f"extract failed for {name}: size {actual}, expected {expected}; {detail}"
                )
            os.replace(candidate, dest)
        done.append({"file": name, "playdemo": name[:-4], "note": "extracted", "size": actual})
    return done


def _completed_from_manifest(entry: dict, maps_wanted: list[str], csgo: str) -> list[dict]:
    """Return valid installed files if the manifest fully covers this request."""
    recorded = entry.get("extracted_files", {})
    if not isinstance(recorded, dict) or not recorded:
        return []
    valid = []
    for name, expected in recorded.items():
        dest = os.path.join(csgo, os.path.basename(name))
        try:
            actual = os.path.getsize(dest)
        except OSError:
            continue
        if actual > 0 and (not expected or actual == expected):
            valid.append({"file": os.path.basename(name), "playdemo": os.path.basename(name)[:-4],
                          "note": "manifest-skip", "size": actual})
    if maps_wanted:
        if any(not any(g["file"].lower().endswith(f"-{mp.lower()}.dem") for g in valid)
               for mp in maps_wanted):
            return []
        return [g for g in valid if any(
            g["file"].lower().endswith(f"-{mp.lower()}.dem") for mp in maps_wanted
        )]
    archive_files = entry.get("archive_demos", [])
    if not archive_files or any(not any(g["file"] == name for g in valid) for name in archive_files):
        return []
    return valid


def _run(event: str = "", maps: str = "", latest: int = 0, keep_rars: bool = True,
         dry_run: bool = False, csgo_dir: str = "") -> dict:
    if not event:
        return {"error": "event is required, e.g. event='blast-open-porto-2026'"}
    if latest < 0:
        return {"error": "latest must be 0 or greater"}
    wanted = resolve_maps(maps) if maps else []
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
        if wanted and latest and len(selected) >= latest:
            break
        time.sleep(0.4)
    if latest and not wanted:
        selected = selected[:latest]

    if not wanted and not latest and not dry_run:
        return {
            "event": f"{eid}/{slug}", "mode": "refused",
            "note": "maps= is empty and latest=0: this would download EVERY match archive. "
                    "Pass maps='...' and/or latest=N, or dry_run=True to inspect first.",
            "all_matches": [m["teams"] for m in results],
        }

    plan = []
    for m in selected:
        entry = {}
        try:
            demo_path = m.get("demo_path")
            if demo_path is None:
                _, demo_path = fetch_match_page(m["path"])
            if demo_path:
                entry.update(resolve_demo(demo_path))
                entry["demo_id"] = demo_path.rsplit("/", 1)[-1]
            else:
                entry["error"] = "no demo link on match page"
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)[:120]
        plan.append({**m, **entry})

    if dry_run:
        try:
            found_csgo = discover_csgo(csgo_dir)
        except RuntimeError:
            found_csgo = None
        return {
            "event": f"{eid}/{slug}", "csgo_dir": found_csgo, "mode": "dry-run",
            "maps": wanted, "matches": [
                {k: v for k, v in item.items()
                 if k in ("teams", "score", "played", "hit", "name", "size", "demo_id", "error")}
                for item in plan
            ],
            "total_mb": round(sum(item.get("size", 0) for item in plan) / 1e6, 1),
        }

    csgo = discover_csgo(csgo_dir)
    dl_dir = os.environ.get("HLTV_DEMOS_DL_DIR") or next(
        (path for path in sorted(glob.glob("/mnt/*/Downloads")) if os.path.isdir(path)),
        os.path.expanduser("~/Downloads"))
    os.makedirs(dl_dir, exist_ok=True)
    man = _manifest()
    extracted, downloaded, skipped, errors = [], [], [], []

    for item in plan:
        if not item.get("r2"):
            errors.append({"teams": item["teams"], "error": item.get("error", "no demo url")})
            continue
        demo_id = item.get("demo_id", "?")
        hit_maps = [w for w in wanted if w in item.get("played", [])] if wanted else []
        prior = man.get(demo_id, {})
        complete = _completed_from_manifest(prior, hit_maps, csgo)
        if complete:
            for result in complete:
                result["teams"] = item["teams"]
            extracted.extend(complete)
            skipped.append(f"{item['teams']} (verified from manifest)")
            continue

        dest = os.path.join(dl_dir, item["name"])
        try:
            if os.path.isfile(dest) and (not item["size"] or os.path.getsize(dest) == item["size"]):
                skipped.append(f"{item['teams']} (archive on disk)")
            else:
                # Only adopt the exact archive recorded for this demo ID. Equal size alone is unsafe.
                recorded = prior.get("rar", "")
                if (recorded and os.path.isfile(recorded) and item["size"]
                        and os.path.getsize(recorded) == item["size"]):
                    dest = recorded
                    skipped.append(f"{item['teams']} (archive from manifest)")
                else:
                    note = download(item["r2"], item["size"], dest)
                    downloaded.append(f"{item['teams']}: {note}")

            members = archive_demos(dest)
            targets = _wanted_members(members, hit_maps)
            if not targets:
                label = ", ".join(hit_maps) if hit_maps else "any map"
                raise RuntimeError(f"archive contains no demo for {label}")
            test_archive(dest)
            got = extract(dest, hit_maps, csgo)
            if len(got) != len(targets):
                raise RuntimeError(f"extracted {len(got)} of {len(targets)} expected demos")
            for result in got:
                result["teams"] = item["teams"]
            extracted.extend(got)

            recorded_files = prior.get("extracted_files", {})
            if not isinstance(recorded_files, dict):
                recorded_files = {}
            recorded_files.update({result["file"]: result["size"] for result in got})
            entry = dict(prior)
            entry.update({
                "teams": item["teams"], "rar": dest, "size": item["size"],
                "archive_demos": [member["file"] for member in members],
                "extracted_files": recorded_files,
                "maps_extracted": sorted(recorded_files),  # backward-readable summary
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            man[demo_id] = entry
            _save_manifest(man)
            # Delete only after every requested member was validated and the manifest was saved.
            if not keep_rars and os.path.isfile(dest):
                os.remove(dest)
        except Exception as e:  # noqa: BLE001
            errors.append({"teams": item["teams"], "error": str(e)[:200]})

    return {
        "event": f"{eid}/{slug}", "csgo_dir": csgo, "maps": wanted,
        "selected_matches": [item["teams"] for item in plan],
        "downloaded": downloaded, "skipped": skipped,
        "extracted": extracted,
        "playdemo_commands": [f'playdemo "{result["playdemo"]}"'
                              for result in extracted if "playdemo" in result],
        "errors": errors,
        "total_demos_in_csgo": len([name for name in os.listdir(csgo)
                                    if name.lower().endswith(".dem")]),
    }


async def run(event: str = "", maps: str = "", latest: int = 0, keep_rars: bool = True,
              dry_run: bool = False, csgo_dir: str = "") -> dict:
    """Download and install HLTV demos without blocking the caller's event loop.

    Empty ``maps`` means every demo in each selected match archive. To prevent an
    accidental event-wide download, either set ``maps``, set ``latest``, or use
    ``dry_run=True``. Archives are retained by default; use ``keep_rars=False``
    only when validated extracted demos are enough.
    """
    return await asyncio.to_thread(
        _run, event=event, maps=maps, latest=latest, keep_rars=keep_rars,
        dry_run=dry_run, csgo_dir=csgo_dir,
    )
