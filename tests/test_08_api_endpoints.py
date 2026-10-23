"""
Test Suite 8: API Endpoints (FastAPI Routers, Health, Auth, Documents, Search, Relaciones, External AI)
Cobertura exhaustiva de endpoints HTTP, inyección de dependencias, códigos de estado y manejo de excepciones.
"""

from datetime import date, datetime
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.auth import auth_service
from app.api.documents import get_doc_repo
from app.api.external_ai import get_external_ai_service
from app.api.relaciones import get_relacion_repo
from app.api.search import get_search_service
from app.main import app
from app.models.ai_models import (
    AskResponse,
    CreateSessionResponse,
    DiagnosticResponse,
    SearchResult,
    SearchResponse as AISearchResponse,
    SessionDetail,
    SessionListItem,
)
from app.models.document_models import (
    BeneficioOut,
    CarreraOut,
    CategoriaOut,
    DepartamentoOut,
    DocumentoDetail,
    DocumentoEditableOut,
    DocumentoOut,
    DocumentoUrlOut,
    NombramientoOut,
    SedeCampusOut,
)
from app.models.search_models import (
    AutocompleteResponse,
    FilterOption,
    FilterOptions,
    LexicalSuggestionItem,
    SearchResponse,
)
from app.models.user_models import UserOut, UserRole
from app.security.microsoft_auth import oauth2_scheme, require_admin, require_authenticated


