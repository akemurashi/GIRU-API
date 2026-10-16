"""
API Router para la gestión de relaciones documentales (trazabilidad y linaje jurídico).
Consume los procedimientos almacenados canónicos:
- sp_modificar_o_crear_relacion_documental
- sp_eliminar_relacion_documental
Todas las operaciones de mutación y auditoría de relaciones requieren privilegios de administrador.
"""
from fastapi import APIRouter, Depends
from typing import Dict, Any
from app.models.document_models import RelacionDocumentalCreate, RelacionDocumentalDelete
from app.models.user_models import UserOut
from app.repositories.relacion_repository import RelacionRepository
from app.security.microsoft_auth import require_admin

router = APIRouter()


def get_relacion_repo() -> RelacionRepository:
    return RelacionRepository()


@router.post("/", summary="Crear o modificar relación documental")
async def create_or_update_relation(
    data: RelacionDocumentalCreate,
    repo: RelacionRepository = Depends(get_relacion_repo),
    admin: UserOut = Depends(require_admin),
) -> Dict[str, Any]:
    """
    [ADMIN] Crea o actualiza una relación jurídica entre dos documentos normativos.
    Consume `public.sp_modificar_o_crear_relacion_documental`.
    Aplica triggers a nivel de motor:
    1. Prevención de ciclos dirigidos (DAG).
    2. Sincronización automática de vigencia si el tipo es 'Deroga'.
    """
    return await repo.create_via_sp(data.model_dump())


@router.delete("/", summary="Eliminar relación documental")
async def delete_relation(
    data: RelacionDocumentalDelete,
    repo: RelacionRepository = Depends(get_relacion_repo),
    admin: UserOut = Depends(require_admin),
) -> Dict[str, Any]:
    """
    [ADMIN] Elimina un vínculo del grafo relacional normativo.
    Consume `public.sp_eliminar_relacion_documental`.
    Permite eliminar por ID numérico de relación o por par (origen, destino, tipo).
    """
    return await repo.delete_via_sp(data.model_dump())


@router.get("/{document_id}/lineage", summary="Linaje y relaciones de un documento")
async def get_document_lineage(
    document_id: str,
    repo: RelacionRepository = Depends(get_relacion_repo),
    admin: UserOut = Depends(require_admin),
) -> Dict[str, Any]:
    """
    [ADMIN] Consulta el linaje completo de un documento normativo:
    - Relaciones donde es origen (documentos a los que afecta).
    - Relaciones donde es destino (documentos que lo afectan).
    """
    return await repo.get_document_lineage(document_id)
