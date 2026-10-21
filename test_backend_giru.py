"""
Suite de Pruebas Automatizadas (Unitarias, Reglas de Negocio e Integración de Contratos)
Subsistema Backend — Proyecto G.I.R.U. (Gestión Inteligente de Reglamentos Universitarios)

Ejecución en el repositorio giru-api:
  - Con pytest:   pytest -v test_backend_giru.py
  - Con unittest: python -m unittest -v test_backend_giru.py
"""

import json
import os
import sys
import time
import types
import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pydantic
from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError as PydanticValidationError

# Compatibilidad automática si el runner local tiene Pydantic v1 (<2.0) instalado
if not hasattr(pydantic, "field_validator"):
    from pydantic import root_validator, validator

    def _field_validator(*fields, mode="after", **kwargs):
        pre = mode == "before"
        return validator(*fields, pre=pre, allow_reuse=True)

    def _model_validator(mode="after"):
        def _decorator(fn):
            fn_func = fn.__func__ if isinstance(fn, classmethod) else fn

            def _root_fn(cls, values):
                ns = types.SimpleNamespace(**values)
                fn_func(ns)
                return values

            return root_validator(pre=(mode == "before"), allow_reuse=True)(_root_fn)

        return _decorator

    pydantic.field_validator = _field_validator
    pydantic.model_validator = _model_validator

    _orig_field = pydantic.Field

    def _compat_field(*args, **kwargs):
        if "pattern" in kwargs and "regex" not in kwargs:
            kwargs["regex"] = kwargs.pop("pattern")
        return _orig_field(*args, **kwargs)

    pydantic.Field = _compat_field

    if not hasattr(BaseModel, "model_dump"):
        BaseModel.model_dump = lambda self, *a, **kw: self.dict(*a, **kw)


# Configurar variables de entorno mínimas para pruebas aisladas sin requerir .env externo
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/giru_test")
os.environ.setdefault("COGNITO_DOMAIN", "https://giru-test.auth.us-east-1.amazoncognito.com")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client-id")
os.environ.setdefault("COGNITO_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_TestPool")
os.environ.setdefault("DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar")
os.environ.setdefault("GIRU_IA_URL", "http://localhost:8000")
os.environ.setdefault("GIRU_IA_KEY", "test-internal-api-key")

# Si se ejecuta en un entorno ligero sin drivers de BD instalados, proveer stubs ligeros
# para aislar las pruebas de servicios, esquemas y middlewares sin requerir PostgreSQL activo.
try:
    import pydantic_settings  # noqa: F401
except ImportError:
    ps_stub = types.ModuleType("pydantic_settings")

    class _BaseSettings(BaseModel):
        DATABASE_URL: str = "postgresql+asyncpg://test:test@localhost:5432/giru_test"
        COGNITO_DOMAIN: str = "https://giru-test.auth.us-east-1.amazoncognito.com"
        COGNITO_CLIENT_ID: str = "test-client-id"
        COGNITO_CLIENT_SECRET: str = "test-client-secret"
        COGNITO_USER_POOL_ID: str = "us-east-1_TestPool"
        DOCUMENT_SIGNER_URL: str = "https://signer.giru.usm.cl/firmar"
        GIRU_IA_URL: str = "http://localhost:8000"
        GIRU_IA_KEY: str = "test-internal-api-key"

    ps_stub.BaseSettings = _BaseSettings
    ps_stub.SettingsConfigDict = lambda **kwargs: kwargs
    sys.modules["pydantic_settings"] = ps_stub

try:
    from sqlalchemy.exc import SQLAlchemyError
except ImportError:
    sa_stub = types.ModuleType("sqlalchemy")
    sa_exc_stub = types.ModuleType("sqlalchemy.exc")

    class SQLAlchemyError(Exception):
        pass

    sa_exc_stub.SQLAlchemyError = SQLAlchemyError
    sa_stub.exc = sa_exc_stub
    sys.modules["sqlalchemy"] = sa_stub
    sys.modules["sqlalchemy.exc"] = sa_exc_stub

try:
    import sqlmodel  # noqa: F401
