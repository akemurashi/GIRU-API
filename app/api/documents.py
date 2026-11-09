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
    DocumentoTrazabilidadOut,
    DocumentoUpdate,
    DocumentoUrlOut,
    TrazabilidadUpsertRequest,
    unescape_git_octal,
)
from app.models.search_models import FilterOptions
from app.models.user_models import UserOut
from app.repositories.document_repository import DocumentRepository
from app.repositories.trazabilidad_repository import TrazabilidadRepository
from app.security.microsoft_auth import oauth2_scheme, require_admin, require_authenticated
from app.services.document_url_service import get_signed_url

router = APIRouter()


async def get_doc_repo() -> DocumentRepository:
    """Provee una instancia del repositorio de documentos."""
    return DocumentRepository()


async def get_trazabilidad_repo() -> TrazabilidadRepository:
    """Provee una instancia del repositorio de trazabilidad normativa."""
    return TrazabilidadRepository()


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
    Busca un documento por su título (sin extensión .md o .pdf).
    Soporta secuencias octales escapadas, normalización de extensiones
    y búsqueda tolerante a puntos finales y mayúsculas/minúsculas.
    Útil para el chat AI y resolución de hitos de trazabilidad.
    """
    clean_title = unescape_git_octal(title).strip()
    lower_title = clean_title.lower()
    if lower_title.endswith(".md"):
        clean_title = clean_title[:-3].strip()
    elif lower_title.endswith(".pdf"):
        clean_title = clean_title[:-4].strip()

    clean_title = clean_title.rstrip(".").strip()

    async with get_session() as session:
        stmt = (
            select(Documento)
            .where(text("LOWER(RTRIM(TRIM(titulo), '.')) = LOWER(:title)"))
            .params(title=clean_title)
            .order_by(Documento.isactive.desc(), Documento.creacion.desc().nullslast())
            .limit(1)
        )
        result = await session.execute(stmt)
        doc = result.scalars().first()

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
    "/{document_id}/trazabilidad",
    summary="Obtener trazabilidad normativa (línea de tiempo)",
    responses={404: {"description": "Documento no encontrado"}},
)
async def get_document_trazabilidad(
    document_id: str,
    traza_repo: TrazabilidadRepository = Depends(get_trazabilidad_repo),
    _=Depends(require_authenticated),
) -> DocumentoTrazabilidadOut:
    """
    Retorna la línea de tiempo genealógica pre-calculada (antes y después) y metadatos clave
    del documento consumiendo `public.fn_obtener_trazabilidad_documento`.
    """
    return await traza_repo.get_by_document_id(document_id)


@router.put(
    "/{document_id}/trazabilidad",
    summary="Crear o reemplazar trazabilidad normativa",
    responses={
        404: {"description": "El documento especificado no existe"},
        422: {"description": "Payload de trazabilidad inválido"},
    },
)
async def upsert_document_trazabilidad(
    document_id: str,
    data: TrazabilidadUpsertRequest,
    traza_repo: TrazabilidadRepository = Depends(get_trazabilidad_repo),
    admin: UserOut = Depends(require_admin),
) -> DocumentoTrazabilidadOut:
    """
    [ADMIN] Inserta o actualiza atómicamente la proyección de trazabilidad de un documento
    mediante `public.sp_modificar_o_crear_trazabilidad`.
    """
    return await traza_repo.upsert_via_sp(document_id, data)


@router.delete(
    "/{document_id}/trazabilidad",
    summary="Eliminar trazabilidad normativa de un documento",
    responses={404: {"description": "Documento no encontrado"}},
)
async def delete_document_trazabilidad(
    document_id: str,
    traza_repo: TrazabilidadRepository = Depends(get_trazabilidad_repo),
    admin: UserOut = Depends(require_admin),
) -> dict[str, Any]:
    """
    [ADMIN] Limpia o resetea el historial de trazabilidad de un documento sin alterar
    la norma maestra mediante `public.sp_eliminar_trazabilidad_documento`.
    """
    return await traza_repo.delete_via_sp(document_id)


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
