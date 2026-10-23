"""Servicio para comunicarse con el servicio externo de IA GIRU."""

from collections.abc import AsyncGenerator
import logging
from typing import Any
import httpx

from app.core.config import settings
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

logger = logging.getLogger(__name__)


class ExternalAIService(object):
    """
    Servicio para comunicarse con el servicio externo de IA GIRU.
    Maneja todas las peticiones HTTP con autenticación y timeouts apropiados.
    """

    def __init__(self) -> None:
        self.base_url = settings.GIRU_IA_URL.rstrip("/")
        self.api_key = settings.GIRU_IA_KEY
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        # Timeouts según la guía v1.1: 120s para /preguntar (~20s típico), 10s para el resto
        self.default_timeout = 10.0
        self.search_timeout = 10.0
        self.ask_timeout = 120.0

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        req_timeout: float | None = None,
    ) -> dict[str, Any]:
        """Método interno para realizar peticiones HTTP al servicio de IA."""
        timeout_val = self.default_timeout if req_timeout is None else req_timeout
        url = f"{self.base_url}{endpoint}"

        async with httpx.AsyncClient(timeout=timeout_val) as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=self.headers, params=data)
                elif method == "POST":
                    response = await client.post(url, headers=self.headers, json=data)
                elif method == "DELETE":
                    response = await client.delete(url, headers=self.headers)
                else:
                    raise ValueError(f"Método HTTP no soportado: {method}")

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                # Manejo específico de códigos de error según la guía
                if e.response.status_code == 401:
                    raise RuntimeError("Clave de API inválida o ausente") from e
                if e.response.status_code == 404:
                    raise RuntimeError("La sesión no existe o pertenece a otro user_id") from e
                if e.response.status_code == 502:
                    raise RuntimeError("Falla del motor de grafo o del modelo") from e
                raise RuntimeError(
                    f"Error del servicio de IA: {e.response.status_code} - {e.response.text}"
                ) from e

            except httpx.TimeoutException as e:
                raise TimeoutError("Timeout al comunicarse con el servicio de IA") from e

            except httpx.RequestError as e:
                raise ConnectionError(f"Error de conexión con el servicio de IA: {str(e)}") from e

    async def health_check(self) -> dict[str, Any]:
        """
        Verifica que el servicio de IA esté accesible.
        GET /salud
        Nota: Al reiniciar el servicio tarda ~40s en precargar el grafo en memoria.
        """
        # /salud no requiere autenticación según la guía
        url = f"{self.base_url}/salud"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                raise ConnectionError(
                    "Servicio de IA no accesible (recordar que tras reinicio tarda ~40s en responder): "
                    f"{str(e)}"
                ) from e

    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        """
        Crea una nueva sesión de chat.
        POST /sesiones
        """
        data = {
            "user_id": request.user_id,
            "titulo": request.titulo,
            "modo": request.modo,
        }
        response = await self._request("POST", "/sesiones", data)
        return CreateSessionResponse(**response)

    async def ask(self, request: AskRequest) -> AskResponse:
        """
        Realiza una pregunta al chatbot.
        POST /preguntar
        """
        data: dict[str, Any] = {
            "user_id": request.user_id,
            "session_id": request.session_id,
            "pregunta": request.pregunta,
        }
        if request.modo:
            data["modo"] = request.modo
        if request.documento:
            data["documento"] = request.documento

        response = await self._request("POST", "/preguntar", data, req_timeout=self.ask_timeout)
        return AskResponse(**response)

    async def ask_stream(self, request: AskRequest) -> AsyncGenerator[str, None]:
        """
        Realiza una pregunta al chatbot con streaming SSE usando el nuevo endpoint /preguntar/stream.
        Reenvía el stream tal cual desde el servicio externo sin modificar el formato.
        """
        data: dict[str, Any] = {
            "user_id": request.user_id,
            "session_id": request.session_id,
            "pregunta": request.pregunta,
        }
        if request.modo:
            data["modo"] = request.modo
        if request.documento:
            data["documento"] = request.documento

        url = f"{self.base_url}/preguntar/stream"

        try:
            async with (
                httpx.AsyncClient(timeout=self.ask_timeout) as client,
                client.stream("POST", url, headers=self.headers, json=data) as response,
            ):
                response.raise_for_status()

                # Stream the raw SSE data as-is
                async for chunk in response.aiter_bytes():
                    yield chunk.decode("utf-8")

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise RuntimeError("Clave de API inválida o ausente") from e
            if e.response.status_code == 404:
                raise RuntimeError("La sesión no existe o pertenece a otro user_id") from e
            if e.response.status_code == 502:
                raise RuntimeError("Falla del motor de grafo o del modelo") from e
            raise RuntimeError(
                f"Error del servicio de IA: {e.response.status_code} - {e.response.text}"
            ) from e

        except httpx.TimeoutException as e:
            raise TimeoutError("Timeout al comunicarse con el servicio de IA") from e

        except httpx.RequestError as e:
            raise ConnectionError(f"Error de conexión con el servicio de IA: {str(e)}") from e

        except Exception as e:
            raise RuntimeError(f"Error inesperado: {str(e)}") from e

    async def search(self, request: SearchRequest) -> SearchResponse:
        """
        Realiza una búsqueda semántica.
        POST /buscar
        """
        data = {
            "consulta": request.consulta,
            "k": request.k,
        }
        response = await self._request("POST", "/buscar", data, req_timeout=self.search_timeout)
        return SearchResponse(**response)

    async def list_sessions(self, user_id: str) -> list[SessionListItem]:
        """
        Lista todas las sesiones de un usuario.
        GET /sesiones?user_id=usuario-123
        """
        response = await self._request("GET", "/sesiones", {"user_id": user_id})
        return [SessionListItem(**item) for item in response]

    async def get_session(self, session_id: str, user_id: str) -> SessionDetail:
        """
        Obtiene el detalle de una sesión con todo su historial.
        GET /sesiones/{id}?user_id=usuario-123
        """
        response = await self._request("GET", f"/sesiones/{session_id}", {"user_id": user_id})
        return SessionDetail(**response)

    async def delete_session(self, session_id: str, user_id: str) -> None:
        """
        Elimina una sesión.
        DELETE /sesiones/{id}?user_id=usuario-123
        """
        await self._request("DELETE", f"/sesiones/{session_id}", {"user_id": user_id})

    async def get_diagnostic(self) -> DiagnosticResponse:
        """
        Obtiene información de diagnóstico del servicio de IA.
        GET /diagnostico
        """
        response = await self._request("GET", "/diagnostico")
        return DiagnosticResponse(**response)