except ImportError:
    sqlmodel_stub = types.ModuleType("sqlmodel")
    sqlmodel_stub.SQLModel = object
    sqlmodel_stub.Field = lambda *args, **kwargs: None
    sqlmodel_stub.Relationship = lambda *args, **kwargs: None
    sqlmodel_stub.select = lambda *args, **kwargs: None
    sys.modules["sqlmodel"] = sqlmodel_stub

    doc_repo_stub = types.ModuleType("app.repositories.document_repository")

    class _StubDocumentRepository:
        async def lexical_search(self, *args, **kwargs):
            return [], 0

        async def filter_only_search(self, *args, **kwargs):
            return [], 0

        async def get_lexical_suggestions(self, *args, **kwargs):
            return []

        async def get_filter_options(self, *args, **kwargs):
            return None

    doc_repo_stub.DocumentRepository = _StubDocumentRepository
    sys.modules["app.repositories.document_repository"] = doc_repo_stub

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
    exception_handler,
    general_exception_handler,
    request_id_middleware,
    sqlalchemy_exception_handler,
    validation_exception_handler,
)
from app.models.ai_models import SearchResponse as AISearchResponse, SearchResult as AISearchResult
from app.models.document_models import (
    DocumentoUpdate,
    RelacionDocumentalCreate,
    RelacionDocumentalDelete,
    RelacionDocumentalOut,
)
from app.models.search_models import FilterOptions, SearchFilters, SearchRequest
from app.services.document_service import DocumentService
from app.services.document_url_service import get_signed_url, normalize_s3_key
from app.services.search_service import SearchService


# ==============================================================================
# Suite 1: Validación de Contratos DTO y Filtrado Facetado (RF-03, RF-05)
# ==============================================================================
class TestSuite1SearchModelsAndFacetedFilters(unittest.TestCase):
    """Suite 1: Validación de contratos DTO y Filtrado Facetado (RF-03, RF-05)."""

    def test_01_search_filters_valid_single_and_multi_facets(self):
        """Verifica soporte polimórfico (int y List[int]) en las dimensiones de filtrado facetado."""
        filters = SearchFilters(
            idestadovigencia=1,
            idtipodocumento=[1, 2],
            idrecintouniversitario=[1, 3, 5],
            idcarrera=[10, 20],
            iddepartamento=4,
            creaciondesde="2020-01-01",
            creacionhasta="2025-12-31",
            isactive=True,
        )
        self.assertEqual(filters.idestadovigencia, 1)
        self.assertEqual(filters.idtipodocumento, [1, 2])
        self.assertEqual(filters.idrecintouniversitario, [1, 3, 5])

    def test_02_search_filters_reject_non_positive_ids(self):
        """Verifica que SearchFilters rechace IDs menores o iguales a 0 (individuales o en listas)."""
        with self.assertRaises(PydanticValidationError):
            SearchFilters(idtipodocumento=0)

        with self.assertRaises(PydanticValidationError):
            SearchFilters(idcarrera=[1, -3, 5])

    def test_03_search_filters_reject_inverted_creation_dates(self):
        """Verifica que validate_date_ranges rechace creaciondesde > creacionhasta (HTTP 422)."""
        with self.assertRaises(PydanticValidationError) as ctx:
            SearchFilters(creaciondesde="2025-06-01", creacionhasta="2024-01-01")
        self.assertIn("creaciondesde debe ser menor o igual a creacionhasta", str(ctx.exception))

    def test_04_search_filters_reject_inverted_derogation_dates_and_negative_session(self):
        """Verifica rechazo de derogaciondesde > derogacionhasta y numsesion negativo."""
        with self.assertRaises(PydanticValidationError) as ctx:
            SearchFilters(derogaciondesde=date(2025, 10, 1), derogacionhasta=date(2023, 5, 1))
        self.assertIn("derogaciondesde debe ser menor o igual a derogacionhasta", str(ctx.exception))

        with self.assertRaises(PydanticValidationError):
            SearchFilters(numsesion=-1)

    def test_05_search_request_pagination_bounds(self):
        """Verifica restricciones de frontera en paginación (page >= 1, page_size <= 100)."""
        req = SearchRequest(query="reglamento académico", page=2, page_size=25)
        self.assertEqual(req.page, 2)
        self.assertEqual(req.page_size, 25)

        with self.assertRaises(PydanticValidationError):
            SearchRequest(query="test", page=0)

        with self.assertRaises(PydanticValidationError):
            SearchRequest(query="test", page_size=250)

    def test_06_search_filters_date_range_support_iso_strings_and_date_instances(self):
        """Verifica interoperabilidad de fechas tanto como string ISO como instancias datetime.date."""
        filters_str = SearchFilters(
            creaciondesde="2022-03-01",
            creacionhasta="2022-12-31"
        )
        self.assertEqual(str(filters_str.creaciondesde)[:10], "2022-03-01")
        self.assertEqual(str(filters_str.creacionhasta)[:10], "2022-12-31")

        filters_obj = SearchFilters(
            creaciondesde=date(2022, 3, 1),
            creacionhasta=date(2022, 12, 31)
        )
        self.assertEqual(filters_obj.creaciondesde, date(2022, 3, 1))
        self.assertEqual(filters_obj.creacionhasta, date(2022, 12, 31))

    def test_07_search_filters_confianza_range_bounds(self):
        """Verifica que confianzamin y confianzamax estén estrictamente en el intervalo [0.0, 1.0]."""
        valid_filters = SearchFilters(confianzamin=0.1, confianzamax=0.9)
        self.assertEqual(valid_filters.confianzamin, 0.1)
        self.assertEqual(valid_filters.confianzamax, 0.9)

        with self.assertRaises(PydanticValidationError):
            SearchFilters(confianzamin=-0.05)

        with self.assertRaises(PydanticValidationError):
            SearchFilters(confianzamax=1.05)

    def test_08_search_request_query_max_length_bound(self):
        """Verifica que SearchRequest rechace consultas que excedan el límite de 500 caracteres."""
        valid_req = SearchRequest(query="A" * 500)
        self.assertEqual(len(valid_req.query), 500)

        with self.assertRaises(PydanticValidationError):
            SearchRequest(query="A" * 501)


