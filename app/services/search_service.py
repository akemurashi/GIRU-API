import logging
from app.models.search_models import SearchRequest, SearchResponse, SearchResultItem, FilterOptions
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
        
        results_data = []
        is_processed = False
        raw_query = request.query or ""
        trimmed_query = raw_query.strip()

        # CASO 1: Búsqueda Léxica (si la consulta inicia con '#')
        if trimmed_query.startswith("#"):
            lexical_term = trimmed_query.lstrip("#").strip()
            if lexical_term:
                results_data = await self.doc_repo.lexical_search(
                    query_text=lexical_term,
                    top_k=50,
                    filters=filters if filters else None
                )
                is_processed = True
            else:
                # Si solo se ingresó '#' sin texto, devolver resultados filtrados normales
                results_data = await self.doc_repo.filter_only_search(
                    top_k=50,
                    filters=filters if filters else None
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
                        "entidades": r.entidades
                    }
                
                if ai_results_map:
                    raw_docs = await self.doc_repo.filter_only_search(
                        top_k=50,
                        filters=filters if filters else None,
                        titles=[item["title"] for item in ai_results_map.values()]
                    )
                    
                    for doc in raw_docs:
                        doc_title_key = (doc.get("titulo") or "").strip().lower()
                        if doc_title_key in ai_results_map:
                            doc["score"] = ai_results_map[doc_title_key]["score"]
                            doc["entidades"] = ai_results_map[doc_title_key]["entidades"]
                            results_data.append(doc)
                    
                    # Ordenar por score de similitud de IA en orden descendente
                    results_data.sort(key=lambda x: x["score"], reverse=True)
                    is_processed = True
            except Exception as e:
                logger.warning(f"Error en la busqueda IA, cayendo a DB. Detalle: {e}")

        # CASO 3: Fallback a búsqueda solo por base de datos (si IA falló, devolvió vacío, o consulta vacía)
        if not is_processed:
            results_data = await self.doc_repo.filter_only_search(
                top_k=50,
                filters=filters if filters else None
            )

        total = len(results_data)
        start = (request.page - 1) * request.page_size
        paginated = results_data[start: start + request.page_size]

        return SearchResponse(
            query=request.query,
            total=total,
            page=request.page,
            page_size=request.page_size,
            results=[
                SearchResultItem(
                    documentid=r["document_id"],
                    numero=r.get("numero", ""),
                    titulo=r["titulo"],
                    nommetadato=r.get("nom_meta_dato", ""),
                    tipodocumento=r.get("tipodocumento"),
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
        return await self.doc_repo.get_filter_options()
