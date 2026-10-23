"""
Suite 6: Seguridad, Autenticación y Autorización (AWS Cognito / Microsoft SSO).
Pruebas unitarias para app/security/microsoft_auth.py.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
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


if __name__ == "__main__":
    unittest.main()
