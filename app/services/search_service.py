import asyncio
import inspect
import logging
from typing import Optional, List, Dict, Any, Union
from app.models.search_models import (
    SearchRequest, SearchResponse, SearchResultItem, FilterOptions,
    AutocompleteResponse, LexicalSuggestionItem
)
from app.repositories.document_repository import DocumentRepository
from app.services.external_ai_service import ExternalAIService
from app.models.ai_models import SearchRequest as AISearchRequest

logger = logging.getLogger(__name__)


def apply_reciprocal_rank_fusion(
    sparse_docs: List[Dict],
    dense_docs: List[Dict],
    k: int = 60,
    max_candidates: int = 100
) -> List[Dict]:
    """
    Combina los rankings de búsqueda dispersa (léxica) y densa (semántica) usando
    Reciprocal Rank Fusion (RRF):
        RRF_Score(d) = sum( 1 / (k + rank_m(d)) )
    Donde k=60 es la constante empírica estándar (Cormack et al., 2009).
    Normaliza el score a un rango [0.0, 1.0] basado en el máximo teórico para 2 rankers: 2 / (k + 1).
    """
    scores: Dict[str, float] = {}
    doc_map: Dict[str, Dict] = {}

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
            # Si el documento ya venía de la búsqueda léxica, enriquecemos con entidades y excerpt de IA
            if doc.get("entidades"):
                doc_map[doc_id]["entidades"] = doc["entidades"]
            if doc.get("texto_fragmento") and not doc_map[doc_id].get("texto_fragmento"):
                doc_map[doc_id]["texto_fragmento"] = doc["texto_fragmento"]

    max_possible_score = 2.0 / (k + 1)
    fused_docs: List[Dict] = []
    for doc_id, rrf_score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        doc = doc_map[doc_id]
        normalized_score = round(min(1.0, rrf_score / max_possible_score), 4)
        doc["score"] = normalized_score
        fused_docs.append(doc)

    return fused_docs[:max_candidates]


async def _safe_eval(target: Any) -> Any:
    """Evalúa de forma segura un coroutine o retorna el valor directo si no es awaitable."""
    if inspect.isawaitable(target):
        return await target
    return target


