"""Módulo de autenticación y autorización mediante AWS Cognito y Microsoft SSO."""

import asyncio
import logging
import re
import time
from typing import Any
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2AuthorizationCodeBearer
import httpx
from jose import JWTError, jwt

from app.core.config import settings
from app.core.http_client import use_async_client
from app.models.user_models import UserOut, UserRole

logger = logging.getLogger(__name__)

# Mapeo de grupos de Azure AD a roles internos
# Nota: Ahora Cognito te entregará estos IDs (o nombres) en un atributo del token
# si configuraste el mapeo de atributos (Attribute Mapping) en AWS.
AZURE_GROUP_ROLE_MAP = {
    "AZURE_GROUP_ID_ADMIN": UserRole.ADMIN,
    "AZURE_GROUP_ID_BASIC": UserRole.BASIC,
}

HTTPS_PREFIX: str = "https://"


def _clean_domain(domain: str) -> str:
    """Elimina prefijos de protocolo http(s) y barras diagonales de un dominio."""
    return re.sub(r"^https?://", "", domain).strip("/")


# Configuramos el candado verde para usar el flujo de OAuth2 directamente en Swagger UI.
# authorizationUrl apunta directo a Cognito
# tokenUrl apunta a nuestro backend (interceptamos la llamada de Swagger)
_normalized_domain = _clean_domain(settings.COGNITO_DOMAIN)
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{HTTPS_PREFIX}{_normalized_domain}/oauth2/authorize",
    tokenUrl="/api/v1/auth/docs-token",
)

ADMIN_LIST = [email.strip().lower() for email in settings.ADMIN_EMAILS.split(",") if email.strip()]


