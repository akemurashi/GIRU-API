from app.repositories.vector_repository import VectorRepository
from app.ai.services.embedding_provider import EmbeddingProviderFactory
from app.core.config import settings


class RetrievalResult:
    def __init__(self, document_id: int, title: str, excerpt: str,
                 score: float, page: int | None = None):
        self.document_id = document_id
        self.title = title
        self.excerpt = excerpt
        self.score = score
        self.page = page


class RetrievalService:
    """
    Núcleo compartido entre search_service y answer_service.
    Vectoriza la query y busca los chunks más similares en pgvector.
    Los filtros se aplican como WHERE sobre metadata del documento.
    """

    def __init__(self):
        self.vector_repo = VectorRepository()
        self.embedding_provider = EmbeddingProviderFactory.get_provider()

    async def retrieve(
        self,
        query: str,
        top_k: int = settings.RETRIEVAL_TOP_K,
        filters: dict | None = None,
    ) -> list[RetrievalResult]:
        query_vector = await self.embedding_provider.embed(query)
        raw_results = await self.vector_repo.similarity_search(
            vector=query_vector,
            top_k=top_k,
            filters=filters,
        )
        return [
            RetrievalResult(
                document_id=r["document_id"],
                title=r["title"],
                excerpt=r["chunk_text"],
                score=r["score"],
                page=r.get("page"),
            )
            for r in raw_results
        ]
