"""API Router para operaciones CRUD y consulta documental institucional."""

from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from app.core.database import get_session
from app.models.db_models import Documento
from app.models.document_models import (
    DocumentoDetail,
    DocumentoEditableOut,
    DocumentoOut,
    DocumentoUpdate,
    DocumentoUrlOut,
)
from app.models.search_models import FilterOptions
from app.models.user_models import UserOut
from app.repositories.document_repository import DocumentRepository
from app.security.microsoft_auth import oauth2_scheme, require_admin, require_authenticated
from app.services.document_url_service import get_signed_url

router = APIRouter()


def get_doc_repo() -> DocumentRepository:
    """Provee una instancia del repositorio de documentos."""
    return DocumentRepository()


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints para todos los usuarios autenticados
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_documents(
    skip: int = 0,
    limit: int = 50,
    repo: DocumentRepository = Depends(get_doc_repo),
    _=Depends(require_authenticated),
) -> list[DocumentoOut]:
    """Lista de documentos con metadata básica (exploración sin query)."""
    return await repo.list_documents(skip=skip, limit=limit)


@router.get(
    "/by-title/{title}",
    responses={404: {"description": "Documento no encontrado"}}
)
async def get_document_by_title(
    title: str,
    repo: DocumentRepository = Depends(get_doc_repo),
    _=Depends(require_authenticated),
) -> dict[str, Any]:
    """
    Busca un documento por su título (sin extensión .md).
    Útil para el chat AI que devuelve títulos como "title.md".
    """
    async with get_session() as session:
        # Remove .md extension if present and search
        clean_title = title.replace(".md", "")
        # Case-insensitive search
        stmt = select(Documento).where(text("LOWER(titulo) = LOWER(:title)")).params(title=clean_title)
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()

        if not doc:
            raise HTTPException(status_code=404, detail="Documento no encontrado")

        return {"id": doc.iddocumento, "titulo": doc.titulo}


# =========================================================================
# 1. RUTAS ESTÁTICAS DE ADMINISTRADOR (¡Estas van primero!)
# =========================================================================

@router.get("/admin/catalogs")
@router.get("/catalogs")
async def get_document_catalogs(
    repo: DocumentRepository = Depends(get_doc_repo),
    admin: UserOut = Depends(require_admin),
) -> FilterOptions:
    """Retorna los datos maestros/múltiples para poblar los selects de UI."""
    return await repo.get_filter_options()


@router.get("/admin/editable-doc/{document_id}")
@router.get("/{document_id}/editable")
async def get_editable_document(
    document_id: str,
    repo: DocumentRepository = Depends(get_doc_repo),
    admin: UserOut = Depends(require_admin),
) -> DocumentoEditableOut:
    """
    Retorna un único documento pre-formateado con todos los campos editables
    y arrays planos para la UI del editor.
    """
    return await repo.get_editable_by_id(document_id)


@router.put("/{document_id}")
@router.patch("/{document_id}")
async def update_document(
    document_id: str,
    data: DocumentoUpdate,
    repo: DocumentRepository = Depends(get_doc_repo),
    admin: UserOut = Depends(require_admin),
) -> DocumentoDetail:
    """Modifica y reescribe los metadatos editables y todas las tablas puente."""
    return await repo.update(document_id, data)


@router.patch("/{document_id}/toggle-active")
async def toggle_document_active(
    document_id: str,
    repo: DocumentRepository = Depends(get_doc_repo),
    admin: UserOut = Depends(require_admin),
) -> DocumentoDetail:
    """
    [ADMIN] Activa o desactiva un documento (isactive).
    Un documento inactivo no aparece en búsquedas ordinarias y actualiza ultima_modificacion.
    """
    return await repo.toggle_active(document_id)


@router.get("/{document_id}/detail")
async def get_document_detail_jsonb(
    document_id: str,
    repo: DocumentRepository = Depends(get_doc_repo),
    _=Depends(require_authenticated),
) -> dict[str, Any]:
    """
    Retorna la representación canónica estructurada en JSONB del documento
    ejecutando la función de auditoría oficial `public.fn_obtener_documento_detalle`.
    Incluye todos los catálogos vinculados, tablas satélites y relaciones de linaje.
    """
    return await repo.get_raw_detail(document_id)


@router.get(
    "/{document_id}",
    responses={404: {"description": "Documento no encontrado"}}
)
async def get_document(
    document_id: str,
    repo: DocumentRepository = Depends(get_doc_repo),
    _=Depends(require_authenticated),
) -> DocumentoDetail:
    """Detalle completo de un documento: metadatos, sedes, carreras, beneficios, etc."""
    doc = await repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


# GET /api/v1/documents/{document_id}/url -> {"url": "...", "expires_in": 600}
@router.get("/{document_id}/url")
async def get_document_url(
    document_id: str,
    repo: DocumentRepository = Depends(get_doc_repo),
    _=Depends(require_authenticated),
    token: str = Depends(oauth2_scheme),
) -> DocumentoUrlOut:
    """Genera una URL prefirmada de S3 para visualizar o descargar el archivo original."""
    # 1) Busca en la BD la ruta del PDF (lanza 404 si el documento no existe)
    s3_key = await repo.get_s3_key(document_id)
    # 2) Pide la URL firmada a AWS reenviando el mismo token del usuario
    return await get_signed_url(s3_key, token)
