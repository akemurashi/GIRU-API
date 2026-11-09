"""
Test Suite 10: Security Remediation & Vulnerability Verification (R1, R2, R3, R4)
Authoritative Specifications:
- Requirement R1: External AI Router & Session Isolation (IDOR Fix) & Admin Diagnostic Guard (ORIGINAL_REQUEST.md §R1, PROJECT.md §R1.1, §R1.2)
- Requirement R2: Authentication & JWT Claim Verification Hardening & JWKS Caching (ORIGINAL_REQUEST.md §R2, PROJECT.md §R2.1, §R2.2, §R2.3)
- Requirement R3: Production Database Error Redaction (ORIGINAL_REQUEST.md §R3, PROJECT.md §R3.1)
- Requirement R4: Search Wildcard Sanitization (LIKE/ILIKE Comodines) (ORIGINAL_REQUEST.md §R4, PROJECT.md §R4.1)

Author: teamwork_test_writer_mtest
"""

from datetime import datetime
import json
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
import httpx
from jose import JWTError
from sqlalchemy.exc import SQLAlchemyError

import tests.base  # noqa: F401 - configures test environment variables
from app.api.auth import auth_service
from app.api.external_ai import get_external_ai_service
from app.core.config import Settings, settings
from app.core.middleware import general_exception_handler, sqlalchemy_exception_handler
from app.main import app
from app.models.ai_models import (
    AskResponse,
    CreateSessionResponse,
    DiagnosticResponse,
    SessionDetail,
    SessionListItem,
)
from app.models.user_models import UserOut, UserRole
from app.repositories.document_repository import DocumentRepository
from app.security.microsoft_auth import (
    CognitoAuth,
    require_admin,
    require_authenticated,
)


