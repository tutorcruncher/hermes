import hashlib
from typing import TYPE_CHECKING

import aioredis
from tortoise.exceptions import DoesNotExist

from app.settings import Settings

if TYPE_CHECKING:
    from app.models import Config

settings = Settings()


async def sign_args(*args):
    s = settings.signing_key + ':' + '-'.join(str(a) for a in args if a)
    return hashlib.sha1(s.encode()).hexdigest()


def get_bearer(auth: str):
    try:
        return auth.split(' ')[1]
    except (AttributeError, IndexError):
        return


async def get_redis_client() -> 'aioredis.Redis':
    return await aioredis.from_url(settings.redis_dsn)


async def get_config() -> 'Config':
    """
    We always want to have one Config object.
    """
    from app.models import Config

    try:
        config = await Config.get()
    except DoesNotExist:
        config = await Config.create()

    from app.models import Admin

    if not await Admin.exists():
        await Admin.create(
            email='testing@tutorcruncher.com',
            username='testing@tutorcruncher.com',
            password='testing',
            is_bdr_person=True,
            is_sales_person=True,
            tc2_admin_id=66,
            pd_owner_id=15396545,
        )

    return config
