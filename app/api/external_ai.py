from fastapi import APIRouter, Depends, HTTPException, Query
from app.models.ai_models import (
    CreateSessionRequest,
    CreateSessionResponse,
    AskRequest,
    AskResponse,
    SearchRequest,
    SearchResponse,
    SessionDetail,
    SessionListItem,
    DiagnosticResponse
)
from app.services.external_ai_service import ExternalAIService
from app.security.microsoft_auth import require_authenticated

router = APIRouter()


def get_external_ai_service() -> ExternalAIService:
    return ExternalAIService()


@router.get("/health")
async def health_check(service: ExternalAIService = Depends(get_external_ai_service)):
    """
    Verifica que el servicio externo de IA esté accesible.
    Este endpoint no requiere autenticación.
    """
    try:
        result = await service.health_check()
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Servicio de IA no disponible: {str(e)}")


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    request: CreateSessionRequest,
    service: ExternalAIService = Depends(get_external_ai_service),
    _=Depends(require_authenticated),
):
    """
    Crea una nueva sesión de chat con el servicio de IA.
    Guarda el session_id para usarlo en preguntas posteriores.
    """
    try:
        return await service.create_session(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions", response_model=list[SessionListItem])
async def list_sessions(
    user_id: str = Query(..., description="ID del usuario"),
    service: ExternalAIService = Depends(get_external_ai_service),
    _=Depends(require_authenticated),
):
    """
    Lista todas las sesiones de un usuario.
    """
    try:
        return await service.list_sessions(user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    user_id: str = Query(..., description="ID del usuario"),
    service: ExternalAIService = Depends(get_external_ai_service),
    _=Depends(require_authenticated),
):
    """
    Obtiene el detalle de una sesión con todo su historial de mensajes.
    Útil para repintar una conversación cuando el usuario la reabre.
    """
    try:
        return await service.get_session(session_id, user_id)
    except Exception as e:
        if "no existe" in str(e).lower() or "404" in str(e):
            raise HTTPException(status_code=404, detail="Sesión no encontrada")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    user_id: str = Query(..., description="ID del usuario"),
    service: ExternalAIService = Depends(get_external_ai_service),
    _=Depends(require_authenticated),
):
    """
    Elimina una sesión de chat.
    """
    try:
        await service.delete_session(session_id, user_id)
        return {"status": "deleted"}
    except Exception as e:
        if "no existe" in str(e).lower() or "404" in str(e):
            raise HTTPException(status_code=404, detail="Sesión no encontrada")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask", response_model=AskResponse)
async def ask(
    request: AskRequest,
    service: ExternalAIService = Depends(get_external_ai_service),
    _=Depends(require_authenticated),
):
    """
    Realiza una pregunta al chatbot del servicio de IA.
    Tiene memoria automática basada en el session_id.

    Timeouts: Este endpoint puede tardar hasta 180 segundos según la guía.
    """
    try:
        return await service.ask(request)
    except Exception as e:
        if "no existe" in str(e).lower() or "404" in str(e):
            raise HTTPException(status_code=404, detail="Sesión no encontrada")
        if "502" in str(e):
            raise HTTPException(status_code=502, detail="Falla del motor de grafo o del modelo")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    service: ExternalAIService = Depends(get_external_ai_service),
    _=Depends(require_authenticated),
):
    """
    Realiza una búsqueda semántica en el servicio de IA.
    Devuelve documentos rankeados por similitud semántica.

    Nota: Los nombres de archivo (documento) deben resolverse contra la base de datos
    para obtener los enlaces S3 de los PDFs originales.
    """
    try:
        return await service.search(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diagnostic", response_model=DiagnosticResponse)
async def diagnostic(
    service: ExternalAIService = Depends(get_external_ai_service),
    _=Depends(require_authenticated),
):
    """
    Obtiene información de diagnóstico del servicio de IA.
    Devuelve qué grafo está montado y cuántas entidades, relaciones y documentos tiene.

    Este endpoint es para uso administrativo y no debería exponerse al usuario final.
    """
    try:
        return await service.get_diagnostic()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
