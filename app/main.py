import os

import aioredis
from fastapi import FastAPI
from fastapi_admin.app import app as admin_app
from fastapi_admin.constants import BASE_DIR
from tortoise.contrib.fastapi import register_tortoise

from app.admin.auth import AuthProvider
from app.callbooker.views import cb_router
from app.settings import Settings
from app.tc2.views import tc2_router

from app.admin import resources, views

settings = Settings()

app = FastAPI()
app.mount('/admin', admin_app)
register_tortoise(
    app,
    db_url=settings.pg_dsn,
    modules={'models': ['app.models']},
    generate_schemas=True,
    add_exception_handlers=True,
)
app.include_router(tc2_router, prefix='/tc2')
app.include_router(cb_router, prefix='/callbooker')


@app.on_event('startup')
async def startup():
    redis = await aioredis.from_url(settings.redis_dsn)
    await admin_app.configure(
        logo_url='https://preview.tabler.io/static/logo-white.svg',
        template_folders=[os.path.join(BASE_DIR, 'admin/templates')],
        providers=[AuthProvider()],
        redis=redis,
    )
