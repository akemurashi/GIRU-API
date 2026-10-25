"""Servicio para resolución y firma de URLs de documentos almacenados en AWS S3."""

from typing import Any
from fastapi import HTTPException
import httpx

from app.core.config import settings


def normalize_s3_key(value: str) -> str:
    """Deja la ruta en el formato que exige la API: raw/uploads/..."""
    key = value.strip()
    if key.startswith("s3://"):
        parts = key.split("/", 3)
        key = parts[3] if len(parts) == 4 else ""
    return key.lstrip("/")


async def get_signed_url(s3_key: str, token: str) -> dict[str, Any]:
    """Pide a la API de AWS una URL temporal firmada para acceder al PDF."""
    if not settings.DOCUMENT_SIGNER_URL:
        raise HTTPException(status_code=503, detail="Servicio de documentos no configurado")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                settings.DOCUMENT_SIGNER_URL,
                json={"key": normalize_s3_key(s3_key)},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="No se pudo contactar el servicio de documentos")

    # 200: todo bien; devuelve {"url": "...", "expires_in": 600}
    if response.status_code == 200:
        return response.json()
    # 401: el token expiró o es inválido; el frontend debe renovar la sesión
    if response.status_code == 401:
        raise HTTPException(status_code=401, detail="Sesion expirada")
    # 404: la ruta es válida pero el archivo no existe en S3
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Archivo no encontrado en el almacenamiento")
    # 400: la ruta no cumple las reglas (por ejemplo, no es un .pdf)
    if response.status_code == 400:
        raise HTTPException(status_code=422, detail="Documento no visualizable")
    # Cualquier otro código (429, 500, etc.): falla del servicio externo
    raise HTTPException(status_code=502, detail="No se pudo obtener el documento")
