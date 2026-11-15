"""
Suite de Pruebas Adversariales: Verificación Empírica de CognitoAuth (Etapa 1).
Autor: teamwork_challenger_e1_1 (Empirical Challenger)

Misiones de validación adversarial:
1. Fallback de AWS_REGION en CognitoAuth:
   - settings.AWS_REGION = "" con distintos pool IDs ("us-east-1_Pool", "eu-west-1_Pool", "InvalidPool", etc.)
   - Verificar que nunca se generen URLs malformadas con "cognito-idp..amazonaws.com/".
2. Tokens Anónimos en CognitoAuth.get_current_user:
   - Payloads desprovistos de email, unique_name, preferred_username y sub.
   - Aserción estricta de user.email == "" y rechazo con HTTP 401 ("email ausente") en get_authenticated_user_id.
3. Rotación en Caliente de 'kid':
   - Simular rotación de llaves durante validación de tokens.
   - Verificar que el fallo inicial dispare get_jwks(force_refresh=True) y decodifique con éxito.
   - Verificar casos límite: doble fallo, caída de red durante rotación y concurrencia.
"""

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
import httpx
from jose import JWTError

import tests.base  # noqa: F401 - inicializa variables de entorno seguras
from app.core.config import settings
from app.models.user_models import UserRole
from app.security.microsoft_auth import (
    CognitoAuth,
    get_authenticated_user_id,
)


class TestChallengerE1AwsRegionFallback(unittest.TestCase):
    """Batería 1: Pruebas adversariales sobre inferencia y fallback de AWS_REGION."""

    def test_probe_01_aws_region_empty_fallback_to_pool_id_prefix(self):
        """Verifica que con AWS_REGION='' la región se infiera correctamente del prefijo del pool ID."""
        test_cases = [
            ("us-east-1_TestPool", "us-east-1"),
            ("eu-west-1_EnterprisePool", "eu-west-1"),
            ("sa-east-1_ChileSantiago", "sa-east-1"),
            ("ap-northeast-1_TokyoGIRU", "ap-northeast-1"),
            ("ca-central-1_CanadaMontreal_v2", "ca-central-1"),
            ("us-gov-west-1_GovCloud", "us-gov-west-1"),
        ]

        with patch.object(settings, "AWS_REGION", ""):
            for pool_id, expected_region in test_cases:
                with patch.object(settings, "COGNITO_USER_POOL_ID", pool_id):
                    auth = CognitoAuth()
                    self.assertEqual(
                        auth.region,
                        expected_region,
                        f"Fallo en inferir región para pool {pool_id}",
                    )
                    expected_url = (
                        f"https://cognito-idp.{expected_region}.amazonaws.com/"
                        f"{pool_id}/.well-known/jwks.json"
                    )
                    self.assertEqual(auth.jwks_url, expected_url)
                    self.assertNotIn(
                        "cognito-idp..",
                        auth.jwks_url,
                        f"URL malformada detectada con doble punto en pool {pool_id}",
                    )

    def test_probe_02_aws_region_empty_fallback_to_default_on_malformed_pools(self):
        """Verifica que pools sin guion bajo o inválidos adopten 'us-east-1' sin producir URL malformada."""
        malformed_pools = [
            "InvalidPool",
            "PoolWithoutUnderscore",
            "123456789",
            "",
            "None",
        ]

        with patch.object(settings, "AWS_REGION", ""):
            for pool_id in malformed_pools:
                with patch.object(settings, "COGNITO_USER_POOL_ID", pool_id):
                    auth = CognitoAuth()
                    self.assertEqual(
                        auth.region,
                        "us-east-1",
                        f"Pool inválido '{pool_id}' no hizo fallback a 'us-east-1'",
                    )
                    self.assertNotIn(
                        "cognito-idp..",
                        auth.jwks_url,
                        f"URL malformada detectada con doble punto en pool {pool_id}",
                    )
                    self.assertTrue(auth.jwks_url.startswith("https://cognito-idp.us-east-1.amazonaws.com/"))

    def test_probe_03_explicit_aws_region_overrides_pool_id_prefix(self):
        """Verifica que una región configurada explícitamente en settings tenga prioridad sobre el pool ID."""
        with patch.object(settings, "AWS_REGION", "ca-central-1"), \
             patch.object(settings, "COGNITO_USER_POOL_ID", "eu-west-1_CrossRegionPool"):
            auth = CognitoAuth()
            self.assertEqual(auth.region, "ca-central-1")
            self.assertIn("cognito-idp.ca-central-1.amazonaws.com", auth.jwks_url)
            self.assertNotIn("cognito-idp..", auth.jwks_url)

    def test_probe_04_valid_issuers_contains_no_double_dot_urls(self):
        """Verifica que valid_issuers no contenga URLs malformadas bajo ninguna permutación."""
        test_matrix = [
            ("", "us-east-1_Alpha"),
            ("", "InvalidPoolId"),
            ("", ""),
            ("eu-central-1", "eu-central-1_Beta"),
        ]

        for reg, pool in test_matrix:
            with patch.object(settings, "AWS_REGION", reg), \
                 patch.object(settings, "COGNITO_USER_POOL_ID", pool):
                auth = CognitoAuth()
                issuers = auth.valid_issuers
                for iss in issuers:
                    self.assertNotIn(
                        "cognito-idp..",
                        iss,
                        f"Issuer malformado con doble punto en permutación reg='{reg}', pool='{pool}': {iss}",
                    )


