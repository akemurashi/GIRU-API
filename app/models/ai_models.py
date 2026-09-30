from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class CreateSessionRequest(BaseModel):
    user_id: str = Field(..., description="ID del usuario")
    titulo: Optional[str] = Field(None, description="Título de la conversación")
    modo: str = Field(default="cascade", description="Modo de recuperación: cascade, local, global, agent, document")


class CreateSessionResponse(BaseModel):
    id: str = Field(..., description="ID de la sesión")
    user_id: str = Field(..., description="ID del usuario")
    titulo: str = Field(..., description="Título de la conversación")
    modo: str = Field(..., description="Modo de recuperación")
    creada: datetime = Field(..., description="Fecha de creación")
    actualizada: datetime = Field(..., description="Fecha de última actualización")


class AskRequest(BaseModel):
    user_id: str = Field(..., description="ID del usuario")
    session_id: str = Field(..., description="ID de la sesión")
    pregunta: str = Field(..., min_length=1, max_length=2000, description="Pregunta del usuario")
    modo: Optional[str] = Field(None, description="Modo de recuperación (opcional)")
    documento: Optional[str] = Field(None, description="Nombre del documento (obligatorio si modo='document')")


class Fuente(BaseModel):
    documento: str = Field(..., description="Nombre del archivo del documento")
    referencia: Optional[str] = Field(None, description="Referencia adicional")


class AskResponse(BaseModel):
    session_id: str = Field(..., description="ID de la sesión")
    respuesta: str = Field(..., description="Respuesta generada por el modelo")
    fuentes: List[Fuente] = Field(default_factory=list, description="Fuentes citadas")
    modo: str = Field(..., description="Modo de recuperación utilizado")
    tiempo_s: float = Field(..., description="Tiempo de procesamiento en segundos")
    llamadas_llm: int = Field(..., description="Número de llamadas al LLM")


class SearchRequest(BaseModel):
    consulta: str = Field(..., min_length=1, description="Consulta de búsqueda")
    k: int = Field(default=10, ge=1, le=50, description="Número de resultados a devolver")


class SearchResult(BaseModel):
    documento: str = Field(..., description="Nombre del archivo del documento")
    puntaje: float = Field(..., ge=0.0, le=1.0, description="Puntaje de similitud coseno")
    entidades: List[str] = Field(default_factory=list, description="Entidades del grafo que gatillaron la coincidencia")


class SearchResponse(BaseModel):
    consulta: str = Field(..., description="Consulta realizada")
    resultados: List[SearchResult] = Field(default_factory=list, description="Resultados de la búsqueda")


class ChatMessage(BaseModel):
    rol: str = Field(..., description="Rol del mensaje: user o assistant")
    contenido: str = Field(..., description="Contenido del mensaje")
    creado: datetime = Field(..., description="Fecha de creación")
    meta: Optional[dict] = Field(None, description="Metadatos adicionales")


class SessionDetail(BaseModel):
    id: str = Field(..., description="ID de la sesión")
    titulo: str = Field(..., description="Título de la conversación")
    modo: str = Field(..., description="Modo de recuperación")
    mensajes: List[ChatMessage] = Field(default_factory=list, description="Historial de mensajes")


class SessionListItem(BaseModel):
    id: str = Field(..., description="ID de la sesión")
    user_id: str = Field(..., description="ID del usuario")
    titulo: str = Field(..., description="Título de la conversación")
    modo: str = Field(..., description="Modo de recuperación")
    creada: datetime = Field(..., description="Fecha de creación")
    actualizada: datetime = Field(..., description="Fecha de última actualización")


class DiagnosticResponse(BaseModel):
    grafo: str = Field(..., description="Tipo de grafo montado")
    entidades: int = Field(..., description="Número de entidades")
    relaciones: int = Field(..., description="Número de relaciones")
    documentos: int = Field(..., description="Número de documentos")
