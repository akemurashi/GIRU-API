"""
Suite 3: Orquestación de Búsqueda, Reglas del DBA y Fallback en cascada (RF-04, RF-05, RF-08, RNF-03).
"""

import unittest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import HTTPException

import tests.base  # noqa: F401
from app.models.ai_models import (
    SearchResponse as AISearchResponse,
    SearchResult as AISearchResult,
)
from app.models.search_models import SearchFilters, SearchRequest
from app.services.search_service import SearchService, apply_reciprocal_rank_fusion


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
            page_size=20,
        )
        resp = await self.service.search(req)

        self.assertEqual(resp.total, 0)
        self.service.doc_repo.filter_only_search.assert_awaited_once_with(
            filters={"idestadovigencia": 1},
            page=1,
            page_size=20,
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
            page_size=15,
        )
        resp = await self.service.search(req)

        self.assertEqual(resp.total, 0)
        self.service.doc_repo.filter_only_search.assert_awaited_once_with(
            filters={"idtipodocumento": 2},
            page=2,
            page_size=15,
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


if __name__ == "__main__":
    unittest.main()
