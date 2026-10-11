"""Fill META_PAGE_ID, META_IG_USER_ID and a never-expiring META_PAGE_ACCESS_TOKEN in .env.

    python scripts/meta_tokens.py

Get a short-lived user token first from the Graph API Explorer
(developers.facebook.com/tools/explorer) with the permissions below. The script asks for the App ID,
then reads the App Secret and that token from the clipboard (never shown), exchanges the token for a
long-lived one, reads the Page token and the linked Instagram account, writes them to .env, checks
the Page token never expires. No token is ever printed.
Run it again whenever the token is invalidated (password change, app removed).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
GRAPH = "https://graph.facebook.com/v26.0"
POWERSHELL = shutil.which("powershell") or "powershell"

PERMISSIONS = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "read_insights",
    "business_management",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
]


def graph_get(path: str, **params: str) -> dict:
    # Never raise_for_status: httpx errors include the URL, and the URL carries the token.
    resp = httpx.get(f"{GRAPH}/{path}", params=params, timeout=30)
    data = resp.json()
    if "error" in data:
        err = data["error"]
        sys.exit(f"Meta error on {path}: {err.get('message')} (code {err.get('code')})")
    return data


def write_env(values: dict[str, str]) -> None:
    with ENV_PATH.open(encoding="utf-8", newline="") as f:  # keep the file's line endings
        text = f.read()
    for key, value in values.items():
        pattern = re.compile(rf"^{key}=[^\r\n]*", re.MULTILINE)
        if pattern.search(text):
            line = f"{key}={value}"
            text = pattern.sub(lambda _, line=line: line, text)
        else:
            text = text.rstrip("\n") + f"\n{key}={value}\n"
    with ENV_PATH.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def from_clipboard(what: str) -> str:
    # Read the clipboard, not a hidden prompt: pasting into getpass gets mangled in some terminals.
    input(f"Copy the {what}, then press Enter here (it is read from the clipboard, not shown)...")
    out = subprocess.run(  # noqa: S603 - fixed command, no user input
        [POWERSHELL, "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def clear_clipboard() -> None:
    subprocess.run(  # noqa: S603 - fixed command, no user input
        [POWERSHELL, "-NoProfile", "-Command", "Set-Clipboard -Value ' '"], check=False
    )


def pick_page(pages: list[dict]) -> dict:
    if not pages:
        sys.exit("No Pages on this token. In the Explorer popup, tick The Enchanted Everyday Page.")
    if len(pages) == 1:
        return pages[0]
    for i, page in enumerate(pages):
        print(f"  [{i}] {page['name']}")
    return pages[int(input("Which Page? Number: ").strip())]


def main() -> None:
    print("Permissions the Explorer token needs:\n  " + "\n  ".join(PERMISSIONS) + "\n")
    app_id = input("App ID (App settings -> Basic): ").strip()
    if not app_id.isdigit():
        sys.exit("The App ID is digits only. Copy it from the top of App settings -> Basic.")
    app_secret = from_clipboard("App Secret (App settings -> Basic -> Show)")
    if app_secret == app_id:
        sys.exit("The clipboard still holds the App ID. Copy the App Secret, then run again.")
    if not re.fullmatch(r"[0-9a-f]{32}", app_secret):
        sys.exit(
            f"That App Secret doesn't look right ({len(app_secret)} characters; it should be 32 "
            "letters a-f and digits). Click Show next to App Secret and copy it again."
        )
    short_token = from_clipboard("user token from the Graph API Explorer")
    clear_clipboard()
    if not short_token.startswith("EAA"):
        sys.exit(
            f"That token doesn't look right ({len(short_token)} characters; it starts with EAA)."
        )

    long_token = graph_get(
        "oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=app_id,
        client_secret=app_secret,
        fb_exchange_token=short_token,
    )["access_token"]
    print("Exchanged for a long-lived user token.")

    granted = graph_get("me/permissions", access_token=long_token)["data"]
    have = {p["permission"] for p in granted if p["status"] == "granted"}
    missing = [p for p in PERMISSIONS if p not in have]
    if missing:
        print("Warning, not granted: " + ", ".join(missing))

    pages = graph_get(
        "me/accounts",
        fields="id,name,access_token,instagram_business_account",
        access_token=long_token,
    )["data"]
    page = pick_page(pages)
    ig = page.get("instagram_business_account")
    if not ig:
        sys.exit(f"Page '{page['name']}' has no linked Instagram professional account.")

    page_token = page["access_token"]
    info = graph_get("debug_token", input_token=page_token, access_token=f"{app_id}|{app_secret}")[
        "data"
    ]
    if info.get("expires_at", 0) != 0:
        sys.exit("The Page token expires; it should not. Run again with a fresh Explorer token.")

    username = graph_get(ig["id"], fields="username", access_token=page_token)["username"]

    write_env(
        {
            "META_PAGE_ID": page["id"],
            "META_IG_USER_ID": ig["id"],
            "META_PAGE_ACCESS_TOKEN": page_token,
        }
    )
    print(f"\nDone. Page: {page['name']} ({page['id']})")
    print(f"Instagram: @{username} ({ig['id']})")
    print("Page token: never expires. Saved to .env.")


if __name__ == "__main__":
    main()
