"""Repositorio de persistencia y consulta para la proyección de trazabilidad normativa (Read Model CQRS)."""

import json
import re
from typing import Any
from uuid import UUID
from sqlalchemy import text

from app.core.database import get_session
from app.core.exceptions import (
    DatabaseError,
    DocumentNotFoundError,
    ValidationError as AppValidationError,
)
from app.models.document_models import (
    DocumentoTrazabilidadOut,
    TrazabilidadUpsertRequest,
)


class TrazabilidadRepository(object):
    """
    Acceso a PostgreSQL para la tabla satélite `public.documentotrazabilidad`.
    Consume las funciones y procedimientos almacenados canónicos:
    - fn_obtener_trazabilidad_documento
    - sp_modificar_o_crear_trazabilidad
    - sp_eliminar_trazabilidad_documento
    """

    @staticmethod
    def _handle_sp_error(e: Exception, document_id: str) -> None:
        """
        Captura y clasifica excepciones generadas por los procedimientos almacenados de trazabilidad,
        traduciéndolas a excepciones semánticas de dominio (ej. SQLSTATE 23503 -> DocumentNotFoundError).
        """
        msg = str(e)
        orig = getattr(e, "orig", None)
        sqlstate = None
        if orig is not None:
            msg = str(orig)
            sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)

        match = re.search(r"(?:RaiseError|RaiseException)'>:\s*([^\n\[]+)", msg)
        clean_msg = match.group(1).strip() if match else msg
        lower_msg = clean_msg.lower()

        if (
            sqlstate == "23503"
            or "23503" in clean_msg
            or "foreign key" in lower_msg
            or "fk_documentotrazabilidad_documento" in lower_msg
            or "No se encontró el documento" in clean_msg
            or "no existe en documento" in lower_msg
        ):
            raise DocumentNotFoundError(document_id)

        if "Validación:" in clean_msg or "Parámetro:" in clean_msg:
            raise AppValidationError(clean_msg, details={"document_id": document_id})

        raise DatabaseError(
            f"Error al procesar la trazabilidad documental: {clean_msg}",
            {"document_id": document_id},
        )

    @staticmethod
    async def get_by_document_id(document_id: UUID | str) -> DocumentoTrazabilidadOut:
        """
        Obtiene la línea de tiempo genealógica y metadatos clave de un documento
        consumiendo `public.fn_obtener_trazabilidad_documento`.
        """
        try:
            doc_uuid = UUID(str(document_id))
        except ValueError as exc:
            raise DocumentNotFoundError(document_id) from exc

        async with get_session() as session:
            stmt = text("SELECT public.fn_obtener_trazabilidad_documento(:id) AS data")
            result = await session.execute(stmt, {"id": doc_uuid})
            raw_data = result.scalar()

            if not raw_data:
                raise DocumentNotFoundError(document_id)

            parsed = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            return DocumentoTrazabilidadOut.model_validate(parsed)

    async def upsert_via_sp(
        self,
        document_id: UUID | str,
        data: TrazabilidadUpsertRequest,
    ) -> DocumentoTrazabilidadOut:
        """
        Inserta o actualiza atómicamente la proyección de trazabilidad de un documento
        mediante `public.sp_modificar_o_crear_trazabilidad` y retorna el estado resultante.
        """
        try:
            doc_uuid = UUID(str(document_id))
        except ValueError as exc:
            raise DocumentNotFoundError(document_id) from exc

        antes_json = json.dumps([item.model_dump(mode="json") for item in data.antes])
        despues_json = json.dumps([item.model_dump(mode="json") for item in data.despues])

        call_stmt = text("""
            CALL public.sp_modificar_o_crear_trazabilidad(
                p_iddocumento => :p_iddocumento,
                p_antes => CAST(:p_antes AS jsonb),
                p_despues => CAST(:p_despues AS jsonb)
            )
        """)

        try:
            async with get_session() as session:
                await session.execute(
                    call_stmt,
                    {
                        "p_iddocumento": doc_uuid,
                        "p_antes": antes_json,
                        "p_despues": despues_json,
                    },
                )
                await session.commit()
        except Exception as e:
            self._handle_sp_error(e, str(document_id))

        return await self.get_by_document_id(doc_uuid)

    async def delete_via_sp(self, document_id: UUID | str) -> dict[str, Any]:
        """
        Elimina o resetea el registro de trazabilidad de un documento preservando íntegro
        el documento maestro mediante `public.sp_eliminar_trazabilidad_documento`.
        """
        try:
            doc_uuid = UUID(str(document_id))
        except ValueError as exc:
            raise DocumentNotFoundError(document_id) from exc

        call_stmt = text("""
            CALL public.sp_eliminar_trazabilidad_documento(
                p_iddocumento => :p_iddocumento
            )
        """)

        try:
            async with get_session() as session:
                await session.execute(call_stmt, {"p_iddocumento": doc_uuid})
                await session.commit()
        except Exception as e:
            self._handle_sp_error(e, str(document_id))

        return {
            "status": "ok",
            "iddocumento": str(doc_uuid),
            "message": "Trazabilidad eliminada exitosamente",
        }
