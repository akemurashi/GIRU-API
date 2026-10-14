import httpx
import json
from typing import List, Optional, AsyncGenerator
from app.core.config import settings
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


class ExternalAIService:
    """
    Servicio para comunicarse con el servicio externo de IA GIRU.
    Maneja todas las peticiones HTTP con autenticación y timeouts apropiados.
    """

    def __init__(self):
        self.base_url = settings.GIRU_IA_URL.rstrip("/")
        self.api_key = settings.GIRU_IA_KEY
        self.headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json"
        }
        # Timeouts según la guía: 180s para /preguntar, 15s para el resto
        self.default_timeout = 10.0
        self.search_timeout = 10.0
        self.ask_timeout = 180.0

    async def _request(self, method: str, endpoint: str, data: Optional[dict] = None, timeout: Optional[float] = None) -> dict:
        """
        Método interno para realizar peticiones HTTP al servicio de IA.
        """
        if timeout is None:
            timeout = self.default_timeout

        url = f"{self.base_url}{endpoint}"

        async with httpx.AsyncClient(timeout=timeout) as client:
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
                    raise Exception("Clave de API inválida o ausente")
                elif e.response.status_code == 404:
                    raise Exception("La sesión no existe o pertenece a otro user_id")
                elif e.response.status_code == 502:
                    raise Exception("Falla del motor de grafo o del modelo")
                else:
                    raise Exception(f"Error del servicio de IA: {e.response.status_code} - {e.response.text}")

            except httpx.TimeoutException:
                raise Exception("Timeout al comunicarse con el servicio de IA")

            except httpx.RequestError as e:
                raise Exception(f"Error de conexión con el servicio de IA: {str(e)}")

    async def health_check(self) -> dict:
        """
        Verifica que el servicio de IA esté accesible.
        GET /salud
        """
        # /salud no requiere autenticación según la guía
        url = f"{self.base_url}/salud"
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                raise Exception(f"Servicio de IA no accesible: {str(e)}")

    async def create_session(self, request: CreateSessionRequest) -> CreateSessionResponse:
        """
        Crea una nueva sesión de chat.
        POST /sesiones
        """
        data = {
            "user_id": request.user_id,
            "titulo": request.titulo,
            "modo": request.modo
        }
        response = await self._request("POST", "/sesiones", data)
        return CreateSessionResponse(**response)

    async def ask(self, request: AskRequest) -> AskResponse:
        """
        Realiza una pregunta al chatbot.
        POST /preguntar
        """
        data = {
            "user_id": request.user_id,
            "session_id": request.session_id,
            "pregunta": request.pregunta
        }
        if request.modo:
            data["modo"] = request.modo
        if request.documento:
            data["documento"] = request.documento

        response = await self._request("POST", "/preguntar", data, timeout=self.ask_timeout)
        return AskResponse(**response)

    async def ask_stream(self, request: AskRequest) -> AsyncGenerator[str, None]:
        """
        Realiza una pregunta al chatbot con streaming SSE usando el nuevo endpoint /preguntar/stream.
        Reenvía el stream tal cual desde el servicio externo sin modificar el formato.
        """
        data = {
            "user_id": request.user_id,
            "session_id": request.session_id,
            "pregunta": request.pregunta
        }
        if request.modo:
            data["modo"] = request.modo
        if request.documento:
            data["documento"] = request.documento

        url = f"{self.base_url}/preguntar/stream"

        print(f"Attempting to connect to external AI service at: {url}")
        print(f"Request data: {data}")

        try:
            async with httpx.AsyncClient(timeout=self.ask_timeout) as client:
                async with client.stream("POST", url, headers=self.headers, json=data) as response:
                    print(f"Response status: {response.status_code}")
                    print(f"Response headers: {dict(response.headers)}")

                    response.raise_for_status()

                    # Stream the raw SSE data as-is
                    async for chunk in response.aiter_bytes():
                        yield chunk.decode('utf-8')

        except httpx.HTTPStatusError as e:
            print(f"HTTP Status Error: {e.response.status_code} - {e.response.text}")
            if e.response.status_code == 401:
                raise Exception("Clave de API inválida o ausente")
            elif e.response.status_code == 404:
                raise Exception("La sesión no existe o pertenece a otro user_id")
            elif e.response.status_code == 502:
                raise Exception("Falla del motor de grafo o del modelo")
            else:
                raise Exception(f"Error del servicio de IA: {e.response.status_code} - {e.response.text}")

        except httpx.TimeoutException:
            print("Timeout occurred")
            raise Exception("Timeout al comunicarse con el servicio de IA")

        except httpx.RequestError as e:
            print(f"Request Error: {str(e)}")
            raise Exception(f"Error de conexión con el servicio de IA: {str(e)}")

        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            raise Exception(f"Error inesperado: {str(e)}")

    async def search(self, request: SearchRequest) -> SearchResponse:
        """
        Realiza una búsqueda semántica.
        POST /buscar
        """
        data = {
            "consulta": request.consulta,
            "k": request.k
        }
        response = await self._request("POST", "/buscar", data, timeout=self.search_timeout)
        return SearchResponse(**response)

    async def list_sessions(self, user_id: str) -> List[SessionListItem]:
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
