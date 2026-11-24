"""The least nesting depth of a token header at which jwt.get_unverified_header lets RecursionError escape (#655)."""
import base64, sys
import jwt
def b64(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def tok(d): return f"{b64(b'{\"alg\":\"RS256\",\"kid\":\"k\",\"x\":' + b'[' * d + b']' * d + b'}')}.{b64(b'{}')}.{b64(b'sig')}"
lo, hi = 1, 200_000
def escapes(d):
    try: jwt.get_unverified_header(tok(d))
    except RecursionError: return True
    except jwt.PyJWTError: return False
    return False
if not escapes(hi): print(f"PyJWT {jwt.__version__}: no RecursionError escapes up to depth {hi}"); sys.exit()
while lo < hi:
    mid = (lo + hi) // 2
    lo, hi = (lo, mid) if escapes(mid) else (mid + 1, hi)
print(f"PyJWT {jwt.__version__}, Python {sys.version.split()[0]}: RecursionError escapes from depth {lo}; that token is {len(tok(lo))} bytes")
