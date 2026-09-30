from app.models.search_models import SearchRequest, SearchResponse, SearchResultItem, FilterOptions
#from app.services.retrieval_service import RetrievalService
from app.repositories.document_repository import DocumentRepository


class SearchService:
    def __init__(self):
        #self.retrieval = RetrievalService()
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
                    documentid=r.document_id,
                    numero=getattr(r, 'numero', ''),
                    titulo=r.title,
                    nommetadato=getattr(r, 'nommetadato', ''),
                    tipodocumento=getattr(r, 'tipodocumento', None),
                    tipodecision=getattr(r, 'tipodecision', None),
                    estadovigencia=getattr(r, 'estadovigencia', None),
                    numacuerdo=getattr(r, 'numacuerdo', None),
                    numsesion=getattr(r, 'numsesion', None),
                    creacion=getattr(r, 'creacion', None),
                    derogacion=getattr(r, 'derogacion', None),
                    aplicacioninmediata=getattr(r, 'aplicacioninmediata', None),
                    sedes=getattr(r, 'sedes', []),
                    categorias=getattr(r, 'categorias', []),
                    score=r.score,
                    excerpt=r.excerpt,
                )
                for r in paginated
            ],
        )

    async def get_filter_options(self) -> FilterOptions:
        return await self.doc_repo.get_filter_options()
