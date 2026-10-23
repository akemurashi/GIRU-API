"""Modelos de datos para filtros, peticiones y respuestas de búsqueda de documentos."""

from datetime import date
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator


class SearchFilters(BaseModel):
    """
    Filtros completos alineados al esquema de base de datos.
    Todos opcionales — se aplican solo si el usuario los selecciona.
    Soporta enteros individuales o listas de enteros para selección múltiple.
    """

    # Metadatos básicos del documento
    numero: str | None = None
    nommetadato: str | None = None
    numacuerdo: int | None = None
    numsesion: int | None = None

    # Vigencia (EstadoVigencia)
    idestadovigencia: int | list[int] | None = None

    # Fechas importantes (tabla Documento)
    creaciondesde: date | str | None = None
    creacionhasta: date | str | None = None
    derogaciondesde: date | str | None = None
    derogacionhasta: date | str | None = None
    anios: list[int] | None = None

    # Búsqueda booleana
    aplicacioninmediata: bool | None = None
    isactive: bool | None = None

    # Tipo documento (TipoDocumento)
    idtipodocumento: int | list[int] | None = None

    # Tipo decisión (TipoDecision)
    idtipodecision: int | list[int] | None = None

    # Tipo sesión (TipoSesion)
    idtiposesion: int | list[int] | None = None

    # Categoría (Categoria -> MacroCategoria)
    idcategoria: int | list[int] | None = None
    idmacrocategoria: int | list[int] | None = None

    # Área (TipoArea -> subAreas)
    idtipoarea: int | list[int] | None = None
    idsubarea: int | list[int] | None = None

    # Beneficios (BeneficioInterno -> DocumentoBeneficio)
    idbeneficio: int | list[int] | None = None

    # Sede / Campus (SedeCampus -> DocumentoSedeCampus)
    idrecintouniversitario: int | list[int] | None = None

    # Departamento (Departamento -> DocumentoDepartamento)
    iddepartamento: int | list[int] | None = None

    # Carrera (Carrera -> DocumentoCarrera)
    idcarrera: int | list[int] | None = None

    # Tipo programa (TipoPrograma -> NivelAcademico)
    idtipoprograma: int | list[int] | None = None

    # Nivel académico (NivelAcademico -> DocumentoNivel)
    idnivel: int | list[int] | None = None

    # Rol / Nombramiento (TipoNombramiento -> DocumentoNombramiento)
    idtiponombramiento: int | list[int] | None = None

    # Jornada (Jornada -> DocumentoJornada)
    idjornada: int | list[int] | None = None

    # Rol institucional (RolInstitucional -> DocumentoRol)
    idrol: int | list[int] | None = None

    # Filtros de linaje/trazabilidad (RelacionDocumental)
    idrespaldolegal: int | list[int] | None = None
    idtiporelacion: int | list[int] | None = None
    idfuente: int | list[int] | None = None
    verificada: bool | None = None
    confianzamin: float | None = None
    confianzamax: float | None = None

    # Filtros de chunks (DocumentoChunk)
    idtipopagina: int | list[int] | None = None

    @field_validator('numacuerdo', 'numsesion')
    @classmethod
    def validate_positive_int(cls, v: int | None) -> int | None:
        """Valida que los números de acuerdo y sesión sean positivos."""
        if v is not None and v < 0:
            raise ValueError('Debe ser un número entero positivo')
        return v

    @field_validator(
        'idestadovigencia', 'idtipodocumento', 'idtipodecision',
        'idtiposesion', 'idcategoria', 'idmacrocategoria',
        'idtipoarea', 'idsubarea', 'idbeneficio', 'idrecintouniversitario',
        'iddepartamento', 'idcarrera', 'idtipoprograma', 'idnivel',
        'idtiponombramiento', 'idjornada', 'idrol', 'idrespaldolegal',
        'idtiporelacion', 'idfuente', 'idtipopagina',
        mode='before'
    )
    @classmethod
    def validate_id(cls, v: int | list[int] | None) -> int | list[int] | None:
        """Valida que los identificadores sean enteros positivos."""
        if isinstance(v, int) and v <= 0:
            raise ValueError('ID debe ser un entero positivo')
        if isinstance(v, list) and any(not isinstance(item, int) or item <= 0 for item in v):
            raise ValueError('Todos los IDs de la lista deben ser enteros positivos')
        return v

    @field_validator('confianzamin', 'confianzamax')
    @classmethod
    def validate_confianza_range(cls, v: float | None) -> float | None:
        """Valida que los valores de confianza estén entre 0.0 y 1.0."""
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('confianza debe estar entre 0.00 y 1.00')
        return v

    @model_validator(mode='after')
    def validate_date_ranges(self) -> 'SearchFilters':
        """Valida coherencia en los rangos de fechas (desde <= hasta)."""
        def to_d(d: date | str | None) -> date | None:
            """Convierte texto o fecha a objeto date normalizado."""
            if isinstance(d, str):
                try:
                    return date.fromisoformat(d[:10])
                except Exception:
                    return None
            return d

        c_desde = to_d(self.creaciondesde)
        c_hasta = to_d(self.creacionhasta)
        if c_desde and c_hasta and c_desde > c_hasta:
            raise ValueError('creaciondesde debe ser menor o igual a creacionhasta')

        d_desde = to_d(self.derogaciondesde)
        d_hasta = to_d(self.derogacionhasta)
        if d_desde and d_hasta and d_desde > d_hasta:
            raise ValueError('derogaciondesde debe ser menor o igual a derogacionhasta')

        return self


