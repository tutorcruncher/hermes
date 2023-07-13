import hashlib
from typing import TYPE_CHECKING

import aioredis
from tortoise.exceptions import DoesNotExist

from app.settings import Settings

if TYPE_CHECKING:
    from app.models import Configs

settings = Settings()


async def sign_args(*args):
    s = settings.signing_key + ':' + '-'.join(str(a) for a in args if a)
    return hashlib.sha1(s.encode()).hexdigest()


def get_bearer(auth: str):
    try:
        return auth.split(' ')[1]
    except (AttributeError, IndexError):
        return


redis_client = aioredis.from_url(settings.redis_dsn)


async def get_config() -> 'Configs':
    """
    We always want to have one Config object.
    """
    from app.models import Configs

    try:
        config = await Configs.get()
    except DoesNotExist:
        config = await Configs.create()
    return config
