"""
Suite 4: Middlewares, Mapeo Semántico de Excepciones y Trazabilidad (RF-08, RNF-04, RNF-05).
"""

import json
import types
import unittest

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

import tests.base  # noqa: F401
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    CatalogNotFoundError,
    DAGCycleError,
    DatabaseError,
    DocumentNotFoundError,
    EmbeddingError,
    IngestError,
    RelationNotFoundError,
    SearchError,
    UniqueConstraintError,
    ValidationError as AppValidationError,
)
from app.core.middleware import (
    exception_handler,
    general_exception_handler,
    request_id_middleware,
    sqlalchemy_exception_handler,
    validation_exception_handler,
)


class TestSuite4MiddlewareExceptionMappingAndTraceability(unittest.IsolatedAsyncioTestCase):
    """Suite 4: Mapeo semántico de excepciones y trazabilidad X-Request-ID."""

    async def test_30_middleware_semantic_exception_mapping_complete_catalog(self):
        """Verifica traducción determinista de las 12 excepciones canónicas a códigos HTTP."""
        scope = {"type": "http", "method": "GET", "path": "/api/v1/documents/1", "headers": []}
        request = Request(scope)
        request.state.request_id = "req-trace-uuid-2026"

        cases = [
            (AuthenticationError("Token expirado"), 401, "authentication_error"),
            (AuthorizationError("Se requiere rol admin"), 403, "authorization_error"),
            (DocumentNotFoundError(999), 404, "not_found"),
            (RelationNotFoundError(888), 404, "not_found"),
            (AppValidationError("Ciclo detectado en DAG", field="iddocumentodestino"), 422, "validation_error"),
            (DAGCycleError("Ciclo detectado"), 422, "dag_cycle_error"),
            (CatalogNotFoundError("Categoria inexistente"), 400, "catalog_not_found"),
            (UniqueConstraintError("Numero duplicado"), 409, "unique_constraint_error"),
            (DatabaseError("Fallo en pool asyncpg"), 500, "database_error"),
            (SearchError("Fallo de motor"), 500, "search_error"),
            (EmbeddingError("Fallo de embedding"), 500, "search_error"),
            (IngestError("Fallo de ingest"), 500, "ingest_error"),
        ]

        for exc, expected_status, expected_error_code in cases:
            with self.subTest(exception=type(exc).__name__):
                response = await exception_handler(request, exc)
                self.assertEqual(response.status_code, expected_status)
                body = json.loads(response.body.decode("utf-8"))
                self.assertEqual(body["error"], expected_error_code)
                self.assertEqual(body["request_id"], "req-trace-uuid-2026")

    async def test_31_validation_exception_handler_pydantic_errors(self):
        """Verifica que validation_exception_handler transforme RequestValidationError a HTTP 422 estándar."""
        scope = {"type": "http", "method": "POST", "path": "/api/v1/search", "headers": []}
        request = Request(scope)
        request.state.request_id = "req-val-999"

        exc = RequestValidationError([
            {"loc": ("body", "page"), "msg": "Input should be greater than 0", "type": "greater_than"}
        ])
        response = await validation_exception_handler(request, exc)
        self.assertEqual(response.status_code, 422)
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["error"], "validation_error")
        self.assertEqual(body["request_id"], "req-val-999")
        self.assertEqual(body["details"]["errors"][0]["field"], "body.page")

    async def test_32_sqlalchemy_exception_handler(self):
        """Verifica que sqlalchemy_exception_handler capture fallos de driver a HTTP 500 database_error."""
        scope = {"type": "http", "method": "GET", "path": "/api/v1/documents", "headers": []}
        request = Request(scope)
        request.state.request_id = "req-sql-555"

        exc = SQLAlchemyError("Deadlock detectado en PostgreSQL")
        response = await sqlalchemy_exception_handler(request, exc)
        self.assertEqual(response.status_code, 500)
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["error"], "database_error")
        self.assertEqual(body["request_id"], "req-sql-555")

    async def test_33_general_exception_handler_development_and_production(self):
        """Verifica que general_exception_handler oculte detalles en producción y los exponga en desarrollo."""
        # Caso Producción (oculta detalles de error)
        scope_prod = {
            "type": "http", "method": "GET", "path": "/api/v1/test", "headers": [],
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="production"))
        }
        req_prod = Request(scope_prod)
        req_prod.state.request_id = "req-prod"
        resp_prod = await general_exception_handler(req_prod, RuntimeError("Crash inesperado"))
        self.assertEqual(resp_prod.status_code, 500)
        body_prod = json.loads(resp_prod.body.decode("utf-8"))
        self.assertEqual(body_prod["error"], "internal_error")
        self.assertEqual(body_prod["details"], {})

        # Caso Desarrollo (expone detalles para debugging)
        scope_dev = {
            "type": "http", "method": "GET", "path": "/api/v1/test", "headers": [],
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="development"))
        }
        req_dev = Request(scope_dev)
        req_dev.state.request_id = "req-dev"
        resp_dev = await general_exception_handler(req_dev, RuntimeError("Traceback de depuracion"))
        self.assertEqual(resp_dev.status_code, 500)
        body_dev = json.loads(resp_dev.body.decode("utf-8"))
        self.assertIn("Traceback de depuracion", body_dev["details"]["detail"])

    async def test_34_request_id_middleware_propagation_and_generation(self):
        """Verifica que request_id_middleware propague header existente o genere un nuevo UUID si no existe."""
        # 1. Header provisto por el cliente
        scope_with_header = {
            "type": "http", "method": "GET", "path": "/test",
            "headers": [(b"x-request-id", b"custom-client-trace-123")]
        }
        req1 = Request(scope_with_header)
        async def call_next_1(req):
            return Response(content="ok")

        resp1 = await request_id_middleware(req1, call_next_1)
        self.assertEqual(resp1.headers["X-Request-ID"], "custom-client-trace-123")
        self.assertEqual(req1.state.request_id, "custom-client-trace-123")

        # 2. Header ausente (debe generar UUID)
        scope_without_header = {"type": "http", "method": "GET", "path": "/test", "headers": []}
        req2 = Request(scope_without_header)
        async def call_next_2(req):
            return Response(content="ok")

        resp2 = await request_id_middleware(req2, call_next_2)
        self.assertIn("X-Request-ID", resp2.headers)
        self.assertEqual(req2.state.request_id, resp2.headers["X-Request-ID"])


if __name__ == "__main__":
    unittest.main()
