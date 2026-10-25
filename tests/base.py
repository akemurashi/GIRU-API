"""
Utilidades, configuraciones de entorno y mocks compartidos para la suite de pruebas GIRU.
"""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# Configurar variables de entorno mínimas para aislamiento total sin depender de .env real
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/giru_test")
os.environ.setdefault("COGNITO_DOMAIN", "giru-test.auth.us-east-1.amazoncognito.com")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client-id")
os.environ.setdefault("COGNITO_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_TestPool")
os.environ.setdefault("COGNITO_REDIRECT_URI", "https://giru.usm.cl/callback")
os.environ.setdefault("DOCUMENT_SIGNER_URL", "https://signer.giru.usm.cl/firmar")
os.environ.setdefault("GIRU_IA_URL", "http://localhost:8000")
os.environ.setdefault("GIRU_IA_KEY", "test-internal-api-key")
os.environ.setdefault("ADMIN_EMAILS", "admin@usm.cl, rector@usm.cl")
os.environ.setdefault("APP_ENV", "testing")
