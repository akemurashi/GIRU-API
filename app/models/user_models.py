from pydantic import BaseModel
from typing import Optional
from enum import Enum


class UserRole(str, Enum):
    """
    Roles que se asignan tras el login con Microsoft SSO.
    El rol se determina por el grupo de Azure AD al que pertenece el usuario.
    """
    BASIC = "basic"             # chatbot
    ADMIN = "admin"             # administrador/mantenedor


class UserOut(BaseModel):
    email: Optional[str] = None
    name: str
    role: UserRole
