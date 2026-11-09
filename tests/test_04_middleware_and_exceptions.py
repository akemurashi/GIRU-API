"""
Suite 4: Middlewares, Mapeo Semántico de Excepciones y Trazabilidad (RF-08, RNF-04, RNF-05).
"""

import json
import types
import unittest
from unittest.mock import patch

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

import tests.base  # noqa: F401
from app.core.config import settings
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
    _is_development,
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

    async def test_32b_sqlalchemy_exception_handler_production_redacts_details(self):
        """Verifica que sqlalchemy_exception_handler oculte detalles de SQL, tablas y parámetros en producción."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents",
            "headers": [],
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="production")),
        }
        request = Request(scope)
        request.state.request_id = "req-sql-prod"

        exc = SQLAlchemyError(
            "(psycopg2.errors.UniqueViolation) duplicate key value violates unique constraint 'users_email_key'\n"
            "DETAIL: Key (email)=(admin@usm.cl) already exists.\n"
            "[SQL: INSERT INTO users (email, secret_token) VALUES (%(email)s, %(token)s)]\n"
            "[parameters: {'email': 'admin@usm.cl', 'token': 's3cr3t_p4ssw0rd'}]"
        )
        response = await sqlalchemy_exception_handler(request, exc)
        self.assertEqual(response.status_code, 500)
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["error"], "database_error")
        self.assertEqual(body["message"], "Error en la base de datos")
        self.assertEqual(body["details"], {})
        self.assertEqual(body["request_id"], "req-sql-prod")

        # Verificar que ningún dato sensible o detalle de base de datos se exponga en la respuesta
        raw_response = response.body.decode("utf-8")
        self.assertNotIn("secret_token", raw_response)
        self.assertNotIn("s3cr3t_p4ssw0rd", raw_response)
        self.assertNotIn("users_email_key", raw_response)
        self.assertNotIn("admin@usm.cl", raw_response)
        self.assertNotIn("INSERT INTO", raw_response)

    async def test_32c_sqlalchemy_exception_handler_development_exposes_details(self):
        """Verifica que sqlalchemy_exception_handler exponga detalles diagnósticos en modo desarrollo."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents",
            "headers": [],
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="development")),
        }
        request = Request(scope)
        request.state.request_id = "req-sql-dev"

        exc = SQLAlchemyError("Deadlock detectado en transaccion PostgreSQL")
        response = await sqlalchemy_exception_handler(request, exc)
        self.assertEqual(response.status_code, 500)
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["error"], "database_error")
        self.assertEqual(body["details"], {"detail": "Deadlock detectado en transaccion PostgreSQL"})
        self.assertIn("Deadlock detectado en transaccion PostgreSQL", body["details"]["detail"])

    async def test_32d_sqlalchemy_exception_handler_scope_lacking_app_graceful(self):
        """Verifica que scope sin 'app' no lance KeyError y aplique fallback a settings.APP_ENV."""
        scope_no_app = {"type": "http", "method": "GET", "path": "/api/v1/documents", "headers": []}

        # 1. Fallback a desarrollo cuando settings.APP_ENV == 'development'
        req_no_app_dev = Request(scope_no_app)
        req_no_app_dev.state.request_id = "req-no-app-dev"
        exc = SQLAlchemyError("Error de conexion DB")
        with patch.object(settings, "APP_ENV", "development"):
            resp_dev = await sqlalchemy_exception_handler(req_no_app_dev, exc)
            self.assertEqual(resp_dev.status_code, 500)
            body_dev = json.loads(resp_dev.body.decode("utf-8"))
            self.assertEqual(body_dev["error"], "database_error")
            self.assertIn("Error de conexion DB", body_dev["details"]["detail"])

        # 2. Fallback a producción cuando settings.APP_ENV == 'production'
        req_no_app_prod = Request(scope_no_app)
        req_no_app_prod.state.request_id = "req-no-app-prod"
        with patch.object(settings, "APP_ENV", "production"):
            resp_prod = await sqlalchemy_exception_handler(req_no_app_prod, exc)
            self.assertEqual(resp_prod.status_code, 500)
            body_prod = json.loads(resp_prod.body.decode("utf-8"))
            self.assertEqual(body_prod["error"], "database_error")
            self.assertEqual(body_prod["details"], {})
            self.assertNotIn("Error de conexion DB", resp_prod.body.decode("utf-8"))

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

        # Caso Scope sin clave 'app' (evita KeyError: 'app')
        scope_no_app = {"type": "http", "method": "GET", "path": "/api/v1/test", "headers": []}
        req_no_app = Request(scope_no_app)
        req_no_app.state.request_id = "req-no-app"

        with patch.object(settings, "APP_ENV", "production"):
            resp_no_app_prod = await general_exception_handler(req_no_app, RuntimeError("Fallo sin app en scope"))
            self.assertEqual(resp_no_app_prod.status_code, 500)
            body_no_app_prod = json.loads(resp_no_app_prod.body.decode("utf-8"))
            self.assertEqual(body_no_app_prod["details"], {})

        with patch.object(settings, "APP_ENV", "development"):
            resp_no_app_dev = await general_exception_handler(req_no_app, RuntimeError("Fallo sin app en scope"))
            self.assertEqual(resp_no_app_dev.status_code, 500)
            body_no_app_dev = json.loads(resp_no_app_dev.body.decode("utf-8"))
            self.assertIn("Fallo sin app en scope", body_no_app_dev["details"]["detail"])

    def test_33b_is_development_helper(self):
        """Verifica la lógica de la función auxiliar _is_development en múltiples contextos."""
        # Scope con app.state.APP_ENV == 'development'
        req1 = Request({
            "type": "http",
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="development"))
        })
        self.assertTrue(_is_development(req1))

        # Scope con app.state.APP_ENV == 'production'
        req2 = Request({
            "type": "http",
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="production"))
        })
        self.assertFalse(_is_development(req2))

        # Scope sin app: respeta settings.APP_ENV
        req3 = Request({"type": "http"})
        with patch.object(settings, "APP_ENV", "development"):
            self.assertTrue(_is_development(req3))
        with patch.object(settings, "APP_ENV", "production"):
            self.assertFalse(_is_development(req3))

        # Objeto sin scope o con scope no dict
        fake_req = types.SimpleNamespace()
        with patch.object(settings, "APP_ENV", "development"):
            self.assertTrue(_is_development(fake_req))
        with patch.object(settings, "APP_ENV", "production"):
            self.assertFalse(_is_development(fake_req))

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
