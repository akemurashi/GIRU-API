"""
Suite 5: Orquestación del Servicio de Documentos y Linaje (RF-06, RF-07).
"""

import unittest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import tests.base  # noqa: F401
from app.models.document_models import (
    DocumentoUpdate,
    RelacionDocumentalCreate,
    RelacionDocumentalDelete,
)
from app.services.document_service import DocumentService


class TestSuite5DocumentServiceOrchestration(unittest.IsolatedAsyncioTestCase):
    """Suite 5: Orquestación de DocumentService y gestión de relaciones documentales."""

    async def asyncSetUp(self):
        self.service = DocumentService()
        self.service.doc_repo = MagicMock()
        self.service.rel_repo = MagicMock()

    async def test_35_document_service_update_and_toggle_active(self):
        """Verifica que update_document y toggle_active deleguen al repositorio correspondiente."""
        self.service.doc_repo.update = AsyncMock(return_value={"id": "doc-1", "titulo": "Actualizado"})
        self.service.doc_repo.toggle_active = AsyncMock(return_value={"id": "doc-1", "isactive": False})

        upd = DocumentoUpdate(titulo="Actualizado")
        res_update = await self.service.update_document("doc-1", upd)
        self.assertEqual(res_update["titulo"], "Actualizado")
        self.service.doc_repo.update.assert_awaited_once_with("doc-1", upd)

        res_toggle = await self.service.toggle_active("doc-1")
        self.assertFalse(res_toggle["isactive"])
        self.service.doc_repo.toggle_active.assert_awaited_once_with("doc-1")

    async def test_36_document_service_raw_detail(self):
        """Verifica que get_raw_detail invoque fn_obtener_documento_detalle mediante el repositorio."""
        self.service.doc_repo.get_raw_detail = AsyncMock(return_value={"iddocumento": "doc-1", "raw": True})
        res = await self.service.get_raw_detail("doc-1")
        self.assertTrue(res["raw"])
        self.service.doc_repo.get_raw_detail.assert_awaited_once_with("doc-1")

    async def test_37_document_service_relation_crud_and_lineage(self):
        """Verifica operaciones CRUD de relaciones jurídicas y trazabilidad del linaje."""
        self.service.rel_repo.create_via_sp = AsyncMock(return_value={"idrelacion": 10})
        self.service.rel_repo.delete_via_sp = AsyncMock(return_value={"deleted": True})
        self.service.rel_repo.get_document_lineage = AsyncMock(return_value={"origen": [], "destino": []})

        # Crear relación
        rel_data = RelacionDocumentalCreate(
            iddocumentoorigen=uuid4(),
            iddocumentodestino=uuid4(),
            nombretiporelacion="Deroga",
            confianza=0.9
        )
        res_create = await self.service.create_or_update_relation(rel_data)
        self.assertEqual(res_create["idrelacion"], 10)
        self.service.rel_repo.create_via_sp.assert_awaited_once_with(rel_data.model_dump())

        # Eliminar relación
        del_data = RelacionDocumentalDelete(idrelacion=10)
        res_del = await self.service.delete_relation(del_data)
        self.assertTrue(res_del["deleted"])
        self.service.rel_repo.delete_via_sp.assert_awaited_once_with(del_data.model_dump())

        # Linaje
        doc_id = uuid4()
        lineage = await self.service.get_document_lineage(doc_id)
        self.assertIn("origen", lineage)
        self.service.rel_repo.get_document_lineage.assert_awaited_once_with(doc_id)


if __name__ == "__main__":
    unittest.main()
