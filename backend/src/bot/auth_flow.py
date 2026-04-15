"""Claude OAuth PKCE flow for Telegram-based authentication.

Flow:
1. Bot generates PKCE pair + state, builds authorization URL with
   redirect_uri=https://platform.claude.com/oauth/code/callback
2. Kevin opens the URL, authorizes on claude.com
3. Browser redirects to https://platform.claude.com/oauth/code/callback?code=...&state=...
   (this page loads fine — no "connection refused")
4. Kevin copies the full URL from the address bar and sends it to the bot
5. Bot extracts the code, exchanges it for tokens, saves credentials
"""

import base64
import hashlib
import json
import os
import time
import urllib.parse
from pathlib import Path

import aiohttp
import structlog

logger = structlog.get_logger()

_CREDENTIALS_FILE = Path("/root/.claude/.credentials.json")

# OAuth endpoints and client config (same as Claude Code CLI prod config)
_AUTH_URL = "https://claude.com/cai/oauth/authorize"
_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
_MANUAL_REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
_SCOPES = "org:create_api_key user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"


# ── Credential helpers ─────────────────────────────────────────────────────

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
        if expires_at and isinstance(expires_at, (int, float)):
            if expires_at < (time.time() * 1000 + 300_000):
                return False
        return True
    except Exception:
        return False


async def try_refresh_token() -> bool:
    """Try to silently refresh the access token using the stored refresh token."""
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
                timeout=aiohttp.ClientTimeout(total=30),
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
    """Return True if valid credentials exist or could be refreshed silently."""
    if is_authenticated():
        return True
    return await try_refresh_token()


def save_credentials(token_data: dict) -> None:
    """Write tokens to ~/.claude/.credentials.json (CLI-compatible format)."""
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
        "expiresAt": int((time.time() + expires_in) * 1000),  # milliseconds, same as CLI
        "scopes": token_data.get("scope", _SCOPES).split(),
        "subscriptionType": token_data.get("subscription_type", "unknown"),
        "rateLimitTier": token_data.get("rate_limit_tier", "default"),
    }

    _CREDENTIALS_FILE.write_text(json.dumps(existing, indent=2))
    logger.info("Claude credentials saved", path=str(_CREDENTIALS_FILE))


# ── PKCE auth flow ─────────────────────────────────────────────────────────

def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def start_pkce_auth() -> tuple[str, str, str]:
    """
    Build the Claude AI OAuth authorization URL.

    Uses redirect_uri=https://platform.claude.com/oauth/code/callback so that
    Kevin's browser lands on a real Anthropic page (no "connection refused").
    Kevin copies the full URL from the address bar and sends it back.

    Returns (auth_url, code_verifier, state).
    """
    code_verifier, code_challenge = _pkce_pair()
    state = base64.urlsafe_b64encode(os.urandom(24)).rstrip(b"=").decode()

    params = urllib.parse.urlencode({
        "code": "true",
        "client_id": _CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _MANUAL_REDIRECT_URI,
        "scope": _SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    auth_url = f"{_AUTH_URL}?{params}"
    logger.info("PKCE auth URL generated", challenge_prefix=code_challenge[:8], state_prefix=state[:8])
    return auth_url, code_verifier, state


async def complete_pkce_auth(
    user_input: str,
    code_verifier: str,
    expected_state: str,
) -> None:
    """
    Exchange the authorization code for tokens and save credentials.

    user_input: full callback URL from address bar, OR just the authorization code.
    Raises ValueError with a descriptive message on failure.
    """
    user_input = user_input.strip()

    # Anthropic's callback page displays "code#state" as a combined string.
    # Strip the fragment (everything from '#' onwards) to get the bare code.
    if "#" in user_input and not user_input.startswith("http"):
        user_input = user_input.split("#")[0].strip()

    code = user_input
    received_state: str | None = None

    # If a full URL was pasted instead of a bare code, extract the code param
    try:
        parsed = urllib.parse.urlparse(user_input)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                code = qs["code"][0]
                received_state = qs.get("state", [""])[0] or None
                if received_state and received_state != expected_state:
                    raise ValueError(
                        "State-Parameter stimmt nicht überein — bitte eine neue Nachricht "
                        "schicken um den Flow neu zu starten."
                    )
    except ValueError:
        raise
    except Exception:
        pass  # treat entire input as bare code

    logger.info("Starting PKCE token exchange", code_len=len(code))

    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            _TOKEN_URL,
            json={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _MANUAL_REDIRECT_URI,
                "client_id": _CLIENT_ID,
                "code_verifier": code_verifier,
                "state": expected_state,
            },
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        )
        if resp.status != 200:
            body = await resp.text()
            logger.error("Token exchange failed", status=resp.status, body=body[:400])
            raise ValueError(
                f"Token-Exchange fehlgeschlagen (HTTP {resp.status}):\n{body[:300]}"
            )
        token_data = await resp.json()

    save_credentials(token_data)

    if not is_authenticated():
        # Credential file exists but fails validation — report details
        try:
            raw = json.loads(_CREDENTIALS_FILE.read_text())
            oauth = raw.get("claudeAiOauth", {})
            expires_at = oauth.get("expiresAt")
            now_ms = int(time.time() * 1000)
            raise ValueError(
                f"Credentials gespeichert, aber ungültig.\n"
                f"access_token: {'✓' if oauth.get('accessToken') else '✗'}, "
                f"expiresAt: {expires_at} (now_ms={now_ms}, diff={((expires_at or 0) - now_ms) // 1000}s)"
            )
        except ValueError:
            raise
        except Exception as ex:
            raise ValueError(f"Credentials gespeichert, aber Validierung fehlgeschlagen: {ex}")

    logger.info("PKCE auth completed successfully")