# ==============================================================================
# Suite 2: Modelos Documentales, Linaje y Microservicio S3 (RF-03, RF-07, RNF-01, RNF-04)
# ==============================================================================
class TestSuite2DocumentModelsAndS3Offloading(unittest.IsolatedAsyncioTestCase):
    """Suite 2: Reglas de negocio de edición documental, linaje y Offloading S3."""

    def test_09_documento_update_modo_puentes_and_s3_immutability(self):
        """Verifica patrón modo_puentes (REEMPLAZAR|AGREGAR|ELIMINAR) e inmutabilidad de urlarchivooriginals3."""
        upd = DocumentoUpdate(
            titulo="Reglamento de Evaluación",
            tipo_documento_nombre="Reglamento",
            sedesids=[1, 2],
            modo_puentes="AGREGAR",
        )
        self.assertEqual(upd.modo_puentes, "AGREGAR")
        fields_dict = getattr(DocumentoUpdate, "model_fields", None) or getattr(DocumentoUpdate, "__fields__", {})
        self.assertNotIn("urlarchivooriginals3", fields_dict)

        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", modo_puentes="SOBREESCRIBIR")

    def test_10_documento_update_negative_session_and_bridge_ids_validation(self):
        """Verifica validación de enteros positivos en sesión, acuerdo y tablas puente en DocumentoUpdate."""
        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", numsesion=-1)

        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", numacuerdo=-5)

        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", sedesids=[1, 0])

        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", carrerasids=[10, -2])

    def test_11_relacion_documental_confianza_bounds(self):
        """Verifica que el nivel de confianza en relaciones jurídicas esté acotado a [0.0, 1.0]."""
        rel = RelacionDocumentalCreate(
            iddocumentoorigen=uuid4(),
            iddocumentodestino=uuid4(),
            nombretiporelacion="Deroga",
            confianza=0.95,
        )
        self.assertEqual(rel.confianza, 0.95)

        with self.assertRaises(PydanticValidationError):
            RelacionDocumentalCreate(
                iddocumentoorigen=uuid4(),
                iddocumentodestino=uuid4(),
                confianza=1.5,
            )

        with self.assertRaises(PydanticValidationError):
            RelacionDocumentalOut(
                idrelacion=1,
                iddocumentoorigen=uuid4(),
                iddocumentodestino=uuid4(),
                idtiporelacion=1,
                idrespaldolegal=1,
                idfuentedeteccion=1,
                fechaefecto=date(2025, 1, 1),
                confianza=-0.2,
                verificada=True,
                textoevidencia="Evidencia",
            )

    def test_12_relacion_documental_delete_contract(self):
        """Verifica contrato de payload para eliminación de relación jurídica por idrelacion o par de documentos."""
        del_by_id = RelacionDocumentalDelete(idrelacion=42)
        self.assertEqual(del_by_id.idrelacion, 42)

        orig_id = uuid4()
        dest_id = uuid4()
        del_by_pair = RelacionDocumentalDelete(
            iddocumentoorigen=orig_id,
            iddocumentodestino=dest_id,
            idtiporelacion=2
        )
        self.assertEqual(del_by_pair.iddocumentoorigen, orig_id)
        self.assertEqual(del_by_pair.iddocumentodestino, dest_id)

    def test_13_normalize_s3_key_offloading(self):
        """Verifica la normalización de rutas S3 para el microservicio firmador."""
        self.assertEqual(
            normalize_s3_key("s3://giru-normativas-usm/raw/uploads/064_2016_DECRETO.pdf"),
            "raw/uploads/064_2016_DECRETO.pdf",
        )
        self.assertEqual(
            normalize_s3_key("/raw/uploads/reglamento_general.pdf"),
            "raw/uploads/reglamento_general.pdf",
        )

    async def test_14_get_signed_url_success_and_token_forwarding(self):
        """Verifica caso exitoso (HTTP 200) de firma temporal con reenvío de Bearer token."""
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "url": "https://giru-bucket.s3.amazonaws.com/raw/uploads/doc.pdf?X-Amz-Expires=600",
            "expires_in": 600,
        }

        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            res = await get_signed_url("s3://bucket/raw/uploads/doc.pdf", "jwt-token-usm")
            self.assertEqual(res["expires_in"], 600)
            mock_post.assert_awaited_once_with(
                "https://signer.giru.usm.cl/firmar",
                json={"key": "raw/uploads/doc.pdf"},
                headers={"Authorization": "Bearer jwt-token-usm"},
            )

    async def test_15_get_signed_url_missing_configuration_503(self):
        """Verifica HTTP 503 cuando el microservicio firmador no tiene URL configurada."""
        with patch.object(settings, "DOCUMENT_SIGNER_URL", ""):
            with self.assertRaises(HTTPException) as ctx:
                await get_signed_url("raw/uploads/doc.pdf", "jwt-token-usm")
            self.assertEqual(ctx.exception.status_code, 503)

    async def test_16_get_signed_url_token_expired_401(self):
        """Verifica traducción semántica de token expirado o inválido (HTTP 401)."""
        mock_response = MagicMock(status_code=401)
        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with self.assertRaises(HTTPException) as ctx:
                await get_signed_url("raw/uploads/doc.pdf", "token-expirado")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Sesion expirada", ctx.exception.detail)

    async def test_17_get_signed_url_file_not_found_404(self):
        """Verifica traducción semántica de archivo inexistente en S3 (HTTP 404)."""
        mock_response = MagicMock(status_code=404)
        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with self.assertRaises(HTTPException) as ctx:
                await get_signed_url("raw/uploads/inexistente.pdf", "jwt-token-usm")
            self.assertEqual(ctx.exception.status_code, 404)

    async def test_18_get_signed_url_invalid_format_422(self):
        """Verifica traducción semántica de formato no visualizable (400 -> HTTP 422)."""
        mock_response = MagicMock(status_code=400)
        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with self.assertRaises(HTTPException) as ctx:
                await get_signed_url("raw/uploads/archivo.exe", "jwt-token-usm")
            self.assertEqual(ctx.exception.status_code, 422)

    async def test_19_get_signed_url_network_and_upstream_error_502(self):
        """Verifica traducción de errores de conexión y fallos no controlados del Signer a HTTP 502."""
        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            # Caso 1: Error de red / timeout de conexión
            mock_post.side_effect = httpx.ConnectError("Connection timeout to Signer")
            with self.assertRaises(HTTPException) as ctx_net:
                await get_signed_url("raw/uploads/doc.pdf", "jwt-token-usm")
            self.assertEqual(ctx_net.exception.status_code, 502)

            # Caso 2: Error 500 del servicio firmador
            mock_post.side_effect = None
            mock_post.return_value = MagicMock(status_code=500)
            with self.assertRaises(HTTPException) as ctx_up:
                await get_signed_url("raw/uploads/doc.pdf", "jwt-token-usm")
            self.assertEqual(ctx_up.exception.status_code, 502)