# =============================================================================
# TIER 1: External AI Router & Session Isolation (IDOR + Admin Restriction) [R1]
# =============================================================================
class TestSuite10Tier1ExternalAISessionIsolationAndRBAC(unittest.IsolatedAsyncioTestCase):
    """
    Tier 1: Pruebas de mitigación IDOR y control de acceso RBAC en endpoints de IA Externa.
    Authoritative Source: ORIGINAL_REQUEST.md §R1 y PROJECT.md §R1.1, §R1.2.
    """

    def setUp(self):
        super().setUp()
        self.client = TestClient(app, raise_server_exceptions=False)
        self.mock_ai_service = AsyncMock()

        self.alice_email = "alice@usm.cl"
        self.victim_email = "victim@usm.cl"

        # Usuario autenticado estándar (rol básico)
        self.mock_user_alice = UserOut(
            email=self.alice_email,
            name="Alice Alumna",
            role=UserRole.BASIC,
        )

        # Usuario administrador
        self.mock_user_admin = UserOut(
            email="admin@usm.cl",
            name="Admin General",
            role=UserRole.ADMIN,
        )

        # Configuración de dependencias compartidas
        self.mock_ai_service.get_diagnostic = AsyncMock(
            return_value=DiagnosticResponse(
                grafo="universidad_normativa",
                entidades=5000,
                relaciones=12000,
                documentos=1500,
            )
        )
        app.dependency_overrides[get_external_ai_service] = lambda: self.mock_ai_service
        # Inyectar Alice como identidad autenticada base del sistema
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.mock_user_alice

    def tearDown(self):
        app.dependency_overrides.clear()
        super().tearDown()

    def test_r1_01_create_session_enforces_authenticated_user_identity(self):
        """
        R1.1 (IDOR Prevention): Al crear una sesión, el servidor DEBE sobreescribir cualquier
        user_id suministrado en el cuerpo de la petición con el email del usuario autenticado (alice@usm.cl).
        """
        self.mock_ai_service.create_session = AsyncMock(
            return_value=CreateSessionResponse(
                id="ses-101",
                user_id=self.alice_email,
                titulo="Consulta de Pruebas",
                modo="cascade",
                creada=datetime.now(),
                actualizada=datetime.now(),
            )
        )

        # Intento de ataque IDOR: Alice intenta crear una sesión a nombre de la víctima
        payload = {
            "user_id": self.victim_email,
            "titulo": "Sesion Inyectada",
            "modo": "cascade",
        }
        res = self.client.post("/api/v1/ai/sessions", json=payload)
        self.assertEqual(res.status_code, 200)

        # Verificación autoritativa: el servicio externo DEBE haber recibido alice@usm.cl
        self.mock_ai_service.create_session.assert_awaited_once()
        forwarded_request = self.mock_ai_service.create_session.await_args[0][0]
        self.assertEqual(
            forwarded_request.user_id,
            self.alice_email,
            f"IDOR Detectado: user_id enviado a ExternalAIService fue '{forwarded_request.user_id}', "
            f"se esperaba '{self.alice_email}'",
        )

    def test_r1_02_list_sessions_ignores_client_user_id_query_param(self):
        """
        R1.1 (IDOR Prevention): GET /api/v1/ai/sessions debe listar únicamente las sesiones
        del usuario autenticado, ignorando cualquier user_id en los query parameters.
        """
        self.mock_ai_service.list_sessions = AsyncMock(return_value=[])

        # Intento de ataque IDOR: Alice consulta las sesiones de la víctima vía query param
        res = self.client.get(f"/api/v1/ai/sessions?user_id={self.victim_email}")
        self.assertEqual(res.status_code, 200)

        # Verificación autoritativa: list_sessions DEBE ser invocado con el correo de Alice
        self.mock_ai_service.list_sessions.assert_awaited_once_with(self.alice_email)

    def test_r1_03_get_session_enforces_authenticated_user_identity(self):
        """
        R1.1 (IDOR Prevention): GET /api/v1/ai/sessions/{session_id} debe validar pertenencia
        usando exclusivamente la identidad del usuario autenticado.
        """
        self.mock_ai_service.get_session = AsyncMock(
            return_value=SessionDetail(
                id="ses-101",
                user_id=self.alice_email,
                titulo="Sesion Alice",
                modo="cascade",
                mensajes=[],
                creada=datetime.now(),
                actualizada=datetime.now(),
            )
        )

        # Alice intenta leer la sesión enviando el id de la víctima
        res = self.client.get(f"/api/v1/ai/sessions/ses-101?user_id={self.victim_email}")
        self.assertEqual(res.status_code, 200)

        # Verificación autoritativa: get_session debe ser invocado con (session_id, alice_email)
        self.mock_ai_service.get_session.assert_awaited_once_with("ses-101", self.alice_email)

    def test_r1_04_delete_session_enforces_authenticated_user_identity(self):
        """
        R1.1 (IDOR Prevention): DELETE /api/v1/ai/sessions/{session_id} debe impedir que un
        usuario borre sesiones pertenecientes a otros identities.
        """
        self.mock_ai_service.delete_session = AsyncMock(return_value=None)

        res = self.client.delete(f"/api/v1/ai/sessions/ses-101?user_id={self.victim_email}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "deleted"})

        # Verificación autoritativa: delete_session debe ser invocado con (session_id, alice_email)
        self.mock_ai_service.delete_session.assert_awaited_once_with("ses-101", self.alice_email)

    def test_r1_05_ask_enforces_authenticated_user_identity(self):
        """
        R1.1 (IDOR Prevention): POST /api/v1/ai/ask debe forzar el user_id del usuario autenticado
        en la solicitud transmitida al servicio de IA.
        """
        self.mock_ai_service.ask = AsyncMock(
            return_value=AskResponse(
                session_id="ses-101",
                respuesta="Respuesta segura",
                fuentes=[],
                modo="cascade",
                tiempo_s=0.5,
                llamadas_llm=1,
            )
        )

        payload = {
            "session_id": "ses-101",
            "user_id": self.victim_email,
            "pregunta": "¿Cuál es mi información confidencial?",
        }
        res = self.client.post("/api/v1/ai/ask", json=payload)
        self.assertEqual(res.status_code, 200)

        self.mock_ai_service.ask.assert_awaited_once()
        ask_request = self.mock_ai_service.ask.await_args[0][0]
        self.assertEqual(
            ask_request.user_id,
            self.alice_email,
            f"IDOR Detectado en /ask: user_id fue '{ask_request.user_id}', se esperaba '{self.alice_email}'",
        )

    def test_r1_06_ask_stream_enforces_authenticated_user_identity(self):
        """
        R1.1 (IDOR Prevention): POST /api/v1/ai/ask-stream debe asociar el flujo streaming
        estrictamente a la identidad del usuario autenticado.
        """
        captured_request = None

        async def mock_stream(req):
            nonlocal captured_request
            captured_request = req
            yield "event: token\ndata: OK\n\n"

        self.mock_ai_service.ask_stream = mock_stream

        payload = {
            "session_id": "ses-101",
            "user_id": self.victim_email,
            "pregunta": "Stream con ID alterado",
        }
        res = self.client.post("/api/v1/ai/ask-stream", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(captured_request)
        self.assertEqual(
            captured_request.user_id,
            self.alice_email,
            f"IDOR Detectado en /ask-stream: user_id fue '{captured_request.user_id}'",
        )

    def test_r1_07_diagnostic_endpoint_rejects_basic_role_with_403(self):
        """
        R1.2 (Diagnostic RBAC Restriction): GET /api/v1/ai/diagnostic DEBE rechazar peticiones
        de usuarios con rol básico con HTTP 403 Forbidden y mensaje explicativo.
        """
        # Alice tiene rol BASIC
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.mock_user_alice
        res = self.client.get("/api/v1/ai/diagnostic")
        self.assertEqual(
            res.status_code,
            403,
            f"Fallo de autorización: usuario básico obtuvo {res.status_code} en vez de 403 Forbidden",
        )
        self.assertIn("Acceso restringido a administradores", res.json().get("detail", ""))

    def test_r1_08_diagnostic_endpoint_allows_admin_role_with_200(self):
        """
        R1.2 (Diagnostic RBAC Restriction): GET /api/v1/ai/diagnostic DEBE permitir acceso
        a usuarios con rol ADMIN.
        """
        # Usuario con rol ADMIN
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.mock_user_admin
        self.mock_ai_service.get_diagnostic = AsyncMock(
            return_value=DiagnosticResponse(
                grafo="universidad_normativa",
                entidades=5000,
                relaciones=12000,
                documentos=1500,
            )
        )

        res = self.client.get("/api/v1/ai/diagnostic")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["grafo"], "universidad_normativa")

    def test_r1_09_diagnostic_endpoint_rejects_unauthenticated_request_with_401(self):
        """
        R1.2: Petición sin credenciales a /api/v1/ai/diagnostic debe responder HTTP 401 Unauthorized.
        """
        # Eliminar cualquier override para simular cliente anónimo
        app.dependency_overrides.clear()
        res = self.client.get("/api/v1/ai/diagnostic")
        self.assertEqual(res.status_code, 401)


# =============================================================================
# TIER 2: JWT Claim Verification Hardening & JWKS Caching [R2]
# =============================================================================
class TestSuite10Tier2AuthenticationAndJwtHardening(unittest.IsolatedAsyncioTestCase):
    """
    Tier 2: Pruebas de verificación estricta de claims (aud, client_id, iss),
    caché en memoria de JWKS y sanitización de configuraciones por defecto.
    Authoritative Source: ORIGINAL_REQUEST.md §R2 y PROJECT.md §R2.1, §R2.2, §R2.3.
    """

    def setUp(self):
        self.auth = CognitoAuth()

    async def test_r2_01_jwks_caching_eliminates_repeated_network_fetches(self):
        """
        R2.2: Dos solicitudes consecutivas a CognitoAuth deben consultar la red (JWKS)
        exactamente UNA vez gracias a la caché en memoria con TTL de 1 hora.
        """
        mock_jwks = {"keys": [{"kid": "key-1", "kty": "RSA", "n": "mock", "e": "AQAB"}]}
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = mock_jwks

        payload = {"email": "test@usm.cl", "given_name": "Test", "family_name": "User"}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = mock_resp

            # Primera invocación: llena la caché
            user1 = await self.auth.get_current_user(token="token-alpha")
            self.assertEqual(user1.email, "test@usm.cl")

            # Segunda invocación: debe reutilizar la caché en memoria sin llamadas HTTP adicionales
            user2 = await self.auth.get_current_user(token="token-beta")
            self.assertEqual(user2.email, "test@usm.cl")

            self.assertEqual(
                mock_get.await_count,
                1,
                f"Fallo de caché JWKS: se esperaban 1 llamada HTTP pero se realizaron {mock_get.await_count}",
            )

    async def test_r2_02_jwks_force_refresh_bypasses_cached_keys(self):
        """
        R2.2: Invocar get_jwks(force_refresh=True) debe invalidar la caché y consultar la red.
        """
        if not hasattr(self.auth, "get_jwks"):
            # Invocar directamente para exponer la ausencia del método en la fase unremediated
            getattr(self.auth, "get_jwks")(force_refresh=True)

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": [{"kid": "key-fresh"}]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            jwks1 = await self.auth.get_jwks()
            self.assertIn("keys", jwks1)

            # Forzar actualización
            jwks2 = await self.auth.get_jwks(force_refresh=True)
            self.assertIn("keys", jwks2)
            self.assertEqual(mock_get.await_count, 2)

    async def test_r2_03_jwks_network_outage_falls_back_to_stale_cache(self):
        """
        R2.2: Ante una falla de red (e.g., timeout o 500) en refresh, el servicio debe
        retener y devolver la clave en caché en lugar de abortar abruptamente.
        """
        if not hasattr(self.auth, "get_jwks"):
            getattr(self.auth, "get_jwks")()

        mock_resp_ok = MagicMock(status_code=200)
        mock_resp_ok.json.return_value = {"keys": [{"kid": "key-stale"}]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp_ok
            # Llenar caché
            await self.auth.get_jwks()

            # Simular caída de red en siguiente refresh
            mock_get.side_effect = httpx.RequestError("Network unreachable")
            fallback_jwks = await self.auth.get_jwks(force_refresh=True)
            self.assertEqual(fallback_jwks["keys"][0]["kid"], "key-stale")

    async def test_r2_04_jwks_empty_cache_network_failure_raises_503(self):
        """
        R2.2: Si la caché está vacía y la red falla, debe elevarse HTTPException(503).
        """
        if not hasattr(self.auth, "get_jwks"):
            # Provocar ejecución directa
            await getattr(self.auth, "get_jwks")()

        fresh_auth = CognitoAuth()
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")
            with self.assertRaises(HTTPException) as ctx:
                await fresh_auth.get_jwks()
            self.assertEqual(ctx.exception.status_code, 503)

    async def test_r2_05_jwt_validates_matching_aud_claim(self):
        """
        R2.1: Token con claim 'aud' coincidente con self.client_id debe validarse con éxito.
        """
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": []}

        payload = {
            "aud": self.auth.client_id,
            "email": "aud.valido@usm.cl",
            "given_name": "Aud",
            "family_name": "Valid",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = mock_resp
            user = await self.auth.get_current_user(token="valid-aud-token")
            self.assertEqual(user.email, "aud.valido@usm.cl")

    async def test_r2_06_jwt_rejects_mismatched_aud_claim(self):
        """
        R2.1: Token con claim 'aud' que no coincide con el client_id configurado DEBE
        ser rechazado con HTTPException(401).
        """
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": []}

        payload = {
            "aud": "rogue-unauthorized-client-id",
            "email": "infiltrado@usm.cl",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = mock_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="rogue-aud-token")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Token inválido", ctx.exception.detail)

    async def test_r2_07_jwt_validates_matching_client_id_claim(self):
        """
        R2.1: Token con claim 'client_id' coincidente con self.client_id debe validarse con éxito.
        """
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": []}

        payload = {
            "client_id": self.auth.client_id,
            "email": "client.valido@usm.cl",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = mock_resp
            user = await self.auth.get_current_user(token="valid-client-id-token")
            self.assertEqual(user.email, "client.valido@usm.cl")

    async def test_r2_08_jwt_rejects_mismatched_client_id_claim(self):
        """
        R2.1: Token con claim 'client_id' discrepante DEBE ser rechazado con HTTPException(401).
        """
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": []}

        payload = {
            "client_id": "malicious-app-client",
            "email": "attacker@usm.cl",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = mock_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="bad-client-id-token")
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_r2_09_jwt_validates_matching_iss_claim(self):
        """
        R2.1: Token con claim 'iss' perteneciente al User Pool de Cognito esperado debe validarse.
        """
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": []}

        expected_iss = f"https://cognito-idp.{self.auth.region}.amazonaws.com/{self.auth.user_pool_id}"
        payload = {
            "iss": expected_iss,
            "email": "iss.valido@usm.cl",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = mock_resp
            user = await self.auth.get_current_user(token="valid-iss-token")
            self.assertEqual(user.email, "iss.valido@usm.cl")

    async def test_r2_10_jwt_rejects_untrusted_iss_claim(self):
        """
        R2.1: Token con claim 'iss' no reconocido DEBE ser rechazado con HTTPException(401).
        """
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": []}

        payload = {
            "iss": "https://untrusted-fake-idp.com/malicious_pool",
            "email": "spoofed@usm.cl",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = mock_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="untrusted-iss-token")
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_r2_11_jwt_backward_compatibility_omitted_claims(self):
        """
        R2.1: Tokens legados que no incluyan 'aud', 'client_id' o 'iss' (como en mocks históricos)
        deben seguir siendo aceptados sin lanzar excepción (100% retrocompatibilidad).
        """
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": []}

        payload = {
            "email": "legacy@usm.cl",
            "name": "Usuario Legado",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = mock_resp
            user = await self.auth.get_current_user(token="legacy-token")
            self.assertEqual(user.email, "legacy@usm.cl")

    def test_r2_12_config_admin_emails_default_is_sanitized(self):
        """
        R2.3: La configuración por defecto de Settings no debe contener correos ficticios
        'ejemplo.admin@usm.cl' ni 'name@example.com'.
        """
        # Evaluar la clase Settings directamente para inspeccionar valores predeterminados
        field_default = Settings.model_fields["ADMIN_EMAILS"].default
        self.assertNotIn("ejemplo.admin@usm.cl", field_default)
        self.assertNotIn("name@example.com", field_default)
        self.assertEqual(field_default, "")


# =============================================================================
# TIER 3: Production Database Error Redaction [R3]
# =============================================================================
class TestSuite10Tier3DatabaseErrorRedaction(unittest.IsolatedAsyncioTestCase):
    """
    Tier 3: Pruebas de anonimización de errores de base de datos en producción y preservación en desarrollo.
    Authoritative Source: ORIGINAL_REQUEST.md §R3 y PROJECT.md §R3.1.
    """

    async def test_r3_01_sqlalchemy_handler_redacts_details_in_production_environment(self):
        """
        R3.1: En producción (APP_ENV="production"), sqlalchemy_exception_handler NO debe
        filtrar consultas SQL crudas, nombres de columnas ni mensajes del motor en el cuerpo JSON.
        """
        scope_prod = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/documents",
            "headers": [],
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="production")),
        }
        req_prod = Request(scope_prod)
        req_prod.state.request_id = "req-prod-db-leak"

        sensitive_sql_error = (
            "CRITICAL: (psycopg2.errors.UndefinedColumn) column 'super_secret_token' does not exist "
            "[SQL: SELECT id, password_hash, super_secret_token FROM users WHERE email = 'admin@usm.cl']"
        )
        exc = SQLAlchemyError(sensitive_sql_error)

        response = await sqlalchemy_exception_handler(req_prod, exc)
        self.assertEqual(response.status_code, 500)

        body_str = response.body.decode("utf-8")
        body = json.loads(body_str)

        self.assertEqual(body["error"], "database_error")
        self.assertEqual(
            body["details"],
            {},
            f"Fuga de información en producción: details contiene '{body['details']}'",
        )
        self.assertNotIn(
            "super_secret_token",
            body_str,
            "Vulnerabilidad detectada: el nombre de columna confidencial fue expuesto al cliente",
        )
        self.assertNotIn(
            "password_hash",
            body_str,
            "Vulnerabilidad detectada: la consulta SQL fue expuesta en el cuerpo de respuesta HTTP",
        )

    async def test_r3_02_sqlalchemy_handler_exposes_details_in_development_environment(self):
        """
        R3.1: En modo desarrollo (APP_ENV="development"), sqlalchemy_exception_handler
        debe incluir los detalles de la excepción en details['detail'] para facilitar la depuración local.
        """
        scope_dev = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents",
            "headers": [],
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="development")),
        }
        req_dev = Request(scope_dev)
        req_dev.state.request_id = "req-dev-debug"

        dev_error_msg = "Dev debug: connection to PostgreSQL server on 127.0.0.1 refused"
        exc = SQLAlchemyError(dev_error_msg)

        response = await sqlalchemy_exception_handler(req_dev, exc)
        self.assertEqual(response.status_code, 500)

        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["error"], "database_error")
        self.assertIn("detail", body["details"])
        self.assertIn(dev_error_msg, body["details"]["detail"])

    async def test_r3_03_sqlalchemy_handler_redacts_details_in_testing_and_staging(self):
        """
        R3.1: Cualquier entorno no explícitamente catalogado como 'development' (e.g. testing, staging, None)
        debe anonimizar los detalles por principio de menor privilegio / seguridad por defecto.
        """
        scope_staging = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents",
            "headers": [],
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="staging")),
        }
        req_staging = Request(scope_staging)
        req_staging.state.request_id = "req-staging"

        exc = SQLAlchemyError("Deadlock detectado en transaccion T1")
        response = await sqlalchemy_exception_handler(req_staging, exc)

        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(
            body["details"],
            {},
            f"Fallo de anonimización en staging: se esperaba details vacío, se obtuvo {body['details']}",
        )

    async def test_r3_04_sqlalchemy_handler_resilient_to_missing_app_scope(self):
        """
        R3.1: Las peticiones que no posean la clave 'app' en scope (como en pruebas sintéticas)
        no deben arrojar un KeyError no controlado al evaluar el entorno.
        """
        scope_no_app = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents",
            "headers": [],
        }
        req_no_app = Request(scope_no_app)
        req_no_app.state.request_id = "req-synthetic"

        exc = SQLAlchemyError("Error de prueba sintética")
        response = await sqlalchemy_exception_handler(req_no_app, exc)
        self.assertEqual(response.status_code, 500)
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["error"], "database_error")

    async def test_r3_05_general_exception_handler_resilient_to_missing_app_scope(self):
        """
        R3.1: general_exception_handler tampoco debe elevar KeyError si el scope carece de 'app'.
        """
        scope_no_app = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/documents",
            "headers": [],
        }
        req = Request(scope_no_app)
        req.state.request_id = "req-no-app-gen"

        response = await general_exception_handler(req, RuntimeError("Crash inesperado"))
        self.assertEqual(response.status_code, 500)
        body = json.loads(response.body.decode("utf-8"))
        self.assertEqual(body["error"], "internal_error")


