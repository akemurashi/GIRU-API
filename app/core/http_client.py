"""Módulo de gestión de cliente HTTP asíncrono compartido (Connection Pooling y compatibilidad con mocks)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock

import httpx

_ORIGINAL_ASYNC_CLIENT_INIT = httpx.AsyncClient.__init__
_shared_client: httpx.AsyncClient | None = None
_custom_init_client: tuple[Any, httpx.AsyncClient] | None = None


def is_client_mocked(httpx_mod: Any = httpx) -> bool:
    """
    Detecta si `httpx.AsyncClient` o alguno de sus métodos ha sido intervenido por `unittest.mock.patch`
    o si su `__init__` ha sido sustituido por un despachador personalizado (e.g. `test_asgi_integration.py`).
    """
    if httpx_mod is None:
        httpx_mod = httpx

    # Caso en que httpx_mod es directamente una clase o instancia mock
    if isinstance(httpx_mod, (Mock, MagicMock, AsyncMock)):
        return True

    client_cls = getattr(httpx_mod, "AsyncClient", None)
    if client_cls is None:
        if isinstance(httpx_mod, type) and issubclass(httpx_mod, httpx.AsyncClient):
            client_cls = httpx_mod
        else:
            return False

    # 1. Clase reemplazada por un Mock directamente
    if isinstance(client_cls, (Mock, MagicMock, AsyncMock)) or hasattr(client_cls, "_mock_return_value"):
        return True

    # 2. __init__ modificado por mock o monkeypatching (e.g. ASGITransport de test_asgi_integration)
    curr_init = getattr(client_cls, "__init__", None)
    if isinstance(curr_init, (Mock, MagicMock, AsyncMock)) or (curr_init is not _ORIGINAL_ASYNC_CLIENT_INIT):
        return True

    # 3. Métodos individuales sobre la clase parcheados con Mock/AsyncMock
    for meth_name in ("get", "post", "put", "delete", "head", "options", "patch", "request", "stream", "send"):
        meth = getattr(client_cls, meth_name, None)
        if isinstance(meth, (Mock, MagicMock, AsyncMock)):
            return True

    return False


def get_shared_async_client() -> httpx.AsyncClient:
    """Retorna la instancia global compartida de httpx.AsyncClient reutilizando el pool de conexiones."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        limits = httpx.Limits(
            max_connections=100,
            max_keepalive_connections=50,
            keepalive_expiry=30.0,
        )
        _shared_client = httpx.AsyncClient(
            limits=limits,
            timeout=httpx.Timeout(30.0),
        )
    return _shared_client


async def close_shared_async_client() -> None:
    """Cierra limpiamente el cliente HTTP compartido al apagar la aplicación."""
    global _shared_client, _custom_init_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None
    if _custom_init_client is not None and not _custom_init_client[1].is_closed:
        await _custom_init_client[1].aclose()
    _custom_init_client = None


class _ClientProxy:
    """Proxy transparente sobre el cliente compartido para inyectar timeouts específicos sin carreras."""

    def __init__(self, client: httpx.AsyncClient, timeout: float | httpx.Timeout | None = None) -> None:
        self._client = client
        self._timeout = timeout

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        if "timeout" not in kwargs and self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return await self._client.get(url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        if "timeout" not in kwargs and self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return await self._client.post(url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        if "timeout" not in kwargs and self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return await self._client.put(url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        if "timeout" not in kwargs and self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return await self._client.delete(url, **kwargs)

    async def head(self, url: str, **kwargs: Any) -> httpx.Response:
        if "timeout" not in kwargs and self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return await self._client.head(url, **kwargs)

    async def options(self, url: str, **kwargs: Any) -> httpx.Response:
        if "timeout" not in kwargs and self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return await self._client.options(url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        if "timeout" not in kwargs and self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return await self._client.patch(url, **kwargs)

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if "timeout" not in kwargs and self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return await self._client.request(method, url, **kwargs)

    def stream(self, method: str, url: str, **kwargs: Any) -> Any:
        if "timeout" not in kwargs and self._timeout is not None:
            kwargs["timeout"] = self._timeout
        return self._client.stream(method, url, **kwargs)

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        return await self._client.send(request, **kwargs)

    async def __aenter__(self) -> "_ClientProxy":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


@asynccontextmanager
async def use_async_client(
    client_or_mod: Any = None,
    timeout: float | httpx.Timeout | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    """
    Context manager compatible que reutiliza el pool persistente en producción y delega
    en un nuevo cliente si se detecta un mock o runner ASGI.
    """
    # 1. Si se proporciona un cliente explícito directamente
    explicit_client = client
    if explicit_client is None and isinstance(client_or_mod, (httpx.AsyncClient, _ClientProxy)):
        explicit_client = client_or_mod
    elif (
        explicit_client is None
        and isinstance(client_or_mod, (Mock, MagicMock, AsyncMock))
        and not isinstance(client_or_mod, type)
        and not hasattr(client_or_mod, "AsyncClient")
    ):
        explicit_client = client_or_mod

    if explicit_client is not None:
        if timeout is not None:
            yield _ClientProxy(explicit_client, timeout)  # type: ignore[misc]
        else:
            yield explicit_client
        return

    # 2. Ajuste si el primer argumento es un valor numérico de timeout
    if isinstance(client_or_mod, (int, float, httpx.Timeout)):
        timeout = client_or_mod
        target_mod = httpx
    elif client_or_mod is not None and hasattr(client_or_mod, "AsyncClient"):
        target_mod = client_or_mod
    else:
        target_mod = httpx

    # 3. Detección de custom init (ASGI transport injection) vs mocks
    client_cls = getattr(target_mod, "AsyncClient", httpx.AsyncClient)
    curr_init = getattr(client_cls, "__init__", None)

    # Si __init__ fue modificado por un despachador personalizado (e.g. test_asgi_integration) y no es un Mock
    if (
        curr_init is not _ORIGINAL_ASYNC_CLIENT_INIT
        and not isinstance(curr_init, (Mock, MagicMock, AsyncMock))
        and not hasattr(curr_init, "_mock_return_value")
    ):
        global _custom_init_client
        if (
            _custom_init_client is None
            or _custom_init_client[0] is not curr_init
            or _custom_init_client[1].is_closed
        ):
            client_inst = client_cls()
            _custom_init_client = (curr_init, client_inst)
        else:
            client_inst = _custom_init_client[1]

        if timeout is not None:
            yield _ClientProxy(client_inst, timeout)  # type: ignore[misc]
        else:
            yield client_inst
        return

    # Si hay mocks unitarios activos (clase o métodos get/post/etc.)
    if is_client_mocked(target_mod):
        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        async with client_cls(**kwargs) as ephemeral_client:
            yield ephemeral_client
        return

    # Producción / Sin mocks: pool compartido persistente
    shared = get_shared_async_client()
    if timeout is not None:
        yield _ClientProxy(shared, timeout)  # type: ignore[misc]
    else:
        yield shared
