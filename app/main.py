from fastapi import FastAPI
from tortoise.contrib.fastapi import register_tortoise

from app.callbooker.views import cb_router
from app.settings import Settings
from app.tc2.views import tc2_router

settings = Settings()

app = FastAPI()
register_tortoise(
    app,
    db_url=settings.pg_dsn,
    modules={'models': ['app.models']},
    generate_schemas=True,
    add_exception_handlers=True,
)
app.include_router(tc2_router, prefix='/tc2')
app.include_router(cb_router, prefix='/callbooker')
