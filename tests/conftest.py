import pytest
from tortoise.contrib.test import finalizer, initializer

from app.utils import settings


@pytest.fixture(scope='module')
def anyio_backend():
    return 'asyncio'


@pytest.fixture(scope='module', autouse=True)
def initialize_tests(request):
    # Autouse means this is always called. Used to initialise tortoise.
    if settings.dev_mode:
        print(str(settings.pg_dsn_test))
        initializer(['app.models'], db_url=str(settings.pg_dsn_test))
    else:
        print(str(settings.pg_dsn))
        initializer(['app.models'], db_url=str(settings.pg_dsn))
    request.addfinalizer(finalizer)
