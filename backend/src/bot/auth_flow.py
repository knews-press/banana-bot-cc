"""Interactive Claude auth flow via CLI subprocess.

When Claude is not authenticated, the bot launches `claude auth login`,
captures its local server port, sends Kevin the browser auth URL, and when
Kevin pastes back the localhost callback URL (which his browser can't reach),
the bot makes the internal HTTP request to the CLI's local server on that port.
"""

import asyncio
import json
import time
import urllib.parse
from pathlib import Path

import aiohttp
import structlog

logger = structlog.get_logger()

_CREDENTIALS_FILE = Path("/root/.claude/.credentials.json")

# Token URL used for refresh only
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_SCOPES = "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"


def is_authenticated() -> bool:
    """Return True if valid, non-expired Claude credentials exist."""
    if not _CREDENTIALS_FILE.exists():
        return False
    try:
        data = json.loads(_CREDENTIALS_FILE.read_text())
        oauth = data.get("claudeAiOauth", {})
        if not oauth.get("accessToken"):
            return False
        expires_at = oauth.get("expiresAt", 0)
        # expiresAt is in milliseconds; reject if expiring within 5 minutes
        if expires_at and expires_at < (time.time() * 1000 + 300_000):
            return False
        return True
    except Exception:
        return False


async def try_refresh_token() -> bool:
    """Try to silently refresh the access token using the stored refresh token.

    Returns True if the refresh succeeded and new credentials were saved,
    False if the refresh failed (user must re-authenticate manually).
    """
    if not _CREDENTIALS_FILE.exists():
        return False
    try:
        data = json.loads(_CREDENTIALS_FILE.read_text())
        refresh_token = data.get("claudeAiOauth", {}).get("refreshToken")
        if not refresh_token:
            return False
    except Exception:
        return False

    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                _TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": _CLIENT_ID,
                },
            )
            if resp.status != 200:
                text = await resp.text()
                logger.warning("Token refresh failed", status=resp.status, body=text[:200])
                return False
            token_data = await resp.json()
            save_credentials(token_data)
            logger.info("Claude token refreshed successfully")
            return True
    except Exception as e:
        logger.warning("Token refresh error", error=str(e))
        return False


async def ensure_authenticated() -> bool:
    """Return True if valid credentials exist or could be refreshed silently.

    Call this instead of is_authenticated() in the message handler so that
    an expired token is renewed automatically without user interaction.
    """
    if is_authenticated():
        return True
    return await try_refresh_token()


def save_credentials(token_data: dict) -> None:
    """Write tokens to ~/.claude/.credentials.json.

    Preserves any existing top-level keys (e.g. other auth providers).
    """
    _CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if _CREDENTIALS_FILE.exists():
        try:
            existing = json.loads(_CREDENTIALS_FILE.read_text())
        except Exception:
            pass

    expires_in = token_data.get("expires_in", 3600)
    existing["claudeAiOauth"] = {
        "accessToken": token_data.get("access_token"),
        "refreshToken": token_data.get("refresh_token"),
        "expiresAt": int((time.time() + expires_in) * 1000),
        "scopes": token_data.get("scope", _SCOPES).split(),
        "subscriptionType": token_data.get("subscription_type", "unknown"),
        "rateLimitTier": token_data.get("rate_limit_tier", "default"),
    }

    _CREDENTIALS_FILE.write_text(json.dumps(existing, indent=2))
    logger.info("Claude credentials saved", path=str(_CREDENTIALS_FILE))


def _get_listening_ports() -> set[int]:
    """Return all ports currently in TCP LISTEN state."""
    ports = set()
    for path in ['/proc/net/tcp', '/proc/net/tcp6']:
        try:
            with open(path, 'r') as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and parts[3] == '0A':  # LISTEN
                        port_hex = parts[1].split(':')[1]
                        ports.add(int(port_hex, 16))
        except Exception:
            pass
    return ports


async def start_cli_auth() -> tuple[str, int, asyncio.subprocess.Process]:
    """
    Launch 'claude auth login', detect its local server port, and return
    (browser_auth_url, port, process).

    browser_auth_url uses http://localhost:{port}/callback so Kevin's browser
    redirects there after authorization. Kevin copies the full URL from the
    address bar (connection refused is expected) and sends it back.
    """
    import os
    ports_before = _get_listening_ports()

    env = {**os.environ, 'NO_COLOR': '1', 'TERM': 'dumb'}
    proc = await asyncio.create_subprocess_exec(
        'claude', 'auth', 'login',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    # Read until CLI prints the "visit:" line with the manual URL
    manual_url = None
    try:
        async def _read_url():
            nonlocal manual_url
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode('utf-8', errors='replace').strip()
                logger.debug("claude auth login", line=text)
                if 'visit:' in text.lower():
                    manual_url = text.split('visit:', 1)[1].strip()
                    return
        await asyncio.wait_for(_read_url(), timeout=20)
    except asyncio.TimeoutError:
        proc.kill()
        raise ValueError("Timeout: CLI hat keine Auth-URL ausgegeben (20s)")

    if not manual_url:
        proc.kill()
        raise ValueError("CLI hat die Auth-URL nicht ausgegeben")

    # Give the server a moment to bind, then detect new listening port
    await asyncio.sleep(1.0)
    ports_after = _get_listening_ports()
    new_ports = ports_after - ports_before

    if not new_ports:
        proc.kill()
        raise ValueError("Konnte den CLI-Port nicht ermitteln")

    port = max(new_ports)
    logger.info("CLI local server detected", port=port)

    # Construct browser URL: same params as manual URL but with localhost redirect
    try:
        parsed = urllib.parse.urlparse(manual_url)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        params['redirect_uri'] = [f'http://localhost:{port}/callback']
        new_query = urllib.parse.urlencode({k: v[0] for k, v in params.items()})
        browser_url = f"https://claude.com/cai/oauth/authorize?{new_query}"
    except Exception as e:
        proc.kill()
        raise ValueError(f"URL-Konstruktion fehlgeschlagen: {e}")

    # Drain stdout in background to prevent buffer blocking
    async def _drain():
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
        except Exception:
            pass
    asyncio.ensure_future(_drain())

    return browser_url, port, proc


async def complete_cli_auth(
    callback_url: str,
    port: int,
    proc: asyncio.subprocess.Process,
) -> bool:
    """
    Forward Kevin's callback URL to the CLI's local server (same container).
    The CLI exchanges the code and saves credentials to ~/.claude/.credentials.json.

    Returns True if credentials were saved successfully.
    """
    parsed = urllib.parse.urlparse(callback_url.strip())
    internal_url = f"http://localhost:{port}/callback"
    if parsed.query:
        internal_url += f"?{parsed.query}"

    logger.info("Forwarding callback to CLI server", url=internal_url)

    async with aiohttp.ClientSession() as session:
        try:
            await session.get(
                internal_url,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,
            )
        except aiohttp.ClientConnectionError:
            pass  # CLI closes connection after processing — expected
        except Exception as e:
            logger.warning("Callback forwarding error", error=str(e))

    # Poll for credentials (up to 10s)
    for _ in range(20):
        await asyncio.sleep(0.5)
        if is_authenticated():
            logger.info("CLI auth: credentials saved")
            break

    try:
        proc.kill()
    except Exception:
        pass

    return is_authenticated()
