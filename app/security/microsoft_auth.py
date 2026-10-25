"""Módulo de autenticación y autorización mediante AWS Cognito y Microsoft SSO."""

from typing import Any
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2AuthorizationCodeBearer
import httpx
from jose import JWTError, jwt

from app.core.config import settings
from app.models.user_models import UserOut, UserRole

# Mapeo de grupos de Azure AD a roles internos
# Nota: Ahora Cognito te entregará estos IDs (o nombres) en un atributo del token
# si configuraste el mapeo de atributos (Attribute Mapping) en AWS.
AZURE_GROUP_ROLE_MAP = {
    "AZURE_GROUP_ID_ADMIN": UserRole.ADMIN,
    "AZURE_GROUP_ID_BASIC": UserRole.BASIC,
}

# Configuramos el candado verde para usar el flujo de OAuth2 directamente en Swagger UI.
# authorizationUrl apunta directo a Cognito
# tokenUrl apunta a nuestro backend (interceptamos la llamada de Swagger)
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"https://{settings.COGNITO_DOMAIN}/oauth2/authorize",
    tokenUrl="/api/v1/auth/docs-token",
)

ADMIN_LIST = [email.strip().lower() for email in settings.ADMIN_EMAILS.split(",") if email.strip()]


class CognitoAuth(object):
    """
    Autenticación vía AWS Cognito (que por detrás usa Microsoft SSO).
    El rol se determina por los atributos mapeados en el JWT de Cognito.
    """

    def __init__(self) -> None:
        self.region = settings.AWS_REGION
        self.user_pool_id = settings.COGNITO_USER_POOL_ID
        self.client_id = settings.COGNITO_CLIENT_ID
        self.cognito_domain = settings.COGNITO_DOMAIN
        # URL donde residen las llaves públicas de Cognito para validar firmas JWT
        self.jwks_url = f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}/.well-known/jwks.json"

    def get_login_url(self) -> str:
        """Genera la URL para el Hosted UI de Cognito en lugar del de Microsoft."""
        redirect_uri = settings.COGNITO_REDIRECT_URI

        return (
            f"https://{self.cognito_domain}/oauth2/authorize"
            f"?client_id={self.client_id}&response_type=code"
            f"&scope=openid+email+profile"
            f"&redirect_uri={redirect_uri}"
            f"&identity_provider=EntraID"
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """
        Intercambia el código de autorización por los tokens de Cognito.
        Reemplaza a la implementación de MSAL.
        """
        token_url = f"https://{self.cognito_domain}/oauth2/token"

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Error intercambiando código con Cognito")

            # Devuelve access_token y id_token
            return response.json()

    @staticmethod
    def _resolve_role(groups: list[str]) -> UserRole:
        """Determina el rol interno según los grupos mapeados."""
        resolved = UserRole.BASIC
        if groups:
            for group_id, role in AZURE_GROUP_ROLE_MAP.items():
                if group_id in groups:
                    resolved = role
                    if role == UserRole.ADMIN:
                        break
        return resolved

    async def get_current_user(self, token: str = Depends(oauth2_scheme)) -> UserOut:
        """Dependency: valida JWT de Cognito y devuelve el usuario."""
        try:
            # 1. Obtener las llaves públicas de Cognito
            async with httpx.AsyncClient() as client:
                jwks_resp = await client.get(self.jwks_url)
                jwks = jwks_resp.json()

            # 2. Decodificar y validar el JWT usando python-jose
            # Validará automáticamente la firma, la expiración (exp) y el emisor (iss)
            # Dependiendo si usas id_token o access_token, el audience puede variar en Cognito
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                audience=self.client_id,
                options={
                    "verify_aud": False,
                    "verify_at_hash": False,
                },
            )

            # 3. Extraer datos (Cognito inyecta estos campos basándose en Azure)
            email = payload.get("email") or payload.get("unique_name") or payload.get("preferred_username")
            given_name = payload.get("given_name", "")
            family_name = payload.get("family_name", "")

            # Armamos el nombre completo. Si por alguna razón vienen vacíos, dejamos un valor por defecto.
            if given_name or family_name:
                name = f"{given_name} {family_name}".strip()
            else:
                name = "Usuario"

            # Si email es None, intentar obtener de otros campos o usar un valor por defecto
            if not email:
                email = payload.get("sub", "unknown@example.com")

            # Los grupos dependen de cómo mapeaste "GroupMember.Read.All" en Cognito.
            # A veces llega en "cognito:groups" o en un atributo custom como "custom:azure_groups"
            azure_groups = payload.get("custom:azure_groups", [])
            if isinstance(azure_groups, str):
                # Ajustar según como llegue el string
                azure_groups = azure_groups.split(",")

            role = self._resolve_role(azure_groups)

            # Override role if email is in ADMIN_LIST from .env config
            if isinstance(email, str) and email.lower() in ADMIN_LIST:
                role = UserRole.ADMIN

            return UserOut(email=email, name=name, role=role)

        except JWTError as e:
            raise HTTPException(status_code=401, detail=f"Token inválido o expirado: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────────
# Dependencies de autorización por rol
# ─────────────────────────────────────────────────────────────────────────────

auth_service = CognitoAuth()


def require_admin(user: UserOut = Depends(auth_service.get_current_user)) -> UserOut:
    """Solo permite paso a usuarios con rol ADMIN o correos autorizados en .env."""
    if user.role not in (UserRole.ADMIN, "admin"):
        raise HTTPException(status_code=403, detail="Acceso restringido a administradores")
    return user


def require_authenticated(user: UserOut = Depends(auth_service.get_current_user)) -> UserOut:
    """Permite paso a cualquier usuario autenticado."""
    return user
