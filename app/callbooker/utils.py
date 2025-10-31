import datetime
import logging

from pytz import utc

logger = logging.getLogger('hermes.callbooker')


def iso_8601_to_datetime(dt_str: str) -> datetime.datetime:
    """Convert ISO 8601 datetime string to datetime object"""
    # Removing the UTC timezone as `fromisoformat` doesn't support ISO 8601
    return datetime.datetime.fromisoformat(dt_str.rstrip('Z')).replace(tzinfo=utc)
