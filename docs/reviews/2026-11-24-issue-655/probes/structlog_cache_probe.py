"""Which sequence makes capture_logs() miss auth.py's jwks_key_skipped line (#658 order-dependent failure)."""
import io, contextlib, structlog
from cmapi.core import observability
from cmapi.core.auth import Jwks
bad = [{"kty": "RSA", "kid": "leak", "use": "sig", "alg": "RS256", "n": "AQAB", "e": ["AQAB"]}]
def captured():
    with contextlib.redirect_stdout(io.StringIO()), structlog.testing.capture_logs() as logs:
        Jwks._signing_keys(bad)
    return [l["event"] for l in logs]
import sys
case = sys.argv[1]
if case in ("configure+log", "configure+log+configure", "configure-error+log"):
    observability.configure_logging("ERROR" if case == "configure-error+log" else "INFO")
    with contextlib.redirect_stdout(io.StringIO()):
        observability.log.warning("warm")
if case == "configure+log+configure":
    observability.configure_logging("INFO")
if case == "configure-only":
    observability.configure_logging("INFO")
print(f"{case}: captured {captured()}")
