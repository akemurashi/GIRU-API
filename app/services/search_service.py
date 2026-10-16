import logging
from app.models.search_models import (
    SearchRequest, SearchResponse, SearchResultItem, FilterOptions,
    AutocompleteResponse, LexicalSuggestionItem
)
from app.repositories.document_repository import DocumentRepository
from app.services.external_ai_service import ExternalAIService
from app.models.ai_models import SearchRequest as AISearchRequest

logger = logging.getLogger(__name__)

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

        # CASO 1: Búsqueda Léxica (si la consulta inicia con '#')
        if trimmed_query.startswith("#"):
            lexical_term = trimmed_query.lstrip("#").strip()
            if lexical_term:
                paginated, total = await self.doc_repo.lexical_search(
                    query_text=lexical_term,
                    filters=filters if filters else None,
                    page=request.page,
                    page_size=request.page_size
                )
                is_processed = True
            else:
                # Si solo se ingresó '#' sin texto, devolver resultados filtrados normales
                paginated, total = await self.doc_repo.filter_only_search(
                    filters=filters if filters else None,
                    page=request.page,
                    page_size=request.page_size
                )
                is_processed = True

        # CASO 2: Búsqueda Semántica con IA (cuando NO inicia con '#')
        elif trimmed_query:
            try:
                ai_req = AISearchRequest(consulta=trimmed_query, k=50)
                ai_resp = await self.ai_service.search(ai_req)
                
                ai_results_map = {}
                for r in ai_resp.resultados:
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
                    raw_docs = await self.doc_repo.filter_only_search(
                        top_k=50,
                        filters=filters if filters else None,
                        titles=[item["title"] for item in ai_results_map.values()]
                    )
                    
                    results_data = []
                    for doc in raw_docs:
                        doc_title_key = (doc.get("titulo") or "").strip().lower()
                        if doc_title_key in ai_results_map:
                            doc["score"] = ai_results_map[doc_title_key]["score"]
                            doc["entidades"] = ai_results_map[doc_title_key]["entidades"]
                            results_data.append(doc)
                    
                    # Ordenar por score de similitud de IA en orden descendente
                    results_data.sort(key=lambda x: x["score"], reverse=True)
                    total = len(results_data)
                    start = (request.page - 1) * request.page_size
                    paginated = results_data[start: start + request.page_size]
                    is_processed = True
            except Exception as e:
                logger.warning(f"Error en la busqueda IA, cayendo a DB. Detalle: {e}")

        # CASO 3: Fallback a búsqueda solo por base de datos (si IA falló, devolvió vacío, o consulta vacía)
        if not is_processed:
            paginated, total = await self.doc_repo.filter_only_search(
                filters=filters if filters else None,
                page=request.page,
                page_size=request.page_size
            )

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
