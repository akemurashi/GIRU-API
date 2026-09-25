from contextlib import asynccontextmanager

from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.core.config import settings
from sqlalchemy import text


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


async def check_db_connection():
    """Temporary development diagnostic for the PostgreSQL connection."""
    try:
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
    # For development only - use Alembic in production migrations.
    # async with async_engine.begin() as conn:
    #     await conn.run_sync(SQLModel.metadata.create_all)
    pass
