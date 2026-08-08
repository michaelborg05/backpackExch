"""
Tools/fetch_render_logs.py
==========================
Pull logs out of Render's Logs API for a workspace, with optional text/level
filters and time window, following pagination until the window is exhausted.

Primary use: reconstruct why prod took (or skipped) a trade, by pulling the
"[TI]" trend-invalidation lines and signal-generation lines around a timestamp.

Auth: needs a Render API key (Account Settings → API Keys, starts with "rnd_").
Supply it via RENDER_API_KEY in the environment or .env.

Usage:
    # everything in a window
    python Tools/fetch_render_logs.py --start 2026-07-27T12:00Z --end 2026-07-27T14:00Z

    # only trend-invalidation decisions
    python Tools/fetch_render_logs.py --start 2026-08-08T00:00Z --text "[TI]"

    # narrow to one service (otherwise all resources in the workspace)
    python Tools/fetch_render_logs.py --resource srv-xxxxxxxx --text SOL_USDC

Note on retention: Render keeps logs for a limited period (7 days on many
plans). If a query returns nothing for an older window, the logs are likely
expired rather than missing — check the plan's retention before concluding
the app was silent.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

API = "https://api.render.com/v1/logs"
SERVICES_API = "https://api.render.com/v1/services"
DEFAULT_OWNER = "tea-d55jffe3jp1c739test0"


def discover_resources(client: "httpx.Client", owner: str) -> list:
    """List every service id in the workspace.

    The logs endpoint rejects a query with no resource filter
    ("must specify at least one resource in filters"), so when the caller
    doesn't name a service we look them all up and pass them explicitly.
    """
    resp = client.get(SERVICES_API, params={"ownerId": owner, "limit": 100})
    resp.raise_for_status()
    ids = []
    for item in resp.json():
        svc = item.get("service", item)
        if svc.get("id"):
            ids.append(svc["id"])
    return ids


def _iso(value: str) -> str:
    """Accept 2026-07-27T12:00Z / ...+00:00 / a bare date, return RFC3339 UTC."""
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        dt = datetime.strptime(v, "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch logs from the Render API")
    p.add_argument("--owner", default=os.getenv("RENDER_OWNER_ID", DEFAULT_OWNER),
                   help="Workspace / owner id (tea-...)")
    p.add_argument("--resource", action="append", default=None,
                   help="Service id (srv-...). Repeatable. Default: every service in "
                        "the workspace, looked up automatically — the logs endpoint "
                        "rejects a query with no resource filter.")
    p.add_argument("--start", default=None, help="Window start, e.g. 2026-07-27T12:00Z")
    p.add_argument("--end", default=None, help="Window end. Default: now")
    p.add_argument("--hours", type=float, default=2.0,
                   help="If --start omitted, look back this many hours (default 2)")
    p.add_argument("--text", action="append", default=None,
                   help="Substring filter, repeatable (Render ANDs them)")
    p.add_argument("--level", action="append", default=None,
                   help="Log level filter, e.g. error / warning")
    p.add_argument("--limit", type=int, default=100,
                   help="Rows per page, max 100 (default 100)")
    p.add_argument("--max-pages", type=int, default=50,
                   help="Safety cap on pagination (default 50 = 5000 rows)")
    p.add_argument("--out", default=None, help="Write lines to this file as well as stdout")
    args = p.parse_args()

    key = os.getenv("RENDER_API_KEY")
    if not key:
        print("ERROR: RENDER_API_KEY not set (Render dashboard → Account Settings → "
              "API Keys). Add it to .env or export it.", file=sys.stderr)
        return 2

    end = _iso(args.end) if args.end else _iso(datetime.now(timezone.utc).isoformat())
    if args.start:
        start = _iso(args.start)
    else:
        start = _iso((datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat())

    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    client = httpx.Client(timeout=30.0, headers=headers)

    resources = args.resource
    if not resources:
        try:
            resources = discover_resources(client, args.owner)
        except httpx.HTTPStatusError as exc:
            print(f"ERROR: could not list services for {args.owner}: {exc}", file=sys.stderr)
            client.close()
            return 2
        if not resources:
            print(f"ERROR: no services found in workspace {args.owner}.", file=sys.stderr)
            client.close()
            return 2

    params = {
        "ownerId": args.owner,
        "startTime": start,
        "endTime": end,
        "limit": min(max(args.limit, 1), 100),
        "direction": "forward",
        "resource": resources,
    }
    if args.text:
        params["text"] = args.text
    if args.level:
        params["level"] = args.level

    sink = open(args.out, "w") if args.out else None
    total = 0

    try:
        for page in range(args.max_pages):
            # The logs endpoint rate-limits hard when paginating a wide window.
            # Back off and retry rather than dropping the tail of the results.
            for attempt in range(6):
                resp = client.get(API, params=params)
                if resp.status_code != 429:
                    break
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                print(f"[rate-limited, retrying in {wait:.0f}s]", file=sys.stderr)
                time.sleep(wait)
            else:
                print("ERROR: still rate-limited after 6 attempts — narrow the window "
                      "(--start/--end) or add a --text filter.", file=sys.stderr)
                return 2

            if resp.status_code == 401:
                print("ERROR: 401 — API key rejected.", file=sys.stderr)
                return 2
            if resp.status_code == 404:
                print(f"ERROR: 404 — owner {args.owner!r} or resource not found.",
                      file=sys.stderr)
                return 2
            resp.raise_for_status()
            body = resp.json()

            for row in body.get("logs", []):
                line = f"{row.get('timestamp','')} {row.get('message','').rstrip()}"
                print(line)
                if sink:
                    sink.write(line + "\n")
                total += 1

            if not body.get("hasMore"):
                break
            nxt = body.get("nextStartTime")
            if not nxt or nxt == params["startTime"]:
                break
            params["startTime"] = nxt
        else:
            print(f"[warn] stopped at --max-pages={args.max_pages}; window may be "
                  f"incomplete", file=sys.stderr)
    finally:
        client.close()
        if sink:
            sink.close()

    print(f"\n[{total} log line(s)] {start} → {end}", file=sys.stderr)
    if total == 0:
        print("[hint] No rows. Either the filters matched nothing, or the window is "
              "past Render's log retention for this plan.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
