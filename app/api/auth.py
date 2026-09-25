from fastapi import APIRouter, HTTPException, Depends, Query
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