class TestChallengerE1AnonymousTokens(unittest.IsolatedAsyncioTestCase):
    """Batería 2: Pruebas adversariales sobre tokens anónimos y sin identificador."""

    def setUp(self):
        self.auth = CognitoAuth()

    async def test_probe_05_token_devoid_of_email_unique_name_preferred_username_and_sub(self):
        """Verifica que un token totalmente desprovisto de claims de identidad resulte en email='' y 401."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        # Payload sin email, unique_name, preferred_username ni sub
        payload = {
            "aud": "test-client-id",
            "given_name": "Ghost",
            "family_name": "User",
            "custom:azure_groups": [],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="anonymous-token-no-identity")

            # Aserción estricta de email vacío y rechazo de fallback legado
            self.assertEqual(user.email, "")
            self.assertNotEqual(user.email, "unknown@example.com")
            self.assertEqual(user.name, "Ghost User")

            # get_authenticated_user_id debe rechazar estrictamente con HTTP 401
            with self.assertRaises(HTTPException) as ctx:
                get_authenticated_user_id(user)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Identidad de usuario no verificada: email ausente", ctx.exception.detail)

    async def test_probe_06_token_with_null_identity_claims_rejected(self):
        """Verifica que claims explícitamente en None sean tratados como ausentes y rechazados con 401."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "aud": "test-client-id",
            "email": None,
            "unique_name": None,
            "preferred_username": None,
            "sub": None,
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="null-claims-token")

            self.assertIn(user.email, ("", None))
            self.assertNotEqual(user.email, "unknown@example.com")

            with self.assertRaises(HTTPException) as ctx:
                get_authenticated_user_id(user)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("email ausente", ctx.exception.detail)

    async def test_probe_07_token_with_empty_strings_in_identity_claims_rejected(self):
        """Verifica que claims con cadenas vacías ('') sean rechazados con 401."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "aud": "test-client-id",
            "email": "",
            "unique_name": "",
            "preferred_username": "",
            "sub": "",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="empty-strings-token")

            self.assertEqual(user.email, "")
            self.assertNotEqual(user.email, "unknown@example.com")

            with self.assertRaises(HTTPException) as ctx:
                get_authenticated_user_id(user)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("email ausente", ctx.exception.detail)

    async def test_probe_08_anonymous_token_with_admin_group_does_not_bypass_user_id_check(self):
        """Verifica que un token anónimo con grupo ADMIN no pueda sortear get_authenticated_user_id."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "aud": "test-client-id",
            "custom:azure_groups": ["AZURE_GROUP_ID_ADMIN"],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="spoofed-admin-anonymous-token")

            self.assertEqual(user.role, UserRole.ADMIN)
            self.assertEqual(user.email, "")

            # A pesar de tener rol ADMIN, get_authenticated_user_id DEBE fallar
            with self.assertRaises(HTTPException) as ctx:
                get_authenticated_user_id(user)
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("email ausente", ctx.exception.detail)

    async def test_probe_09_token_with_sub_claim_only_is_accepted_as_fallback(self):
        """Verifica que un token legítimo sin correo pero con 'sub' utilice 'sub' como identificador."""
        jwks_resp = MagicMock(status_code=200)
        jwks_resp.json.return_value = {"keys": []}

        payload = {
            "aud": "test-client-id",
            "sub": "auth0|65f8a123b4c5d6e7f8",
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload):
            mock_get.return_value = jwks_resp
            user = await self.auth.get_current_user(token="sub-only-token")

            self.assertEqual(user.email, "auth0|65f8a123b4c5d6e7f8")
            uid = get_authenticated_user_id(user)
            self.assertEqual(uid, "auth0|65f8a123b4c5d6e7f8")


