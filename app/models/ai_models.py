"""Modelos de datos para la API de Inteligencia Artificial (RAG y Chat)."""

from datetime import datetime
from pydantic import BaseModel, Field

# Constantes para descripciones repetidas de campos
DESC_USER_ID = "ID del usuario"
DESC_SESSION_ID = "ID de la sesión"
DESC_CONV_TITLE = "Título de la conversación"
DESC_RECOVERY_MODE = "Modo de recuperación"
DESC_CREATION_DATE = "Fecha de creación"


class CreateSessionRequest(BaseModel):
    """Solicitud para crear una nueva sesión de conversación."""

    user_id: str = Field(..., description=DESC_USER_ID)
    titulo: str | None = Field(None, description=DESC_CONV_TITLE)
    modo: str = Field(
        default="cascade",
        description="Modo de recuperación: cascade, local, global, agent, document"
    )


class CreateSessionResponse(BaseModel):
    """Respuesta con los metadatos de la sesión creada."""

    id: str = Field(..., description=DESC_SESSION_ID)
    user_id: str = Field(..., description=DESC_USER_ID)
    titulo: str = Field(..., description=DESC_CONV_TITLE)
    modo: str = Field(..., description=DESC_RECOVERY_MODE)
    creada: datetime = Field(..., description=DESC_CREATION_DATE)
    actualizada: datetime = Field(..., description="Fecha de última actualización")


class AskRequest(BaseModel):
    """Solicitud de consulta o pregunta al chatbot."""

    user_id: str = Field(..., description=DESC_USER_ID)
    session_id: str = Field(..., description=DESC_SESSION_ID)
    pregunta: str = Field(..., min_length=1, max_length=2000, description="Pregunta del usuario")
    modo: str | None = Field(None, description="Modo de recuperación (opcional)")
    documento: str | None = Field(
        None,
        description="Nombre del documento (obligatorio si modo='document')"
    )


class Fuente(BaseModel):
    """Cita o fragmento de documento que respalda la respuesta generada."""

    documento: str = Field(..., description="Nombre del archivo del documento")
    referencia: str | None = Field(
        None,
        description="Identificador interno obsoleto (siempre null, no utilizar)"
    )
    fragmento: str | None = Field(
        None,
        description="Texto literal del documento que respalda la respuesta (verificado)"
    )


class AskResponse(BaseModel):
    """Respuesta generada por el modelo de lenguaje junto a sus fuentes."""

    session_id: str = Field(..., description=DESC_SESSION_ID)
    respuesta: str = Field(..., description="Respuesta generada por el modelo")
    fuentes: list[Fuente] = Field(
        default_factory=list,
        description="Fuentes citadas (máximo 5, ordenadas por relevancia)"
    )
    modo: str = Field(..., description=DESC_RECOVERY_MODE)
    tiempo_s: float = Field(..., description="Tiempo de procesamiento en segundos")
    llamadas_llm: int = Field(..., description="Número de llamadas al LLM")


class SearchRequest(BaseModel):
    """Solicitud de búsqueda semántica simple."""

    consulta: str = Field(..., min_length=1, description="Consulta de búsqueda")
    k: int = Field(default=50, ge=1, le=100, description="Número de resultados a devolver (1 a 100)")


class SearchResult(BaseModel):
    """Resultado individual de búsqueda con su puntaje de relevancia."""

    documento: str = Field(..., description="Nombre del archivo del documento")
    puntaje: float = Field(..., description="Puntaje de relevancia para ordenamiento")
    entidades: list[str] | None = Field(
        default_factory=list,
        description="Entidades (opcional/obsoleto en v2)"
    )


class SearchResponse(BaseModel):
    """Lista de resultados retornados tras una búsqueda."""

    consulta: str = Field(..., description="Consulta realizada")
    resultados: list[SearchResult] = Field(
        default_factory=list,
        description="Resultados de la búsqueda"
    )


class ChatMessage(BaseModel):
    """Mensaje individual en el historial de conversación."""

    rol: str = Field(..., description="Rol del mensaje: user o assistant")
    contenido: str = Field(..., description="Contenido del mensaje")
    creado: datetime = Field(..., description=DESC_CREATION_DATE)
    meta: dict | None = Field(None, description="Metadatos adicionales")


class SessionDetail(BaseModel):
    """Detalle completo de una sesión de conversación con su historial."""

    id: str = Field(..., description=DESC_SESSION_ID)
    titulo: str = Field(..., description=DESC_CONV_TITLE)
    modo: str = Field(..., description=DESC_RECOVERY_MODE)
    mensajes: list[ChatMessage] = Field(
        default_factory=list,
        description="Historial de mensajes"
    )


class SessionListItem(BaseModel):
    """Elemento resumido de sesión para listados de usuario."""

    id: str = Field(..., description=DESC_SESSION_ID)
    user_id: str = Field(..., description=DESC_USER_ID)
    titulo: str = Field(..., description=DESC_CONV_TITLE)
    modo: str = Field(..., description=DESC_RECOVERY_MODE)
    creada: datetime = Field(..., description=DESC_CREATION_DATE)
    actualizada: datetime = Field(..., description="Fecha de última actualización")


class DiagnosticResponse(BaseModel):
    """Estado y métricas de diagnóstico del grafo de conocimiento."""

    grafo: str = Field(..., description="Tipo de grafo montado")
    entidades: int = Field(..., description="Número de entidades")
    relaciones: int = Field(..., description="Número de relaciones")
    documentos: int = Field(..., description="Número de documentos")
