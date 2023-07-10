import hashlib

from app.settings import Settings

settings = Settings()


async def sign_args(**kwargs):
    s = settings.signing_key + ':' + '-'.join(str(a) for a in kwargs.values() if a)
    return hashlib.sha1(s.encode()).hexdigest()
