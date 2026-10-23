"""Repositorio de persistencia y trazabilidad de relaciones documentales en PostgreSQL."""

import re
from uuid import UUID
from sqlmodel import delete, select, text

from app.core.database import get_session
from app.core.exceptions import (
    CatalogNotFoundError,
    DAGCycleError,
    DatabaseError,
    DocumentNotFoundError,
    RelationNotFoundError,
    UniqueConstraintError,
    ValidationError as AppValidationError,
)
from app.models.db_models import Documento, RelacionDocumental


class RelacionRepository(object):
    """
    Acceso a PostgreSQL para la tabla RelacionDocumental (trazabilidad/linaje jurídico).
    Implementado con SQLModel async y procedimientos almacenados canónicos.
    """

    @staticmethod
    def _handle_sp_error(e: Exception) -> None:
        """
        Captura y clasifica excepciones generadas por procedimientos almacenados y triggers en PostgreSQL,
        traduciéndolas a excepciones semánticas de la aplicación.
        """
        msg = str(e)
        orig = getattr(e, "orig", None)
        if orig:
            msg = str(orig)

        match = re.search(r"(?:RaiseError|RaiseException)'>:\s*([^\n\[]+)", msg)
        clean_msg = match.group(1).strip() if match else msg

        if "No se encontró el documento" in clean_msg:
            raise DocumentNotFoundError(clean_msg)
        if "Unicidad:" in clean_msg or "duplicate key" in clean_msg.lower():
            raise UniqueConstraintError(clean_msg)
        if "Violación de Grafo Acíclico (DAG)" in clean_msg or "ciclo" in clean_msg.lower():
            raise DAGCycleError(clean_msg)
        if "Catálogo:" in clean_msg:
            raise CatalogNotFoundError(clean_msg)
        if "Validación:" in clean_msg or "Parámetro:" in clean_msg:
            raise AppValidationError(clean_msg)
        raise DatabaseError(f"Error al procesar la relación documental: {clean_msg}")

    async def create_via_sp(self, data: dict[str, object]) -> dict[str, object]:
        """
        Crea o actualiza una relación jurídica entre documentos consumiendo
        el procedimiento almacenado canónico `public.sp_modificar_o_crear_relacion_documental`.
        Garantiza prevención de ciclos (DAG) y sincronización automática de vigencia/derogación.
        """
        try:
            origen_uuid = UUID(str(data["iddocumentoorigen"]))
            destino_uuid = UUID(str(data["iddocumentodestino"]))
        except (ValueError, KeyError) as ex:
            raise AppValidationError(f"Identificador UUID de documento inválido: {ex}")

        sp_params = {
            "p_iddocumentoorigen": origen_uuid,
            "p_iddocumentodestino": destino_uuid,
            "p_idtiporelacion": data.get("idtiporelacion"),
            "p_nombretiporelacion": data.get("nombretiporelacion"),
            "p_detallemodificacion": data.get("detallemodificacion"),
            "p_fechaefecto": data.get("fechaefecto"),
            "p_verificada": data.get("verificada", True),
            "p_confianza": data.get("confianza", 1.00),
            "p_textoevidencia": data.get("textoevidencia"),
            "p_idfuentedeteccion": data.get("idfuentedeteccion"),
            "p_idrespaldolegal": data.get("idrespaldolegal"),
            "p_idrelacion": data.get("idrelacion"),
        }

        call_stmt = text("""
            CALL public.sp_modificar_o_crear_relacion_documental(
                p_iddocumentoorigen => :p_iddocumentoorigen,
                p_iddocumentodestino => :p_iddocumentodestino,
                p_idtiporelacion => :p_idtiporelacion,
                p_nombretiporelacion => :p_nombretiporelacion,
                p_detallemodificacion => :p_detallemodificacion,
                p_fechaefecto => :p_fechaefecto,
                p_verificada => :p_verificada,
                p_confianza => :p_confianza,
                p_textoevidencia => :p_textoevidencia,
                p_idfuentedeteccion => :p_idfuentedeteccion,
                p_idrespaldolegal => :p_idrespaldolegal,
                p_idrelacion => :p_idrelacion
            )
        """)

        try:
            async with get_session() as session:
                await session.execute(call_stmt, sp_params)
                await session.commit()
        except Exception as e:
            self._handle_sp_error(e)

        return {"status": "ok", "message": "Relación procesada exitosamente"}

    async def delete_via_sp(self, data: dict[str, object]) -> dict[str, object]:
        """
        Elimina un vínculo del grafo relacional consumiendo el procedimiento
        `public.sp_eliminar_relacion_documental` por ID directo o por par (origen, destino).
        """
        origen_uuid = None
        if data.get("iddocumentoorigen"):
            try:
                origen_uuid = UUID(str(data["iddocumentoorigen"]))
            except ValueError:
                raise AppValidationError("iddocumentoorigen debe ser un UUID válido")

        destino_uuid = None
        if data.get("iddocumentodestino"):
            try:
                destino_uuid = UUID(str(data["iddocumentodestino"]))
            except ValueError:
                raise AppValidationError("iddocumentodestino debe ser un UUID válido")

        sp_params = {
            "p_idrelacion": data.get("idrelacion"),
            "p_iddocumentoorigen": origen_uuid,
            "p_iddocumentodestino": destino_uuid,
            "p_idtiporelacion": data.get("idtiporelacion"),
        }

        call_stmt = text("""
            CALL public.sp_eliminar_relacion_documental(
                p_idrelacion => :p_idrelacion,
                p_iddocumentoorigen => :p_iddocumentoorigen,
                p_iddocumentodestino => :p_iddocumentodestino,
                p_idtiporelacion => :p_idtiporelacion
            )
        """)

        try:
            async with get_session() as session:
                await session.execute(call_stmt, sp_params)
                await session.commit()
        except Exception as e:
            self._handle_sp_error(e)

        return {"status": "ok", "message": "Relación eliminada exitosamente"}

    @staticmethod
    async def get_by_id(relacion_id: int) -> RelacionDocumental:
        """Obtiene una relación por su ID."""
        async with get_session() as session:
            stmt = select(RelacionDocumental).where(RelacionDocumental.idrelacion == relacion_id)
            result = await session.execute(stmt)
            relacion = result.scalar_one_or_none()

            if not relacion:
                raise RelationNotFoundError(relacion_id)

            return relacion

    @staticmethod
    async def get_document_lineage(document_id: UUID | str) -> dict[str, object]:
        """
        Obtiene el linaje completo de un documento:
        - Relaciones donde es origen (documentos que modifica/deroga)
        - Relaciones donde es destino (documentos que lo modifican/derogan)
        """
        try:
            doc_uuid = UUID(str(document_id))
        except ValueError:
            raise DocumentNotFoundError(str(document_id))

        async with get_session() as session:
            # Relaciones como origen (este documento modifica a otros)
            stmt_origen = (
                select(RelacionDocumental)
                .where(RelacionDocumental.iddocumentoorigen == doc_uuid)
            )
            result_origen = await session.execute(stmt_origen)
            relaciones_origen = result_origen.scalars().all()

            # Relaciones como destino (otros documentos modifican a este)
            stmt_destino = (
                select(RelacionDocumental)
                .where(RelacionDocumental.iddocumentodestino == doc_uuid)
            )
            result_destino = await session.execute(stmt_destino)
            relaciones_destino = result_destino.scalars().all()

            return {
                "document_id": str(doc_uuid),
                "relaciones_como_origen": [
                    {
                        "idrelacion": r.idrelacion,
                        "iddocumentodestino": str(r.iddocumentodestino),
                        "idtiporelacion": r.idtiporelacion,
                        "detallemodificacion": r.detallemodificacion,
                        "detalledemodificacion": r.detallemodificacion,
                        "fechaefecto": str(r.fechaefecto) if r.fechaefecto else None,
                        "verificada": r.verificada,
                        "confianza": float(r.confianza) if r.confianza is not None else 1.0,
                    }
                    for r in relaciones_origen
                ],
                "relaciones_como_destino": [
                    {
                        "idrelacion": r.idrelacion,
                        "iddocumentoorigen": str(r.iddocumentoorigen),
                        "idtiporelacion": r.idtiporelacion,
                        "detallemodificacion": r.detallemodificacion,
                        "detalledemodificacion": r.detallemodificacion,
                        "fechaefecto": str(r.fechaefecto) if r.fechaefecto else None,
                        "verificada": r.verificada,
                        "confianza": float(r.confianza) if r.confianza is not None else 1.0,
                    }
                    for r in relaciones_destino
                ],
            }

    @staticmethod
    async def get_related_documents(document_id: UUID | str) -> list[dict[str, object]]:
        """
        Obtiene todos los documentos relacionados (tanto origen como destino)
        con información de la relación.
        """
        try:
            doc_uuid = UUID(str(document_id))
        except ValueError:
            raise DocumentNotFoundError(str(document_id))

        async with get_session() as session:
            stmt_origen = (
                select(RelacionDocumental)
                .where(RelacionDocumental.iddocumentoorigen == doc_uuid)
            )
            res_origen = await session.execute(stmt_origen)
            origen_rels = res_origen.scalars().all()

            stmt_destino = (
                select(RelacionDocumental)
                .where(RelacionDocumental.iddocumentodestino == doc_uuid)
            )
            res_destino = await session.execute(stmt_destino)
            destino_rels = res_destino.scalars().all()

            related_docs: list[dict[str, object]] = []
            for rel in origen_rels:
                stmt = select(Documento).where(Documento.iddocumento == rel.iddocumentodestino)
                res = await session.execute(stmt)
                doc = res.scalar_one_or_none()
                if doc:
                    related_docs.append({
                        "documento": doc,
                        "relacion": rel,
                        "tipo": "destino",
                    })

            for rel in destino_rels:
                stmt = select(Documento).where(Documento.iddocumento == rel.iddocumentoorigen)
                res = await session.execute(stmt)
                doc = res.scalar_one_or_none()
                if doc:
                    related_docs.append({
                        "documento": doc,
                        "relacion": rel,
                        "tipo": "origen",
                    })

            return related_docs

    @staticmethod
    async def delete(relacion_id: int) -> bool:
        """Elimina una relación documental por id directo."""
        async with get_session() as session:
            stmt = delete(RelacionDocumental).where(RelacionDocumental.idrelacion == relacion_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    @staticmethod
    async def list_by_document(document_id: UUID | str) -> list[RelacionDocumental]:
        """Lista todas las relaciones de un documento (como origen o destino)."""
        try:
            doc_uuid = UUID(str(document_id))
        except ValueError:
            raise DocumentNotFoundError(str(document_id))

        async with get_session() as session:
            stmt = select(RelacionDocumental).where(
                (RelacionDocumental.iddocumentoorigen == doc_uuid)
                | (RelacionDocumental.iddocumentodestino == doc_uuid)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
