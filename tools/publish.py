#!/usr/bin/env python3
"""Upload and publish themes to the Chrome Web Store. Stdlib only.

    python3 tools/publish.py --version 1.0.7 [slug ...]
    python3 tools/publish.py --version 1.0.7 --dry-run     # zip only, no network

Item ids come from store-items.json, a {slug: item_id} map. Only themes listed
there are touched. Each one has to be created once by hand -- upload any zip in
the Developer Dashboard -- since the API can update an item but cannot create one.

Needs CWS_CLIENT_ID, CWS_CLIENT_SECRET and CWS_REFRESH_TOKEN in the environment.

The zip is built from the committed dist/ with only the version rewritten, so
what ships is what is in the tree, not a rebuild against whatever Zed's themes
happen to look like today.
"""

import argparse
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).parent.parent
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/chromewebstore/v1.1/items/{id}"
PUBLISH_URL = "https://www.googleapis.com/chromewebstore/v1.1/items/{id}/publish"


ITEM_URL = "https://www.googleapis.com/chromewebstore/v1.1/items/{id}"


def request(url, data=None, method=None, headers=(), form=False, fatal=True):
    if form:
        data = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers:
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        detail = f"HTTP {e.code}: {e.read().decode(errors='replace').strip()}"
        if fatal:
            sys.exit(f"{method or 'GET'} {url} -> {detail}")
        return {"_error": detail}
    return json.loads(body) if body else {}


def access_token():
    missing = [k for k in ("CWS_CLIENT_ID", "CWS_CLIENT_SECRET", "CWS_REFRESH_TOKEN")
               if not os.environ.get(k)]
    if missing:
        sys.exit(f"missing environment: {', '.join(missing)}")
    got = request(TOKEN_URL, method="POST", form=True, data={
        "client_id": os.environ["CWS_CLIENT_ID"],
        "client_secret": os.environ["CWS_CLIENT_SECRET"],
        "refresh_token": os.environ["CWS_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    })
    return got["access_token"]


def zip_theme(folder, version):
    """Zip `folder`, rewriting only manifest.json's version."""
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["version"] = version
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.name != "manifest.json":
                z.write(path, path.relative_to(folder).as_posix())
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="manifest version to ship")
    ap.add_argument("--target", default="default", choices=["default", "trustedTesters"])
    ap.add_argument("--dist", default=HERE / "dist", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="build the zips, skip the API")
    ap.add_argument("--check", action="store_true",
                    help="verify the credentials mint an access token, then stop")
    ap.add_argument("--themes", default="",
                    help="whitespace-separated slugs, so callers need no shell splitting")
    ap.add_argument("slugs", nargs="*", help="themes to publish; default is every configured one")
    args = ap.parse_args()
    slugs = args.slugs + args.themes.split()
    bad = [s for s in slugs if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", s)]
    if bad:
        sys.exit(f"not theme slugs: {', '.join(bad)}")

    items_file = HERE / "store-items.json"
    if not items_file.is_file():
        sys.exit(f"{items_file} not found -- see the docstring for what it holds")
    items = {k: v for k, v in json.loads(items_file.read_text()).items()
             if not k.startswith("_")}

    if args.check:
        token = access_token()
        print("credentials OK: refresh token exchanged for an access token")
        auth = (("Authorization", f"Bearer {token}"), ("x-goog-api-version", "2"))
        broken = []
        for slug, item_id in items.items():
            # Reaching each item now catches a typo'd or unowned id here rather
            # than part way through a publish.
            got = request(ITEM_URL.format(id=item_id) + "?projection=DRAFT",
                          headers=auth, fatal=False)
            if "_error" in got:
                print(f"  {slug}: UNREACHABLE {item_id} -- {got['_error']}")
                broken.append(slug)
            else:
                print(f"  {slug}: ok, uploadState {got.get('uploadState', '?')}")
        if broken:
            sys.exit(f"unreachable items: {', '.join(broken)}")
        if items:
            print(f"all {len(items)} configured item(s) reachable")
        return
    if slugs:
        unknown = [s for s in slugs if s not in items]
        if unknown:
            sys.exit(f"not in store-items.json: {', '.join(unknown)}")
        items = {s: items[s] for s in slugs}
    if not items:
        sys.exit("no items configured in store-items.json, nothing to publish")

    token = None if args.dry_run else access_token()
    auth = () if args.dry_run else (("Authorization", f"Bearer {token}"),
                                    ("x-goog-api-version", "2"))
    failed = []
    for slug, item_id in items.items():
        folder = args.dist / slug
        if not folder.is_dir():
            sys.exit(f"{folder} does not exist -- run build.py first")
        blob = zip_theme(folder, args.version)
        print(f"{slug}: {len(blob)} bytes, version {args.version}", end="", flush=True)
        if args.dry_run:
            print("  (dry run)")
            continue

        got = request(UPLOAD_URL.format(id=item_id) + "?uploadType=media",
                      data=blob, method="PUT", headers=auth)
        if got.get("uploadState") not in ("SUCCESS", "IN_PROGRESS"):
            print(f"\n  upload failed: {json.dumps(got)}")
            failed.append(slug)
            continue

        got = request(PUBLISH_URL.format(id=item_id)
                      + f"?publishTarget={args.target}", method="POST", headers=auth)
        statuses = got.get("status", [])
        print(f"  uploaded, publish status {statuses or 'OK'}")
        # Anything other than OK or the review-queue notice is a real failure.
        if any(s not in ("OK", "ITEM_PENDING_REVIEW") for s in statuses):
            print(f"  {got.get('statusDetail')}")
            failed.append(slug)

    if failed:
        sys.exit(f"\nfailed: {', '.join(failed)}")
    print(f"\n{len(items)} theme(s) {'zipped' if args.dry_run else 'submitted'}")


if __name__ == "__main__":
    main()
