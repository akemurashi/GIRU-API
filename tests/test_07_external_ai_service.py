"""
Suite 7: Servicio de IA Externa GIRU (RAG, Chat, Streaming SSE, Sesiones).
Pruebas unitarias para app/services/external_ai_service.py.
"""

from datetime import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import tests.base  # noqa: F401
from app.models.ai_models import (
    AskRequest,
    CreateSessionRequest,
    SearchRequest,
)
from app.services.external_ai_service import ExternalAIService


class TestSuite7ExternalAIService(unittest.IsolatedAsyncioTestCase):
    """Pruebas del cliente HTTP para el motor externo de IA (Gemma / RAG)."""

    def setUp(self):
        self.ai = ExternalAIService()

    async def test_01_health_check_success_and_error(self):
        """Verifica endpoint de salud del motor de IA (GET /salud)."""
        mock_ok = MagicMock(status_code=200)
        mock_ok.json.return_value = {"estado": "operativo", "modelo": "gemma"}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_ok
            res = await self.ai.health_check()
            self.assertEqual(res["estado"], "operativo")

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectError("Service down")
            with self.assertRaises(ConnectionError):
                await self.ai.health_check()

    async def test_02_request_http_methods(self):
        """Verifica métodos GET, POST, DELETE y rechazo de métodos no soportados."""
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            res_get = await self.ai._request("GET", "/test", {"q": "1"})
            self.assertTrue(res_get["ok"])

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_resp
            res_post = await self.ai._request("POST", "/test", {"body": "data"})
            self.assertTrue(res_post["ok"])

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = mock_resp
            res_del = await self.ai._request("DELETE", "/test")
            self.assertTrue(res_del["ok"])

        with self.assertRaises(ValueError):
            await self.ai._request("PATCH", "/test")

    async def test_03_request_error_translations(self):
        """Verifica traducción de errores HTTPStatusError, Timeout y Connection."""
        request = httpx.Request("POST", "http://test")

        for code, expected_match in [
            (401, "Clave de API inválida"),
            (404, "La sesión no existe"),
            (502, "Falla del motor de grafo"),
            (500, "Error del servicio de IA: 500"),
        ]:
            response = httpx.Response(code, request=request, text="error info")
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.side_effect = httpx.HTTPStatusError("Err", request=request, response=response)
                with self.assertRaises(RuntimeError) as ctx:
                    await self.ai._request("POST", "/error")
                self.assertIn(expected_match, str(ctx.exception))

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Timeout")
            with self.assertRaises(TimeoutError):
                await self.ai._request("POST", "/timeout")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.side_effect = httpx.RequestError("Network drop", request=request)
            with self.assertRaises(ConnectionError):
                await self.ai._request("POST", "/net")

    async def test_04_create_session_and_ask(self):
        """Verifica creación de sesiones y preguntas síncronas al chatbot."""
        self.ai._request = AsyncMock()

        now = datetime.now()
        self.ai._request.return_value = {
            "id": "ses-100",
            "user_id": "u1",
            "titulo": "Consulta de Matrícula",
            "modo": "cascade",
            "creada": now,
            "actualizada": now,
        }
        create_req = CreateSessionRequest(user_id="u1", titulo="Consulta de Matrícula", modo="cascade")
        sess = await self.ai.create_session(create_req)
        self.assertEqual(sess.id, "ses-100")

        self.ai._request.return_value = {
            "session_id": "ses-100",
            "respuesta": "La matrícula se paga en marzo.",
            "fuentes": [{"documento": "Reglamento.pdf", "fragmento": "Texto"}],
            "modo": "cascade",
            "tiempo_s": 1.25,
            "llamadas_llm": 1,
        }
        ask_req = AskRequest(user_id="u1", session_id="ses-100", pregunta="¿Cuándo pago?", modo="cascade")
        ans = await self.ai.ask(ask_req)
        self.assertEqual(ans.respuesta, "La matrícula se paga en marzo.")

    async def test_05_search_and_get_diagnostic(self):
        """Verifica búsqueda semántica y diagnóstico de salud."""
        self.ai._request = AsyncMock()

        self.ai._request.return_value = {
            "consulta": "aranceles",
            "resultados": [{"documento": "doc.pdf", "puntaje": 0.9, "entidades": []}],
        }
        s_res = await self.ai.search(SearchRequest(consulta="aranceles", k=5))
        self.assertEqual(s_res.consulta, "aranceles")
        self.assertEqual(len(s_res.resultados), 1)

        self.ai._request.return_value = {
            "grafo": "Neo4j",
            "entidades": 150,
            "relaciones": 300,
            "documentos": 25,
        }
        diag = await self.ai.get_diagnostic()
        self.assertEqual(diag.grafo, "Neo4j")

    async def test_06_sessions_crud(self):
        """Verifica listado, detalle y eliminación de sesiones de usuario."""
        self.ai._request = AsyncMock()
        now = datetime.now()

        self.ai._request.return_value = [
            {
                "id": "s1",
                "user_id": "u1",
                "titulo": "Sesion 1",
                "modo": "cascade",
                "creada": now,
                "actualizada": now,
            }
        ]
        items = await self.ai.list_sessions(user_id="u1")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].id, "s1")

        self.ai._request.return_value = {
            "id": "s1",
            "titulo": "Sesion 1",
            "modo": "cascade",
            "mensajes": [
                {"rol": "user", "contenido": "Hola", "creado": now}
            ],
        }
        detail = await self.ai.get_session("s1", user_id="u1")
        self.assertEqual(detail.id, "s1")
        self.assertEqual(len(detail.mensajes), 1)

        self.ai._request.return_value = None
        await self.ai.delete_session("s1", user_id="u1")
        self.ai._request.assert_awaited_with("DELETE", "/sesiones/s1", {"user_id": "u1"})

    async def test_07_ask_stream_success_and_errors(self):
        """Verifica streaming SSE de respuestas del chatbot."""
        ask_req = AskRequest(user_id="u1", session_id="s1", pregunta="¿Hola?", modo="cascade")

        # Caso exitoso: streaming de chunks
        async def mock_aiter():
            yield b"data: chunk 1\n\n"
            yield b"data: chunk 2\n\n"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.aiter_bytes = mock_aiter

        mock_stream_ctx = MagicMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient.stream", return_value=mock_stream_ctx):
            chunks = []
            async for chunk in self.ai.ask_stream(ask_req):
                chunks.append(chunk)
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0], "data: chunk 1\n\n")

        # Casos de error en streaming
        request = httpx.Request("POST", "http://test")
        resp_401 = httpx.Response(401, request=request)
        mock_err_ctx = MagicMock()
        mock_err_ctx.__aenter__ = AsyncMock(side_effect=httpx.HTTPStatusError("401", request=request, response=resp_401))
        mock_err_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient.stream", return_value=mock_err_ctx):
            with self.assertRaises(RuntimeError) as ctx:
                async for _ in self.ai.ask_stream(ask_req):
                    pass
            self.assertIn("Clave de API inválida", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
