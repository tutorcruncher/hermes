from contextlib import asynccontextmanager

import logfire
import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.callbooker.views import router as callbooker_router
from app.core.config import settings
from app.core.logging import get_logger
from app.main_app.views import router as main_app_router
from app.pipedrive.views import router as pipedrive_router
from app.tc2.views import router as tc2_router

logger = get_logger('hermes')

# Initialize Logfire
if settings.logfire_token:
    logfire.configure(token=settings.logfire_token)

# Initialize Sentry
if settings.sentry_dsn:
    sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan (startup and shutdown)"""
    # Startup
    logger.info('Starting Hermes application')
    # TODO: Initialize database connections, load config, etc.
    yield
    # Shutdown
    logger.info('Shutting down Hermes application')


# Create FastAPI app
app = FastAPI(
    title='Hermes',
    description='Sales system integrating TC2, Pipedrive, and Callbooker',
    version='4.0.0',
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Instrument with Logfire
logfire.instrument_fastapi(app)


@app.get('/')
async def root():
    """Health check endpoint"""
    return {'status': 'ok', 'app': 'Hermes', 'version': '4.0.0'}


@app.get('/health')
async def health():
    """Health check endpoint"""
    return {'status': 'healthy'}


app.include_router(main_app_router)
app.include_router(pipedrive_router)
app.include_router(tc2_router)
app.include_router(callbooker_router)
