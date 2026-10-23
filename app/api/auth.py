"""API Router para autenticación con SSO de AWS Cognito / Microsoft Azure AD."""

from typing import Any
from fastapi import APIRouter, Depends, Form, HTTPException
from pydantic import BaseModel
from app.models.user_models import UserOut
from app.security.microsoft_auth import auth_service

router = APIRouter()


class TokenRequest(BaseModel):
    """Payload de solicitud de token con código OAuth de autorización."""

    code: str
    redirect_uri: str


class TokenResponse(BaseModel):
    """Estructura de respuesta con tokens de acceso e identidad de Cognito."""

    access_token: str
    id_token: str
    token_type: str = "Bearer"
    expires_in: int
    # Cognito puede enviarlo opcionalmente
    refresh_token: str | None = None


@router.get("/login-url")
def get_login_url() -> dict[str, str]:
    """URL de Cognito (SSO) para redirigir al usuario."""
    return {"url": auth_service.get_login_url()}


@router.post(
    "/callback",
    responses={401: {"description": "Error en el intercambio de código OAuth con Cognito"}}
)
async def auth_callback(body: TokenRequest) -> TokenResponse:
    """
    Recibe el código OAuth de Cognito (enviado por el frontend).
    Intercambia el código por los tokens nativos de Cognito.
    """
    try:
        # Devuelve el dict crudo de Cognito, el cual coincide con TokenResponse
        return await auth_service.exchange_code(body.code, body.redirect_uri)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@router.get("/me")
async def get_current_user(user: UserOut = Depends(auth_service.get_current_user)) -> UserOut:
    """Devuelve datos del usuario activo incluyendo su rol."""
    return user


@router.post(
    "/docs-token",
    include_in_schema=False,
    responses={401: {"description": "Error en el intercambio de token para Swagger"}}
)
async def swagger_oauth_token_exchange(
    grant_type: str = Form(...),
    code: str = Form(None),
    redirect_uri: str = Form(None),
    client_id: str = Form(None)
) -> dict[str, Any]:
    """
    IMPORTANTE: Endpoint exclusivo para que Swagger UI obtenga el id_token.
    Swagger UI por defecto busca 'access_token', pero nosotros necesitamos el 'id_token'
    para validar el usuario (emails, grupos).
    """
    try:
        # Usamos exchange_code con el redirect_uri que envió Swagger UI
        # (usualmente http://localhost:8000/docs/oauth2-redirect)
        tokens = await auth_service.exchange_code(code, redirect_uri)

        # Le enviamos el id_token ocupando el lugar de access_token para que Swagger lo use en el header Bearer
        return {
            "access_token": tokens.get("id_token"),
            "token_type": "bearer"
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
