import os

import pytest
from tortoise.contrib.test import finalizer, initializer

from app.settings import Settings

test_db_url = os.getenv('TEST_DB_URL', 'postgres://postgres@localhost:5432/hermes_test')


@pytest.fixture(scope='module')
def anyio_backend():
    return 'asyncio'


@pytest.fixture(name='settings', scope='module')
def fix_settings():
    return Settings(pg_dsn=test_db_url)


@pytest.fixture(scope='module', autouse=True)
def initialize_tests(request, settings):
    # Autouse means this is always called. Used to initialise tortoise.
    initializer(['app.models'], db_url=settings.pg_dsn)
    request.addfinalizer(finalizer)
