from fastapi import APIRouter, HTTPException, Depends, Query, Form
from pydantic import BaseModel
from app.security.microsoft_auth import auth_service
from app.models.user_models import UserOut

router = APIRouter()

class TokenRequest(BaseModel):
    code: str
    redirect_uri: str

class TokenResponse(BaseModel):
    access_token: str
    id_token: str
    token_type: str = "Bearer"
    expires_in: int
    refresh_token: str | None = None # Cognito puede enviarlo opcionalmente

@router.get("/login-url")
def get_login_url():
    """URL de Cognito (SSO) para redirigir al usuario."""
    return {"url": auth_service.get_login_url()}


@router.post("/callback", response_model=TokenResponse)
async def auth_callback(body: TokenRequest):
    """
    Recibe el código OAuth de Cognito (enviado por el frontend).
    Intercambia el código por los tokens nativos de Cognito.
    """
    try:
        # Devuelve el dict crudo de Cognito, el cual coincide con TokenResponse
        return await auth_service.exchange_code(body.code, body.redirect_uri) 
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

@router.get("/me", response_model=UserOut)
async def get_current_user(user: UserOut = Depends(auth_service.get_current_user)):
    """Devuelve datos del usuario activo incluyendo su rol."""
    return user

@router.post("/docs-token", include_in_schema=False)
async def swagger_oauth_token_exchange(
    grant_type: str = Form(...),
    code: str = Form(None), 
    redirect_uri: str = Form(None),
    client_id: str = Form(None)
):
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
