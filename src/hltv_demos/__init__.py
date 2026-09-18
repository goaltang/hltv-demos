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
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests as cr

BASE = "https://www.hltv.org"
WORK = os.path.expanduser("~/tools/hltv-demos")
MANIFEST = os.path.join(WORK, "manifest.json")
SEVENZ = os.path.join(WORK, "7zz")
SEVENZ_URL = "https://www.7-zip.org/a/7z2501-linux-x64.tar.xz"
SEVENZ_SHA256 = "4ca3b7c6f2f67866b92622818b58233dc70367be2f36b498eb0bdeaaa44b53f4"
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


def _validate_demo_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "r2-demos.hltv.org":
        raise RuntimeError(f"untrusted demo download URL: {parsed.scheme}://{parsed.hostname or '?'}")
    return url


def _head_size(url: str) -> int:
    _validate_demo_url(url)
    try:
        h = cr.head(url, impersonate="chrome", timeout=30, allow_redirects=False)
        try:
            if h.status_code != 200:
                return 0
            _validate_demo_url(str(h.url))
            return int(h.headers.get("content-length") or 0)
        finally:
            h.close()
    except Exception:  # noqa: BLE001 - HEAD failure means the size is unknown.
        return 0


def _supported_platform() -> tuple[bool, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    ok = system == "linux" and machine in ("x86_64", "amd64")
    return ok, f"{system}/{machine}"


def ensure_7zz() -> str:
    system_7z = shutil.which("7zz") or shutil.which("7z")
    if system_7z:
        return system_7z
    if os.path.exists(SEVENZ) and os.access(SEVENZ, os.X_OK):
        return SEVENZ
    supported, label = _supported_platform()
    if not supported:
        raise RuntimeError(
            f"automatic 7-Zip setup supports Linux x86-64/WSL2 only (detected {label}). "
            "Install 7zz/7z yourself and put it on PATH."
        )
    os.makedirs(WORK, mode=0o700, exist_ok=True)
    archive_path = os.path.join(WORK, "7z.tar.xz")
    r = _get(SEVENZ_URL)
    payload = r.content
    r.close()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != SEVENZ_SHA256:
        raise RuntimeError(
            f"7-Zip checksum mismatch: got {digest}, expected {SEVENZ_SHA256}; nothing executed"
        )
    with open(archive_path, "wb") as f:
        f.write(payload)
    with tarfile.open(archive_path, "r:xz") as archive:
        member = archive.getmember("7zz")
        source = archive.extractfile(member)
        if source is None or not member.isfile():
            raise RuntimeError("verified 7-Zip archive does not contain a regular 7zz file")
        fd, tmp = tempfile.mkstemp(prefix="7zz-", dir=WORK)
        try:
            with os.fdopen(fd, "wb") as target:
                shutil.copyfileobj(source, target)
            os.chmod(tmp, 0o755)
            os.replace(tmp, SEVENZ)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return SEVENZ


def _csgo_candidates(explicit: str = "") -> list[str]:
    values = []
    if explicit:
        values.append(explicit)
    env = os.environ.get("HLTV_DEMOS_CSGO_DIR")
    if env:
        values.append(env)
    values += [
        "/mnt/d/steam/steamapps/common/Counter-Strike Global Offensive",
        "/mnt/c/Program Files (x86)/Steam/steamapps/common/Counter-Strike Global Offensive",
        os.path.expanduser("~/.steam/steam/steamapps/common/Counter-Strike Global Offensive"),
        os.path.expanduser("~/.local/share/Steam/steamapps/common/Counter-Strike Global Offensive"),
    ]
    values += glob.glob("/mnt/*/steamapps/common/Counter-Strike Global Offensive")
    out = []
    for value in values:
        path = os.path.abspath(os.path.expanduser(value.rstrip("/\\")))
        # Accept either the game root or the final game/csgo directory.
        if os.path.basename(path).lower() == "csgo" and os.path.basename(os.path.dirname(path)).lower() == "game":
            demo_dir = path
        else:
            demo_dir = os.path.join(path, "game", "csgo")
        if demo_dir not in out:
            out.append(demo_dir)
    return out


def discover_csgo(explicit: str = "") -> str:
    for demo_dir in _csgo_candidates(explicit):
        if os.path.isdir(demo_dir) and os.access(demo_dir, os.W_OK):
            return demo_dir
    raise RuntimeError(
        "CS2 game/csgo directory was not found or is not writable. Pass either the game root "
        "or the final game/csgo path with --csgo-dir, or set HLTV_DEMOS_CSGO_DIR."
    )


def _existing_parent(path: str) -> str:
    current = os.path.abspath(os.path.expanduser(path))
    while not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return current


def doctor(csgo_dir: str = "", download_dir: str = "") -> dict:
    supported, platform_label = _supported_platform()
    python_ok = tuple(map(int, platform.python_version_tuple()[:2])) >= (3, 10)
    system_seven = shutil.which("7zz") or shutil.which("7z")
    bundled_seven = SEVENZ if os.path.isfile(SEVENZ) and os.access(SEVENZ, os.X_OK) else None
    seven_value = system_seven or bundled_seven
    try:
        csgo = discover_csgo(csgo_dir)
        csgo_ok, csgo_note = True, csgo
    except RuntimeError as exc:
        csgo_ok, csgo_note = False, str(exc)
    work_parent = _existing_parent(WORK)
    work_ok = os.path.isdir(work_parent) and os.access(work_parent, os.W_OK)
    requested_download = os.path.abspath(os.path.expanduser(
        download_dir or os.environ.get("HLTV_DEMOS_DL_DIR") or "~/Downloads"
    ))
    download_parent = _existing_parent(requested_download)
    download_ok = os.path.isdir(download_parent) and os.access(download_parent, os.W_OK)
    return {
        "ok": supported and python_ok and csgo_ok and work_ok and download_ok,
        "platform": {"ok": supported, "value": platform_label,
                     "note": "supported" if supported else "auto-setup supports Linux x86-64/WSL2 only"},
        "python": {"ok": python_ok, "value": platform.python_version()},
        "seven_zip": {"ok": bool(seven_value), "value": seven_value,
                      "note": "available" if seven_value else
                              "optional now; a checksum-verified copy is downloaded before first extraction"},
        "csgo_dir": {"ok": csgo_ok, "value": csgo_note},
        "download_dir": {"ok": download_ok, "value": requested_download,
                         "note": f"writable parent: {download_parent}"},
        "work_dir": {"ok": work_ok, "value": WORK,
                     "note": f"writable parent: {work_parent}"},
    }


def find_event(query: str) -> tuple[str, str]:
    cleaned = query.strip()
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("hltv.org", "www.hltv.org"):
            raise ValueError("event URL must use the hltv.org host")
        direct = re.fullmatch(r"/events/(\d+)/([a-z0-9-]+)/?", parsed.path, re.IGNORECASE)
        if not direct:
            raise ValueError("expected an HLTV event URL like https://www.hltv.org/events/1234/event-slug")
        return direct.group(1), direct.group(2).lower()
    direct = re.fullmatch(r"/?events/(\d+)/([a-z0-9-]+)/?", cleaned, re.IGNORECASE)
    if direct:
        return direct.group(1), direct.group(2).lower()
    if not cleaned:
        raise ValueError("event is required; pass an HLTV event URL, name, or slug")
    r = _get(f"{BASE}/search?query={quote_plus(cleaned)}")
    candidates = list(dict.fromkeys(re.findall(
        r'href="/events/(\d+)/([a-z0-9-]+)"', r.text, re.IGNORECASE
    )))
    r.close()
    if not candidates:
        raise RuntimeError(f"no HLTV event found for {query!r}")
    want = re.sub(r"[^a-z0-9]", "", cleaned.lower())
    exact = [(eid, slug) for eid, slug in candidates
             if want == re.sub(r"[^a-z0-9]", "", slug.lower())]
    if len(exact) == 1:
        return exact[0]
    close = [(eid, slug) for eid, slug in candidates
             if want and want in re.sub(r"[^a-z0-9]", "", slug.lower())]
    if len(close) == 1:
        return close[0]
    if len(candidates) == 1:
        return candidates[0]
    choices = ", ".join(f"{BASE}/events/{eid}/{slug}" for eid, slug in candidates[:5])
    raise RuntimeError(
        f"event name {query!r} is ambiguous. Use one exact HLTV event URL. Candidates: {choices}"
    )


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
    _validate_demo_url(loc)
    parsed = urlparse(loc)
    name = parsed.path.rsplit("/", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,240}\.(?:rar|7z|zip)", name, re.IGNORECASE):
        raise RuntimeError(f"unsafe demo archive filename: {name!r}")
    return {"r2": loc, "name": name, "size": _head_size(loc)}


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



def _emit(progress: Callable[[str], None] | None, message: str) -> None:
    if progress:
        with suppress(Exception):  # Progress rendering must never abort a download.
            progress(message)


def _require_space(path: str, needed: int, purpose: str) -> None:
    if needed <= 0:
        return
    free = shutil.disk_usage(path).free
    reserve = max(256 * 1024 * 1024, needed // 10)
    if free < needed + reserve:
        raise RuntimeError(
            f"not enough free space for {purpose}: need about {(needed + reserve) / 1e9:.2f} GB, "
            f"have {free / 1e9:.2f} GB at {path}"
        )

def download(r2: str, size: int, dest: str, progress: Callable[[str], None] | None = None) -> str:
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
    _validate_demo_url(r2)
    r = cr.get(r2, impersonate="chrome", timeout=(30, 3600), stream=True,
               headers=headers, allow_redirects=False)
    try:
        _validate_demo_url(str(r.url))
        if r.status_code not in (200, 206):
            raise RuntimeError(f"download http {r.status_code}")
        if offset and r.status_code == 206:
            content_range = r.headers.get("content-range", "")
            if not re.match(rf"bytes\s+{offset}-\d+/", content_range, re.IGNORECASE):
                raise RuntimeError(f"invalid resume response: {content_range!r}")
        mode = "ab" if (offset and r.status_code == 206) else "wb"
        got = offset if mode == "ab" else 0
        last_report = t0
        with open(part, mode) as f:
            for chunk in r.iter_content(1024 * 512):
                if chunk:
                    f.write(chunk)
                    got += len(chunk)
                    now = time.time()
                    if progress and now - last_report >= 1:
                        total = f"/{size / 1e6:.0f} MB" if size else " MB"
                        _emit(progress, f"Downloaded {got / 1e6:.0f}{total}")
                        last_report = now
    finally:
        r.close()
    if size and got != size:
        raise RuntimeError(f"size mismatch: got {got} want {size} (part kept for resume)")
    os.replace(part, dest)
    return f"downloaded {got/1e6:.0f}MB in {time.time()-t0:.0f}s"


def archive_demos(rar: str) -> list[dict]:
    """List demo members and their uncompressed sizes using 7-Zip's stable format."""
    out = subprocess.run(
        [ensure_7zz(), "l", "-slt", rar], capture_output=True, text=True, timeout=300,
        check=False,
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
                filename = os.path.basename(normalized)
                if member_size <= 0:
                    raise RuntimeError(f"demo member has invalid size: {path!r} ({member_size})")
                if any(item["file"].casefold() == filename.casefold() for item in demos):
                    raise RuntimeError(f"archive has duplicate demo basename: {filename!r}")
                demos.append({"member": path, "file": filename, "size": member_size})
            current = {}
        elif " = " in line:
            key, value = line.split(" = ", 1)
            current[key] = value
    return demos


def test_archive(rar: str) -> None:
    result = subprocess.run(
        [ensure_7zz(), "t", rar], capture_output=True, text=True, timeout=900, check=False
    )
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
                                 capture_output=True, text=True, timeout=900, check=False)
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


def _build_download_plan(event: str, maps: str = "", latest: int = 0,
                         keep_rars: bool = True, csgo_dir: str = "",
                         download_dir: str = "", progress: Callable[[str], None] | None = None,
                         allow_unbounded_preview: bool = False) -> dict:
    """Resolve a stable match/archive selection without modifying local state."""
    if not event:
        raise ValueError("event is required")
    if latest < 0:
        raise ValueError("latest must be 0 or greater")
    wanted = resolve_maps(maps) if maps else []
    eid, slug = find_event(event)
    event_url = f"{BASE}/events/{eid}/{slug}"
    _emit(progress, f"Resolved event: {event_url}")
    results = list_results(eid)
    _emit(progress, f"Found {len(results)} result(s); scanning played maps")

    selected = []
    for index, match in enumerate(results, 1):
        _emit(progress, f"Scanning match {index}/{len(results)}: {match['teams']}")
        played, demo_path = fetch_match_page(match["path"]) if wanted else ([], None)
        match["played"], match["demo_path"] = played, demo_path
        if wanted:
            hit = [name for name in wanted if name in played]
            if hit:
                match["hit"] = hit
                selected.append(match)
        else:
            selected.append(match)
        if wanted and latest and len(selected) >= latest:
            break
        time.sleep(0.4)
    if latest and not wanted:
        selected = selected[:latest]

    if not wanted and not latest and not allow_unbounded_preview:
        return {
            "event": f"{eid}/{slug}", "event_url": event_url, "mode": "refused",
            "note": "maps= is empty and latest=0: this would download EVERY match archive. "
                    "Pass maps='...' and/or latest=N, or use a dry run to inspect first.",
            "all_matches": [match["teams"] for match in results],
            "wanted": wanted, "plan": [], "keep_rars": keep_rars,
            "csgo_config": csgo_dir, "download_config": download_dir,
        }

    plan = []
    for match in selected:
        entry = {}
        try:
            demo_path = match.get("demo_path")
            if demo_path is None:
                _, demo_path = fetch_match_page(match["path"])
            if demo_path:
                entry.update(resolve_demo(demo_path))
                entry["demo_id"] = demo_path.rsplit("/", 1)[-1]
            else:
                entry["error"] = "no demo link on match page"
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)[:200]
        plan.append({**match, **entry})
    return {
        "event": f"{eid}/{slug}", "event_url": event_url, "wanted": wanted,
        "plan": plan, "keep_rars": keep_rars, "csgo_config": csgo_dir,
        "download_config": download_dir,
    }


def _public_download_plan(prepared: dict) -> dict:
    try:
        found_csgo = prepared.get("resolved_csgo") or discover_csgo(prepared["csgo_config"])
    except RuntimeError:
        found_csgo = None
    prospective_download = prepared.get("resolved_download") or os.path.abspath(os.path.expanduser(
        prepared["download_config"] or os.environ.get("HLTV_DEMOS_DL_DIR") or "~/Downloads"
    ))
    plan = prepared["plan"]
    result = {
        "event": prepared["event"], "event_url": prepared["event_url"],
        "csgo_dir": found_csgo, "download_dir": prospective_download, "mode": "dry-run",
        "maps": prepared["wanted"],
        "keep_rars": prepared["keep_rars"],
        "matches": [
            {key: value for key, value in item.items()
             if key in ("teams", "score", "played", "hit", "name", "size", "demo_id", "error")}
            for item in plan
        ],
        "total_bytes": sum(item.get("size", 0) for item in plan),
        "total_mb": round(sum(item.get("size", 0) for item in plan) / 1e6, 1),
        "errors": [{"teams": item["teams"], "error": item["error"]}
                   for item in plan if item.get("error")],
    }
    if not plan:
        result["error"] = "no matches matched the requested filters"
    return result


def _execute_download_plan(prepared: dict, allow_unknown_size: bool = False,
                           progress: Callable[[str], None] | None = None) -> dict:
    """Execute exactly the demo IDs and URLs frozen in ``prepared``; never rediscover matches."""
    if prepared.get("mode") == "refused":
        return {key: value for key, value in prepared.items()
                if key in ("event", "event_url", "mode", "note", "all_matches")}
    plan = prepared["plan"]
    if not plan:
        return {"event": prepared["event"], "error": "no matches matched the requested filters"}
    csgo = prepared.get("resolved_csgo") or discover_csgo(prepared["csgo_config"])
    if not os.path.isdir(csgo) or not os.access(csgo, os.W_OK):
        raise RuntimeError(f"approved CS2 directory is no longer writable: {csgo}")
    dl_dir = prepared.get("resolved_download") or os.path.abspath(os.path.expanduser(
        prepared["download_config"] or os.environ.get("HLTV_DEMOS_DL_DIR") or "~/Downloads"
    ))
    os.makedirs(dl_dir, exist_ok=True)
    if not os.access(dl_dir, os.W_OK):
        raise RuntimeError(f"download directory is not writable: {dl_dir}")
    _emit(progress, f"Download directory: {dl_dir}")
    _emit(progress, f"CS2 demo directory: {csgo}")
    man = _manifest()
    wanted = prepared["wanted"]
    keep_rars = prepared["keep_rars"]
    extracted, downloaded, skipped, errors = [], [], [], []

    for item in plan:
        if not item.get("r2"):
            errors.append({"teams": item["teams"], "error": item.get("error", "no demo url")})
            continue
        demo_id = item.get("demo_id")
        if not demo_id:
            errors.append({"teams": item["teams"], "error": "missing HLTV demo ID"})
            continue
        if not item.get("size") and not allow_unknown_size:
            errors.append({
                "teams": item["teams"],
                "error": "archive size is unknown; retry later or explicitly allow unknown size",
            })
            continue
        hit_maps = [name for name in wanted if name in item.get("played", [])] if wanted else []
        prior = man.get(demo_id, {})
        complete = _completed_from_manifest(prior, hit_maps, csgo)
        if complete:
            for result in complete:
                result["teams"] = item["teams"]
            extracted.extend(complete)
            skipped.append(f"{item['teams']} (verified from manifest)")
            continue

        dest = os.path.realpath(os.path.join(dl_dir, item["name"]))
        if os.path.commonpath([os.path.realpath(dl_dir), dest]) != os.path.realpath(dl_dir):
            errors.append({"teams": item["teams"], "error": "archive destination escaped download directory"})
            continue
        try:
            if os.path.isfile(dest) and item["size"] and os.path.getsize(dest) == item["size"]:
                skipped.append(f"{item['teams']} (archive on disk)")
            else:
                recorded = prior.get("rar", "")
                if (recorded and os.path.isfile(recorded) and item["size"]
                        and os.path.getsize(recorded) == item["size"]):
                    dest = recorded
                    skipped.append(f"{item['teams']} (archive from manifest)")
                else:
                    part_size = os.path.getsize(dest + ".part") if os.path.exists(dest + ".part") else 0
                    remaining = (item["size"] - part_size
                                 if item["size"] and part_size <= item["size"] else item["size"])
                    _require_space(dl_dir, remaining, f"archive for {item['teams']}")
                    _emit(progress, f"Downloading: {item['teams']}")
                    note = download(item["r2"], item["size"], dest, progress=progress)
                    downloaded.append(f"{item['teams']}: {note}")

            _emit(progress, f"Testing archive: {item['teams']}")
            members = archive_demos(dest)
            targets = _wanted_members(members, hit_maps)
            if not targets:
                label = ", ".join(hit_maps) if hit_maps else "any map"
                raise RuntimeError(f"archive contains no demo for {label}")
            _require_space(csgo, sum(target["size"] for target in targets),
                           f"extracted demos for {item['teams']}")
            test_archive(dest)
            _emit(progress, f"Extracting {len(targets)} demo(s): {item['teams']}")
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
                "maps_extracted": sorted(recorded_files),
                "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            man[demo_id] = entry
            _save_manifest(man)
            if not keep_rars and os.path.isfile(dest):
                os.remove(dest)
        except Exception as exc:  # noqa: BLE001
            errors.append({"teams": item["teams"], "error": str(exc)[:200]})

    return {
        "event": prepared["event"], "event_url": prepared["event_url"],
        "csgo_dir": csgo, "download_dir": dl_dir, "maps": wanted,
        "selected_matches": [item["teams"] for item in plan],
        "downloaded": downloaded, "skipped": skipped, "extracted": extracted,
        "playdemo_commands": [f'playdemo "{result["playdemo"]}"'
                              for result in extracted if "playdemo" in result],
        "errors": errors,
        "total_demos_in_csgo": len([name for name in os.listdir(csgo)
                                    if name.lower().endswith(".dem")]),
    }


def _run(event: str = "", maps: str = "", latest: int = 0, keep_rars: bool = True,
         dry_run: bool = False, csgo_dir: str = "", download_dir: str = "",
         allow_unknown_size: bool = False,
         progress: Callable[[str], None] | None = None) -> dict:
    prepared = _build_download_plan(
        event=event, maps=maps, latest=latest, keep_rars=keep_rars,
        csgo_dir=csgo_dir, download_dir=download_dir, progress=progress,
        allow_unbounded_preview=dry_run,
    )
    if dry_run:
        return _public_download_plan(prepared)
    return _execute_download_plan(prepared, allow_unknown_size=allow_unknown_size, progress=progress)


async def run(event: str = "", maps: str = "", latest: int = 0, keep_rars: bool = True,
              dry_run: bool = False, csgo_dir: str = "", download_dir: str = "",
              allow_unknown_size: bool = False,
              progress: Callable[[str], None] | None = None) -> dict:
    """Download and install HLTV demos without blocking the caller's event loop.

    Empty ``maps`` means every demo in each selected match archive. To prevent an
    accidental event-wide download, either set ``maps``, set ``latest``, or use
    ``dry_run=True``. Archives are retained by default; use ``keep_rars=False``
    only when validated extracted demos are enough.
    """
    return await asyncio.to_thread(
        _run, event=event, maps=maps, latest=latest, keep_rars=keep_rars,
        dry_run=dry_run, csgo_dir=csgo_dir, download_dir=download_dir,
        allow_unknown_size=allow_unknown_size, progress=progress,
    )
