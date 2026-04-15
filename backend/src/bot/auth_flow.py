"""Interactive Claude OAuth login flow (PKCE) via Telegram.

When Claude is not authenticated, the bot sends the user an authorization URL.
The user clicks it, authenticates on claude.ai, and pastes the resulting code back.
The bot then exchanges the code for tokens and saves them to ~/.claude/.credentials.json.
"""

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from pathlib import Path

import aiohttp
import structlog

logger = structlog.get_logger()

# ── OAuth config (extracted from Claude Code CLI prod config) ──────────────────
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_AUTH_URL = "https://claude.com/cai/oauth/authorize"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_MANUAL_REDIRECT_URL = "https://platform.claude.com/oauth/code/callback"
_SCOPES = "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"

_CREDENTIALS_FILE = Path("/root/.claude/.credentials.json")


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
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": _CLIENT_ID,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
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


def build_auth_url() -> tuple[str, str]:
    """Generate PKCE pair and build OAuth authorization URL.

    Returns:
        (url, code_verifier) – send url to user, keep verifier for exchange step.
    """
    # PKCE
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    state = secrets.token_urlsafe(16)

    params = urllib.parse.urlencode({
        "code": "true",
        "client_id": _CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _MANUAL_REDIRECT_URL,
        "scope": _SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    url = f"{_AUTH_URL}?{params}"
    return url, verifier


async def exchange_code(code: str, verifier: str) -> dict:
    """Exchange authorization code for access/refresh tokens.

    Args:
        code: The authorization code pasted by the user.
        verifier: The PKCE code_verifier generated in build_auth_url().

    Returns:
        Token response dict from claude.ai.

    Raises:
        ValueError: If the token exchange fails.
    """
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            _TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code.strip(),
                "redirect_uri": _MANUAL_REDIRECT_URL,
                "client_id": _CLIENT_ID,
                "code_verifier": verifier,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "anthropic-beta": "oauth-2025-04-20",
            },
        )
        if resp.status != 200:
            text = await resp.text()
            logger.error("Token exchange failed", status=resp.status, body=text[:300])
            raise ValueError(f"Token-Austausch fehlgeschlagen ({resp.status}): {text[:200]}")
        return await resp.json()


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
