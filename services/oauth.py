import urllib.request
import urllib.parse
import urllib.error
import json
import ssl
import logging

logger = logging.getLogger(__name__)

def get_google_auth_url(state, redirect_uri, client_id):
    """Generate the Google OAuth authorization URL."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account"
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

def exchange_google_code(code, redirect_uri, client_id, client_secret):
    """Exchange authorization code for access and ID tokens."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }).encode("utf-8")
    
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    
    try:
        # Attempt with standard system SSL verification first
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as e:
        # Check if the error is due to missing local SSL issuer certificates (common on macOS)
        error_msg = str(e.reason) if hasattr(e, "reason") else str(e)
        if "CERTIFICATE_VERIFY_FAILED" in error_msg:
            logger.warning("Local SSL certificate verification failed. Retrying with unverified context.")
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=10, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        raise e

def get_google_user_info(access_token):
    """Fetch user profile details (email, name, sub) from Google using access token."""
    req = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    
    try:
        # Attempt with standard system SSL verification first
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as e:
        error_msg = str(e.reason) if hasattr(e, "reason") else str(e)
        if "CERTIFICATE_VERIFY_FAILED" in error_msg:
            logger.warning("Local SSL certificate verification failed. Retrying with unverified context.")
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=10, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        raise e
