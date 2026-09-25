from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional
from uuid import UUID
from datetime import date


# ─────────────────────────────────────────
# Filtros
# ─────────────────────────────────────────

class SearchFilters(BaseModel):
    """
    Filtros completos alineados al esquema de base de datos.
    Todos opcionales — se aplican solo si el usuario los selecciona.
    """

    # Metadatos básicos del documento
    numero: Optional[str] = None                   # número único del documento
    nommetadato: Optional[str] = None            # nombre único del metadato
    numacuerdo: Optional[int] = None              # número de acuerdo (INT en BD)
    numsesion: Optional[int] = None                # número de sesión (INT en BD)

    # Vigencia (EstadoVigencia)
    idestadovigencia: Optional[int] = None       # FK a EstadoVigencia

    # Fechas importantes (tabla Documento)
    creaciondesde: Optional[date] = None
    creacionhasta: Optional[date] = None
    derogaciondesde: Optional[date] = None
    derogacionhasta: Optional[date] = None

    # Búsqueda booleana
    aplicacioninmediata: Optional[bool] = None
    isactive: Optional[bool] = None

    # Tipo documento (TipoDocumento)
    idtipodocumento: Optional[int] = None

    # Tipo decisión (TipoDecision)
    idtipodecision: Optional[int] = None

    # Tipo sesión (TipoSesion)
    idtiposesion: Optional[int] = None

    # Categoría (Categoria → MacroCategoria)
    idcategoria: Optional[int] = None
    idmacrocategoria: Optional[int] = None

    # Área (TipoArea → subAreas)
    idtipoarea: Optional[int] = None
    idsubarea: Optional[int] = None

    # Beneficios (BeneficioInterno → DocumentoBeneficio)
    idbeneficio: Optional[int] = None

    # Sede / Campus (SedeCampus → DocumentoSedeCampus)
    idrecintouniversitario: Optional[int] = None

    # Departamento (Departamento → DocumentoDepartamento)
    iddepartamento: Optional[int] = None

    # Carrera (Carrera → DocumentoCarrera)
    idcarrera: Optional[int] = None

    # Tipo programa (TipoPrograma → NivelAcademico)
    idtipoprograma: Optional[int] = None

    # Nivel académico (NivelAcademico → DocumentoNivel)
    idnivel: Optional[int] = None

    # Rol / Nombramiento (TipoNombramiento → DocumentoNombramiento)
    idtiponombramiento: Optional[int] = None

    # Jornada (Jornada → DocumentoJornada)
    idjornada: Optional[int] = None

    # Rol institucional (RolInstitucional → DocumentoRol)
    idrol: Optional[int] = None

    # Filtros de linaje/trazabilidad (RelacionDocumental)
    idrespaldolegal: Optional[int] = None
    idtiporelacion: Optional[int] = None
    idfuente: Optional[int] = None
    verificada: Optional[bool] = None
    confianzamin: Optional[float] = None
    confianzamax: Optional[float] = None

    # Filtros de chunks (DocumentoChunk)
    idtipopagina: Optional[int] = None

    @field_validator('numacuerdo', 'numsesion')
    @classmethod
    def validate_positive_int(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError('Debe ser un número entero positivo')
        return v

    @field_validator('idestadovigencia', 'idtipodocumento', 'idtipodecision', 
                      'idtiposesion', 'idcategoria', 'idmacrocategoria',
                      'idtipoarea', 'idsubarea', 'idbeneficio', 'idrecintouniversitario',
                      'iddepartamento', 'idcarrera', 'idtipoprograma', 'idnivel',
                      'idtiponombramiento', 'idjornada', 'idrol', 'idrespaldolegal',
                      'idtiporelacion', 'idfuente', 'idtipopagina')
    @classmethod
    def validate_id(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError('ID debe ser un entero positivo')
        return v

    @field_validator('confianzamin', 'confianzamax')
    @classmethod
    def validate_confianza_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('confianza debe estar entre 0.00 y 1.00')
        return v

    @model_validator(mode='after')
    def validate_date_ranges(self) -> 'SearchFilters':
        if self.creaciondesde and self.creacionhasta:
            if self.creaciondesde > self.creacionhasta:
                raise ValueError('creaciondesde debe ser menor o igual a creacionhasta')
        
        if self.derogaciondesde and self.derogacionhasta:
            if self.derogaciondesde > self.derogacionhasta:
                raise ValueError('derogaciondesde debe ser menor o igual a derogacionhasta')
        
        return self


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    filters: SearchFilters = SearchFilters()
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


# ─────────────────────────────────────────
# Resultados
# ─────────────────────────────────────────

class SearchResultItem(BaseModel):
    documentid: int
    numero: str
    titulo: str
    nommetadato: str
    tipodocumento: Optional[str]
    tipodecision: Optional[str]
    estadovigencia: Optional[str]
    numacuerdo: Optional[int]
    numsesion: Optional[int]
    creacion: Optional[date]
    derogacion: Optional[date]
    aplicacioninmediata: Optional[bool]
    sedes: list[str] = []             # muchos a muchos
    categorias: list[str] = []
    score: float
    excerpt: str                      # fragmento relevante del chunk


class SearchResponse(BaseModel):
    query: str
    total: int
    page: int
    page_size: int
    results: list[SearchResultItem]


# ─────────────────────────────────────────
# Opciones de filtros (para el frontend)
# ─────────────────────────────────────────

class FilterOption(BaseModel):
    id: int
    nombre: str

class FilterOptions(BaseModel):
    """
    Todos los valores disponibles para poblar los dropdowns del frontend.
    Se obtienen con GET /search/filters
    Incluye todos los catálogos base y entidades jerárquicas.
    """
    # Catálogos base (15 tablas)
    tipos_area: list[FilterOption] = []
    macro_categorias: list[FilterOption] = []
    tipos_documento: list[FilterOption] = []
    estados_vigencia: list[FilterOption] = []
    respaldos_legales: list[FilterOption] = []
    roles_institucionales: list[FilterOption] = []
    beneficios: list[FilterOption] = []
    sedes_campus: list[FilterOption] = []
    tipos_nombramiento: list[FilterOption] = []
    jornadas: list[FilterOption] = []
    tipos_programa: list[FilterOption] = []
    departamentos: list[FilterOption] = []
    tipos_sesion: list[FilterOption] = []
    tipos_decision: list[FilterOption] = []
    tipos_relacion: list[FilterOption] = []
    fuentes_deteccion: list[FilterOption] = []
    tipos_pagina: list[FilterOption] = []
    
    # Entidades jerárquicas (4 tablas)
    sub_areas: list[FilterOption] = []
    categorias: list[FilterOption] = []
    niveles_academicos: list[FilterOption] = []
    carreras: list[FilterOption] = []
