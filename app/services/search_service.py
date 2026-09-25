from app.models.search_models import SearchRequest, SearchResponse, SearchResultItem, FilterOptions
from app.services.retrieval_service import RetrievalService
from app.repositories.document_repository import DocumentRepository


class SearchService:
    def __init__(self):
        self.retrieval = RetrievalService()
        self.doc_repo = DocumentRepository()

    async def search(self, request: SearchRequest) -> SearchResponse:
        # Construir dict de filtros solo con los valores que el usuario seleccionó
        filters = {k: v for k, v in request.filters.model_dump().items() if v is not None}

        results = await self.retrieval.retrieve(
            query=request.query,
            top_k=request.page_size * request.page,
            filters=filters if filters else None,
        )

        start = (request.page - 1) * request.page_size
        paginated = results[start: start + request.page_size]

        return SearchResponse(
            query=request.query,
            total=len(results),
            page=request.page,
            page_size=request.page_size,
            results=[
                SearchResultItem(
                    document_id=r.document_id,
                    numero=r.numero if hasattr(r, 'numero') else "",
                    titulo=r.title if hasattr(r, 'title') else r.titulo if hasattr(r, 'titulo') else "",
                    nom_meta_dato=r.nom_meta_dato if hasattr(r, 'nom_meta_dato') else "",
                    tipo_documento=r.tipo_documento if hasattr(r, 'tipo_documento') else None,
                    tipo_decision=r.tipo_decision if hasattr(r, 'tipo_decision') else None,
                    estado_vigencia=r.estado_vigencia if hasattr(r, 'estado_vigencia') else None,
                    num_acuerdo=r.num_acuerdo if hasattr(r, 'num_acuerdo') else None,
                    num_sesion=r.num_sesion if hasattr(r, 'num_sesion') else None,
                    creacion=r.creacion if hasattr(r, 'creacion') else None,
                    derogacion=r.derogacion if hasattr(r, 'derogacion') else None,
                    aplicacion_inmediata=r.aplicacion_inmediata if hasattr(r, 'aplicacion_inmediata') else None,
                    sedes=r.sedes if hasattr(r, 'sedes') else [],
                    categorias=r.categorias if hasattr(r, 'categorias') else [],
                    score=r.score,
                    excerpt=r.excerpt,
                )
                for r in paginated
            ],
        )

    async def get_filter_options(self) -> FilterOptions:
        return await self.doc_repo.get_filter_options()
