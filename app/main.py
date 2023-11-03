import logging.config
import os
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi_admin.app import app as admin_app
from starlette.middleware.cors import CORSMiddleware
from tortoise.contrib.fastapi import register_tortoise

from app.admin import resources, views  # noqa: F401
from app.admin.auth import AuthProvider
from app.callbooker.views import cb_router
from app.hermes.views import main_router
from app.logging import config
from app.pipedrive.views import pipedrive_router
from app.settings import Settings
from app.tc2.views import tc2_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_app_settings = Settings()

if _app_settings.sentry_dsn:
    sentry_sdk.init(dsn=_app_settings.sentry_dsn)


app = FastAPI()
allowed_origins = ['https://tutorcruncher.com']
if _app_settings.dev_mode:
    allowed_origins = ['*']
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=['*'], allow_headers=['*'])
logging.config.dictConfig(config)
register_tortoise(
    app,
    db_url=_app_settings.pg_dsn,
    modules={'models': ['app.models']},
    generate_schemas=True,
    add_exception_handlers=True,
)
app.include_router(tc2_router, prefix='/tc2')
app.include_router(cb_router, prefix='/callbooker')
app.include_router(pipedrive_router, prefix='/pipedrive')
app.include_router(main_router, prefix='')
# Has to go last otherwise it will override other routes
app.mount('/', admin_app)


async def _startup():
    from app.models import Admin
    from app.utils import get_redis_client

    await admin_app.configure(
        template_folders=[os.path.join(BASE_DIR, 'admin/templates/')],
        providers=[AuthProvider(Admin)],
        language_switch=False,
        redis=await get_redis_client(),
        admin_path='',
    )
    from app.utils import get_config

    await get_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup()
    yield
