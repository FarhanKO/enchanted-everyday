"""Fill YOUTUBE_REFRESH_TOKEN in .env by signing in to the channel once.

    python scripts/youtube_auth.py

Needs YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env (a Desktop app OAuth client). Opens the
Google sign-in in your browser; pick the account and then the channel (a Brand Account channel is
listed separately from your personal profile). Google warns the app is unverified: click Advanced,
then Go to <app name> (unsafe). Google redirects back to a one-shot server on 127.0.0.1, the code is
exchanged for a refresh token, written to .env and checked against the channel. No token is printed.
Run it again if uploads start failing with invalid_grant (password change, access revoked).
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import re
import secrets
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - endpoint, not a secret
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def read_env(key: str) -> str:
    match = re.search(rf"^{key}=([^\r\n#]*)", ENV_PATH.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1).strip() if match else ""


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


def make_server(state: str) -> tuple[http.server.HTTPServer, str, dict[str, str]]:
    """One-request server on a free 127.0.0.1 port; Google's redirect query lands in result."""
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in query.items()})
            ok = "code" in result and result.get("state") == state
            body = (
                "Signed in. You can close this tab and go back to the terminal."
                if ok
                else "Sign-in did not finish. Go back to the terminal."
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args: object) -> None:  # keep the code out of the terminal
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    return server, f"http://127.0.0.1:{server.server_port}", result


def main() -> None:
    client_id = read_env("YOUTUBE_CLIENT_ID")
    client_secret = read_env("YOUTUBE_CLIENT_SECRET")
    if not client_id.endswith(".apps.googleusercontent.com"):
        sys.exit(
            "YOUTUBE_CLIENT_ID in .env is missing or wrong (it ends .apps.googleusercontent.com)."
        )
    if not client_secret:
        sys.exit(
            "YOUTUBE_CLIENT_SECRET in .env is empty. Copy client_secret from the client's JSON."
        )

    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    server, redirect_uri, result = make_server(state)

    url = (
        AUTH_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",  # ask for a refresh token
                "prompt": "consent",  # and get a new one even if access was granted before
                "state": state,
                "code_challenge": challenge.decode(),
                "code_challenge_method": "S256",
            }
        )
    )
    print("Opening the Google sign-in in your browser.")
    print("Pick the account, then The Enchanted Everyday channel.")
    print(
        "On 'Google hasn't verified this app': Advanced -> Go to ... (unsafe) -> tick all boxes.\n"
    )
    print(f"If no browser opens, paste this link into one:\n{url}\n")
    webbrowser.open(url)
    server.handle_request()
    server.server_close()

    if result.get("state") != state:
        sys.exit("The sign-in reply didn't match this run. Run the script again.")
    if "error" in result:
        sys.exit(f"Google returned an error: {result['error']}")

    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": result["code"],
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    tokens = resp.json()
    if "error" in tokens:
        sys.exit(f"Token exchange failed: {tokens['error']}: {tokens.get('error_description')}")
    if "refresh_token" not in tokens:
        sys.exit(
            "Google sent no refresh token. Remove the app at myaccount.google.com/permissions, "
            "then run again."
        )
    granted = set(tokens.get("scope", "").split())
    missing = [s.rsplit("/", 1)[-1] for s in SCOPES if s not in granted]
    if missing:
        print("Warning, not granted (tick every box on the consent screen): " + ", ".join(missing))

    channels = httpx.get(
        CHANNELS_URL,
        params={"part": "snippet", "mine": "true"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=30,
    ).json()
    items = channels.get("items") or []
    if not items:
        sys.exit("Signed in, but that account has no channel. Run again and pick the channel.")

    write_env({"YOUTUBE_REFRESH_TOKEN": tokens["refresh_token"]})
    print(f"\nDone. Channel: {items[0]['snippet']['title']} ({items[0]['id']})")
    print("Refresh token saved to .env.")


if __name__ == "__main__":
    main()
