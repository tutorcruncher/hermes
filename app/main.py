import logging.config
import os
from contextlib import asynccontextmanager

import logfire
import sentry_sdk
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi_admin.app import app as admin_app
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from starlette.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import RegisterTortoise

from app.admin import resources, views  # noqa: F401
from app.admin.auth import AuthProvider
from app.base_schema import build_custom_field_schema
from app.callbooker.views import cb_router
from app.hermes.views import main_router
from app.logging import config
from app.pipedrive.views import pipedrive_router
from app.settings import Settings
from app.tc2.views import tc2_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_app_settings = Settings()
if _app_settings.sentry_dsn:
    sentry_sdk.init(
        dsn=_app_settings.sentry_dsn,
    )


TORTOISE_CONFIG = {
    'connections': {'default': str(_app_settings.pg_dsn)},
    'apps': {
        'models': {
            'models': ['app.models', 'aerich.models'],
            'default_connection': 'default',
        }
    },
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _config = RegisterTortoise(
        app,
        config=TORTOISE_CONFIG,
        modules={'models': ['app.models']},
        generate_schemas=True,
        add_exception_handlers=True,
    )
    async with _config:
        await _startup()
        yield


async def _startup():
    from app.models import Admin
    from app.utils import get_config, get_redis_client

    await admin_app.configure(
        template_folders=[os.path.join(BASE_DIR, 'admin/templates/')],
        providers=[AuthProvider(Admin)],
        language_switch=False,
        redis=await get_redis_client(),
        admin_path='',
        favicon_url='/assets/favicon.ico',
    )
    await get_config()
    await build_custom_field_schema()


app = FastAPI(lifespan=lifespan)

allowed_origins = ['https://tutorcruncher.com', 'http://localhost:3000']
if _app_settings.dev_mode:
    allowed_origins = ['*']
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=['*'], allow_headers=['*'])
if bool(_app_settings.logfire_token):
    logfire.instrument_fastapi(app)
    logfire.instrument_pydantic()
    logfire.configure(send_to_logfire=True, token=_app_settings.logfire_token)

    FastAPIInstrumentor.instrument_app(app)

logging.config.dictConfig(config)

app.include_router(tc2_router, prefix='/tc2')
app.include_router(cb_router, prefix='/callbooker')
app.include_router(pipedrive_router, prefix='/pipedrive')
app.include_router(main_router, prefix='')
# Has to go last otherwise it will override other routes
app.mount('/assets', StaticFiles(directory='app/assets'), name='assets')
app.mount('/', admin_app)

COMMIT = os.getenv('HEROKU_SLUG_COMMIT', '-')[:7]
RELEASE_CREATED_AT = os.getenv('HEROKU_RELEASE_CREATED_AT', '-')
if bool(_app_settings.logfire_token):
    logfire.info('starting app {commit=} {release_created_at=}', commit=COMMIT, release_created_at=RELEASE_CREATED_AT)
