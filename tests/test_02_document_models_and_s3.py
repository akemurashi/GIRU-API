"""
Suite 2: Reglas de negocio de edición documental, linaje y Offloading S3 (RF-03, RF-07, RNF-01, RNF-04).
"""

from datetime import date
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
import httpx
from pydantic import ValidationError as PydanticValidationError

import tests.base  # noqa: F401
from app.core.config import settings
from app.models.document_models import (
    DocumentoUpdate,
    RelacionDocumentalCreate,
    RelacionDocumentalDelete,
    RelacionDocumentalOut,
)
from app.services.document_url_service import get_signed_url, normalize_s3_key


class TestSuite2DocumentModelsAndS3Offloading(unittest.IsolatedAsyncioTestCase):
    """Suite 2: Reglas de negocio de edición documental, linaje y Offloading S3."""

    def test_09_documento_update_modo_puentes_and_s3_immutability(self):
        """Verifica patrón modo_puentes (REEMPLAZAR|AGREGAR|ELIMINAR) e inmutabilidad de urlarchivooriginals3."""
        upd = DocumentoUpdate(
            titulo="Reglamento de Evaluación",
            tipo_documento_nombre="Reglamento",
            sedesids=[1, 2],
            modo_puentes="AGREGAR",
        )
        self.assertEqual(upd.modo_puentes, "AGREGAR")
        fields_dict = getattr(DocumentoUpdate, "model_fields", None) or getattr(DocumentoUpdate, "__fields__", {})
        self.assertNotIn("urlarchivooriginals3", fields_dict)

        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", modo_puentes="SOBREESCRIBIR")

    def test_10_documento_update_negative_session_and_bridge_ids_validation(self):
        """Verifica validación de enteros positivos en sesión, acuerdo y tablas puente en DocumentoUpdate."""
        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", numsesion=-1)

        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", numacuerdo=-5)

        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", sedesids=[1, 0])

        with self.assertRaises(PydanticValidationError):
            DocumentoUpdate(titulo="Decreto", carrerasids=[10, -2])

    def test_11_relacion_documental_confianza_bounds(self):
        """Verifica que el nivel de confianza en relaciones jurídicas esté acotado a [0.0, 1.0]."""
        rel = RelacionDocumentalCreate(
            iddocumentoorigen=uuid4(),
            iddocumentodestino=uuid4(),
            nombretiporelacion="Deroga",
            confianza=0.95,
        )
        self.assertEqual(rel.confianza, 0.95)

        with self.assertRaises(PydanticValidationError):
            RelacionDocumentalCreate(
                iddocumentoorigen=uuid4(),
                iddocumentodestino=uuid4(),
                confianza=1.5,
            )

        with self.assertRaises(PydanticValidationError):
            RelacionDocumentalOut(
                idrelacion=1,
                iddocumentoorigen=uuid4(),
                iddocumentodestino=uuid4(),
                idtiporelacion=1,
                idrespaldolegal=1,
                idfuentedeteccion=1,
                fechaefecto=date(2025, 1, 1),
                confianza=-0.2,
                verificada=True,
                textoevidencia="Evidencia",
            )

    def test_12_relacion_documental_delete_contract(self):
        """Verifica contrato de payload para eliminación de relación jurídica por idrelacion o par de documentos."""
        del_by_id = RelacionDocumentalDelete(idrelacion=42)
        self.assertEqual(del_by_id.idrelacion, 42)

        orig_id = uuid4()
        dest_id = uuid4()
        del_by_pair = RelacionDocumentalDelete(
            iddocumentoorigen=orig_id,
            iddocumentodestino=dest_id,
            idtiporelacion=2
        )
        self.assertEqual(del_by_pair.iddocumentoorigen, orig_id)
        self.assertEqual(del_by_pair.iddocumentodestino, dest_id)

    def test_13_normalize_s3_key_offloading(self):
        """Verifica la normalización de rutas S3 para el microservicio firmador."""
        self.assertEqual(
            normalize_s3_key("s3://giru-normativas-usm/raw/uploads/064_2016_DECRETO.pdf"),
            "raw/uploads/064_2016_DECRETO.pdf",
        )
        self.assertEqual(
            normalize_s3_key("/raw/uploads/reglamento_general.pdf"),
            "raw/uploads/reglamento_general.pdf",
        )

    async def test_14_get_signed_url_success_and_token_forwarding(self):
        """Verifica caso exitoso (HTTP 200) de firma temporal con reenvío de Bearer token."""
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "url": "https://giru-bucket.s3.amazonaws.com/raw/uploads/doc.pdf?X-Amz-Expires=600",
            "expires_in": 600,
        }

        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            res = await get_signed_url("s3://bucket/raw/uploads/doc.pdf", "jwt-token-usm")
            self.assertEqual(res["expires_in"], 600)
            mock_post.assert_awaited_once_with(
                "https://signer.giru.usm.cl/firmar",
                json={"key": "raw/uploads/doc.pdf"},
                headers={"Authorization": "Bearer jwt-token-usm"},
            )

    async def test_15_get_signed_url_missing_configuration_503(self):
        """Verifica HTTP 503 cuando el microservicio firmador no tiene URL configurada."""
        with patch.object(settings, "DOCUMENT_SIGNER_URL", ""):
            with self.assertRaises(HTTPException) as ctx:
                await get_signed_url("raw/uploads/doc.pdf", "jwt-token-usm")
            self.assertEqual(ctx.exception.status_code, 503)

    async def test_16_get_signed_url_token_expired_401(self):
        """Verifica traducción semántica de token expirado o inválido (HTTP 401)."""
        mock_response = MagicMock(status_code=401)
        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with self.assertRaises(HTTPException) as ctx:
                await get_signed_url("raw/uploads/doc.pdf", "token-expirado")
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("Sesion expirada", ctx.exception.detail)

    async def test_17_get_signed_url_file_not_found_404(self):
        """Verifica traducción semántica de archivo inexistente en S3 (HTTP 404)."""
        mock_response = MagicMock(status_code=404)
        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with self.assertRaises(HTTPException) as ctx:
                await get_signed_url("raw/uploads/inexistente.pdf", "jwt-token-usm")
            self.assertEqual(ctx.exception.status_code, 404)

    async def test_18_get_signed_url_invalid_format_422(self):
        """Verifica traducción semántica de formato no visualizable (400 -> HTTP 422)."""
        mock_response = MagicMock(status_code=400)
        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with self.assertRaises(HTTPException) as ctx:
                await get_signed_url("raw/uploads/archivo.exe", "jwt-token-usm")
            self.assertEqual(ctx.exception.status_code, 422)

    async def test_19_get_signed_url_network_and_upstream_error_502(self):
        """Verifica traducción de errores de conexión y fallos no controlados del Signer a HTTP 502."""
        with patch.object(settings, "DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            # Caso 1: Error de red / timeout de conexión
            mock_post.side_effect = httpx.ConnectError("Connection timeout to Signer")
            with self.assertRaises(HTTPException) as ctx_net:
                await get_signed_url("raw/uploads/doc.pdf", "jwt-token-usm")
            self.assertEqual(ctx_net.exception.status_code, 502)

            # Caso 2: Error 500 del servicio firmador
            mock_post.side_effect = None
            mock_post.return_value = MagicMock(status_code=500)
            with self.assertRaises(HTTPException) as ctx_up:
                await get_signed_url("raw/uploads/doc.pdf", "jwt-token-usm")
            self.assertEqual(ctx_up.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