# =============================================================================
# TIER 4: Search Wildcard Sanitization (% and _) [R4]
# =============================================================================
class TestSuite10Tier4SearchWildcardSanitization(unittest.IsolatedAsyncioTestCase):
    r"""
    Tier 4: Pruebas de sanitización de comodines LIKE/ILIKE (%, _, \) en repositorio de documentos.
    Authoritative Source: ORIGINAL_REQUEST.md §R4 y PROJECT.md §R4.1.
    """

    def test_r4_01_escape_like_wildcards_unit_transformations(self):
        """
        R4.1: La función estática _escape_like_wildcards debe escapar backslash (\\),
        porcentaje (%) y guión bajo (_) con el orden de reemplazo adecuado.
        """
        if not hasattr(DocumentRepository, "_escape_like_wildcards"):
            # Invocar getattr para forzar falla limpia en fase previa a remediación
            getattr(DocumentRepository, "_escape_like_wildcards")("test")

        # Casos individuales
        self.assertEqual(DocumentRepository._escape_like_wildcards("100%"), "100\\%")
        self.assertEqual(DocumentRepository._escape_like_wildcards("doc_1"), "doc\\_1")
        self.assertEqual(DocumentRepository._escape_like_wildcards("path\\to"), "path\\\\to")

        # Caso compuesto y orden estricto de escape
        raw = "100%_aprobado\\final"
        escaped = DocumentRepository._escape_like_wildcards(raw)
        self.assertEqual(escaped, "100\\%\\_aprobado\\\\final")

    def test_r4_02_escape_like_wildcards_edge_cases(self):
        """
        R4.1: _escape_like_wildcards debe manejar cadenas vacías, cadenas sin comodines y repeticiones.
        """
        if not hasattr(DocumentRepository, "_escape_like_wildcards"):
            getattr(DocumentRepository, "_escape_like_wildcards")("")

        self.assertEqual(DocumentRepository._escape_like_wildcards(""), "")
        self.assertEqual(DocumentRepository._escape_like_wildcards("Reglamento General 2026"), "Reglamento General 2026")
        self.assertEqual(DocumentRepository._escape_like_wildcards("%%%%"), "\\%\\%\\%\\%")
        self.assertEqual(DocumentRepository._escape_like_wildcards("____"), "\\_\\_\\_\\_")

    @patch("app.repositories.document_repository.get_session")
    async def test_r4_03_lexical_search_escapes_wildcard_parameters(self, mock_get_session):
        """
        R4.1: lexical_search debe suministrar like_query y starts_query con caracteres escapados,
        conservando exact_query en formato literal para coincidencia exacta con '='.
        """
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        row_mock = MagicMock()
        row_mock.iddocumento = uuid4()
        row_mock.numero = "999"
        row_mock.titulo = "Doc 100%_arancel"
        row_mock.nommetadato = "Doc Meta"
        row_mock.match_boost = 100.0
        row_mock.full_count = 1
        row_mock.creacion = datetime.now()

        mock_res = MagicMock()
        mock_res.fetchall.return_value = [row_mock]
        mock_session.execute.return_value = mock_res

        query_input = "100%_arancel\\test"
        await repo.lexical_search(query_text=query_input, page=1, page_size=10)

        mock_session.execute.assert_awaited_once()
        call_args = mock_session.execute.await_args
        params = call_args[0][1]

        # Coincidencia exacta '=' no debe tener comodines escapados
        self.assertEqual(params["exact_query"], query_input)

        # starts_query y like_query DEBEN contener los comodines escapados con backslash
        expected_escaped = "100\\%\\_arancel\\\\test"
        self.assertEqual(
            params["starts_query"],
            f"{expected_escaped}%",
            f"Fallo de sanitización en starts_query: '{params['starts_query']}' no fue escapado",
        )
        self.assertEqual(
            params["like_query"],
            f"%{expected_escaped}%",
            f"Fallo de sanitización en like_query: '{params['like_query']}' no fue escapado",
        )

    @patch("app.repositories.document_repository.get_session")
    async def test_r4_04_lexical_search_sql_contains_escape_clause(self, mock_get_session):
        """
        R4.1: La consulta SQL ejecutada en lexical_search DEBE contener cláusula ESCAPE '\\'
        para todos los operadores LIKE e ILIKE.
        """
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        mock_res = MagicMock()
        mock_res.fetchall.return_value = []
        mock_session.execute.return_value = mock_res

        await repo.lexical_search(query_text="normativa", page=1, page_size=10)

        mock_session.execute.assert_awaited_once()
        sql_clause = str(mock_session.execute.await_args[0][0])
        self.assertIn(
            "ESCAPE '\\'",
            sql_clause,
            "Fallo de especificación SQL: la cláusula ESCAPE '\\' está ausente en la consulta LIKE/ILIKE",
        )

    @patch("app.repositories.document_repository.get_session")
    async def test_r4_05_lexical_suggestions_escapes_contains_parameter(self, mock_get_session):
        """
        R4.1: get_lexical_suggestions debe escapar comodines en el parámetro :contains
        e incluir la cláusula ESCAPE '\\' en la consulta SQL.
        """
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        mock_res = MagicMock()
        mock_res.fetchall.return_value = []
        mock_session.execute.return_value = mock_res

        await repo.get_lexical_suggestions(term="reg_%", limit=5)

        mock_session.execute.assert_awaited_once()
        call_args = mock_session.execute.await_args
        sql_clause = str(call_args[0][0])
        params = call_args[0][1]

        # Parámetro contains debe tener % y _ escapados
        self.assertEqual(
            params["contains"],
            "%reg\\_\\%%",
            f"Fallo de sanitización en suggestions :contains: '{params['contains']}'",
        )
        self.assertIn(
            "ESCAPE '\\'",
            sql_clause,
            "Fallo de especificación SQL: get_lexical_suggestions carece de cláusula ESCAPE '\\'",
        )

    def test_r4_06_adversarial_wildcard_injection_resilience(self):
        """
        R4.1: Inyección adversaria con secuencias arbitrarias de metacaracteres comodines
        debe producir una cadena saneada que no distorsione las expresiones de búsqueda.
        """
        if not hasattr(DocumentRepository, "_escape_like_wildcards"):
            getattr(DocumentRepository, "_escape_like_wildcards")("%%")

        malicious_input = "%_%_\\%_\\_\\%"
        sanitized = DocumentRepository._escape_like_wildcards(malicious_input)

        # Ningún '%' o '_' desprotegido debe quedar sin su prefijo '\\'
        self.assertNotIn("%%", sanitized)
        self.assertNotIn("__", sanitized)
        self.assertEqual(sanitized, "\\%\\_\\%\\_\\\\\\%\\_\\\\\\_\\\\\\%")


if __name__ == "__main__":
    unittest.main()
