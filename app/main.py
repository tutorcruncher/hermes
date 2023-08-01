import logging
import os

import aioredis
import sentry_sdk
from fastapi import FastAPI
from fastapi_admin.app import app as admin_app
from tortoise.contrib.fastapi import register_tortoise

from app.admin import resources, views  # noqa: F401
from app.admin.auth import AuthProvider
from app.callbooker.views import cb_router
from app.hermes.views import main_router
from app.pipedrive.views import pipedrive_router
from app.settings import Settings
from app.tc2.views import tc2_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_app_settings = Settings()

if _app_settings.sentry_dsn:
    sentry_sdk.init(dsn=_app_settings.sentry_dsn)


app = FastAPI()
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


@app.on_event('startup')
async def startup():
    redis = await aioredis.from_url(_app_settings.redis_dsn)
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


if __name__ == '__main__':
    import uvicorn

    log_config = uvicorn.config.LOGGING_CONFIG

    # log_config['formatters']['access']['fmt'] = '%(name)20s: %(levelname)9s - %(message)s'
    # log_config['formatters']['default']['fmt'] = '%(name)20s: %(levelname)9s - %(message)s'
    log_config['loggers']['hermes'] = {
        'handlers': ['default'],
        'level': 'DEBUG' if _app_settings else 'INFO',
        'propagate': False,
    }
    uvicorn.run(
        app,
        host=_app_settings.host,
        port=_app_settings.port,
        log_level=logging.DEBUG if _app_settings.dev_mode else logging.INFO,
        log_config=log_config,
    )
