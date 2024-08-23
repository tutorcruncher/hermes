import hashlib
import logging
import unicodedata
from typing import TYPE_CHECKING

import aioredis
from tortoise.exceptions import DoesNotExist

from app.settings import Settings

if TYPE_CHECKING:
    from app.models import Config

settings = Settings()
logger = logging.getLogger('utils')


async def sign_args(*args):
    s = settings.signing_key + ':' + '-'.join(str(a) for a in args if a)
    return hashlib.sha1(s.encode()).hexdigest()


def get_bearer(auth: str):
    try:
        return auth.split(' ')[1]
    except (AttributeError, IndexError):
        return


async def get_redis_client() -> 'aioredis.Redis':
    return aioredis.from_url(str(settings.redis_dsn))


async def get_config() -> 'Config':
    """
    We always want to have one Config object.
    """
    from app.models import Config

    try:
        config = await Config.get()
    except DoesNotExist:
        config = await Config.create()

    # When testing locally, you can add your own admin user here. Set the pd_owner_id to your own Pipedrive user ID.

    return config


def sanitise_string(input_string: str) -> str:
    """
    Sanitises the input string based on the specified rules:
    - Convert to ASCII
    - Convert spaces to hyphens
    - Remove characters that aren't alphanumerics, underscores, or hyphens
    - Convert to lowercase
    - Strip leading and trailing whitespace
    to match django's slugify function
    """

    # Convert to ASCII
    ascii_string = unicodedata.normalize('NFKD', input_string).encode('ascii', 'ignore').decode()

    # Convert spaces to hyphens and strip leading/trailing whitespace
    hyphenated_string = ascii_string.replace(' ', '-').strip()

    # Remove characters that aren't alphanumerics, underscores, or hyphens
    sanitized_string = ''.join(char for char in hyphenated_string if char.isalnum() or char in ['_', '-'])

    # Convert to lowercase
    return sanitized_string.lower()