# ==============================================================================
# Suite 3: Orquestación de Búsqueda, Reglas del DBA y Fallback (RF-04, RF-05, RF-08, RNF-03)
# ==============================================================================
class TestSuite3SearchServiceOrchestrationAndFallback(unittest.IsolatedAsyncioTestCase):
    """Suite 3: Enrutador adaptativo en 3 etapas, reglas del DBA y Fallback en cascada."""

    async def asyncSetUp(self):
        self.service = SearchService()
        self.service.doc_repo = MagicMock()
        self.service.doc_repo.lexical_search = AsyncMock(return_value=[])
        self.service.doc_repo.filter_only_search = AsyncMock(return_value=([], 0))
        self.service.ai_service = MagicMock()
        self.service.ai_service.search = AsyncMock()

    async def test_20_autocomplete_dba_rule_1_min_3_chars(self):
        """Verifica Regla 1 del DBA: menos de 3 caracteres tras '#' no consulta PostgreSQL (evita Seq Scan)."""
        self.service.doc_repo.get_lexical_suggestions = AsyncMock()

        resp_short = await self.service.get_autocomplete_suggestions("#ar", limit=10)
        self.assertTrue(resp_short.is_lexical)
        self.assertEqual(resp_short.suggestions, [])
        self.service.doc_repo.get_lexical_suggestions.assert_not_awaited()

        resp_non_hash = await self.service.get_autocomplete_suggestions("arancel", limit=10)
        self.assertFalse(resp_non_hash.is_lexical)
        self.assertEqual(resp_non_hash.suggestions, [])
        self.service.doc_repo.get_lexical_suggestions.assert_not_awaited()

    async def test_21_autocomplete_dba_rule_2_clamp_limit_10(self):
        """Verifica Regla 2 del DBA: el límite de sugerencias se acota estrictamente a 10."""
        self.service.doc_repo.get_lexical_suggestions = AsyncMock(
            return_value=[
                {
                    "documentid": str(uuid4()),
                    "numero": "064/2016",
                    "titulo": "Reglamento de Aranceles",
                    "nommetadato": "DECRETO-064-2016",
                    "matched_field": "titulo",
                    "suggestion": "Reglamento de Aranceles",
                }
            ]
        )

        resp = await self.service.get_autocomplete_suggestions("#arancel", limit=50)
        self.assertTrue(resp.is_lexical)
        self.assertEqual(len(resp.suggestions), 1)
        self.service.doc_repo.get_lexical_suggestions.assert_awaited_once_with(
            term="arancel", limit=10
        )

    async def test_22_autocomplete_dba_rule_clamp_minimum_limit_1(self):
        """Verifica que límites negativos o 0 en autocompletado se acoten a un mínimo de 1."""
        self.service.doc_repo.get_lexical_suggestions = AsyncMock(return_value=[])

        resp = await self.service.get_autocomplete_suggestions("#arancel", limit=-5)
        self.assertTrue(resp.is_lexical)
        self.service.doc_repo.get_lexical_suggestions.assert_awaited_once_with(
            term="arancel", limit=1
        )

    async def test_23_search_stage_1_lexical_trigram_routing(self):
        """Verifica Etapa 1: consultas con '#' se enrutan al índice GIN de trigramas sin llamar a IA."""
        doc_uuid = uuid4()
        self.service.doc_repo.lexical_search = AsyncMock(
            return_value=(
                [
                    {
                        "iddocumento": doc_uuid,
                        "numero": "064/2016",
                        "titulo": "Reglamento de Aranceles",
                        "nommetadato": "DEC-064-2016",
                        "tipodocumento": "Decreto",
                        "estadovigencia": "Vigente",
                        "sedes": ["Casa Central Valparaíso"],
                        "categorias": ["Aranceles"],
                    }
                ],
                1,
            )
        )
        self.service.ai_service.search = AsyncMock()

        req = SearchRequest(
            query="#arancel",
            filters=SearchFilters(idestadovigencia=1),
            page=1,
            page_size=20,
        )
        resp = await self.service.search(req)

        self.assertEqual(resp.total, 1)
        self.assertEqual(resp.results[0].titulo, "Reglamento de Aranceles")
        self.service.doc_repo.lexical_search.assert_awaited_once_with(
            query_text="arancel",
            filters={"idestadovigencia": 1},
            page=1,
            page_size=20,
        )
        self.service.ai_service.search.assert_not_awaited()

    async def test_24_search_stage_1_hash_without_term_routes_to_filter_only(self):
        """Verifica que consultas con solo '#' sin término enruten directamente a búsqueda filtrada."""
        self.service.doc_repo.filter_only_search = AsyncMock(return_value=([], 0))
        self.service.doc_repo.lexical_search = AsyncMock()
        self.service.ai_service.search = AsyncMock()

        req = SearchRequest(
            query="#    ",
            filters=SearchFilters(idestadovigencia=1),
            page=1,
            page_size=20
        )
        resp = await self.service.search(req)

        self.assertEqual(resp.total, 0)
        self.service.doc_repo.filter_only_search.assert_awaited_once_with(
            filters={"idestadovigencia": 1},
            page=1,
            page_size=20
        )
        self.service.doc_repo.lexical_search.assert_not_awaited()
        self.service.ai_service.search.assert_not_awaited()

    async def test_25_search_empty_query_routes_to_filter_only(self):
        """Verifica que consultas vacías o de puros espacios no llamen a IA y enruten a filter_only_search."""
        self.service.doc_repo.filter_only_search = AsyncMock(return_value=([], 0))
        self.service.ai_service.search = AsyncMock()

        req = SearchRequest(
            query="   ",
            filters=SearchFilters(idtipodocumento=2),
            page=2,
            page_size=15
        )
        resp = await self.service.search(req)

        self.assertEqual(resp.total, 0)
        self.service.doc_repo.filter_only_search.assert_awaited_once_with(
            filters={"idtipodocumento": 2},
            page=2,
            page_size=15
        )
        self.service.ai_service.search.assert_not_awaited()

    async def test_26_search_stage_2_hybrid_semantic_and_faceted_cross(self):
        """Verifica Etapa 2: búsqueda semántica IA + normalización (.md/.pdf) + cruce facetado en BD y orden por score."""
        self.service.ai_service.search = AsyncMock(
            return_value=AISearchResponse(
                consulta="suspensión de estudios",
                resultados=[
                    AISearchResult(
                        documento="Decreto-Becas.pdf",
                        puntaje=0.78,
                        entidades=["Becas"],
                    ),
                    AISearchResult(
                        documento="Reglamento-Estudiantil.md",
                        puntaje=0.94,
                        entidades=["Suspensión", "Retiro Temporal"],
                    ),
                ],
            )
        )
        self.service.doc_repo.filter_only_search = AsyncMock(
            return_value=[
                {
                    "iddocumento": uuid4(),
                    "numero": "010/2022",
                    "titulo": "Decreto-Becas",
                    "nommetadato": "DEC-010-2022",
                    "tipodocumento": "Decreto",
                    "estadovigencia": "Vigente",
                },
                {
                    "iddocumento": uuid4(),
                    "numero": "001/2023",
                    "titulo": "Reglamento-Estudiantil",
                    "nommetadato": "REG-001-2023",
                    "tipodocumento": "Reglamento",
                    "estadovigencia": "Vigente",
                },
            ]
        )

        req = SearchRequest(
            query="suspensión de estudios",
            filters=SearchFilters(idestadovigencia=1, idrecintouniversitario=[1]),
            page=1,
            page_size=10,
        )
        resp = await self.service.search(req)

        self.assertEqual(resp.total, 2)
        self.assertEqual(resp.results[0].titulo, "Reglamento-Estudiantil")
        self.assertEqual(resp.results[0].score, 0.94)
        self.assertEqual(resp.results[0].entidades, ["Suspensión", "Retiro Temporal"])
        self.assertEqual(resp.results[1].titulo, "Decreto-Becas")
        self.assertEqual(resp.results[1].score, 0.78)

        called_kwargs = self.service.doc_repo.filter_only_search.call_args.kwargs
        self.assertEqual(called_kwargs["titles"], ["Decreto-Becas", "Reglamento-Estudiantil"])
        self.assertEqual(
            called_kwargs["filters"],
            {"idestadovigencia": 1, "idrecintouniversitario": [1]},
        )

    async def test_27_search_stage_2_semantic_ai_empty_results_fallback(self):
        """Verifica que si la IA responde sin resultados, se active Fallback a búsqueda léxica en BD."""
        self.service.ai_service.search = AsyncMock(
            return_value=AISearchResponse(consulta="concepto raro", resultados=[])
        )
        self.service.doc_repo.lexical_search = AsyncMock(return_value=[])

        req = SearchRequest(query="concepto raro", filters=SearchFilters(idtipodocumento=1), page=1, page_size=20)
        resp = await self.service.search(req)

        self.assertEqual(resp.total, 0)
        self.service.doc_repo.lexical_search.assert_called()

    async def test_28_search_stage_3_cascade_fallback_on_ai_timeout(self):
        """Verifica Etapa 3 (RNF-03): ante caída o timeout de GIRU-IA, activa Fallback automático a búsqueda léxica en BD."""
        doc_uuid = uuid4()
        self.service.ai_service.search = AsyncMock(
            side_effect=HTTPException(status_code=503, detail="Servicio de IA no disponible")
        )
        self.service.doc_repo.lexical_search = AsyncMock(
            return_value=[
                {
                    "iddocumento": doc_uuid,
                    "numero": "045/2021",
                    "titulo": "Reglamento Orgánico USM",
                    "nommetadato": "REG-045-2021",
                    "tipodocumento": "Reglamento",
                    "estadovigencia": "Vigente",
                }
            ]
        )

        req = SearchRequest(
            query="consulta cuando IA está caída",
            filters=SearchFilters(idtipodocumento=2),
            page=1,
            page_size=20,
        )
        resp = await self.service.search(req)

        self.assertEqual(resp.total, 1)
        self.assertEqual(resp.results[0].titulo, "Reglamento Orgánico USM")
        self.service.doc_repo.lexical_search.assert_called()

    async def test_29_search_service_get_filter_options_delegation(self):
        """Verifica delegación canónica de get_filter_options con flag de tipos activos."""
        self.service.doc_repo.get_filter_options = AsyncMock(return_value=MagicMock())
        await self.service.get_filter_options()
        self.service.doc_repo.get_filter_options.assert_awaited_once_with(
            only_active_tipos_documento=True
        )

    def test_29b_reciprocal_rank_fusion_math(self):
        """Verifica el cálculo de RRF (k=60) y priorización de documentos presentes en ambos motores."""
        from app.services.search_service import apply_reciprocal_rank_fusion
        doc_lex_1 = {"document_id": "1", "titulo": "Doc 1"}
        doc_lex_2 = {"document_id": "2", "titulo": "Doc 2"}
        doc_sem_2 = {"document_id": "2", "titulo": "Doc 2"}
        doc_sem_3 = {"document_id": "3", "titulo": "Doc 3"}

        # Doc 2 en ambas fuentes -> Rank 1 en resultado fusionado con score más alto
        fused = apply_reciprocal_rank_fusion(sparse_docs=[doc_lex_1, doc_lex_2], dense_docs=[doc_sem_2, doc_sem_3])
        self.assertEqual(fused[0]["document_id"], "2")
        self.assertGreater(fused[0]["score"], fused[1]["score"])
        self.assertLessEqual(fused[0]["score"], 1.0)
        self.assertEqual(len(fused), 3)


