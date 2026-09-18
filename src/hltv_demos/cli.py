"""Friendly command-line interface for hltv-demos."""
import argparse
import asyncio
import json
import sys
import traceback
from collections.abc import Sequence

from . import doctor, run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hltv_demos",
        description="Plan, download, validate, and install CS2 GOTV demos from HLTV.",
    )
    parser.add_argument("--event", default="", help="HLTV event URL, exact name, or slug")
    parser.add_argument("--maps", default="", help='English/Chinese maps, e.g. "Mirage,Nuke" or "炼狱小镇"')
    parser.add_argument("--latest", type=int, default=0, help="N most recent matching matches (0 = all)")
    parser.add_argument(
        "--keep-rars", action=argparse.BooleanOptionalAction, default=True,
        help="keep archives (default); use --no-keep-rars to delete after verified extraction",
    )
    parser.add_argument("--dry-run", action="store_true", help="show the plan without writing or downloading")
    parser.add_argument("--yes", action="store_true", help="confirm a real download (required unless --dry-run)")
    parser.add_argument("--doctor", action="store_true", help="check platform, CS2, 7-Zip, and writable paths")
    parser.add_argument("--csgo-dir", default="", help="CS2 root or final game/csgo directory")
    parser.add_argument("--download-dir", default="", help="archive directory (default: ~/Downloads)")
    parser.add_argument("--allow-unknown-size", action="store_true", help="allow an archive with no known size (unsafe)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--debug", action="store_true", help="show a traceback for unexpected failures")
    return parser


def _print_human(result: dict) -> None:
    if result.get("error"):
        print(f"Error: {result['error']}")
        return
    if result.get("mode") == "dry-run":
        print(f"Event: {result.get('event_url', result.get('event'))}")
        print(f"Matches: {len(result.get('matches', []))}")
        print(f"Estimated archives: {result.get('total_mb', 0):.1f} MB")
        print(f"Archive directory: {result.get('download_dir')}")
        print(f"CS2 directory: {result.get('csgo_dir') or 'not found; run --doctor'}")
        for match in result.get("matches", []):
            maps = ", ".join(match.get("hit") or match.get("played") or []) or "all demos"
            size = match.get("size", 0) / 1e6
            print(f"  - {match.get('teams', '?')} [{maps}] {size:.1f} MB")
            if match.get("error"):
                print(f"    Error: {match['error']}")
        print("Review this plan, then repeat the command with --yes and without --dry-run.")
        return
    if result.get("mode") == "refused":
        print(f"Refused: {result.get('note', 'unsafe request')}")
        return
    print(f"Event: {result.get('event_url', result.get('event'))}")
    print(f"CS2 directory: {result.get('csgo_dir')}")
    print(f"Downloaded: {len(result.get('downloaded', []))}; skipped: {len(result.get('skipped', []))}")
    print(f"Installed demos: {len(result.get('extracted', []))}")
    for command in result.get("playdemo_commands", []):
        print(f"  {command}")
    for error in result.get("errors", []):
        print(f"Error [{error.get('teams', '?')}]: {error.get('error', 'unknown error')}")


def _print_doctor(result: dict, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print("hltv-demos doctor")
    for name, check in result.items():
        if name == "ok":
            continue
        status = "PASS" if check.get("ok") else ("WARN" if name == "seven_zip" else "FAIL")
        value = check.get("value")
        note = check.get("note", "")
        print(f"[{status}] {name}: {value or note}")
        if value and note:
            print(f"       {note}")
    print("Ready." if result.get("ok") else "Not ready. Fix the FAIL items above.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.latest < 0:
        parser.error("--latest must be 0 or greater")
    if args.doctor:
        result = doctor(args.csgo_dir, args.download_dir)
        _print_doctor(result, args.json)
        return 0 if result.get("ok") else 1
    if not args.event:
        parser.error("--event is required unless --doctor is used")
    if not args.dry_run and not args.yes:
        message = "A real run requires --yes. First inspect the same command with --dry-run."
        if args.json:
            print(json.dumps({"error": message}, ensure_ascii=False, indent=2))
        else:
            print(f"Refused: {message}")
        return 1

    def progress(message: str) -> None:
        print(f"[hltv-demos] {message}", file=sys.stderr, flush=True)

    try:
        result = asyncio.run(run(
            event=args.event,
            maps=args.maps,
            latest=args.latest,
            keep_rars=args.keep_rars,
            dry_run=args.dry_run,
            csgo_dir=args.csgo_dir,
            download_dir=args.download_dir,
            allow_unknown_size=args.allow_unknown_size,
            progress=progress,
        ))
    except KeyboardInterrupt:
        print("Cancelled; partial downloads were kept for resume.", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False) if args.json else f"Invalid input: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001
        if args.debug:
            traceback.print_exc(file=sys.stderr)
        message = f"{type(exc).__name__}: {exc}"
        print(json.dumps({"error": message}, ensure_ascii=False, indent=2) if args.json else f"Error: {message}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)
    failed = bool(result.get("error") or result.get("errors") or result.get("mode") == "refused")
    return 1 if failed else 0


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
