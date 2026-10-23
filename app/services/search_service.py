"""Servicio de búsqueda híbrida y autocompletado para el catálogo documental de GIRU."""

import asyncio
import inspect
import logging
from typing import Any

from app.models.ai_models import SearchRequest as AISearchRequest
from app.models.search_models import (
    AutocompleteResponse,
    FilterOptions,
    LexicalSuggestionItem,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.repositories.document_repository import DocumentRepository
from app.services.external_ai_service import ExternalAIService

logger = logging.getLogger(__name__)


def _merge_dense_metadata(existing_doc: dict[str, Any], dense_doc: dict[str, Any]) -> None:
    """Enriquece el documento existente con entidades y fragmentos semánticos."""
    if dense_doc.get("entidades"):
        existing_doc["entidades"] = dense_doc["entidades"]
    if dense_doc.get("texto_fragmento") and not existing_doc.get("texto_fragmento"):
        existing_doc["texto_fragmento"] = dense_doc["texto_fragmento"]


def _clean_doc_name(raw_name: str) -> str:
    """Elimina extensiones conocidas (.md, .pdf) del nombre de documento."""
    name = raw_name.strip()
    lower_name = name.lower()
    if lower_name.endswith(".md"):
        return name[:-3].strip()
    if lower_name.endswith(".pdf"):
        return name[:-4].strip()
    return name


def apply_reciprocal_rank_fusion(
    sparse_docs: list[dict[str, Any]],
    dense_docs: list[dict[str, Any]],
    k: int = 60,
    max_candidates: int = 100,
) -> list[dict[str, Any]]:
    """
    Combina los rankings de búsqueda dispersa (léxica) y densa (semántica) usando
    Reciprocal Rank Fusion (RRF):
        RRF_Score(d) = sum( 1 / (k + rank_m(d)) )
    Donde k=60 es la constante empírica estándar (Cormack et al., 2009).
    Normaliza el score a un rango [0.0, 1.0] basado en el máximo teórico para 2 rankers: 2 / (k + 1).
    """
    scores: dict[str, float] = {}
    doc_map: dict[str, dict[str, Any]] = {}

    # Rank léxico (1-indexed)
    for rank, doc in enumerate(sparse_docs, start=1):
        doc_id = str(doc.get("iddocumento") or doc.get("document_id"))
        scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank))
        if doc_id not in doc_map:
            doc_map[doc_id] = dict(doc)

    # Rank semántico (1-indexed)
    for rank, doc in enumerate(dense_docs, start=1):
        doc_id = str(doc.get("iddocumento") or doc.get("document_id"))
        scores[doc_id] = scores.get(doc_id, 0.0) + (1.0 / (k + rank))
        if doc_id not in doc_map:
            doc_map[doc_id] = dict(doc)
        else:
            _merge_dense_metadata(doc_map[doc_id], doc)

    max_possible_score = 2.0 / (k + 1)
    fused_docs: list[dict[str, Any]] = []
    for doc_id, rrf_score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        doc = doc_map[doc_id]
        normalized_score = round(min(1.0, rrf_score / max_possible_score), 4)
        doc["score"] = normalized_score
        fused_docs.append(doc)

    return fused_docs[:max_candidates]


async def _safe_eval(target: object) -> object:
    """Evalúa de forma segura un coroutine o retorna el valor directo si no es awaitable."""
    if inspect.isawaitable(target):
        return await target
    return target


