from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
import uuid
import logging

from app.core.exceptions import (
    BaseAppException,
    DocumentNotFoundError,
    RelationNotFoundError,
    ValidationError as AppValidationError,
    DatabaseError,
    SearchError,
    EmbeddingError,
    AuthenticationError,
    AuthorizationError,
    IngestError
)
from app.core.error_responses import (
    ErrorResponse,
    ValidationErrorResponse,
    DatabaseErrorResponse,
    NotFoundResponse,
    AuthenticationErrorResponse,
    AuthorizationErrorResponse,
    SearchErrorResponse,
    IngestErrorResponse
)

logger = logging.getLogger(__name__)


async def exception_handler(request: Request, exc: BaseAppException) -> JSONResponse:
    """Handler for custom application exceptions."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    
    # Map exception types to response types
    response_mapping = {
        DocumentNotFoundError: (NotFoundResponse, status.HTTP_404_NOT_FOUND),
        RelationNotFoundError: (NotFoundResponse, status.HTTP_404_NOT_FOUND),
        AppValidationError: (ValidationErrorResponse, status.HTTP_422_UNPROCESSABLE_ENTITY),
        DatabaseError: (DatabaseErrorResponse, status.HTTP_500_INTERNAL_SERVER_ERROR),
        SearchError: (SearchErrorResponse, status.HTTP_500_INTERNAL_SERVER_ERROR),
        EmbeddingError: (SearchErrorResponse, status.HTTP_500_INTERNAL_SERVER_ERROR),
        AuthenticationError: (AuthenticationErrorResponse, status.HTTP_401_UNAUTHORIZED),
        AuthorizationError: (AuthorizationErrorResponse, status.HTTP_403_FORBIDDEN),
        IngestError: (IngestErrorResponse, status.HTTP_500_INTERNAL_SERVER_ERROR),
    }
    
    response_class, status_code = response_mapping.get(
        type(exc), (ErrorResponse, status.HTTP_500_INTERNAL_SERVER_ERROR)
    )
    
    # Build response
    response_data = {
        "error": response_class.__fields__["error"].default,
        "message": exc.message,
        "details": exc.details,
        "timestamp": exc.__class__.__name__,
        "request_id": request_id
    }
    
    logger.error(
        f"Request {request_id} failed: {exc.__class__.__name__} - {exc.message}",
        extra={"request_id": request_id, "details": exc.details}
    )
    
    return JSONResponse(
        status_code=status_code,
        content=response_data
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handler for Pydantic validation errors."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    
    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(loc) for loc in error["loc"]),
            "message": error["msg"],
            "type": error["type"]
        })
    
    response_data = {
        "error": "validation_error",
        "message": "Error de validación en los datos de entrada",
        "details": {"errors": errors},
        "timestamp": str(exc.__class__.__name__),
        "request_id": request_id
    }
    
    logger.warning(
        f"Request {request_id} validation failed: {errors}",
        extra={"request_id": request_id, "errors": errors}
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response_data
    )


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Handler for SQLAlchemy database errors."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    
    response_data = {
        "error": "database_error",
        "message": "Error en la base de datos",
        "details": {"detail": str(exc)},
        "timestamp": str(exc.__class__.__name__),
        "request_id": request_id
    }
    
    logger.error(
        f"Request {request_id} database error: {exc}",
        extra={"request_id": request_id, "exception": str(exc)}
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response_data
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler for unhandled exceptions."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    
    response_data = {
        "error": "internal_error",
        "message": "Error interno del servidor",
        "details": {"detail": str(exc)} if request.app.state.APP_ENV == "development" else {},
        "timestamp": str(exc.__class__.__name__),
        "request_id": request_id
    }
    
    logger.error(
        f"Request {request_id} unhandled exception: {exc}",
        extra={"request_id": request_id, "exception": str(exc)},
        exc_info=True
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response_data
    )


async def request_id_middleware(request: Request, call_next):
    """Middleware to add request ID to each request."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    
    return response