class SearchRequest(BaseModel):
    """Solicitud paginada de búsqueda documental con filtros."""

    query: str = Field(default="", max_length=500)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class SearchResultItem(BaseModel):
    """Elemento individual de resultado de búsqueda con metadatos y fragmento."""

    documentid: UUID | str
    numero: str
    titulo: str
    nommetadato: str
    tipodocumento: str | None = None
    tipodecision: str | None = None
    estadovigencia: str | None = None
    numacuerdo: int | None = None
    numsesion: int | None = None
    creacion: date | None = None
    derogacion: date | None = None
    aplicacioninmediata: bool | None = None
    sedes: list[str] = Field(default_factory=list)
    categorias: list[str] = Field(default_factory=list)
    score: float
    excerpt: str
    entidades: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Respuesta con total de coincidencias y lista de resultados paginados."""

    query: str
    total: int
    page: int
    page_size: int
    results: list[SearchResultItem]


class FilterOption(BaseModel):
    """Opción individual para un menú desplegable de filtro."""

    id: int
    nombre: str
    parent_id: int | None = None
    code: str | None = None


class FilterOptions(BaseModel):
    """
    Todos los valores disponibles para poblar los dropdowns del frontend.
    Se obtienen con GET /search/filters.
    Incluye todos los catálogos base y entidades jerárquicas.
    """

    tipos_area: list[FilterOption] = Field(default_factory=list)
    macro_categorias: list[FilterOption] = Field(default_factory=list)
    tipos_documento: list[FilterOption] = Field(default_factory=list)
    estados_vigencia: list[FilterOption] = Field(default_factory=list)
    respaldos_legales: list[FilterOption] = Field(default_factory=list)
    roles_institucionales: list[FilterOption] = Field(default_factory=list)
    roles: list[FilterOption] = Field(default_factory=list)
    beneficios: list[FilterOption] = Field(default_factory=list)
    sedes_campus: list[FilterOption] = Field(default_factory=list)
    sedes: list[FilterOption] = Field(default_factory=list)
    tipos_nombramiento: list[FilterOption] = Field(default_factory=list)
    jornadas: list[FilterOption] = Field(default_factory=list)
    tipos_programa: list[FilterOption] = Field(default_factory=list)
    departamentos: list[FilterOption] = Field(default_factory=list)
    tipos_sesion: list[FilterOption] = Field(default_factory=list)
    tipos_decision: list[FilterOption] = Field(default_factory=list)
    tipos_relacion: list[FilterOption] = Field(default_factory=list)
    fuentes_deteccion: list[FilterOption] = Field(default_factory=list)
    tipos_pagina: list[FilterOption] = Field(default_factory=list)

    sub_areas: list[FilterOption] = Field(default_factory=list)
    categorias: list[FilterOption] = Field(default_factory=list)
    niveles_academicos: list[FilterOption] = Field(default_factory=list)
    carreras: list[FilterOption] = Field(default_factory=list)


class LexicalSuggestionItem(BaseModel):
    """Sugerencia individual para el autocompletado léxico."""

    documentid: str
    numero: str
    titulo: str
    nommetadato: str
    matched_field: str
    suggestion: str


class AutocompleteResponse(BaseModel):
    """Respuesta con sugerencias léxicas para autocompletado."""

    query: str
    is_lexical: bool
    suggestions: list[LexicalSuggestionItem] = Field(default_factory=list)
