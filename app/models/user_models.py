"""Modelos de usuario y roles de autenticación."""

from enum import Enum
from pydantic import BaseModel


class UserRole(str, Enum):
    """
    Roles que se asignan tras el login con Microsoft SSO.
    El rol se determina por el grupo de Azure AD al que pertenece el usuario.
    """
    BASIC = "basic"             # chatbot
    ADMIN = "admin"             # administrador/mantenedor


class UserOut(BaseModel):
    """Esquema de salida con datos básicos del usuario autenticado."""

    email: str | None = None
    name: str
    role: UserRole

