"""Módulo de conexión y gestión de sesiones asíncronas con la base de datos PostgreSQL."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from app.core.config import settings

logger = logging.getLogger(__name__)

# Create async engine
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    future=True,
)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """
    Context manager for getting async database sessions.

    Usage:
        async with get_session() as session:
            # do database operations
    """
    async with AsyncSession(async_engine) as session:
        yield session


async def ensure_schema_compatibility() -> None:
    """
    Asegura que la columna de auditoria 'ultima_modificacion'
    exista en la tabla 'documento' acorde a PROCEDIMIENTOS_ALMACENADOS.md.
    """
    try:
        async with async_engine.begin() as conn:
            await conn.execute(
                text("""
                    ALTER TABLE public.documento
                    ADD COLUMN IF NOT EXISTS ultima_modificacion TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
                """)
            )
            logger.info("Verificación de esquema: columna 'ultima_modificacion' asegurada en 'documento'.")
    except Exception as e:
        logger.warning("No se pudo verificar o alterar 'ultima_modificacion': %s", e)


async def check_db_connection() -> dict[str, Any]:
    """Temporary development diagnostic for the PostgreSQL connection."""
    try:
        # Asegurar esquema al diagnosticar la conexión
        await ensure_schema_compatibility()

        async with async_engine.connect() as connection:

            # Database and schema we're actually connected to
            db_result = await connection.execute(
                text("""
                    SELECT
                        current_database(),
                        current_schema()
                """)
            )

            db_row = db_result.fetchone()

            # Look for Documento in every schema
            table_result = await connection.execute(
                text("""
                    SELECT
                        table_schema,
                        table_name
                    FROM information_schema.tables
                    WHERE LOWER(table_name) = LOWER('Documento')
                    ORDER BY table_schema
                """)
            )

            tables = [
                {
                    "schema": row[0],
                    "table": row[1],
                }
                for row in table_result.fetchall()
            ]

            return {
                "connected": True,
                "database": db_row[0] if db_row else None,
                "current_schema": db_row[1] if db_row else None,
                "documento_tables": tables,
            }

    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
        }


async def init_db() -> None:
    """Initialize database tables - use Alembic for production migrations."""
    await ensure_schema_compatibility()
