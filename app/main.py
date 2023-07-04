from fastapi import FastAPI
from tortoise.contrib.fastapi import register_tortoise

from app.tutorcruncher2.views import tc2_router
from app.settings import Settings

settings = Settings()

app = FastAPI()
register_tortoise(
    app,
    db_url=settings.pg_dsn,
    modules={'models': ['app.models']},
    generate_schemas=True,
    add_exception_handlers=True,
)
app.include_router(tc2_router)
