import logging.config
import os
from urllib.parse import urlparse

import aioredis
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

if _app_settings.testing:
    redis = aioredis.from_url(_app_settings.redis_dsn)
else:
    url = urlparse(_app_settings.redis_dsn)
    redis = aioredis.Redis(host=url.hostname, port=url.port, password=url.password, ssl=True, ssl_cert_reqs='none')

if _app_settings.sentry_dsn:
    sentry_sdk.init(dsn=_app_settings.sentry_dsn)


app = FastAPI()
allowed_origins = ['https://tutorcruncher.com/', 'https://tutorcruncher.com']
if _app_settings.dev_mode:
    allowed_origins = ['*']
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=['*'], allow_headers=['*'])
logging.config.dictConfig(config)

TORTOISE_ORM = {
    'connections': {'default': str(_app_settings.pg_dsn)},
    'apps': {
        'models': {
            'models': ['app.models', 'aerich.models'],
            'default_connection': 'default',
        }
    },
}

register_tortoise(
    app,
    db_url=_app_settings.pg_dsn,
    generate_schemas=True,
    add_exception_handlers=True,
    config=TORTOISE_ORM,
)
app.include_router(tc2_router, prefix='/tc2')
app.include_router(cb_router, prefix='/callbooker')
app.include_router(pipedrive_router, prefix='/pipedrive')
app.include_router(main_router, prefix='')
# Has to go last otherwise it will override other routes
app.mount('/', admin_app)


@app.on_event('startup')
async def startup():
    from app.models import Admin

    await admin_app.configure(
        template_folders=[os.path.join(BASE_DIR, 'admin/templates/')],
        providers=[AuthProvider(Admin)],
        language_switch=False,
        redis=redis,
        admin_path='',
    )
    from app.utils import get_config

    await get_config()
