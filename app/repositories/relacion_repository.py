from sqlmodel import select, delete, update, text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from datetime import date
from app.models.db_models import RelacionDocumental, Documento, RespaldoLegal, TipoRelacion
from app.core.database import get_session
from app.core.exceptions import RelationNotFoundError, DatabaseError


class RelacionRepository:
    """
    Acceso a PostgreSQL para la tabla RelacionDocumental (trazabilidad/linaje jurídico).
    Implementado con SQLModel async.
    """

    async def check_cycle_detection(self, origen_id: int, destino_id: int) -> bool:
        """
        Uses recursive CTE to detect if adding relation (origen_id -> destino_id)
        would create a cycle in the document graph.
        Returns True if cycle would be created.
        """
        async with get_session() as session:
            query = text("""
                WITH RECURSIVE path AS (
                    SELECT iddocumentoorigen, iddocumentodestino
                    FROM relaciondocumental
                    WHERE iddocumentoorigen = :destino_id
                    
                    UNION ALL
                    
                    SELECT r.iddocumentoorigen, r.iddocumentodestino
                    FROM relaciondocumental r
                    INNER JOIN path p ON r.iddocumentoorigen = p.iddocumentodestino
                )
                SELECT EXISTS(
                    SELECT 1 FROM path WHERE iddocumentoorigen = :origen_id
                )
            """)
            result = await session.execute(query, {"origen_id": origen_id, "destino_id": destino_id})
            return result.scalar()

    async def updatedocumentstatus(self, session, documentid: int):
        """
        Updates document to 'Derogado' status when verified derogation is added.
        Assumes 'Derogado' status has idestadovigencia = 2.
        """
        stmt = (
            update(Documento)
            .where(Documento.iddocumento == documentid)
            .values(
                idestadovigencia=2,  # Derogado
                derogacion=date.today(),
                isactive=False
            )
        )
        await session.execute(stmt)

    async def create(self, data: dict) -> RelacionDocumental:
        """
        Crea una nueva relación documental entre dos documentos.
        Includes cycle detection and automatic status update for 'Deroga' relations.
        """
        # Check for cycles before inserting
        has_cycle = await self.check_cycle_detection(
            data["iddocumentoorigen"],
            data["iddocumentodestino"]
        )
        if has_cycle:
            raise DatabaseError(
                "Cycle detected: This relation would create a circular reference",
                {"origen": data["iddocumentoorigen"], "destino": data["iddocumentodestino"]}
            )
        
        async with get_session() as session:
            try:
                relacion = RelacionDocumental(
                    idrespaldolegal=data["idrespaldolegal"],
                    idtiporelacion=data["idtiporelacion"],
                    iddocumentoorigen=data["iddocumentoorigen"],
                    iddocumentodestino=data["iddocumentodestino"],
                    detalledemodificacion=data.get("detalledemodificacion"),
                    fechaefecto=data["fechaefecto"],
                    idfuentedeteccion=data.get("idfuentedeteccion"),
                    confianza=data.get("confianza", 1.00),
                    verificada=data.get("verificada", False),
                    textoevidencia=data.get("textoevidencia")
                )
                session.add(relacion)
                await session.commit()
                await session.refresh(relacion)
                
                # Automatic status update for "Deroga" relations (idtiporelacion == 2)
                # when verificada is True
                if (data["idtiporelacion"] == 2 and 
                    data.get("verificada", False)):
                    await self.updatedocumentstatus(
                        session,
                        data["iddocumentodestino"]
                    )
                    await session.commit()
                
                return relacion
            except Exception as e:
                if "duplicate key" in str(e).lower():
                    raise DatabaseError(
                        "This relation already exists",
                        {"origen": data["iddocumentoorigen"], 
                         "destino": data["iddocumentodestino"],
                         "tipo_relacion": data["idtiporelacion"]}
                    )
                raise

    async def get_by_id(self, relacion_id: int) -> RelacionDocumental:
        """Obtiene una relación por su ID."""
        async with get_session() as session:
            stmt = select(RelacionDocumental).where(RelacionDocumental.idrelacion == relacion_id)
            result = await session.execute(stmt)
            relacion = result.scalar_one_or_none()
            
            if not relacion:
                raise RelationNotFoundError(relacion_id)
            
            return relacion

    async def get_document_lineage(self, document_id: int) -> dict:
        """
        Obtiene el linaje completo de un documento:
        - Relaciones donde es origen (documentos que modifica/deroga)
        - Relaciones donde es destino (documentos que lo modifican/derogan)
        """
        async with get_session() as session:
            # Relaciones como origen (este documento modifica a otros)
            stmt_origen = (
                select(RelacionDocumental)
                .where(RelacionDocumental.iddocumentoorigen == document_id)
            )
            result_origen = await session.execute(stmt_origen)
            relaciones_origen = result_origen.scalars().all()

            # Relaciones como destino (otros documentos modifican a este)
            stmt_destino = (
                select(RelacionDocumental)
                .where(RelacionDocumental.iddocumentodestino == document_id)
            )
            result_destino = await session.execute(stmt_destino)
            relaciones_destino = result_destino.scalars().all()

            return {
                "origen": relaciones_origen,
                "destino": relaciones_destino
            }

    async def get_related_documents(self, document_id: int) -> List[dict]:
        """
        Obtiene todos los documentos relacionados (tanto origen como destino)
        con información de la relación.
        """
        async with get_session() as session:
            # Get document info for related documents
            lineage = await self.get_document_lineage(document_id)
            
            related_docs = []
            
            # Process origen relations
            for rel in lineage["origen"]:
                stmt = select(Documento).where(Documento.iddocumento == rel.iddocumentodestino)
                result = await session.execute(stmt)
                doc = result.scalar_one_or_none()
                if doc:
                    related_docs.append({
                        "documento": doc,
                        "relacion": rel,
                        "tipo": "destino"  # este documento modifica a 'doc'
                    })
            
            # Process destino relations
            for rel in lineage["destino"]:
                stmt = select(Documento).where(Documento.iddocumento == rel.iddocumentoorigen)
                result = await session.execute(stmt)
                doc = result.scalar_one_or_none()
                if doc:
                    related_docs.append({
                        "documento": doc,
                        "relacion": rel,
                        "tipo": "origen"  # 'doc' modifica a este documento
                    })
            
            return related_docs

    async def delete(self, relacion_id: int) -> bool:
        """Elimina una relación documental."""
        async with get_session() as session:
            stmt = delete(RelacionDocumental).where(RelacionDocumental.idrelacion == relacion_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def list_by_document(self, document_id: int) -> List[RelacionDocumental]:
        """
        Lista todas las relaciones de un documento (como origen o destino).
        """
        async with get_session() as session:
            stmt = select(RelacionDocumental).where(
                (RelacionDocumental.iddocumentoorigen == document_id) |
                (RelacionDocumental.iddocumentodestino == document_id)
            )
            result = await session.execute(stmt)
            return result.scalars().all()
