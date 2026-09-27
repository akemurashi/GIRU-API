from app.repositories.vector_repository import VectorRepository
from app.repositories.document_repository import DocumentRepository
from app.ai.services.embedding_provider import EmbeddingProviderFactory
from app.core.config import settings


class RetrievalResult:
    def __init__(self, document_id: int, title: str, excerpt: str,
                 score: float, page: int | None = None, **kwargs):
        self.document_id = document_id
        self.title = title
        self.excerpt = excerpt
        self.score = score
        self.page = page
        # Store additional metadata fields
        self.numero = kwargs.get('numero', '')
        self.nommetadato = kwargs.get('nommetadato', '')
        self.tipodocumento = kwargs.get('tipodocumento')
        self.tipodecision = kwargs.get('tipodecision')
        self.estadovigencia = kwargs.get('estadovigencia')
        self.numacuerdo = kwargs.get('numacuerdo')
        self.numsesion = kwargs.get('numsesion')
        self.creacion = kwargs.get('creacion')
        self.derogacion = kwargs.get('derogacion')
        self.aplicacioninmediata = kwargs.get('aplicacioninmediata')
        self.sedes = kwargs.get('sedes', [])
        self.categorias = kwargs.get('categorias', [])


class RetrievalService:
    """
    Núcleo compartido entre search_service y answer_service.
    Vectoriza la query y busca los chunks más similares en pgvector.
    Los filtros se aplican como WHERE sobre metadata del documento.
    """

    def __init__(self):
        self.vector_repo = VectorRepository()
        self.doc_repo = DocumentRepository()
        self.embedding_provider = EmbeddingProviderFactory.get_provider()

    async def retrieve(
        self,
        query: str,
        top_k: int = settings.RETRIEVAL_TOP_K,
        filters: dict | None = None,
    ) -> list[RetrievalResult]:
        # If query is empty, use filter-only search on documento table (skip vector similarity)
        if not query or query.strip() == "":
            raw_results = await self.doc_repo.filter_only_search(
                top_k=top_k,
                filters=filters,
            )
        else:
            query_vector = await self.embedding_provider.embed(query)
            raw_results = await self.vector_repo.similarity_search(
                vector=query_vector,
                top_k=top_k,
                filters=filters,
            )
        
        return [
            RetrievalResult(
                document_id=r["document_id"],
                title=r["titulo"],
                excerpt=r["texto_fragmento"],
                score=r["score"],
                page=r.get("numero_pagina"),
                numero=r.get("numero", ""),
                nommetadato=r.get("nom_meta_dato", ""),
                tipodocumento=r.get("tipodocumento"),
                tipodecision=r.get("tipodecision"),
                estadovigencia=r.get("estadovigencia"),
                numacuerdo=r.get("numacuerdo"),
                numsesion=r.get("numsesion"),
                creacion=r.get("creacion"),
                derogacion=r.get("derogacion"),
                aplicacioninmediata=r.get("aplicacion_inmediata"),
            )
            for r in raw_results
        ]
