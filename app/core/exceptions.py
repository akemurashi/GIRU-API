from typing import Optional, Any


class BaseAppException(Exception):
    """Base exception for all application errors."""
    def __init__(self, message: str, details: Optional[dict] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class DatabaseError(BaseAppException):
    """Error en operaciones de base de datos."""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(f"Error de base de datos: {message}", details)


class DocumentNotFoundError(BaseAppException):
    """Documento no encontrado."""
    def __init__(self, document_id: Any):
        super().__init__(
            f"Documento con ID {document_id} no encontrado",
            {"document_id": str(document_id)}
        )


class ValidationError(BaseAppException):
    """Error de validación de datos."""
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[dict] = None):
        error_details = {"field": field} if field else {}
        error_details.update(details or {})
        super().__init__(f"Error de validación: {message}", error_details)


class SearchError(BaseAppException):
    """Error en búsqueda semántica."""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(f"Error de búsqueda: {message}", details)


class EmbeddingError(BaseAppException):
    """Error en generación de embeddings."""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(f"Error de embedding: {message}", details)


class AuthenticationError(BaseAppException):
    """Error de autenticación."""
    def __init__(self, message: str = "No autenticado", details: Optional[dict] = None):
        super().__init__(message, details)


class AuthorizationError(BaseAppException):
    """Error de autorización."""
    def __init__(self, message: str = "Acceso denegado", details: Optional[dict] = None):
        super().__init__(message, details)


class IngestError(BaseAppException):
    """Error en ingestión de documentos."""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(f"Error de ingestión: {message}", details)


class RelationNotFoundError(BaseAppException):
    """Relación documental no encontrada."""
    def __init__(self, relacion_id: Any):
        super().__init__(
            f"Relación documental con ID {relacion_id} no encontrada",
            {"relacion_id": str(relacion_id)}
        )


class UniqueConstraintError(BaseAppException):
    """Violación de restricción de unicidad (numero, nommetadato, etc.)."""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(f"Unicidad: {message}", details)


class DAGCycleError(BaseAppException):
    """Violación de grafo acíclico dirigido en relaciones documentales."""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(f"Violación de Grafo Acíclico (DAG): {message}", details)


class CatalogNotFoundError(BaseAppException):
    """Entidad de catálogo no encontrada."""
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(f"Catálogo: {message}", details)

