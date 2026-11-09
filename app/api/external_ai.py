"""API Router para interactuar con el microservicio externo de IA (RAG, Chatbot y Grafo)."""

import json
from collections.abc import AsyncGenerator
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from app.models.ai_models import (
    AskRequest,
    AskResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    DiagnosticResponse,
    SearchRequest,
    SearchResponse,
    SessionDetail,
    SessionListItem,
)
from app.models.user_models import UserOut
from app.security.microsoft_auth import (
    get_authenticated_user_id,
    require_admin,
    require_authenticated,
)
from app.services.external_ai_service import ExternalAIService

router = APIRouter()

USER_ID_DESC = "ID del usuario"
ERR_NOT_FOUND_SUBSTR = "no existe"
ERR_SESSION_NOT_FOUND = "Sesión no encontrada"

# Alias para compatibilidad con modulos dependientes y tests
_get_authenticated_user_id = get_authenticated_user_id


_shared_external_ai_service: ExternalAIService | None = None


async def get_external_ai_service() -> ExternalAIService:
    """Provee una instancia del cliente del servicio externo de IA."""
    global _shared_external_ai_service
    if _shared_external_ai_service is None:
        _shared_external_ai_service = ExternalAIService()
    return _shared_external_ai_service


@router.get(
    "/health",
    responses={503: {"description": "Servicio de IA no disponible"}}
)
async def health_check(
    service: ExternalAIService = Depends(get_external_ai_service)
) -> dict[str, Any]:
    """
    Verifica que el servicio externo de IA esté accesible.
    Este endpoint no requiere autenticación.
    """
    try:
        return await service.health_check()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Servicio de IA no disponible: {str(e)}")


@router.post(
    "/sessions",
    responses={500: {"description": "Error interno del servidor de IA"}}
)
async def create_session(
    request: CreateSessionRequest,
    service: ExternalAIService = Depends(get_external_ai_service),
    current_user: UserOut = Depends(require_authenticated),
) -> CreateSessionResponse:
    """
    Crea una nueva sesión de chat con el servicio de IA.
    Guarda el session_id para usarlo en preguntas posteriores.
    """
    try:
        request.user_id = _get_authenticated_user_id(current_user)
        return await service.create_session(request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/sessions",
    responses={500: {"description": "Error al listar las sesiones del usuario"}}
)
async def list_sessions(
    user_id: str | None = Query(None, description=USER_ID_DESC),
    service: ExternalAIService = Depends(get_external_ai_service),
    current_user: UserOut = Depends(require_authenticated),
) -> list[SessionListItem]:
    """Lista todas las sesiones del usuario autenticado."""
    try:
        authenticated_user_id = _get_authenticated_user_id(current_user)
        return await service.list_sessions(authenticated_user_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/sessions/{session_id}",
    responses={
        404: {"description": ERR_SESSION_NOT_FOUND},
        500: {"description": "Error al recuperar el detalle de la sesión"}
    }
)
async def get_session(
    session_id: str,
    user_id: str | None = Query(None, description=USER_ID_DESC),
    service: ExternalAIService = Depends(get_external_ai_service),
    current_user: UserOut = Depends(require_authenticated),
) -> SessionDetail:
    """
    Obtiene el detalle de una sesión con todo su historial de mensajes.
    Útil para repintar una conversación cuando el usuario la reabre.
    """
    try:
        authenticated_user_id = _get_authenticated_user_id(current_user)
        return await service.get_session(session_id, authenticated_user_id)
    except HTTPException:
        raise
    except Exception as e:
        if ERR_NOT_FOUND_SUBSTR in str(e).lower() or "404" in str(e):
            raise HTTPException(status_code=404, detail=ERR_SESSION_NOT_FOUND)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/sessions/{session_id}",
    responses={
        404: {"description": ERR_SESSION_NOT_FOUND},
        500: {"description": "Error al eliminar la sesión"}
    }
)
async def delete_session(
    session_id: str,
    user_id: str | None = Query(None, description=USER_ID_DESC),
    service: ExternalAIService = Depends(get_external_ai_service),
    current_user: UserOut = Depends(require_authenticated),
) -> dict[str, str]:
    """Elimina una sesión de chat."""
    try:
        authenticated_user_id = _get_authenticated_user_id(current_user)
        await service.delete_session(session_id, authenticated_user_id)
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        if ERR_NOT_FOUND_SUBSTR in str(e).lower() or "404" in str(e):
            raise HTTPException(status_code=404, detail=ERR_SESSION_NOT_FOUND)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/ask",
    responses={
        404: {"description": ERR_SESSION_NOT_FOUND},
        502: {"description": "Falla del motor de grafo o del modelo de IA"},
        500: {"description": "Error al procesar la consulta en IA"}
    }
)
async def ask(
    request: AskRequest,
    service: ExternalAIService = Depends(get_external_ai_service),
    current_user: UserOut = Depends(require_authenticated),
) -> AskResponse:
    """
    Realiza una pregunta al chatbot del servicio de IA.
    Tiene memoria automática basada en el session_id.

    Timeouts: Latencia típica ~20 segundos; timeout configurado a 120 segundos.
    """
    try:
        request.user_id = _get_authenticated_user_id(current_user)
        return await service.ask(request)
    except HTTPException:
        raise
    except Exception as e:
        if ERR_NOT_FOUND_SUBSTR in str(e).lower() or "404" in str(e):
            raise HTTPException(status_code=404, detail=ERR_SESSION_NOT_FOUND)
        if "502" in str(e):
            raise HTTPException(status_code=502, detail="Falla del motor de grafo o del modelo")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask-stream")
async def ask_stream(
    request: AskRequest,
    service: ExternalAIService = Depends(get_external_ai_service),
    current_user: UserOut = Depends(require_authenticated),
) -> StreamingResponse:
    """
    Realiza una pregunta al chatbot del servicio de IA con streaming SSE.
    Reenvía el stream tal cual desde el servicio externo sin modificar el formato.
    """
    request.user_id = _get_authenticated_user_id(current_user)

    async def generate() -> AsyncGenerator[str, None]:
        """Generador asíncrono para emitir eventos de streaming SSE."""
        try:
            # Forward the stream as-is from external AI service
            async for chunk in service.ask_stream(request):
                yield chunk
        except Exception as e:
            # Yield error in SSE format
            yield f"event: error\ndata: {json.dumps({'mensaje': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post(
    "/search",
    responses={500: {"description": "Error al realizar la búsqueda semántica en IA"}}
)
async def search(
    request: SearchRequest,
    service: ExternalAIService = Depends(get_external_ai_service),
    _: UserOut = Depends(require_authenticated),
) -> SearchResponse:
    """
    Realiza una búsqueda semántica en el servicio de IA.
    Devuelve documentos rankeados por similitud semántica.

    Nota: Los nombres de archivo (documento) deben resolverse contra la base de datos
    para obtener los enlaces S3 de los PDFs originales.
    """
    try:
        return await service.search(request)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/diagnostic",
    responses={
        403: {"description": "Acceso restringido a administradores"},
        500: {"description": "Error al consultar diagnósticos de IA"}
    }
)
async def diagnostic(
    service: ExternalAIService = Depends(get_external_ai_service),
    admin: UserOut = Depends(require_admin),
) -> DiagnosticResponse:
    """
    Obtiene información de diagnóstico del servicio de IA.
    Devuelve qué grafo está montado y cuántas entidades, relaciones y documentos tiene.

    Este endpoint es para uso administrativo y no debería exponerse al usuario final.
    """
    try:
        return await service.get_diagnostic()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
