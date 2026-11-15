"""
Suite 6: Seguridad, Autenticación y Autorización (AWS Cognito / Microsoft SSO).
Pruebas unitarias para app/security/microsoft_auth.py.
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import httpx
from jose import JWTError

import tests.base  # noqa: F401
from app.models.user_models import UserOut, UserRole
from app.security.microsoft_auth import (
    CognitoAuth,
    require_admin,
    require_authenticated,
)


class TestSuite6SecurityMicrosoftAuth(unittest.IsolatedAsyncioTestCase):
    """Pruebas de autenticación y autorización con AWS Cognito y Microsoft SSO."""

    def setUp(self):
        self.auth = CognitoAuth()

    def test_01_get_login_url_contains_required_params(self):
        """Verifica que get_login_url construya la URL correcta con scope, client_id e identity_provider."""
        url = self.auth.get_login_url()
        self.assertIn("client_id=test-client-id", url)
        self.assertIn("identity_provider=EntraID", url)
        self.assertIn("scope=openid+email+profile", url)

    async def test_02_exchange_code_success(self):
        """Verifica intercambio exitoso de código de autorización por tokens."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "access_token": "mock-access-token",
            "id_token": "mock-id-token",
            "token_type": "Bearer",
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            tokens = await self.auth.exchange_code("auth-code-123", "https://giru.usm.cl/callback")
            self.assertEqual(tokens["access_token"], "mock-access-token")
            mock_post.assert_awaited_once()

    async def test_03_exchange_code_error_raises_http_400(self):
        """Verifica que exchange_code lance HTTP 400 ante respuesta no exitosa de Cognito."""
        mock_resp = MagicMock(status_code=400, text="Invalid grant")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.exchange_code("bad-code", "https://giru.usm.cl/callback")
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertIn("Error intercambiando código", ctx.exception.detail)

    def test_04_resolve_role_mappings(self):
        """Verifica mapeo de grupos de Azure AD a UserRole."""
        self.assertEqual(self.auth._resolve_role(["AZURE_GROUP_ID_ADMIN"]), UserRole.ADMIN)
        self.assertEqual(self.auth._resolve_role(["AZURE_GROUP_ID_BASIC"]), UserRole.BASIC)
        self.assertEqual(self.auth._resolve_role(["UNKNOWN_GROUP"]), UserRole.BASIC)
        self.assertEqual(self.auth._resolve_role([]), UserRole.BASIC)

    async def test_05_get_current_user_valid_token(self):
        """Verifica validación de JWT y decodificación correcta de claims de usuario."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "email": "estudiante@usm.cl",
            "given_name": "Juan",
            "family_name": "Pérez",
            "custom:azure_groups": ["AZURE_GROUP_ID_BASIC"],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="valid-jwt-token")
            self.assertEqual(user.email, "estudiante@usm.cl")
            self.assertEqual(user.name, "Juan Pérez")
            self.assertEqual(user.role, UserRole.BASIC)

    async def test_06_get_current_user_admin_override_from_env(self):
        """Verifica que emails presentes en ADMIN_EMAILS reciban rol ADMIN automáticamente."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "unique_name": "admin@usm.cl",
            "given_name": "",
            "family_name": "",
            "custom:azure_groups": "SOME_OTHER_GROUP",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload), \
             patch("app.security.microsoft_auth.ADMIN_LIST", ["admin@usm.cl", "rector@usm.cl"]):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="admin-jwt-token")
            self.assertEqual(user.email, "admin@usm.cl")
            self.assertEqual(user.name, "Usuario")
            self.assertEqual(user.role, UserRole.ADMIN)

    async def test_07_get_current_user_invalid_jwt_raises_http_401(self):
        """Verifica que tokens inválidos o expirados lancen HTTP 401."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", side_effect=JWTError("Signature verification failed")):
            mock_get.return_value = jwks_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="invalid-token")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Token inválido o expirado", ctx.exception.detail)

    def test_08_require_admin_guard(self):
        """Verifica dependencias require_admin y require_authenticated."""
        admin_user = UserOut(email="admin@usm.cl", name="Admin", role=UserRole.ADMIN)
        basic_user = UserOut(email="user@usm.cl", name="User", role=UserRole.BASIC)

        self.assertEqual(require_admin(admin_user), admin_user)
        self.assertEqual(require_authenticated(basic_user), basic_user)

        with self.assertRaises(HTTPException) as ctx:
            require_admin(basic_user)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_09_jwks_in_memory_caching_prevents_redundant_network_calls(self):
        """Verifica que llamadas sucesivas a get_jwks usen la caché en memoria y no repitan requests HTTP."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": [{"kid": "test-key-1", "kty": "RSA"}]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp

            jwks1 = await self.auth.get_jwks()
            jwks2 = await self.auth.get_jwks()

            self.assertEqual(jwks1, {"keys": [{"kid": "test-key-1", "kty": "RSA"}]})
            self.assertEqual(jwks2, jwks1)
            self.assertEqual(mock_get.call_count, 1)

    async def test_10_jwks_cache_ttl_expiration_triggers_refetch(self):
        """Verifica que tras expirar el TTL (3600s), get_jwks vuelva a consultar al proveedor."""
        mock_resp1 = MagicMock(status_code=200)
        mock_resp1.json.return_value = {"keys": [{"kid": "key-v1"}]}
        mock_resp2 = MagicMock(status_code=200)
        mock_resp2.json.return_value = {"keys": [{"kid": "key-v2"}]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [mock_resp1, mock_resp2]

            jwks1 = await self.auth.get_jwks()
            self.assertEqual(jwks1["keys"][0]["kid"], "key-v1")
            self.assertEqual(mock_get.call_count, 1)

            # Simular expiración de TTL avanzando el timestamp de caché más allá de 3600s
            self.auth._jwks_cache_time = time.time() - 3601.0

            jwks2 = await self.auth.get_jwks()
            self.assertEqual(jwks2["keys"][0]["kid"], "key-v2")
            self.assertEqual(mock_get.call_count, 2)

    async def test_11_jwks_force_refresh_bypasses_valid_cache(self):
        """Verifica que force_refresh=True fuerce la obtención de JWKS ignorando el TTL vigente."""
        mock_resp1 = MagicMock(status_code=200)
        mock_resp1.json.return_value = {"keys": [{"kid": "initial-key"}]}
        mock_resp2 = MagicMock(status_code=200)
        mock_resp2.json.return_value = {"keys": [{"kid": "rotated-key"}]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = [mock_resp1, mock_resp2]

            jwks1 = await self.auth.get_jwks()
            self.assertEqual(jwks1["keys"][0]["kid"], "initial-key")

            jwks2 = await self.auth.get_jwks(force_refresh=True)
            self.assertEqual(jwks2["keys"][0]["kid"], "rotated-key")
            self.assertEqual(mock_get.call_count, 2)

    async def test_12_jwks_network_failure_resilient_fallback_to_cache(self):
        """Verifica que si la red falla al renovar expirado, devuelva resiliente la caché previa."""
        self.auth._jwks_cache = {"keys": [{"kid": "cached-fallback-key"}]}
        self.auth._jwks_cache_time = time.time() - 4000.0  # Expirado

        # Caso A: Fallo por excepción HTTP
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectError("Network unreachable")
            jwks = await self.auth.get_jwks()
            self.assertEqual(jwks, {"keys": [{"kid": "cached-fallback-key"}]})

        # Caso B: Fallo por status 500
        mock_err_resp = MagicMock(status_code=500)
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_err_resp
            jwks = await self.auth.get_jwks()
            self.assertEqual(jwks, {"keys": [{"kid": "cached-fallback-key"}]})

    async def test_13_jwks_network_failure_without_cache_raises_http_503(self):
        """Verifica que un fallo de red sin caché previa lance HTTP 503."""
        self.auth._jwks_cache = None

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectTimeout("Request timed out")
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_jwks()
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Error conectando con el proveedor de identidad", ctx.exception.detail)

    async def test_14_jwks_status_error_without_cache_raises_http_503(self):
        """Verifica que una respuesta con status no 200 sin caché previa lance HTTP 503."""
        self.auth._jwks_cache = None
        mock_resp = MagicMock(status_code=502)

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_jwks()
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("No se pudo obtener las claves públicas", ctx.exception.detail)

    async def test_15_get_current_user_matching_aud_and_iss_claims_succeeds(self):
        """Verifica que tokens con claims aud e iss correctos sean validados con éxito."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        expected_iss = f"https://cognito-idp.us-east-1.amazonaws.com/{self.auth.user_pool_id}"
        payload = {
            "aud": "test-client-id",
            "iss": expected_iss,
            "email": "profesor@usm.cl",
            "given_name": "Valeria",
            "family_name": "Herskovic",
            "custom:azure_groups": ["AZURE_GROUP_ID_BASIC"],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="valid-token-with-claims")
            self.assertEqual(user.email, "profesor@usm.cl")
            self.assertEqual(user.name, "Valeria Herskovic")
            self.assertEqual(user.role, UserRole.BASIC)

    async def test_16_get_current_user_mismatched_aud_raises_http_401(self):
        """Verifica que tokens con aud no coincidente lancen HTTP 401."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "aud": "unauthorized-client-id",
            "email": "attacker@usm.cl",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="token-bad-aud")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Audience mismatch", ctx.exception.detail)

    async def test_17_get_current_user_mismatched_client_id_raises_http_401(self):
        """Verifica que tokens con claim client_id no coincidente lancen HTTP 401."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "client_id": "malicious-app-client",
            "email": "attacker@usm.cl",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="token-bad-client-id")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Client ID mismatch", ctx.exception.detail)

    async def test_18_get_current_user_mismatched_iss_raises_http_401(self):
        """Verifica que tokens emitidos por un issuer no confiable lancen HTTP 401."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "iss": "https://untrusted-idp.attacker.com",
            "email": "attacker@usm.cl",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="token-bad-iss")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Issuer mismatch", ctx.exception.detail)

    async def test_19_get_current_user_valid_client_id_claim_without_aud(self):
        """Verifica compatibilidad con access tokens de Cognito que contienen client_id en lugar de aud."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "client_id": "test-client-id",
            "email": "estudiante2@usm.cl",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="access-token-cognito")
            self.assertEqual(user.email, "estudiante2@usm.cl")

    async def test_20_aud_as_list_validation(self):
        """Verifica que aud como lista sea validado correctamente (tanto matching como mismatched)."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        # Matching aud en lista
        payload_ok = {
            "aud": ["test-client-id", "other-valid-audience"],
            "email": "user@usm.cl",
        }
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload_ok):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="aud-list-ok")
            self.assertEqual(user.email, "user@usm.cl")

        # Mismatched aud en lista
        payload_bad = {
            "aud": ["foreign-client-1", "foreign-client-2"],
            "email": "user@usm.cl",
        }
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload_bad):
            mock_get.return_value = jwks_resp
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="aud-list-bad")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Audience mismatch", ctx.exception.detail)

    def test_21_default_config_admin_emails_is_empty_and_sanitized(self):
        """Verifica que el valor por defecto de ADMIN_EMAILS en Settings esté vacío y no contenga emails dummy."""
        from app.core.config import Settings
        field_default = Settings.model_fields["ADMIN_EMAILS"].default
        self.assertEqual(field_default, "")
        self.assertNotIn("ejemplo.admin@usm.cl", field_default)
        self.assertNotIn("name@example.com", field_default)

    def test_22_lock_and_valid_issuers_properties(self):
        """Verifica comportamiento de las properties lock y valid_issuers."""
        lock = self.auth.lock
        self.assertIsInstance(lock, asyncio.Lock)
        self.assertIs(self.auth.lock, lock)

        issuers = self.auth.valid_issuers
        self.assertIsInstance(issuers, set)
        self.assertTrue(any("cognito-idp" in iss for iss in issuers))

    async def test_23_get_current_user_fallback_to_sub_claim(self):
        """Verifica que si no hay email, unique_name ni preferred_username, se use el claim sub."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "sub": "cognito-sub-uuid-1234",
            "custom:azure_groups": [],
        }
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="token-sub-fallback")
            self.assertEqual(user.email, "cognito-sub-uuid-1234")

    async def test_24_jwks_double_checked_locking_concurrent_branch(self):
        """Verifica la rama interna del double-checked lock cuando la caché fue poblada concurrentemente."""
        self.auth._jwks_cache = None

        class MockLock:
            async def __aenter__(lock_self):
                self.auth._jwks_cache = {"keys": [{"kid": "concurrent-populated-key"}]}
                self.auth._jwks_cache_time = time.time()
                return lock_self

            async def __aexit__(lock_self, exc_type, exc_val, exc_tb):
                pass

        mock_lock = MockLock()
        with patch.object(CognitoAuth, "lock", new_callable=lambda: property(lambda s: mock_lock)):
            jwks = await self.auth.get_jwks()
            self.assertEqual(jwks, {"keys": [{"kid": "concurrent-populated-key"}]})

    async def test_25_get_current_user_kid_rotation_triggers_force_refresh_and_succeeds(self):
        """Verifica que ante JWTError en el primer decode (rotación de kid), se fuerce el refresco JWKS y reintente con éxito."""
        self.auth._jwks_cache = {"keys": [{"kid": "old-key"}]}
        self.auth._jwks_cache_time = time.time()

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": [{"kid": "new-rotated-key"}]}

        payload = {
            "email": "rotated@usm.cl",
            "given_name": "Maria",
            "family_name": "Perez",
            "custom:azure_groups": [],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", side_effect=[JWTError("Signature verification failed: unknown kid"), payload]) as mock_decode:
            mock_get.return_value = mock_resp
            user = await self.auth.get_current_user(token="token-with-rotated-kid")
            self.assertEqual(user.email, "rotated@usm.cl")
            self.assertEqual(mock_decode.call_count, 2)
            self.assertEqual(mock_get.call_count, 1)

    async def test_26_get_current_user_empty_claims_yields_empty_email_and_401_on_id_extraction(self):
        """Verifica que un token sin email, unique_name, preferred_username ni sub genere email='' y 
        que get_authenticated_user_id rechace con HTTP 401."""
        from app.security.microsoft_auth import get_authenticated_user_id

        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "aud": "test-client-id",
            "given_name": "Anonimo",
            "custom:azure_groups": [],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="anonymous-token")
            self.assertEqual(user.email, "")
            self.assertNotEqual(user.email, "unknown@example.com")

            with self.assertRaises(HTTPException) as ctx:
                get_authenticated_user_id(user)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("email ausente", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