class SearchService(object):
    """Servicio para orquestar la búsqueda documental léxica, híbrida y sugerencias."""

    def __init__(self) -> None:
        self.doc_repo = DocumentRepository()
        self.ai_service = ExternalAIService()

    @staticmethod
    def _parse_sparse_results(lexical_res: object) -> tuple[list[dict[str, Any]], int | None]:
        """Extrae la lista de documentos y el total de la respuesta de búsqueda léxica."""
        if isinstance(lexical_res, tuple):
            return lexical_res[0] or [], lexical_res[1]
        if isinstance(lexical_res, list):
            return lexical_res, len(lexical_res)
        if isinstance(lexical_res, Exception):
            logger.warning("Error en búsqueda léxica concurrente: %s", lexical_res)
        return [], None

    async def _build_dense_docs(
        self,
        ai_res: object,
        filters: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Construye y rankea los candidatos semánticos devueltos por el servicio de IA."""
        resultados = getattr(ai_res, "resultados", None)
        if not resultados:
            return []

        ai_results_map: dict[str, dict[str, Any]] = {}
        for r in resultados:
            name = _clean_doc_name(r.documento)
            key = name.lower()
            ai_results_map[key] = {
                "title": name,
                "score": r.puntaje,
                "entidades": getattr(r, "entidades", None) or [],
            }

        if not ai_results_map:
            return []

        raw_docs = await _safe_eval(self.doc_repo.filter_only_search(
            top_k=50,
            filters=filters,
            titles=[item["title"] for item in ai_results_map.values()],
        ))
        raw_list = raw_docs[0] if isinstance(raw_docs, tuple) else (raw_docs or [])

        dense_docs: list[dict[str, Any]] = []
        for doc in raw_list:
            doc_title_key = (doc.get("titulo") or "").strip().lower()
            if doc_title_key in ai_results_map:
                doc_copy = dict(doc)
                doc_copy["score"] = ai_results_map[doc_title_key]["score"]
                doc_copy["entidades"] = ai_results_map[doc_title_key]["entidades"]
                dense_docs.append(doc_copy)

        dense_docs.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return dense_docs

    @staticmethod
    def _paginate_hybrid_candidates(
        request: SearchRequest,
        sparse_docs: list[dict[str, Any]],
        dense_docs: list[dict[str, Any]],
        sparse_total: int | None,
    ) -> tuple[list[dict[str, Any]], int] | None:
        """Aplica RRF o selecciones individuales y pagina el resultado."""
        if dense_docs and sparse_docs:
            candidates = apply_reciprocal_rank_fusion(sparse_docs=sparse_docs, dense_docs=dense_docs)
            total = len(candidates)
        elif dense_docs:
            candidates = dense_docs
            total = len(dense_docs)
        elif sparse_docs:
            candidates = sparse_docs
            total = sparse_total if sparse_total is not None else len(sparse_docs)
        else:
            return None

        start = (request.page - 1) * request.page_size
        paginated = candidates[start : start + request.page_size]
        return paginated, total

    async def _handle_lexical_prefix(
        self,
        request: SearchRequest,
        filters: dict[str, Any] | None,
        query: str,
    ) -> tuple[list[dict[str, Any]], int]:
        """Maneja consultas directas con prefijo '#'."""
        lexical_term = query.lstrip("#").strip()
        if lexical_term:
            res = await _safe_eval(self.doc_repo.lexical_search(
                query_text=lexical_term,
                filters=filters,
                page=request.page,
                page_size=request.page_size,
            ))
        else:
            res = await _safe_eval(self.doc_repo.filter_only_search(
                filters=filters,
                page=request.page,
                page_size=request.page_size,
            ))

        if isinstance(res, tuple):
            return res[0] or [], res[1]
        paginated = res or []
        return paginated, len(paginated)

    async def _handle_hybrid_search(
        self,
        request: SearchRequest,
        filters: dict[str, Any] | None,
        query: str,
    ) -> tuple[list[dict[str, Any]], int] | None:
        """Ejecuta concurrentemente búsqueda léxica y semántica y las combina."""
        try:
            lexical_task = self.doc_repo.lexical_search(
                query_text=query,
                filters=filters,
                top_k=50,
            )
            ai_task = self.ai_service.search(AISearchRequest(consulta=query, k=50))

            lexical_res, ai_res = await asyncio.gather(
                _safe_eval(lexical_task),
                _safe_eval(ai_task),
                return_exceptions=True,
            )

            sparse_docs, sparse_total = self._parse_sparse_results(lexical_res)

            if isinstance(ai_res, Exception):
                logger.warning(
                    "Fallo o timeout en servicio de IA (%s). Activando Fallback Léxico en BD.",
                    ai_res,
                )
                dense_docs: list[dict[str, Any]] = []
            else:
                dense_docs = await self._build_dense_docs(ai_res, filters)
                if not dense_docs:
                    logger.info("IA devolvió 0 resultados. Activando Fallback Léxico en BD.")

            return self._paginate_hybrid_candidates(request, sparse_docs, dense_docs, sparse_total)

        except Exception as e:
            logger.exception(
                "Error inesperado en orquestación de búsqueda híbrida: %s. Activando Fallback Léxico.",
                e,
            )
            return None

    async def _handle_fallback_search(
        self,
        request: SearchRequest,
        filters: dict[str, Any] | None,
        query: str,
    ) -> tuple[list[dict[str, Any]], int]:
        """Fallback final cuando la búsqueda híbrida no entrega resultados o query vacía."""
        if query and not query.startswith("#"):
            res = await _safe_eval(self.doc_repo.lexical_search(
                query_text=query,
                filters=filters,
                page=request.page,
                page_size=request.page_size,
            ))
        else:
            res = await _safe_eval(self.doc_repo.filter_only_search(
                filters=filters,
                page=request.page,
                page_size=request.page_size,
            ))

        if isinstance(res, tuple):
            return res[0] or [], res[1]
        paginated = res or []
        return paginated, len(paginated)

    @staticmethod
    def _build_search_response(
        request: SearchRequest,
        paginated: list[dict[str, Any]],
        total: int,
    ) -> SearchResponse:
        """Construye el objeto de respuesta estructurado para el API de búsqueda."""
        results = [
            SearchResultItem(
                documentid=str(r.get("document_id") or r.get("iddocumento")),
                numero=r.get("numero", ""),
                titulo=r["titulo"],
                nommetadato=r.get("nom_meta_dato", "") or r.get("nommetadato", ""),
                tipodocumento=r.get("tipodocumento") or r.get("nombretipodocumento"),
                tipodecision=r.get("tipodecision"),
                estadovigencia=r.get("estadovigencia"),
                numacuerdo=r.get("numacuerdo"),
                numsesion=r.get("numsesion"),
                creacion=r.get("creacion"),
                derogacion=r.get("derogacion"),
                aplicacioninmediata=r.get("aplicacion_inmediata"),
                sedes=r.get("sedes", []),
                categorias=r.get("categorias", []),
                score=r.get("score", 1.0),
                excerpt=r.get("texto_fragmento") or r["titulo"],
                entidades=r.get("entidades", []),
            )
            for r in paginated
        ]
        return SearchResponse(
            query=request.query,
            total=total,
            page=request.page,
            page_size=request.page_size,
            results=results,
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Ejecuta la búsqueda multicanal (léxica, híbrida con RRF o por filtros)."""
        filters = {k: v for k, v in request.filters.model_dump().items() if v is not None} or None
        query = (request.query or "").strip()

        result = None
        if query.startswith("#"):
            result = await self._handle_lexical_prefix(request, filters, query)
        elif query:
            result = await self._handle_hybrid_search(request, filters, query)

        if result is None:
            result = await self._handle_fallback_search(request, filters, query)

        paginated, total = result
        return self._build_search_response(request, paginated, total)

    async def get_filter_options(self) -> FilterOptions:
        """Obtiene las opciones de filtro disponibles en el catálogo."""
        return await self.doc_repo.get_filter_options(only_active_tipos_documento=True)

    async def get_autocomplete_suggestions(self, raw_query: str, limit: int = 10) -> AutocompleteResponse:
        """
        Sugerencias de autocompletado exclusivas para búsqueda léxica (#).
        Busca coincidencias en 'titulo' y 'nommetadato' aprovechando el índice GIN con trigramas.
        """
        trimmed = (raw_query or "").strip()

        # Solo se autocompleta cuando se usa '#'
        if not trimmed.startswith("#"):
            return AutocompleteResponse(query=raw_query, is_lexical=False, suggestions=[])

        lexical_term = trimmed.lstrip("#").strip()

        # Regla 1 del DBA: Mínimo 3 caracteres para activar algoritmo de trigramas pg_trgm.
        # Con menos de 3 caracteres pg_trgm no genera trigramas suficientes y fuerza Seq Scan.
        if len(lexical_term) < 3:
            return AutocompleteResponse(query=raw_query, is_lexical=True, suggestions=[])

        # Regla 2 del DBA: Limitar máximo a 10 resultados para no saturar el motor
        clamped_limit = min(max(1, limit), 10)

        raw_suggestions = await self.doc_repo.get_lexical_suggestions(term=lexical_term, limit=clamped_limit)

        return AutocompleteResponse(
            query=raw_query,
            is_lexical=True,
            suggestions=[
                LexicalSuggestionItem(
                    documentid=s["documentid"],
                    numero=s["numero"],
                    titulo=s["titulo"],
                    nommetadato=s["nommetadato"],
                    matched_field=s["matched_field"],
                    suggestion=s["suggestion"],
                )
                for s in raw_suggestions
            ],
        )
