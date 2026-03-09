"""
Shared rate limiter instance — imported by both main.py and routers
to avoid circular imports.
"""
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

_redis_url = os.getenv("REDIS_URL", "")
if _redis_url:
    limiter = Limiter(key_func=get_remote_address, storage_uri=_redis_url)
else:
    limiter = Limiter(key_func=get_remote_address)