class TestSuite8ApiEndpoints(unittest.IsolatedAsyncioTestCase):
    """Pruebas unitarias integradas con TestClient para todos los routers de la API."""

    def setUp(self):
        super().setUp()
        self.mock_user = UserOut(
            email="test@universidad.cl",
            name="Usuario Prueba",
            role=UserRole.BASIC,
        )
        self.mock_admin = UserOut(
            email="admin@universidad.cl",
            name="Admin Prueba",
            role=UserRole.ADMIN,
        )

        # Dependency Overrides para aislar la capa HTTP
        app.dependency_overrides[require_authenticated] = lambda: self.mock_user
        app.dependency_overrides[require_admin] = lambda: self.mock_admin
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.mock_user
        app.dependency_overrides[oauth2_scheme] = lambda: "Bearer mock-test-token"

        self.mock_doc_repo = MagicMock()
        self.mock_rel_repo = MagicMock()
        self.mock_search_service = MagicMock()
        self.mock_ai_service = MagicMock()

        app.dependency_overrides[get_doc_repo] = lambda: self.mock_doc_repo
        app.dependency_overrides[get_relacion_repo] = lambda: self.mock_rel_repo
        app.dependency_overrides[get_search_service] = lambda: self.mock_search_service
        app.dependency_overrides[get_external_ai_service] = lambda: self.mock_ai_service

        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        app.dependency_overrides.clear()
        super().tearDown()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Main & Health Check Endpoints
    # ─────────────────────────────────────────────────────────────────────────

    def test_01_health_check_ok(self):
        """GET /health retorna status 200 'ok'."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    @patch("app.main.check_db_connection", new_callable=AsyncMock)
    def test_02_database_health_connected_and_disconnected(self, mock_check_db):
        """GET /health/db cubre caso conectado (200) y desconectado con error (200)."""
        # Caso 1: Conectado
        mock_check_db.return_value = {
            "connected": True,
            "database": "postgres",
            "current_schema": "public",
            "documento_tables": [{"schema": "public", "table": "documento"}],
        }
        res_ok = self.client.get("/health/db")
        self.assertEqual(res_ok.status_code, 200)
        self.assertTrue(res_ok.json().get("connected"))

        # Caso 2: Desconectado
        mock_check_db.return_value = {
            "connected": False,
            "error": "Timeout al conectar a PostgreSQL",
        }
        res_err = self.client.get("/health/db")
        self.assertEqual(res_err.status_code, 200)
        self.assertEqual(res_err.json(), {
            "database": "disconnected",
            "error": "Timeout al conectar a PostgreSQL",
        })

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Auth Endpoints (/api/v1/auth)
    # ─────────────────────────────────────────────────────────────────────────

    @patch.object(auth_service, "get_login_url", return_value="https://cognito.amazon.com/login?client_id=123")
    def test_03_auth_login_url(self, mock_get_login):
        """GET /api/v1/auth/login-url retorna URL de Cognito."""
        response = self.client.get("/api/v1/auth/login-url")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"url": "https://cognito.amazon.com/login?client_id=123"})

    @patch.object(auth_service, "exchange_code", new_callable=AsyncMock)
    def test_04_auth_callback_success_and_error(self, mock_exchange):
        """POST /api/v1/auth/callback maneja éxito y error 401."""
        # Éxito
        mock_exchange.return_value = {
            "access_token": "acc-123",
            "id_token": "id-456",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        res_ok = self.client.post("/api/v1/auth/callback", json={"code": "code-abc", "redirect_uri": "http://localhost/callback"})
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.json()["access_token"], "acc-123")

        # Error de intercambio
        mock_exchange.side_effect = RuntimeError("Código de autorización inválido o expirado")
        res_err = self.client.post("/api/v1/auth/callback", json={"code": "bad-code", "redirect_uri": "http://localhost/callback"})
        self.assertEqual(res_err.status_code, 401)
        self.assertIn("Código de autorización inválido", res_err.json()["detail"])

    def test_05_auth_me(self):
        """GET /api/v1/auth/me retorna los datos del usuario actual."""
        response = self.client.get("/api/v1/auth/me")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["email"], "test@universidad.cl")
        self.assertEqual(data["role"], "basic")

    @patch.object(auth_service, "exchange_code", new_callable=AsyncMock)
    def test_06_auth_docs_token_success_and_error(self, mock_exchange):
        """POST /api/v1/auth/docs-token para Swagger OAuth maneja éxito y fallo 401."""
        mock_exchange.return_value = {"id_token": "id-token-swagger-789"}
        res_ok = self.client.post(
            "/api/v1/auth/docs-token",
            data={"grant_type": "authorization_code", "code": "swagger-code", "redirect_uri": "http://localhost/docs/oauth2-redirect"},
        )
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.json(), {"access_token": "id-token-swagger-789", "token_type": "bearer"})

        mock_exchange.side_effect = ValueError("Fallo Swagger")
        res_err = self.client.post("/api/v1/auth/docs-token", data={"grant_type": "authorization_code", "code": "invalid"})
        self.assertEqual(res_err.status_code, 401)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Documents Endpoints (/api/v1/documents)
    # ─────────────────────────────────────────────────────────────────────────

    def test_07_documents_list(self):
        """GET /api/v1/documents lista documentos con paginación."""
        doc_uuid = uuid4()
        self.mock_doc_repo.list_documents = AsyncMock(return_value=[
            DocumentoOut(
                iddocumento=doc_uuid,
                numero="123/2026",
                titulo="Reglamento Estudiantil",
                nommetadato="Reglamento Estudiantil",
                isactive=True,
            )
        ])
        response = self.client.get("/api/v1/documents?skip=0&limit=10")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["titulo"], "Reglamento Estudiantil")

    @patch("app.api.documents.get_session")
    def test_08_documents_by_title_found_and_not_found(self, mock_get_session):
        """GET /api/v1/documents/by-title/{title} busca ignorando extensión .md y case-insensitive."""
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        # Caso 1: Encontrado
        doc_mock = MagicMock()
        doc_mock.iddocumento = uuid4()
        doc_mock.titulo = "Estatuto Organico"
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = doc_mock
        mock_session.execute.return_value = result_mock

        res_ok = self.client.get("/api/v1/documents/by-title/Estatuto%20Organico.md")
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.json()["titulo"], "Estatuto Organico")

        # Caso 2: No encontrado (404)
        result_mock.scalar_one_or_none.return_value = None
        res_404 = self.client.get("/api/v1/documents/by-title/Inexistente.md")
        self.assertEqual(res_404.status_code, 404)
        self.assertEqual(res_404.json()["detail"], "Documento no encontrado")

    def test_09_documents_catalogs(self):
        """GET /api/v1/documents/admin/catalogs y /catalogs retornan FilterOptions."""
        self.mock_doc_repo.get_filter_options = AsyncMock(return_value=FilterOptions(
            categorias=[FilterOption(id=1, nombre="Académica")],
            sedes=[FilterOption(id=10, nombre="Casa Central")],
        ))

        res1 = self.client.get("/api/v1/documents/admin/catalogs")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["categorias"][0]["nombre"], "Académica")

        res2 = self.client.get("/api/v1/documents/catalogs")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["sedes"][0]["nombre"], "Casa Central")

    def test_10_documents_editable(self):
        """GET /api/v1/documents/{id}/editable retorna documento para editor."""
        doc_id = str(uuid4())
        self.mock_doc_repo.get_editable_by_id = AsyncMock(return_value=DocumentoEditableOut(
            iddocumento=doc_id,
            numero="555",
            titulo="Decreto de Pruebas",
            nommetadato="Decreto de Pruebas",
            isactive=True,
            sedesids=[1, 2],
        ))

        res = self.client.get(f"/api/v1/documents/{doc_id}/editable")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["sedesids"], [1, 2])

    def test_11_documents_update(self):
        """PUT / PATCH /api/v1/documents/{id} actualiza metadata."""
        doc_id = str(uuid4())
        self.mock_doc_repo.update = AsyncMock(return_value=DocumentoDetail(
            iddocumento=doc_id,
            numero="888/2026",
            titulo="Decreto Actualizado",
            nommetadato="Decreto Actualizado",
            cant_paginas=5,
            isactive=True,
        ))

        payload = {"titulo": "Decreto Actualizado"}
        res_put = self.client.put(f"/api/v1/documents/{doc_id}", json=payload)
        self.assertEqual(res_put.status_code, 200)
        self.assertEqual(res_put.json()["titulo"], "Decreto Actualizado")

        res_patch = self.client.patch(f"/api/v1/documents/{doc_id}", json=payload)
        self.assertEqual(res_patch.status_code, 200)

    def test_12_documents_toggle_active(self):
        """PATCH /api/v1/documents/{id}/toggle-active alterna isactive."""
        doc_id = str(uuid4())
        self.mock_doc_repo.toggle_active = AsyncMock(return_value=DocumentoDetail(
            iddocumento=doc_id,
            numero="111",
            titulo="Doc Toggle",
            nommetadato="Doc Toggle",
            cant_paginas=2,
            isactive=False,
        ))

        res = self.client.patch(f"/api/v1/documents/{doc_id}/toggle-active")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["isactive"])

    def test_13_documents_detail_and_raw_detail(self):
        """GET /api/v1/documents/{id}/detail y GET /api/v1/documents/{id}."""
        doc_id = str(uuid4())
        # Raw detail jsonb
        self.mock_doc_repo.get_raw_detail = AsyncMock(return_value={"id": doc_id, "jsonb": True})
        res_raw = self.client.get(f"/api/v1/documents/{doc_id}/detail")
        self.assertEqual(res_raw.status_code, 200)
        self.assertTrue(res_raw.json()["jsonb"])

        # Detail found
        self.mock_doc_repo.get_by_id = AsyncMock(return_value=DocumentoDetail(
            iddocumento=doc_id,
            numero="999",
            titulo="Doc Detalle",
            nommetadato="Doc Detalle",
            cant_paginas=1,
            isactive=True,
        ))
        res_get = self.client.get(f"/api/v1/documents/{doc_id}")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["titulo"], "Doc Detalle")

        # Detail not found (404)
        self.mock_doc_repo.get_by_id = AsyncMock(return_value=None)
        res_404 = self.client.get(f"/api/v1/documents/{uuid4()}")
        self.assertEqual(res_404.status_code, 404)

    @patch("app.api.documents.get_signed_url", new_callable=AsyncMock)
    def test_14_documents_signed_url(self, mock_get_signed_url):
        """GET /api/v1/documents/{id}/url obtiene S3 key y genera URL firmada."""
        doc_id = str(uuid4())
        self.mock_doc_repo.get_s3_key = AsyncMock(return_value="documents/2026/norma.pdf")
        mock_get_signed_url.return_value = DocumentoUrlOut(
            url="https://s3.amazonaws.com/presigned-url-abc",
            expires_in=600,
        )

        res = self.client.get(f"/api/v1/documents/{doc_id}/url")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["url"], "https://s3.amazonaws.com/presigned-url-abc")

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Relaciones Endpoints (/api/v1/relaciones)
    # ─────────────────────────────────────────────────────────────────────────

    def test_15_relaciones_create_delete_and_lineage(self):
        """POST, DELETE y GET /{id}/lineage en /api/v1/relaciones."""
        doc_orig = str(uuid4())
        doc_dest = str(uuid4())

        # Create
        self.mock_rel_repo.create_via_sp = AsyncMock(return_value={"status": "ok", "message": "Creada"})
        res_post = self.client.post("/api/v1/relaciones/", json={
            "iddocumentoorigen": doc_orig,
            "iddocumentodestino": doc_dest,
            "idtiporelacion": 1,
            "detallemodificacion": "Derogación parcial",
        })
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.json()["status"], "ok")

        # Delete
        self.mock_rel_repo.delete_via_sp = AsyncMock(return_value={"status": "ok", "message": "Eliminada"})
        res_del = self.client.request("DELETE", "/api/v1/relaciones/", json={
            "idrelacion": 42,
        })
        self.assertEqual(res_del.status_code, 200)

        # Lineage
        self.mock_rel_repo.get_document_lineage = AsyncMock(return_value={
            "document_id": doc_orig,
            "relaciones_como_origen": [],
            "relaciones_como_destino": [],
        })
        res_lin = self.client.get(f"/api/v1/relaciones/{doc_orig}/lineage")
        self.assertEqual(res_lin.status_code, 200)
        self.assertEqual(res_lin.json()["document_id"], doc_orig)

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Search Endpoints (/api/v1/search)
    # ─────────────────────────────────────────────────────────────────────────

    def test_16_search_documents_and_filters_and_autocomplete(self):
        """POST /, GET /filters y GET /autocomplete en /api/v1/search."""
        # Search
        self.mock_search_service.search = AsyncMock(return_value=SearchResponse(
            query="estatutos",
            total=0,
            page=1,
            page_size=20,
            results=[],
        ))
        res_search = self.client.post("/api/v1/search/", json={"query": "estatutos"})
        self.assertEqual(res_search.status_code, 200)
        self.assertEqual(res_search.json()["query"], "estatutos")

        # Filters
        self.mock_search_service.get_filter_options = AsyncMock(return_value=FilterOptions(
            categorias=[],
            areas=[],
        ))
        res_filters = self.client.get("/api/v1/search/filters")
        self.assertEqual(res_filters.status_code, 200)

        # Autocomplete
        self.mock_search_service.get_autocomplete_suggestions = AsyncMock(return_value=AutocompleteResponse(
            query="#ley",
            is_lexical=True,
            suggestions=[
                LexicalSuggestionItem(
                    documentid=str(uuid4()),
                    numero="21091",
                    titulo="Ley de Educación",
                    nommetadato="Ley",
                    matched_field="titulo",
                    suggestion="Ley 21091",
                )
            ],
        ))
        res_auto = self.client.get("/api/v1/search/autocomplete?q=%23ley&limit=5")
        self.assertEqual(res_auto.status_code, 200)
        self.assertEqual(len(res_auto.json()["suggestions"]), 1)

    # ─────────────────────────────────────────────────────────────────────────
    # 6. External AI Endpoints (/api/v1/ai)
    # ─────────────────────────────────────────────────────────────────────────

    def test_17_external_ai_health_check(self):
        """GET /api/v1/ai/health cubre 200 OK y 503 cuando el microservicio falla."""
        # Éxito
        self.mock_ai_service.health_check = AsyncMock(return_value={"status": "healthy"})
        res_ok = self.client.get("/api/v1/ai/health")
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.json(), {"status": "healthy"})

        # Error 503
        self.mock_ai_service.health_check = AsyncMock(side_effect=RuntimeError("Connection refused"))
        res_err = self.client.get("/api/v1/ai/health")
        self.assertEqual(res_err.status_code, 503)
        self.assertIn("Connection refused", res_err.json()["detail"])

    def test_18_external_ai_sessions_crud(self):
        """POST, GET (list), GET (detail) y DELETE de sesiones de chat en /api/v1/ai/sessions."""
        # Create
        self.mock_ai_service.create_session = AsyncMock(return_value=CreateSessionResponse(
            id="ses-100",
            user_id="usr-1",
            titulo="Consulta Aranceles",
            modo="general",
            creada=datetime.now(),
            actualizada=datetime.now(),
        ))
        res_create = self.client.post("/api/v1/ai/sessions", json={"user_id": "usr-1", "titulo": "Consulta Aranceles"})
        self.assertEqual(res_create.status_code, 200)
        self.assertEqual(res_create.json()["id"], "ses-100")

        # Create Error 500
        self.mock_ai_service.create_session = AsyncMock(side_effect=ValueError("Fallo sesión"))
        res_create_err = self.client.post("/api/v1/ai/sessions", json={"user_id": "usr-1", "titulo": "Fallo"})
        self.assertEqual(res_create_err.status_code, 500)

        # List
        self.mock_ai_service.list_sessions = AsyncMock(return_value=[
            SessionListItem(
                id="ses-100",
                user_id="usr-1",
                titulo="Consulta Aranceles",
                modo="general",
                creada=datetime.now(),
                actualizada=datetime.now(),
            )
        ])
        res_list = self.client.get("/api/v1/ai/sessions?user_id=usr-1")
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(len(res_list.json()), 1)

        # List Error 500
        self.mock_ai_service.list_sessions = AsyncMock(side_effect=RuntimeError("Fallo listado"))
        res_list_err = self.client.get("/api/v1/ai/sessions?user_id=usr-1")
        self.assertEqual(res_list_err.status_code, 500)

        # Get detail (OK)
        self.mock_ai_service.get_session = AsyncMock(return_value=SessionDetail(
            id="ses-100",
            user_id="usr-1",
            titulo="Consulta Aranceles",
            modo="general",
            mensajes=[],
            creada=datetime.now(),
            actualizada=datetime.now(),
        ))
        res_get = self.client.get("/api/v1/ai/sessions/ses-100?user_id=usr-1")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["id"], "ses-100")

        # Get detail (404 no existe)
        self.mock_ai_service.get_session = AsyncMock(side_effect=ValueError("La sesión no existe"))
        res_get_404 = self.client.get("/api/v1/ai/sessions/ses-fake?user_id=usr-1")
        self.assertEqual(res_get_404.status_code, 404)

        # Get detail (500)
        self.mock_ai_service.get_session = AsyncMock(side_effect=RuntimeError("DB timeout"))
        res_get_500 = self.client.get("/api/v1/ai/sessions/ses-timeout?user_id=usr-1")
        self.assertEqual(res_get_500.status_code, 500)

        # Delete (OK)
        self.mock_ai_service.delete_session = AsyncMock(return_value=None)
        res_del = self.client.delete("/api/v1/ai/sessions/ses-100?user_id=usr-1")
        self.assertEqual(res_del.status_code, 200)
        self.assertEqual(res_del.json(), {"status": "deleted"})

        # Delete (404)
        self.mock_ai_service.delete_session = AsyncMock(side_effect=ValueError("404 Not Found"))
        res_del_404 = self.client.delete("/api/v1/ai/sessions/ses-fake?user_id=usr-1")
        self.assertEqual(res_del_404.status_code, 404)

        # Delete (500)
        self.mock_ai_service.delete_session = AsyncMock(side_effect=RuntimeError("Fallo delete"))
        res_del_500 = self.client.delete("/api/v1/ai/sessions/ses-err?user_id=usr-1")
        self.assertEqual(res_del_500.status_code, 500)

    def test_19_external_ai_ask(self):
        """POST /api/v1/ai/ask cubre 200, 404 sesión inexistente, 502 grafo caído y 500."""
        # 200 OK
        self.mock_ai_service.ask = AsyncMock(return_value=AskResponse(
            session_id="ses-1",
            respuesta="Respuesta del modelo RAG",
            fuentes=[],
            modo="general",
            tiempo_s=1.25,
            llamadas_llm=1,
        ))
        res_ok = self.client.post("/api/v1/ai/ask", json={"session_id": "ses-1", "user_id": "usr-1", "pregunta": "¿Qué es GIRU?"})
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.json()["respuesta"], "Respuesta del modelo RAG")

        # 404 No existe
        self.mock_ai_service.ask = AsyncMock(side_effect=ValueError("La sesion no existe"))
        res_404 = self.client.post("/api/v1/ai/ask", json={"session_id": "ses-1", "user_id": "usr-1", "pregunta": "hola"})
        self.assertEqual(res_404.status_code, 404)

        # 502 Fallo grafo
        self.mock_ai_service.ask = AsyncMock(side_effect=RuntimeError("Error 502 Bad Gateway en motor de grafo"))
        res_502 = self.client.post("/api/v1/ai/ask", json={"session_id": "ses-1", "user_id": "usr-1", "pregunta": "hola"})
        self.assertEqual(res_502.status_code, 502)

        # 500 Error genérico
        self.mock_ai_service.ask = AsyncMock(side_effect=RuntimeError("Error desconocido"))
        res_500 = self.client.post("/api/v1/ai/ask", json={"session_id": "ses-1", "user_id": "usr-1", "pregunta": "hola"})
        self.assertEqual(res_500.status_code, 500)

    def test_20_external_ai_ask_stream(self):
        """POST /api/v1/ai/ask-stream transmite chunks SSE y emite errores SSE si ocurre excepción."""
        async def mock_stream_ok(req):
            yield "event: token\ndata: Hola\n\n"
            yield "event: token\ndata: mundo\n\n"

        self.mock_ai_service.ask_stream = mock_stream_ok
        res_stream = self.client.post("/api/v1/ai/ask-stream", json={"session_id": "ses-1", "user_id": "usr-1", "pregunta": "stream test"})
        self.assertEqual(res_stream.status_code, 200)
        self.assertIn("text/event-stream", res_stream.headers["content-type"])
        self.assertIn("Hola", res_stream.text)

        # Caso de error en el stream
        async def mock_stream_error(req):
            raise RuntimeError("Stream interrumpido")
            yield "never"

        self.mock_ai_service.ask_stream = mock_stream_error
        res_stream_err = self.client.post("/api/v1/ai/ask-stream", json={"session_id": "ses-1", "user_id": "usr-1", "pregunta": "stream error"})
        self.assertEqual(res_stream_err.status_code, 200)
        self.assertIn("event: error", res_stream_err.text)
        self.assertIn("Stream interrumpido", res_stream_err.text)

    def test_21_external_ai_search_and_diagnostic(self):
        """POST /api/v1/ai/search y GET /api/v1/ai/diagnostic cubren éxito y errores 500."""
        # Search OK
        self.mock_ai_service.search = AsyncMock(return_value=AISearchResponse(
            consulta="reglamento",
            resultados=[],
        ))
        res_search = self.client.post("/api/v1/ai/search", json={"consulta": "reglamento"})
        self.assertEqual(res_search.status_code, 200)
        self.assertEqual(res_search.json()["consulta"], "reglamento")

        # Search Error 500
        self.mock_ai_service.search = AsyncMock(side_effect=RuntimeError("Fallo motor búsqueda IA"))
        res_search_err = self.client.post("/api/v1/ai/search", json={"consulta": "reglamento"})
        self.assertEqual(res_search_err.status_code, 500)

        # Diagnostic OK
        self.mock_ai_service.get_diagnostic = AsyncMock(return_value=DiagnosticResponse(
            grafo="universidad_normativa",
            entidades=1500,
            relaciones=3200,
            documentos=450,
        ))
        res_diag = self.client.get("/api/v1/ai/diagnostic")
        self.assertEqual(res_diag.status_code, 200)
        self.assertEqual(res_diag.json()["grafo"], "universidad_normativa")

        # Diagnostic Error 500
        self.mock_ai_service.get_diagnostic = AsyncMock(side_effect=RuntimeError("Error en diagnóstico"))
        res_diag_err = self.client.get("/api/v1/ai/diagnostic")
        self.assertEqual(res_diag_err.status_code, 500)
