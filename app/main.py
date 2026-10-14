from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from app.core.database import get_session
from app.api import auth, search, documents, external_ai
#from app.ai.api import chat
from app.core.config import settings
from app.core.middleware import (
    exception_handler,
    validation_exception_handler,
    sqlalchemy_exception_handler,
    general_exception_handler,
    request_id_middleware
)
from app.core.exceptions import BaseAppException
from app.core.database import check_db_connection


app = FastAPI(
    title="Sistema de Búsqueda de Documentos",
    version="0.1.0",
    description="Búsqueda semántica y chatbot RAG sobre documentos institucionales",
    swagger_ui_init_oauth={
        "clientId": settings.COGNITO_CLIENT_ID,
        "appName": "Sistema de Búsqueda Swagger"
    }
)

# Store app state for middleware
app.state.APP_ENV = settings.APP_ENV

# Add request ID middleware
app.middleware("http")(request_id_middleware)

# Add exception handlers
app.add_exception_handler(BaseAppException, exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, general_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,      prefix="/api/v1/auth",      tags=["auth"])
app.include_router(search.router,    prefix="/api/v1/search",    tags=["search"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
#app.include_router(chat.router,      prefix="/api/v1/chat",      tags=["chat"])
app.include_router(external_ai.router, prefix="/api/v1/ai",      tags=["external-ai"])

@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
async def database_health():
    connected = await check_db_connection()

    if connected:
        async def db_health():
            return await check_db_connection()
        return await db_health()

    return {"database": "disconnected"}
