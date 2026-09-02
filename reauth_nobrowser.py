import os
import sys
import json
import logging
from google_auth_oauthlib.flow import InstalledAppFlow
from src.config import get_channel_by_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reauth")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

def reauth_channel(channel_id: str):
    cfg = get_channel_by_id(channel_id)
    client_secret_path = cfg.google_credentials_file
    token_path = cfg.oauth_token_file

    if not os.path.exists(client_secret_path):
        logger.error(f"Client secret file not found: {client_secret_path}")
        logger.info("Please create a GCP project, enable YouTube Data API v3, create a Desktop OAuth client, and save the JSON file to credentials/.")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(token_path)), exist_ok=True)

    flow = InstalledAppFlow.from_client_secrets_file(
        client_secret_path,
        scopes=SCOPES,
        redirect_uri="http://localhost:8080/"
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true"
    )

    print("\n" + "="*70)
    print(f"AUTHENTICATION FOR CHANNEL: {channel_id}")
    print("="*70)
    print("\n1. Open this URL in your browser (signed in with the channel Gmail):")
    print(f"\n{auth_url}\n")
    print("2. Click 'Advanced' -> 'Go to <app-name> (unsafe)' -> 'Allow/Continue'.")
    print("3. If redirected to localhost:8080 with an error, copy the 'code' parameter from the URL address bar.")
    print("="*70 + "\n")

    try:
        # Try local server first (works on desktop if port 8080 open)
        creds = flow.run_local_server(port=8080, prompt="consent", timeout_seconds=120)
    except Exception as ex:
        logger.warning(f"Local server stopped or timed out ({ex}). Falling back to manual code input...")
        code = input("Paste the full redirect URL or the 'code' value here: ").strip()
        if "code=" in code:
            import urllib.parse
            parsed = urllib.parse.urlparse(code)
            query = urllib.parse.parse_qs(parsed.query)
            code = query.get("code", [code])[0]
        flow.fetch_token(code=code)
        creds = flow.credentials

    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    logger.info(f"✅ Token successfully generated and saved to: {token_path}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python reauth_nobrowser.py <channel_id>")
        sys.exit(1)

    channel_id = sys.argv[1]
    reauth_channel(channel_id)