# ==============================================================================
# Suite 4: Middlewares, Mapeo Semántico de Excepciones y Trazabilidad (RF-08, RNF-04, RNF-05)
# ==============================================================================
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


# ==============================================================================
# Suite 5: Orquestación del Servicio de Documentos y Linaje (RF-06, RF-07)
# ==============================================================================
class TestSuite5DocumentServiceOrchestration(unittest.IsolatedAsyncioTestCase):
    """Suite 5: Orquestación de DocumentService y gestión de relaciones documentales."""

    async def asyncSetUp(self):
        self.service = DocumentService()
        self.service.doc_repo = MagicMock()
        self.service.rel_repo = MagicMock()

    async def test_35_document_service_update_and_toggle_active(self):
        """Verifica que update_document y toggle_active deleguen al repositorio correspondiente."""
        self.service.doc_repo.update = AsyncMock(return_value={"id": "doc-1", "titulo": "Actualizado"})
        self.service.doc_repo.toggle_active = AsyncMock(return_value={"id": "doc-1", "isactive": False})

        upd = DocumentoUpdate(titulo="Actualizado")
        res_update = await self.service.update_document("doc-1", upd)
        self.assertEqual(res_update["titulo"], "Actualizado")
        self.service.doc_repo.update.assert_awaited_once_with("doc-1", upd)

        res_toggle = await self.service.toggle_active("doc-1")
        self.assertFalse(res_toggle["isactive"])
        self.service.doc_repo.toggle_active.assert_awaited_once_with("doc-1")

    async def test_36_document_service_raw_detail(self):
        """Verifica que get_raw_detail invoque fn_obtener_documento_detalle mediante el repositorio."""
        self.service.doc_repo.get_raw_detail = AsyncMock(return_value={"iddocumento": "doc-1", "raw": True})
        res = await self.service.get_raw_detail("doc-1")
        self.assertTrue(res["raw"])
        self.service.doc_repo.get_raw_detail.assert_awaited_once_with("doc-1")

    async def test_37_document_service_relation_crud_and_lineage(self):
        """Verifica operaciones CRUD de relaciones jurídicas y trazabilidad del linaje."""
        self.service.rel_repo.create_via_sp = AsyncMock(return_value={"idrelacion": 10})
        self.service.rel_repo.delete_via_sp = AsyncMock(return_value={"deleted": True})
        self.service.rel_repo.get_document_lineage = AsyncMock(return_value={"origen": [], "destino": []})

        # Crear relación
        rel_data = RelacionDocumentalCreate(
            iddocumentoorigen=uuid4(),
            iddocumentodestino=uuid4(),
            nombretiporelacion="Deroga",
            confianza=0.9
        )
        res_create = await self.service.create_or_update_relation(rel_data)
        self.assertEqual(res_create["idrelacion"], 10)
        self.service.rel_repo.create_via_sp.assert_awaited_once_with(rel_data.model_dump())

        # Eliminar relación
        del_data = RelacionDocumentalDelete(idrelacion=10)
        res_del = await self.service.delete_relation(del_data)
        self.assertTrue(res_del["deleted"])
        self.service.rel_repo.delete_via_sp.assert_awaited_once_with(del_data.model_dump())

        # Linaje
        doc_id = uuid4()
        lineage = await self.service.get_document_lineage(doc_id)
        self.assertIn("origen", lineage)
        self.service.rel_repo.get_document_lineage.assert_awaited_once_with(doc_id)


if __name__ == "__main__":
    t0 = time.perf_counter()
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f"\nTiempo total de ejecución de la suite ({result.testsRun} pruebas): {elapsed_ms:.2f} ms")
    sys.exit(0 if result.wasSuccessful() else 1)