from pathlib import Path

from pydantic import BaseSettings, PostgresDsn

THIS_DIR = Path(__file__).parent.resolve()


class Settings(BaseSettings):
    pg_dsn: PostgresDsn = 'postgres://postgres@localhost:5432/hermes'

    support_ttl_days: int = 4
    call_booker_base_url: str = 'https://tutorcruncher.com/book-a-call/'

    #  TC
    tc2_api_key: str = 'test-key'
    tc2_api_url: str = 'https://localhost:8000/api/'

    class Config:
        env_file = '.env'

    # @validator('pg_dsn')
    # def heroku_ready_pg_dsn(cls, v):
    #     return v.replace('gres://', 'gresql://')