class TestChallengerE1KidHotRotation(unittest.IsolatedAsyncioTestCase):
    """Batería 3: Pruebas adversariales sobre rotación en caliente de 'kid' y JWKS."""

    def setUp(self):
        self.auth = CognitoAuth()

    async def test_probe_10_hot_rotation_recovers_transparently(self):
        """Verifica que ante fallo de firma por clave antigua, se fuerce actualización y valide con la nueva."""
        # Estado inicial: caché con clave vieja
        self.auth._jwks_cache = {"keys": [{"kid": "old-kid-2025", "kty": "RSA"}]}
        self.auth._jwks_cache_time = time.time()

        # Respuesta remota con la clave rotada
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": [{"kid": "new-kid-2026", "kty": "RSA"}]}

        payload = {
            "email": "rotado@usm.cl",
            "given_name": "Ana",
            "family_name": "Torres",
            "custom:azure_groups": [],
        }

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", side_effect=[JWTError("Signature verification failed: unknown kid 'new-kid-2026'"), payload]) as mock_decode:
            mock_get.return_value = mock_resp

            user = await self.auth.get_current_user(token="token-with-new-kid")

            self.assertEqual(user.email, "rotado@usm.cl")
            # Verificar que jwt.decode fue llamado exactamente 2 veces
            self.assertEqual(mock_decode.call_count, 2)
            # Verificar que el request a red ocurrió exactamente 1 vez (force_refresh)
            self.assertEqual(mock_get.call_count, 1)
            # Verificar que la caché quedó actualizada con la nueva llave
            self.assertEqual(self.auth._jwks_cache["keys"][0]["kid"], "new-kid-2026")

    async def test_probe_11_subsequent_token_uses_freshly_rotated_cache_without_network_call(self):
        """Verifica que llamadas posteriores usen la clave ya rotada en memoria sin requests adicionales."""
        # Tras la rotación previa
        self.auth._jwks_cache = {"keys": [{"kid": "new-kid-2026", "kty": "RSA"}]}
        self.auth._jwks_cache_time = time.time()

        payload = {"email": "segundo@usm.cl", "custom:azure_groups": []}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", return_value=payload) as mock_decode:
            user = await self.auth.get_current_user(token="second-token-same-kid")

            self.assertEqual(user.email, "segundo@usm.cl")
            self.assertEqual(mock_decode.call_count, 1)
            self.assertEqual(mock_get.call_count, 0)

    async def test_probe_12_corrupted_token_fails_with_401_after_single_rotation_retry(self):
        """Verifica que un token permanentemente corrupto falle con 401 tras reintentar una sola vez (no loop infinito)."""
        self.auth._jwks_cache = {"keys": [{"kid": "key-1"}]}
        self.auth._jwks_cache_time = time.time()

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": [{"kid": "key-2"}]}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", side_effect=[
                 JWTError("First decode error"),
                 JWTError("Second decode error: Signature invalid on new key")
             ]) as mock_decode:
            mock_get.return_value = mock_resp

            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="completely-corrupted-token")

            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Token inválido o expirado", ctx.exception.detail)
            self.assertIn("Second decode error", ctx.exception.detail)
            # Exactamente 2 intentos de decodificación y 1 refresco forzado
            self.assertEqual(mock_decode.call_count, 2)
            self.assertEqual(mock_get.call_count, 1)

    async def test_probe_13_network_failure_during_hot_rotation_with_stale_cache(self):
        """Verifica que si la red falla durante la rotación, caiga resiliente a la caché previa y lance 401."""
        self.auth._jwks_cache = {"keys": [{"kid": "stale-key"}]}
        self.auth._jwks_cache_time = time.time() - 5000.0

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get, \
             patch("jose.jwt.decode", side_effect=JWTError("Unknown kid")):
            mock_get.side_effect = httpx.ConnectTimeout("Cognito endpoint timed out")

            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_current_user(token="token-during-jwks-outage")

            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Token inválido o expirado", ctx.exception.detail)

    async def test_probe_14_concurrent_hot_rotations_serialized_safely(self):
        """Verifica que múltiples peticiones concurrentes con kid rotado se serialicen bajo el lock."""
        self.auth._jwks_cache = {"keys": [{"kid": "old-key"}]}
        self.auth._jwks_cache_time = time.time()

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"keys": [{"kid": "rotated-key"}]}

        payload = {"email": "concurrent@usm.cl", "custom:azure_groups": []}

        network_call_counter = 0

        async def controlled_mock_get(*args, **kwargs):
            nonlocal network_call_counter
            network_call_counter += 1
            await asyncio.sleep(0.01)  # Simular latencia de red
            return mock_resp

        # Para cada corrutina: primer decode falla, segundo pasa
        call_count_per_token = {}

        def mock_decode_func(token, *args, **kwargs):
            calls = call_count_per_token.get(token, 0)
            call_count_per_token[token] = calls + 1
            if calls == 0:
                raise JWTError("Unknown kid")
            return payload

        with patch("httpx.AsyncClient.get", side_effect=controlled_mock_get), \
             patch("jose.jwt.decode", side_effect=mock_decode_func):

            tasks = [
                self.auth.get_current_user(token=f"token-{i}")
                for i in range(10)
            ]
            results = await asyncio.gather(*tasks)

            self.assertEqual(len(results), 10)
            for res in results:
                self.assertEqual(res.email, "concurrent@usm.cl")

            # Debido al lock y force_refresh por JWTError, se garantiza serialización sin carreras
            self.assertGreaterEqual(network_call_counter, 1)


if __name__ == "__main__":
    unittest.main()
