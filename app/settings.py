from pathlib import Path
from typing import Optional

from pydantic import BaseSettings

THIS_DIR = Path(__file__).parent.resolve()


class Settings(BaseSettings):
    pg_dsn: Optional[str] = 'postgres://postgres@localhost:5432/hermes'

    locale = ''  # Required, don't delete
    app: str = 'src.main:app'

    support_fernet_key: str = 'rqAq-Sc74904KQS9XjpVkQKmkaX7ccfyhOcp5_qyvwQ='
    support_ttl_days: int = 4
    call_booker_base_url: str = 'https://tutorcruncher.com/book-a-call/'

    #  TC
    tc2_api_key: str = 'test-key'
    tc2_api_url: str = 'htts://localhost:8000/api/'

    # @validator('pg_dsn')
    # def heroku_ready_pg_dsn(cls, v):
    #     return v.replace('gres://', 'gresql://')