class CognitoAuth(object):
    """
    Autenticación vía AWS Cognito (que por detrás usa Microsoft SSO).
    El rol se determina por los atributos mapeados en el JWT de Cognito.
    """

    def __init__(self) -> None:
        self.user_pool_id = settings.COGNITO_USER_POOL_ID
        self.region = settings.AWS_REGION or (
            self.user_pool_id.split("_")[0] if "_" in self.user_pool_id else "us-east-1"
        )
        self.client_id = settings.COGNITO_CLIENT_ID
        self.cognito_domain = _clean_domain(settings.COGNITO_DOMAIN)
        # URL donde residen las llaves públicas de Cognito para validar firmas JWT
        self.jwks_url = (
            f"{HTTPS_PREFIX}cognito-idp.{self.region}.amazonaws.com/"
            f"{self.user_pool_id}/.well-known/jwks.json"
        )

        # Caché en memoria de llaves públicas JWKS
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_cache_time: float = 0.0
        # 1 hora (3600s)
        self._jwks_ttl: float = 3600.0
        self._verified_token_cache: dict[str, tuple[float, UserOut]] = {}
        self._lock: asyncio.Lock | None = None

    @property
    def lock(self) -> asyncio.Lock:
        """Lock perezoso asociado al event loop activo para evitar conflictos entre tests."""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._lock is None or (
            current_loop is not None and getattr(self._lock, "_loop", None) not in (None, current_loop)
        ):
            self._lock = asyncio.Lock()
        return self._lock

    @property
    def valid_issuers(self) -> set[str]:
        """Conjunto de emisores (iss) válidos esperados para los tokens."""
        issuers: set[str] = set()
        region = self.region or (self.user_pool_id.split("_")[0] if "_" in self.user_pool_id else "us-east-1")
        if self.user_pool_id:
            cognito_iss = f"{HTTPS_PREFIX}cognito-idp.{region}.amazonaws.com/{self.user_pool_id}"
            issuers.update({cognito_iss, f"{cognito_iss}/"})
            if self.region:
                r_iss = f"{HTTPS_PREFIX}cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"
                issuers.update({r_iss, f"{r_iss}/"})
        if self.cognito_domain:
            domain = _clean_domain(self.cognito_domain)
            issuers.update({f"{HTTPS_PREFIX}{domain}", f"{HTTPS_PREFIX}{domain}/"})
        azure_tenant = getattr(settings, "AZURE_TENANT_ID", "")
        if azure_tenant:
            issuers.update({
                f"{HTTPS_PREFIX}login.microsoftonline.com/{azure_tenant}/v2.0",
                f"{HTTPS_PREFIX}login.microsoftonline.com/{azure_tenant}/v2.0/",
                f"{HTTPS_PREFIX}sts.windows.net/{azure_tenant}/",
                f"{HTTPS_PREFIX}sts.windows.net/{azure_tenant}",
            })
        return issuers

    def get_login_url(self) -> str:
        """Genera la URL para el Hosted UI de Cognito en lugar del de Microsoft."""
        redirect_uri = settings.COGNITO_REDIRECT_URI

        return (
            f"{HTTPS_PREFIX}{self.cognito_domain}/oauth2/authorize"
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
        token_url = f"{HTTPS_PREFIX}{self.cognito_domain}/oauth2/token"

        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        async with use_async_client(httpx) as client:
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

    def _is_cache_valid(self) -> bool:
        """Indica si el caché JWKS en memoria está poblado y dentro de la ventana de validez."""
        return (
            self._jwks_cache is not None
            and (time.time() - self._jwks_cache_time) < self._jwks_ttl
        )

    async def _fetch_jwks_from_network(self) -> dict[str, Any]:
        """Descarga las llaves públicas JWKS remotas o lanza HTTP 503."""
        try:
            async with use_async_client(httpx, timeout=10.0) as client:
                resp = await client.get(self.jwks_url)
                if resp.status_code != 200:
                    raise HTTPException(
                        status_code=503,
                        detail="No se pudo obtener las claves públicas de autenticación",
                    )
                return resp.json()
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Error conectando con el proveedor de identidad: {str(exc)}",
            ) from exc

    async def get_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        """Obtiene las llaves públicas JWKS con caché en memoria y expiración TTL (3600s)."""
        if force_refresh:
            self._verified_token_cache.clear()

        if not force_refresh and self._is_cache_valid():
            return self._jwks_cache

        async with self.lock:
            if not force_refresh and self._is_cache_valid():
                return self._jwks_cache

            try:
                self._jwks_cache = await self._fetch_jwks_from_network()
                self._jwks_cache_time = time.time()
            except HTTPException:
                if self._jwks_cache is None:
                    raise
                logger.warning(
                    "Fallo al renovar JWKS desde %s; utilizando claves en caché.",
                    self.jwks_url,
                )

            return self._jwks_cache

    def _validate_claims(self, payload: dict[str, Any]) -> None:
        """Valida claims aud, client_id e iss cuando están presentes en el payload."""
        aud = payload.get("aud")
        client_id_claim = payload.get("client_id")
        iss = payload.get("iss")

        valid_audiences = {a for a in (self.client_id, getattr(settings, "AZURE_CLIENT_ID", None)) if a}

        if aud is not None:
            aud_list = [aud] if isinstance(aud, str) else list(aud)
            if not any(a in valid_audiences for a in aud_list):
                raise JWTError(f"Audience mismatch: expected one of {valid_audiences}, got {aud}")

        if client_id_claim is not None and client_id_claim not in valid_audiences:
            raise JWTError(f"Client ID mismatch: expected one of {valid_audiences}, got {client_id_claim}")

        if iss is not None:
            normalized_iss = iss.rstrip("/")
            valid_issuers_normalized = {i.rstrip("/") for i in self.valid_issuers}
            if not valid_issuers_normalized or normalized_iss not in valid_issuers_normalized:
                raise JWTError(f"Issuer mismatch: untrusted issuer {iss}")

    async def get_current_user(self, token: str = Depends(oauth2_scheme)) -> UserOut:
        """Dependency: valida JWT de Cognito y devuelve el usuario."""
        now = time.time()
        cached = self._verified_token_cache.get(token)
        if cached is not None and now < cached[0]:
            return cached[1]

        try:
            # 1. Obtener las llaves públicas de Cognito (con caché en memoria)
            jwks = await self.get_jwks()

            # 2. Decodificar y validar el JWT usando python-jose
            # Validará automáticamente la firma, la expiración (exp) y el emisor (iss)
            # Dependiendo si usas id_token o access_token, el audience puede variar en Cognito
            try:
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
            except JWTError:
                # Reintentar forzando la actualización de las llaves en caso de rotación (kid)
                jwks = await self.get_jwks(force_refresh=True)
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

            # 3. Validar claims (aud, client_id, iss) si vienen presentes
            self._validate_claims(payload)

            # 4. Extraer datos (Cognito inyecta estos campos basándose en Azure)
            email = payload.get("email") or payload.get("unique_name") or payload.get("preferred_username")
            given_name = payload.get("given_name", "")
            family_name = payload.get("family_name", "")

            # Armamos el nombre completo. Si por alguna razón vienen vacíos, dejamos un valor por defecto.
            if given_name or family_name:
                name = f"{given_name} {family_name}".strip()
            else:
                name = "Usuario"

            # Si email es None, intentar obtener de otros campos o dejar vacío
            if not email:
                email = payload.get("sub", "")

            # Los grupos dependen de cómo mapeaste "GroupMember.Read.All" en Cognito.
            # A veces llega en "cognito:groups" o en un atributo custom como "custom:azure_groups"
            azure_groups = payload.get("custom:azure_groups", [])
            if isinstance(azure_groups, str):
                # Ajustar según como llegue el string
                azure_groups = azure_groups.split(",")

            role = self._resolve_role(azure_groups)

            # Override role if email is in ADMIN_LIST or settings.ADMIN_EMAILS
            admin_emails = {e.strip().lower() for e in settings.ADMIN_EMAILS.split(",") if e.strip()}
            admin_emails.update(e.lower() for e in ADMIN_LIST)
            if isinstance(email, str) and email.lower() in admin_emails:
                role = UserRole.ADMIN

            user = UserOut(email=email, name=name, role=role)
            exp = payload.get("exp")
            ttl = (exp - now) if exp and (exp - now) > 0 else 60.0
            self._verified_token_cache[token] = (now + min(ttl, 300.0), user)
            if len(self._verified_token_cache) > 500:
                self._verified_token_cache = {
                    k: v for k, v in self._verified_token_cache.items() if v[0] > now
                }
            return user

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


def get_authenticated_user_id(user: UserOut) -> str:
    """Valida y extrae el identificador del usuario autenticado."""
    if not user.email:
        raise HTTPException(
            status_code=401,
            detail="Identidad de usuario no verificada: email ausente",
        )
    return user.email

