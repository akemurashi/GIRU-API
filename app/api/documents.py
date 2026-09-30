from fastapi import APIRouter, Depends, HTTPException
from app.models.document_models import DocumentoOut, DocumentoDetail, DocumentoUpdate, DocumentoUrlOut
from app.models.user_models import UserOut
from app.repositories.document_repository import DocumentRepository
from app.security.microsoft_auth import auth_service, require_authenticated, require_admin, oauth2_scheme
from app.services.document_url_service import get_signed_url

router = APIRouter()

def get_doc_repo() -> DocumentRepository:
    return DocumentRepository()

# ─────────────────────────────────────────────────────────────────────────────
# Endpoints para todos los usuarios autenticados
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[DocumentoOut])
async def list_documents(
    skip: int = 0,
    limit: int = 50,
    repo: DocumentRepository = Depends(get_doc_repo),
   _=Depends(require_authenticated),
):
    """Lista de documentos con metadata básica (exploración sin query)."""
    return await repo.list_documents(skip=skip, limit=limit)

@router.get("/{document_id}", response_model=DocumentoDetail)
async def get_document(
    document_id: int,
    repo: DocumentRepository = Depends(get_doc_repo),
    _=Depends(require_authenticated),
):
    """Detalle completo de un documento: metadatos, sedes, carreras, beneficios, etc."""
    doc = await repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc

# GET /api/v1/documents/{document_id}/url  ->  {"url": "...", "expires_in": 600}
@router.get("/{document_id}/url", response_model=DocumentoUrlOut)
async def get_document_url(
    document_id: int,                                              # id del documento, viene en la URL
    repo: DocumentRepository = Depends(get_doc_repo),              # acceso a la BD
    _=Depends(require_authenticated),                              # rechaza con 401 si el token no es válido
    token: str = Depends(oauth2_scheme),                           # entrega el token obtenido de la autorización
):
    # 1) Busca en la BD la ruta del PDF (lanza 404 si el documento no existe)
    s3_key = await repo.get_s3_key(document_id)
    # 2) Pide la URL firmada a AWS reenviando el mismo token del usuario
    return await get_signed_url(s3_key, token)

# ─────────────────────────────────────────────────────────────────────────────
# Endpoints exclusivos para ADMIN
# ─────────────────────────────────────────────────────────────────────────────

# @router.patch("/{document_id}", response_model=DocumentoDetail)
# async def update_document(
#     document_id: int,
#     body: DocumentoUpdate,
#     repo: DocumentRepository = Depends(get_doc_repo),
#     admin: UserOut = Depends(auth_service.get_current_user),
#     _=Depends(require_admin),
# ):
#     """
#     [ADMIN] Edita metadatos de un documento.
#     Permite actualizar: título, descripción, categoría, sedes, vigencia,
#     carreras, beneficios, nombramientos, departamentos, respaldo legal.
#     """
#     doc = await repo.update(document_id, body)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Documento no encontrado")
#     return doc

# @router.patch("/{document_id}/toggle-active", response_model=DocumentoDetail)
# async def toggle_document_active(
#     document_id: int,
#     repo: DocumentRepository = Depends(get_doc_repo),
#     admin: UserOut = Depends(auth_service.get_current_user),
#     _=Depends(require_admin),
# ):
#     """
#     [ADMIN] Activa o desactiva un documento (es_activo).
#     Un documento inactivo no aparece en búsquedas de usuarios no administradores."""
#     doc = await repo.toggle_active(document_id)
#     if not doc:
#         raise HTTPException(status_code=404, detail="Documento no encontrado")
#     return doc
