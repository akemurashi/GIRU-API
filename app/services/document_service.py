"""Servicio para la orquestación y gestión de documentos normativos y sus relaciones.

Consume la capa de repositorios que ejecutan los procedimientos almacenados canónicos.
"""

import logging
from typing import Any
from uuid import UUID

from app.models.document_models import (
    DocumentoDetail,
    DocumentoUpdate,
    RelacionDocumentalCreate,
    RelacionDocumentalDelete,
)
from app.repositories.document_repository import DocumentRepository
from app.repositories.relacion_repository import RelacionRepository

logger = logging.getLogger(__name__)


class DocumentService(object):
    """Servicio para la orquestación y gestión de documentos normativos y sus relaciones."""

    def __init__(self) -> None:
        self.doc_repo = DocumentRepository()
        self.rel_repo = RelacionRepository()

    async def update_document(self, document_id: str, data: DocumentoUpdate) -> DocumentoDetail:
        """
        Actualiza un documento normativo mediante el procedimiento maestro
        sp_modificar_documento_completo.
        """
        return await self.doc_repo.update(document_id, data)

    async def toggle_active(self, document_id: str) -> DocumentoDetail:
        """
        Modifica la vigencia/visibilidad del documento mediante
        sp_modificar_documento_vigencia.
        """
        return await self.doc_repo.toggle_active(document_id)

    async def get_raw_detail(self, document_id: str) -> dict[str, Any]:
        """
        Retorna la representación canónica en JSONB del documento ejecutando
        la función fn_obtener_documento_detalle.
        """
        return await self.doc_repo.get_raw_detail(document_id)

    async def create_or_update_relation(self, data: RelacionDocumentalCreate) -> dict[str, Any]:
        """
        Crea o actualiza una relación jurídica entre documentos mediante
        sp_modificar_o_crear_relacion_documental.
        """
        return await self.rel_repo.create_via_sp(data.model_dump())

    async def delete_relation(self, data: RelacionDocumentalDelete) -> dict[str, Any]:
        """
        Elimina un vínculo del grafo relacional mediante
        sp_eliminar_relacion_documental.
        """
        return await self.rel_repo.delete_via_sp(data.model_dump())

    async def get_document_lineage(self, document_id: UUID | str) -> dict[str, Any]:
        """
        Retorna el linaje documental completo (relaciones de origen y destino).
        """
        return await self.rel_repo.get_document_lineage(document_id)
