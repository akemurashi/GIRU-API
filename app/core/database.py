from contextlib import asynccontextmanager
import logging

from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.core.config import settings
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Create async engine
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.APP_ENV == "development",
    future=True,
)


@asynccontextmanager
async def get_session():
    """
    Context manager for getting async database sessions.

    Usage:
        async with get_session() as session:
            # do database operations
    """
    async with AsyncSession(async_engine) as session:
        yield session


async def ensure_schema_compatibility():
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
        logger.warning(f"No se pudo verificar o alterar 'ultima_modificacion': {e}")


async def check_db_connection():
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
                "database": db_row[0],
                "current_schema": db_row[1],
                "documento_tables": tables,
            }

    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
        }



async def init_db():
    """Initialize database tables - use Alembic for production migrations."""
    await ensure_schema_compatibility()
