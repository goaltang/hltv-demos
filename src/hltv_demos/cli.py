"""Standalone CLI: hltv_demos --event ... [--maps ...] [--latest N]

The Prime-agent harness wraps this module as a skill; this thin argparse
wrapper lets you use it from any shell:

    hltv_demos --event blast-open-porto-2026 --maps 炼狱小镇 --latest 3 --dry-run
"""
import argparse
import asyncio
import json

from . import run


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="hltv_demos",
        description="Download CS2 GOTV demos from HLTV by event and map "
                    "(Cloudflare-safe, resumable, dedup).",
    )
    ap.add_argument("--event", default="", help='HLTV event name/slug, e.g. "blast-open-porto-2026"')
    ap.add_argument("--maps", default="", help='map filter, English or Chinese, comma separated, e.g. "炼狱小镇" or "Mirage,Nuke"')
    ap.add_argument("--latest", type=int, default=0, help="keep only the N most recent matching matches (0 = all)")
    ap.add_argument("--keep-rars", action="store_true", help="keep downloaded archives after extraction")
    ap.add_argument("--dry-run", action="store_true", help="resolve and report the plan without downloading")
    ap.add_argument("--csgo-dir", default="", help="override CS2 game/csgo directory")
    args = ap.parse_args()

    result = asyncio.run(run(
        event=args.event,
        maps=args.maps,
        latest=args.latest,
        keep_rars=args.keep_rars,
        dry_run=args.dry_run,
        csgo_dir=args.csgo_dir,
    ))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
