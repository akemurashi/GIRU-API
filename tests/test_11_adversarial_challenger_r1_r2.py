"""
Adversarial Probe & Stress Test Suite: Requirement R1 & Requirement R2
Author: teamwork_challenger_1 (Empirical Challenger)

Target Requirements:
- R1: External AI Router & Session Isolation (IDOR Mitigation) & Admin RBAC Diagnostic Guard
- R2: Authentication & JWT Claim Verification Hardening & JWKS Caching Concurrency
"""

import asyncio
import copy
from datetime import datetime
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
from jose import JWTError, jwt
import pytest

import tests.base  # noqa: F401
from app.api.auth import auth_service
from app.api.external_ai import _get_authenticated_user_id, get_external_ai_service
from app.core.config import settings
from app.main import app
from app.models.ai_models import (
    AskRequest,
    AskResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    DiagnosticResponse,
    SessionDetail,
    SessionListItem,
)
from app.models.user_models import UserOut, UserRole
from app.security.microsoft_auth import (
    CognitoAuth,
    require_admin,
    require_authenticated,
)


# =============================================================================
# BATTERY 1: Adversarial Probing of R1 (Session Isolation, IDOR & RBAC)
# =============================================================================
class TestAdversarialBattery1R1SessionIsolationAndRBAC(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial test battery attempting horizontal privilege escalation (IDOR)
    across all AI endpoints, manipulating query parameters, request bodies,
    and HTTP headers.
    """

    def setUp(self):
        super().setUp()
        self.client = TestClient(app, raise_server_exceptions=False)
        self.mock_ai_service = AsyncMock()

        self.alice_email = "alice@usm.cl"
        self.victim_email = "victim@usm.cl"
        self.attacker_injected_id = "target_victim_999@usm.cl"

        self.mock_user_alice = UserOut(
            email=self.alice_email,
            name="Alice Student",
            role=UserRole.BASIC,
        )
        self.mock_user_admin = UserOut(
            email="admin.security@usm.cl",
            name="Admin Security",
            role=UserRole.ADMIN,
        )

        app.dependency_overrides[get_external_ai_service] = lambda: self.mock_ai_service
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.mock_user_alice

    def tearDown(self):
        app.dependency_overrides.clear()
        super().tearDown()

    def test_probe_r1_01_create_session_body_idor_injection_overwritten(self):
        """Probe R1.1: Attacker injects victim's user_id in JSON body of create_session."""
        captured_request = None

        async def fake_create_session(req: CreateSessionRequest):
            nonlocal captured_request
            captured_request = copy.deepcopy(req)
            return CreateSessionResponse(
                id="ses-1001",
                user_id=req.user_id,
                titulo=req.titulo or "Default",
                modo=req.modo,
                creada=datetime.now(),
                actualizada=datetime.now(),
            )

        self.mock_ai_service.create_session = AsyncMock(side_effect=fake_create_session)

        malicious_payload = {
            "user_id": self.victim_email,
            "titulo": "Attacker Hijacked Session",
            "modo": "cascade",
        }
        resp = self.client.post("/api/v1/ai/sessions", json=malicious_payload)

        self.assertEqual(resp.status_code, 200, f"Expected 200, got: {resp.text}")
        self.assertIsNotNone(captured_request)
        # Empirical Assertion: service MUST receive alice@usm.cl, NEVER victim@usm.cl
        self.assertEqual(
            captured_request.user_id,
            self.alice_email,
            f"VULNERABILITY DETECTED: service received {captured_request.user_id} instead of {self.alice_email}",
        )
        self.assertEqual(resp.json()["user_id"], self.alice_email)

    def test_probe_r1_02_create_session_query_param_idor_ignored(self):
        """Probe R1.2: Attacker injects user_id in query parameters while omitting in body."""
        captured_request = None

        async def fake_create_session(req: CreateSessionRequest):
            nonlocal captured_request
            captured_request = copy.deepcopy(req)
            return CreateSessionResponse(
                id="ses-1002",
                user_id=req.user_id,
                titulo="Test",
                modo="cascade",
                creada=datetime.now(),
                actualizada=datetime.now(),
            )

        self.mock_ai_service.create_session = AsyncMock(side_effect=fake_create_session)

        resp = self.client.post(
            f"/api/v1/ai/sessions?user_id={self.attacker_injected_id}",
            json={"titulo": "Test without body user_id"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(captured_request.user_id, self.alice_email)

    def test_probe_r1_03_list_sessions_query_param_idor_tampering(self):
        """Probe R1.3: Attacker attempts to list victim's chat sessions via query param."""
        self.mock_ai_service.list_sessions = AsyncMock(return_value=[])

        resp = self.client.get(f"/api/v1/ai/sessions?user_id={self.victim_email}")
        self.assertEqual(resp.status_code, 200)

        # Assert service was called strictly with alice's identity
        self.mock_ai_service.list_sessions.assert_called_once_with(self.alice_email)

    def test_probe_r1_04_list_sessions_multiple_and_obfuscated_query_params(self):
        """Probe R1.4: Attacker uses URL encoding, uppercase, and multiple user_id params."""
        self.mock_ai_service.list_sessions = AsyncMock(return_value=[])

        resp = self.client.get(
            "/api/v1/ai/sessions?user_id=%20victim%40usm.cl%20&USER_ID=evil%40usm.cl&user_id=another"
        )
        self.assertEqual(resp.status_code, 200)
        self.mock_ai_service.list_sessions.assert_called_once_with(self.alice_email)

    def test_probe_r1_05_get_session_query_param_idor_tampering(self):
        """Probe R1.5: Attacker attempts to read victim's conversation history."""
        self.mock_ai_service.get_session = AsyncMock(
            return_value=SessionDetail(
                id="victim-session-42",
                titulo="Victim Secret Session",
                modo="cascade",
                mensajes=[],
            )
        )

        resp = self.client.get(f"/api/v1/ai/sessions/victim-session-42?user_id={self.victim_email}")
        self.assertEqual(resp.status_code, 200)
        self.mock_ai_service.get_session.assert_called_once_with("victim-session-42", self.alice_email)

    def test_probe_r1_06_delete_session_query_param_idor_tampering(self):
        """Probe R1.6: Attacker attempts to delete victim's conversation."""
        self.mock_ai_service.delete_session = AsyncMock(return_value=None)

        resp = self.client.delete(f"/api/v1/ai/sessions/victim-session-42?user_id={self.victim_email}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "deleted"})
        self.mock_ai_service.delete_session.assert_called_once_with("victim-session-42", self.alice_email)

    def test_probe_r1_07_ask_body_idor_injection_overwritten(self):
        """Probe R1.7: Attacker supplies victim's user_id in ask JSON body."""
        captured_request = None

        async def fake_ask(req: AskRequest):
            nonlocal captured_request
            captured_request = copy.deepcopy(req)
            return AskResponse(
                session_id=req.session_id,
                respuesta="AI Answer",
                fuentes=[],
                modo="cascade",
                tiempo_s=1.2,
                llamadas_llm=1,
            )

        self.mock_ai_service.ask = AsyncMock(side_effect=fake_ask)

        payload = {
            "user_id": self.victim_email,
            "session_id": "ses-99",
            "pregunta": "¿Cuál es la clave del servidor?",
        }
        resp = self.client.post("/api/v1/ai/ask", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            captured_request.user_id,
            self.alice_email,
            f"VULNERABILITY DETECTED: ask received {captured_request.user_id}",
        )

    def test_probe_r1_08_ask_stream_body_idor_injection_overwritten(self):
        """Probe R1.8: Attacker supplies victim's user_id in ask-stream JSON body."""
        captured_request = None

        async def fake_ask_stream(req: AskRequest):
            nonlocal captured_request
            captured_request = copy.deepcopy(req)
            yield "data: chunk1\n\n"
            yield "data: chunk2\n\n"

        self.mock_ai_service.ask_stream = fake_ask_stream

        payload = {
            "user_id": self.victim_email,
            "session_id": "ses-99",
            "pregunta": "Streaming question?",
        }
        resp = self.client.post("/api/v1/ai/ask-stream", json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/event-stream", resp.headers["content-type"])
        self.assertEqual(
            captured_request.user_id,
            self.alice_email,
            f"VULNERABILITY DETECTED: ask_stream received {captured_request.user_id}",
        )

    def test_probe_r1_09_missing_user_email_raises_http_401(self):
        """Probe R1.9: Edge case - token has no email claim (email is None or empty)."""
        user_no_email = UserOut(email=None, name="No Email User", role=UserRole.BASIC)
        app.dependency_overrides[auth_service.get_current_user] = lambda: user_no_email

        # Test on create_session
        resp = self.client.post("/api/v1/ai/sessions", json={"titulo": "Test"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn("email ausente", resp.json()["detail"])

        # Test on list_sessions
        resp = self.client.get("/api/v1/ai/sessions")
        self.assertEqual(resp.status_code, 401)

        # Test on ask
        resp = self.client.post("/api/v1/ai/ask", json={"session_id": "s1", "pregunta": "p"})
        self.assertEqual(resp.status_code, 401)

        # Test unit helper function directly
        with self.assertRaises(HTTPException) as ctx:
            _get_authenticated_user_id(UserOut(email="", name="Empty", role=UserRole.BASIC))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_probe_r1_10_diagnostic_endpoint_strictly_blocks_basic_role(self):
        """Probe R1.10: Basic user attempts to access /diagnostic."""
        self.mock_ai_service.get_diagnostic = AsyncMock(
            return_value=DiagnosticResponse(grafo="test", entidades=1, relaciones=1, documentos=1)
        )
        resp = self.client.get("/api/v1/ai/diagnostic")
        self.assertEqual(
            resp.status_code,
            403,
            f"VULNERABILITY DETECTED: BASIC user got {resp.status_code} instead of 403 Forbidden",
        )
        self.assertIn("restringido", resp.json()["detail"].lower())

    def test_probe_r1_11_diagnostic_endpoint_blocks_spoofed_role_headers(self):
        """Probe R1.11: Basic user sends spoofed headers and query params claiming admin."""
        headers = {
            "X-Role": "admin",
            "Role": "admin",
            "X-Admin": "true",
        }
        resp = self.client.get("/api/v1/ai/diagnostic?role=admin&is_admin=true", headers=headers)
        self.assertEqual(resp.status_code, 403)

    def test_probe_r1_12_diagnostic_endpoint_blocks_unauthenticated_requests(self):
        """Probe R1.12: Unauthenticated request to /diagnostic."""
        app.dependency_overrides.pop(auth_service.get_current_user, None)
        resp = self.client.get("/api/v1/ai/diagnostic")
        self.assertEqual(resp.status_code, 401)

    def test_probe_r1_13_diagnostic_endpoint_allows_legitimate_admin(self):
        """Probe R1.13: Legitimate admin user accesses /diagnostic."""
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.mock_user_admin
        self.mock_ai_service.get_diagnostic = AsyncMock(
            return_value=DiagnosticResponse(
                grafo="universidad_normativa",
                entidades=100,
                relaciones=200,
                documentos=50,
            )
        )
        resp = self.client.get("/api/v1/ai/diagnostic")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["grafo"], "universidad_normativa")

    def test_probe_r1_14_cross_session_tampering_upstream_404_mapped_cleanly(self):
        """
        Probe R1.14: Attacker requests a session_id belonging to another user.
        Upstream external AI service returns 404 ('La sesión no existe o pertenece a otro user_id').
        Router must catch this and return clean HTTP 404 to client without leaking internals.
        """
        self.mock_ai_service.get_session = AsyncMock(
            side_effect=RuntimeError("La sesión no existe o pertenece a otro user_id")
        )
        resp = self.client.get("/api/v1/ai/sessions/victim-session-id")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"], "Sesión no encontrada")

        # Also test on delete_session
        self.mock_ai_service.delete_session = AsyncMock(
            side_effect=RuntimeError("La sesión no existe o pertenece a otro user_id")
        )
        resp = self.client.delete("/api/v1/ai/sessions/victim-session-id")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"], "Sesión no encontrada")

        # Also test on ask
        self.mock_ai_service.ask = AsyncMock(
            side_effect=RuntimeError("La sesión no existe o pertenece a otro user_id")
        )
        resp = self.client.post("/api/v1/ai/ask", json={"session_id": "victim-session-id", "pregunta": "hi"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"], "Sesión no encontrada")

    def test_probe_r1_15_admin_email_set_membership_no_partial_substring_match(self):
        """
        Probe R1.15: Verify that substring/prefix email spoofing cannot elevate to admin.
        For example: 'alice@usm.cl' or 'admin@usm.cl.attacker.com' must NOT match 'admin@usm.cl'.
        """
        with patch.object(settings, "ADMIN_EMAILS", "superadmin@usm.cl,root@usm.cl"):
            # Substring attacker
            spoofed_user = UserOut(
                email="superadmin@usm.cl.attacker.com",
                name="Spoofed",
                role=UserRole.BASIC,
            )
            with self.assertRaises(HTTPException) as ctx:
                require_admin(spoofed_user)
            self.assertEqual(ctx.exception.status_code, 403)

            # Legitimate admin
            legit_admin = UserOut(
                email="superadmin@usm.cl",
                name="Real Admin",
                role=UserRole.ADMIN,
            )
            res = require_admin(legit_admin)
            self.assertEqual(res.role, UserRole.ADMIN)

    def test_probe_r1_16_role_matrix_rbac_probe(self):
        """Probe R1.16: Exhaustive role matrix verification on require_admin."""
        # Standard UserRole.BASIC
        basic_user = UserOut(email="test@usm.cl", name="Test", role=UserRole.BASIC)
        with self.assertRaises(HTTPException) as ctx:
            require_admin(basic_user)
        self.assertEqual(ctx.exception.status_code, 403)

        # Non-admin roles tested via model_construct (bypassing Pydantic validation)
        untrusted_roles = [
            "basic",
            "student",
            "guest",
            "user",
            "None",
            "",
            "ADMIN_FAKE",
            None,
        ]
        for role_val in untrusted_roles:
            user = UserOut.model_construct(email="test@usm.cl", name="Test", role=role_val)
            with self.assertRaises(HTTPException, msg=f"Role {role_val} was not blocked!") as ctx:
                require_admin(user)
            self.assertEqual(ctx.exception.status_code, 403)

        # Valid admin roles
        for admin_val in [UserRole.ADMIN, "admin"]:
            admin_user = UserOut.model_construct(email="test@usm.cl", name="Admin", role=admin_val)
            result = require_admin(admin_user)
            self.assertIn(result.role, (UserRole.ADMIN, "admin"))




# =============================================================================
# BATTERY 2: Adversarial Probing of R2 (JWT Claims & Security)
# =============================================================================
class TestAdversarialBattery2R2JwtClaimHardening(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial probes for JWT claim validation (aud, client_id, iss) and
    edge case handling in CognitoAuth.
    """

    def setUp(self):
        super().setUp()
        self.auth = CognitoAuth()
        self.auth.client_id = "target-client-id-12345"
        self.auth.region = "us-east-1"
        self.auth.user_pool_id = "us-east-1_ValidPoolId"
        self.auth.cognito_domain = "giru-auth.auth.us-east-1.amazoncognito.com"

        # Mock public keys in cache
        self.auth._jwks_cache = {"keys": [{"kid": "test-kid", "kty": "RSA"}]}
        self.auth._jwks_cache_time = time.time()

    def test_probe_r2_01_aud_mismatch_string_rejected(self):
        """Probe R2.1: Token presents aud from another client/application."""
        payload = {"aud": "unauthorized-rogue-client"}
        with self.assertRaises(JWTError) as ctx:
            self.auth._validate_claims(payload)
        self.assertIn("Audience mismatch", str(ctx.exception))

    def test_probe_r2_02_aud_mismatch_array_rejected(self):
        """Probe R2.2: Token presents aud list without valid client_id."""
        payload = {"aud": ["rogue-1", "rogue-2"]}
        with self.assertRaises(JWTError) as ctx:
            self.auth._validate_claims(payload)
        self.assertIn("Audience mismatch", str(ctx.exception))

    def test_probe_r2_03_aud_matching_string_or_in_array_accepted(self):
        """Probe R2.3: Token presents valid aud as string or within an array."""
        # Single string
        self.auth._validate_claims({"aud": self.auth.client_id})
        # Array containing target client ID
        self.auth._validate_claims({"aud": ["other-client", self.auth.client_id]})

    def test_probe_r2_04_client_id_claim_mismatch_rejected(self):
        """Probe R2.4: Token presents mismatched client_id claim."""
        payload = {"client_id": "fake-client-999"}
        with self.assertRaises(JWTError) as ctx:
            self.auth._validate_claims(payload)
        self.assertIn("Client ID mismatch", str(ctx.exception))

    def test_probe_r2_05_client_id_claim_matching_accepted(self):
        """Probe R2.5: Token presents matching client_id claim."""
        self.auth._validate_claims({"client_id": self.auth.client_id})

    def test_probe_r2_06_untrusted_issuer_domain_rejected(self):
        """Probe R2.6: Token signed by untrusted IdP domain (e.g. attacker domain)."""
        payload = {"iss": "https://malicious-idp.attacker.com"}
        with self.assertRaises(JWTError) as ctx:
            self.auth._validate_claims(payload)
        self.assertIn("Issuer mismatch", str(ctx.exception))

    def test_probe_r2_07_spoofed_cognito_pool_rejected(self):
        """Probe R2.7: Token from a different Cognito User Pool ID."""
        payload = {"iss": "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AttackerPool"}
        with self.assertRaises(JWTError) as ctx:
            self.auth._validate_claims(payload)
        self.assertIn("Issuer mismatch", str(ctx.exception))

    def test_probe_r2_08_spoofed_cognito_region_rejected(self):
        """Probe R2.8: Token from a different AWS region."""
        payload = {"iss": f"https://cognito-idp.eu-west-1.amazonaws.com/{self.auth.user_pool_id}"}
        with self.assertRaises(JWTError) as ctx:
            self.auth._validate_claims(payload)
        self.assertIn("Issuer mismatch", str(ctx.exception))

    def test_probe_r2_09_legitimate_issuer_with_or_without_trailing_slash(self):
        """Probe R2.9: Legitimate Cognito issuer with and without trailing slash."""
        valid_iss = f"https://cognito-idp.{self.auth.region}.amazonaws.com/{self.auth.user_pool_id}"
        self.auth._validate_claims({"iss": valid_iss})
        self.auth._validate_claims({"iss": f"{valid_iss}/"})

    def test_probe_r2_10_backward_compatibility_omitted_claims(self):
        """Probe R2.10: Legacy tokens without aud or iss pass without regression."""
        # Empty payload
        self.auth._validate_claims({})
        # Only email and sub
        self.auth._validate_claims({"email": "test@usm.cl", "sub": "sub-123"})

    def test_probe_r2_16_token_with_azure_client_id_when_configured(self):
        """Probe R2.16: Token aud matching AZURE_CLIENT_ID succeeds."""
        with patch.object(settings, "AZURE_CLIENT_ID", "azure-client-uuid-999"):
            self.auth._validate_claims({"aud": "azure-client-uuid-999"})
            self.auth._validate_claims({"client_id": "azure-client-uuid-999"})

    async def test_probe_r2_17_malformed_token_raises_401_in_get_current_user(self):
        """Probe R2.17: Completely malformed or expired JWT token raises HTTP 401."""
        with self.assertRaises(HTTPException) as ctx:
            await self.auth.get_current_user("malformed.jwt.token.here")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Token inválido", ctx.exception.detail)



# =============================================================================
# BATTERY 3: Concurrency & Stress Harness for JWKS Caching
# =============================================================================
class TestAdversarialBattery3JWKSCacheConcurrencyAndStampede(unittest.IsolatedAsyncioTestCase):
    """
    Stress harness probing JWKS caching under heavy concurrent coroutines,
    simulating cold cache stampedes, TTL expiration races, and network failures.
    """

    def setUp(self):
        super().setUp()
        self.auth = CognitoAuth()
        self.auth.client_id = "test-client-id"
        self.auth.region = "us-east-1"
        self.auth.user_pool_id = "us-east-1_TestPool"
        self.dummy_jwks = {"keys": [{"kid": "key-1", "kty": "RSA", "n": "xyz", "e": "AQAB"}]}

    async def test_probe_r2_11_cold_cache_stampede_100_concurrent_coroutines(self):
        """
        Stress Test: 100 coroutines request JWKS simultaneously with empty cache.
        Oracle: Exactly 1 HTTP GET request must be made across the network.
        All 100 coroutines must receive the identical valid keys.
        """
        network_calls_count = 0
        active_requests = 0
        max_parallel_network_calls = 0

        async def simulated_http_get(url, **kwargs):
            nonlocal network_calls_count, active_requests, max_parallel_network_calls
            network_calls_count += 1
            active_requests += 1
            max_parallel_network_calls = max(max_parallel_network_calls, active_requests)
            # Artificial latency to maximize window for race condition / stampede
            await asyncio.sleep(0.04)
            active_requests -= 1

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json = MagicMock(return_value=self.dummy_jwks)
            return mock_resp

        with patch("httpx.AsyncClient.get", side_effect=simulated_http_get):
            # Launch 100 concurrent tasks
            tasks = [asyncio.create_task(self.auth.get_jwks()) for _ in range(100)]
            results = await asyncio.gather(*tasks)

        # Assertions
        self.assertEqual(len(results), 100)
        for res in results:
            self.assertEqual(res, self.dummy_jwks)

        self.assertEqual(
            network_calls_count,
            1,
            f"CACHE STAMPEDE DETECTED: {network_calls_count} HTTP requests made instead of 1!",
        )
        self.assertEqual(
            max_parallel_network_calls,
            1,
            f"PARALLEL FETCH DETECTED: max parallel requests was {max_parallel_network_calls}",
        )

    async def test_probe_r2_12_expired_cache_stampede_50_concurrent_coroutines(self):
        """
        Stress Test: 50 coroutines arrive when TTL has expired (time.time() - cache_time > 3600).
        Oracle: Double-checked locking must refresh exactly ONCE.
        """
        # Prepopulate cache with expired timestamp
        self.auth._jwks_cache = {"keys": [{"kid": "stale-key"}]}
        self.auth._jwks_cache_time = time.time() - 4000  # Expired > 3600s

        network_calls_count = 0

        async def simulated_http_get(url, **kwargs):
            nonlocal network_calls_count
            network_calls_count += 1
            await asyncio.sleep(0.03)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json = MagicMock(return_value=self.dummy_jwks)
            return mock_resp

        with patch("httpx.AsyncClient.get", side_effect=simulated_http_get):
            tasks = [asyncio.create_task(self.auth.get_jwks()) for _ in range(50)]
            results = await asyncio.gather(*tasks)

        self.assertEqual(len(results), 50)
        self.assertEqual(network_calls_count, 1, f"Expected 1 refresh call, got {network_calls_count}")
        for res in results:
            self.assertEqual(res["keys"][0]["kid"], "key-1")

    async def test_probe_r2_13_resilient_fallback_to_stale_cache_on_upstream_failure(self):
        """
        Stress Test: When upstream identity provider suffers an outage (500/timeout),
        the service must gracefully return cached keys rather than failing user requests.
        """
        stale_jwks = {"keys": [{"kid": "cached-stale-key"}]}
        self.auth._jwks_cache = stale_jwks
        self.auth._jwks_cache_time = time.time() - 4000  # Expired

        # Upstream throws ConnectError
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
            jwks = await self.auth.get_jwks(force_refresh=True)

        self.assertEqual(jwks, stale_jwks, "Service failed to fall back to cached JWKS on outage!")

    async def test_probe_r2_14_empty_cache_upstream_outage_raises_503(self):
        """Probe R2.14: When no cache exists and upstream fails, raises HTTP 503."""
        self.auth._jwks_cache = None
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectTimeout("Timeout")):
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_jwks()
            self.assertEqual(ctx.exception.status_code, 503)

    async def test_probe_r2_15_lazy_lock_resilience_across_event_loops(self):
        """Probe R2.15: Lazy lock property detects and binds to running loop cleanly."""
        current_loop = asyncio.get_running_loop()
        lock = self.auth.lock
        self.assertIsInstance(lock, asyncio.Lock)
        # Calling lock again returns the same lock on the same loop
        self.assertIs(self.auth.lock, lock)

    async def test_probe_r2_18_concurrent_force_refresh_serialized_safely(self):
        """Probe R2.18: 30 concurrent coroutines calling force_refresh=True are serialized safely without corruption."""
        fetch_count = 0

        async def simulated_http_get(url, **kwargs):
            nonlocal fetch_count
            fetch_count += 1
            await asyncio.sleep(0.01)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json = MagicMock(return_value={"keys": [{"kid": f"key-{fetch_count}"}]})
            return mock_resp

        with patch("httpx.AsyncClient.get", side_effect=simulated_http_get):
            tasks = [asyncio.create_task(self.auth.get_jwks(force_refresh=True)) for _ in range(30)]
            results = await asyncio.gather(*tasks)

        self.assertEqual(len(results), 30)
        # Because each requested force_refresh=True, each ran under the lock sequentially without race condition
        self.assertEqual(fetch_count, 30)
        self.assertIsNotNone(self.auth._jwks_cache)

    async def test_probe_r2_19_invalid_json_upstream_without_cache_raises_503(self):
        """Probe R2.19: Upstream sends invalid/corrupted JSON without cached fallback."""
        self.auth._jwks_cache = None
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(side_effect=ValueError("Invalid JSON"))

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            with self.assertRaises(HTTPException) as ctx:
                await self.auth.get_jwks()
            self.assertEqual(ctx.exception.status_code, 503)

