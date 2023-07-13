import os

import aioredis
from fastapi import FastAPI
from fastapi_admin.app import app as admin_app
from tortoise.contrib.fastapi import register_tortoise

from app.admin import resources, views  # noqa: F401
from app.admin.auth import AuthProvider
from app.callbooker.views import cb_router
from app.settings import Settings
from app.tc2.views import tc2_router

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

settings = Settings()


def create_app(_settings):
    _app = FastAPI()
    register_tortoise(
        _app,
        db_url=_settings.pg_dsn,
        modules={'models': ['app.models']},
        generate_schemas=True,
        add_exception_handlers=True,
    )
    _app.include_router(tc2_router, prefix='/tc2')
    _app.include_router(cb_router, prefix='/callbooker')
    # Has to go last otherwise it will override other routes
    _app.mount('/', admin_app)

    @_app.on_event('startup')
    async def startup():
        redis = await aioredis.from_url(_settings.redis_dsn)
        await admin_app.configure(
            template_folders=[os.path.join(BASE_DIR, 'admin/templates/')],
            providers=[AuthProvider()],
            language_switch=False,
            redis=redis,
            admin_path='',
        )
        from app.utils import get_config

        await get_config()

    return _app


app = create_app(settings)