class SearchService:
    def __init__(self):
        self.doc_repo = DocumentRepository()
        self.ai_service = ExternalAIService()

    async def search(self, request: SearchRequest) -> SearchResponse:
        # Construir dict de filtros solo con los valores que el usuario seleccionó
        filters = {k: v for k, v in request.filters.model_dump().items() if v is not None}
        
        total = 0
        paginated = []
        is_processed = False
        raw_query = request.query or ""
        trimmed_query = raw_query.strip()

        # CASO 1: Búsqueda Léxica Directa (si la consulta inicia con '#')
        if trimmed_query.startswith("#"):
            lexical_term = trimmed_query.lstrip("#").strip()
            if lexical_term:
                res = await _safe_eval(self.doc_repo.lexical_search(
                    query_text=lexical_term,
                    filters=filters if filters else None,
                    page=request.page,
                    page_size=request.page_size
                ))
                if isinstance(res, tuple):
                    paginated, total = res
                else:
                    paginated = res or []
                    total = len(paginated)
                is_processed = True
            else:
                # Si solo se ingresó '#' sin texto, devolver resultados filtrados normales
                res = await _safe_eval(self.doc_repo.filter_only_search(
                    filters=filters if filters else None,
                    page=request.page,
                    page_size=request.page_size
                ))
                if isinstance(res, tuple):
                    paginated, total = res
                else:
                    paginated = res or []
                    total = len(paginated)
                is_processed = True

        # CASO 2: Búsqueda Híbrida Pura (Dense + Sparse + RRF) cuando NO inicia con '#'
        elif trimmed_query:
            try:
                # Disparar concurrentemente la búsqueda léxica en BD y la semántica en IA
                lexical_task = self.doc_repo.lexical_search(
                    query_text=trimmed_query,
                    filters=filters if filters else None,
                    top_k=50
                )
                ai_task = self.ai_service.search(AISearchRequest(consulta=trimmed_query, k=50))

                lexical_res, ai_res = await asyncio.gather(
                    _safe_eval(lexical_task),
                    _safe_eval(ai_task),
                    return_exceptions=True
                )

                sparse_docs: List[Dict] = []
                sparse_total: Optional[int] = None
                if isinstance(lexical_res, (list, tuple)):
                    if isinstance(lexical_res, tuple):
                        sparse_docs = lexical_res[0] or []
                        sparse_total = lexical_res[1]
                    else:
                        sparse_docs = lexical_res or []
                        sparse_total = len(sparse_docs)
                elif isinstance(lexical_res, Exception):
                    logger.warning(f"Error en búsqueda léxica concurrente: {lexical_res}")

                dense_docs: List[Dict] = []
                # Validar si el servicio de IA respondió exitosamente
                if not isinstance(ai_res, Exception) and getattr(ai_res, "resultados", None):
                    ai_results_map = {}
                    for r in ai_res.resultados:
                        name = r.documento.strip()
                        if name.lower().endswith('.md'):
                            name = name[:-3].strip()
                        elif name.lower().endswith('.pdf'):
                            name = name[:-4].strip()

                        key = name.lower()
                        ai_results_map[key] = {
                            "title": name,
                            "score": r.puntaje,
                            "entidades": getattr(r, "entidades", None) or []
                        }

                    if ai_results_map:
                        raw_semantic_docs = await _safe_eval(self.doc_repo.filter_only_search(
                            top_k=50,
                            filters=filters if filters else None,
                            titles=[item["title"] for item in ai_results_map.values()]
                        ))
                        raw_semantic_list = (
                            raw_semantic_docs[0] if isinstance(raw_semantic_docs, tuple) else (raw_semantic_docs or [])
                        )

                        for doc in raw_semantic_list:
                            doc_title_key = (doc.get("titulo") or "").strip().lower()
                            if doc_title_key in ai_results_map:
                                doc_copy = dict(doc)
                                doc_copy["score"] = ai_results_map[doc_title_key]["score"]
                                doc_copy["entidades"] = ai_results_map[doc_title_key]["entidades"]
                                dense_docs.append(doc_copy)

                        # Ordenar los candidatos semánticos por su puntaje original
                        dense_docs.sort(key=lambda x: x.get("score", 0.0), reverse=True)
                else:
                    if isinstance(ai_res, Exception):
                        logger.warning(f"Fallo o timeout en servicio de IA ({ai_res}). Activando Fallback Léxico en BD.")
                    else:
                        logger.info("IA devolvió 0 resultados. Activando Fallback Léxico en BD.")

                # Fusión Híbrida RRF o Fallback Léxico
                if dense_docs and sparse_docs:
                    fused_results = apply_reciprocal_rank_fusion(
                        sparse_docs=sparse_docs,
                        dense_docs=dense_docs
                    )
                    total = len(fused_results)
                    start = (request.page - 1) * request.page_size
                    paginated = fused_results[start : start + request.page_size]
                    is_processed = True
                elif dense_docs:
                    # Solo la IA aportó resultados
                    total = len(dense_docs)
                    start = (request.page - 1) * request.page_size
                    paginated = dense_docs[start : start + request.page_size]
                    is_processed = True
                elif sparse_docs:
                    # Fallback léxico: IA falló o dio 0, usamos los resultados léxicos obtenidos
                    total = sparse_total if sparse_total is not None else len(sparse_docs)
                    start = (request.page - 1) * request.page_size
                    paginated = sparse_docs[start : start + request.page_size]
                    is_processed = True

            except Exception as e:
                logger.error(f"Error inesperado en orquestación de búsqueda híbrida: {e}. Activando Fallback Léxico.", exc_info=True)

        # CASO 3: Fallback final a base de datos (si la híbrida no produjo resultados o query vacía)
        if not is_processed:
            if trimmed_query and not trimmed_query.startswith("#"):
                # Si había texto pero falló la concurrencia o no hubo candidatos previos, fallback a léxica
                res = await _safe_eval(self.doc_repo.lexical_search(
                    query_text=trimmed_query,
                    filters=filters if filters else None,
                    page=request.page,
                    page_size=request.page_size
                ))
                if isinstance(res, tuple):
                    paginated, total = res
                else:
                    paginated = res or []
                    total = len(paginated)
            else:
                # Si la consulta estaba vacía o era solo '#', buscar solo por filtros de catálogo
                res = await _safe_eval(self.doc_repo.filter_only_search(
                    filters=filters if filters else None,
                    page=request.page,
                    page_size=request.page_size
                ))
                if isinstance(res, tuple):
                    paginated, total = res
                else:
                    paginated = res or []
                    total = len(paginated)

        return SearchResponse(
            query=request.query,
            total=total,
            page=request.page,
            page_size=request.page_size,
            results=[
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
                    entidades=r.get("entidades", [])
                )
                for r in paginated
            ],
        )

    async def get_filter_options(self) -> FilterOptions:
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
                    suggestion=s["suggestion"]
                )
                for s in raw_suggestions
            ]
        )
