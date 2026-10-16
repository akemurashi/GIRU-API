from uuid import UUID as pyUUID
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Union, Any, List
from uuid import UUID
from datetime import date


# ─────────────────────────────────────────
# Filtros
# ─────────────────────────────────────────

class SearchFilters(BaseModel):
    """
    Filtros completos alineados al esquema de base de datos.
    Todos opcionales — se aplican solo si el usuario los selecciona.
    Soporta enteros individuales o listas de enteros para selección múltiple.
    """

    # Metadatos básicos del documento
    numero: Optional[str] = None                   # número único del documento
    nommetadato: Optional[str] = None            # nombre único del metadato
    numacuerdo: Optional[int] = None              # número de acuerdo (INT en BD)
    numsesion: Optional[int] = None                # número de sesión (INT en BD)

    # Vigencia (EstadoVigencia)
    idestadovigencia: Optional[Union[int, List[int]]] = None       # FK a EstadoVigencia

    # Fechas importantes (tabla Documento)
    creaciondesde: Optional[Union[date, str]] = None
    creacionhasta: Optional[Union[date, str]] = None
    derogaciondesde: Optional[Union[date, str]] = None
    derogacionhasta: Optional[Union[date, str]] = None
    anios: Optional[List[int]] = None

    # Búsqueda booleana
    aplicacioninmediata: Optional[bool] = None
    isactive: Optional[bool] = None

    # Tipo documento (TipoDocumento)
    idtipodocumento: Optional[Union[int, List[int]]] = None

    # Tipo decisión (TipoDecision)
    idtipodecision: Optional[Union[int, List[int]]] = None

    # Tipo sesión (TipoSesion)
    idtiposesion: Optional[Union[int, List[int]]] = None

    # Categoría (Categoria → MacroCategoria)
    idcategoria: Optional[Union[int, List[int]]] = None
    idmacrocategoria: Optional[Union[int, List[int]]] = None

    # Área (TipoArea → subAreas)
    idtipoarea: Optional[Union[int, List[int]]] = None
    idsubarea: Optional[Union[int, List[int]]] = None

    # Beneficios (BeneficioInterno → DocumentoBeneficio)
    idbeneficio: Optional[Union[int, List[int]]] = None

    # Sede / Campus (SedeCampus → DocumentoSedeCampus)
    idrecintouniversitario: Optional[Union[int, List[int]]] = None

    # Departamento (Departamento → DocumentoDepartamento)
    iddepartamento: Optional[Union[int, List[int]]] = None

    # Carrera (Carrera → DocumentoCarrera)
    idcarrera: Optional[Union[int, List[int]]] = None

    # Tipo programa (TipoPrograma → NivelAcademico)
    idtipoprograma: Optional[Union[int, List[int]]] = None

    # Nivel académico (NivelAcademico → DocumentoNivel)
    idnivel: Optional[Union[int, List[int]]] = None

    # Rol / Nombramiento (TipoNombramiento → DocumentoNombramiento)
    idtiponombramiento: Optional[Union[int, List[int]]] = None

    # Jornada (Jornada → DocumentoJornada)
    idjornada: Optional[Union[int, List[int]]] = None

    # Rol institucional (RolInstitucional → DocumentoRol)
    idrol: Optional[Union[int, List[int]]] = None

    # Filtros de linaje/trazabilidad (RelacionDocumental)
    idrespaldolegal: Optional[Union[int, List[int]]] = None
    idtiporelacion: Optional[Union[int, List[int]]] = None
    idfuente: Optional[Union[int, List[int]]] = None
    verificada: Optional[bool] = None
    confianzamin: Optional[float] = None
    confianzamax: Optional[float] = None

    # Filtros de chunks (DocumentoChunk)
    idtipopagina: Optional[Union[int, List[int]]] = None

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
                      'idtiporelacion', 'idfuente', 'idtipopagina', mode='before')
    @classmethod
    def validate_id(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, int):
            if v <= 0:
                raise ValueError('ID debe ser un entero positivo')
            return v
        if isinstance(v, list):
            for item in v:
                if not isinstance(item, int) or item <= 0:
                    raise ValueError('Todos los IDs de la lista deben ser enteros positivos')
            return v
        return v

    @field_validator('confianzamin', 'confianzamax')
    @classmethod
    def validate_confianza_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('confianza debe estar entre 0.00 y 1.00')
        return v

    @model_validator(mode='after')
    def validate_date_ranges(self) -> 'SearchFilters':
        def to_d(d):
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
    query: str = Field(default="", max_length=500)
    filters: SearchFilters = SearchFilters()
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


# ─────────────────────────────────────────
# Resultados
# ─────────────────────────────────────────

class SearchResultItem(BaseModel):
    documentid: Union[pyUUID, str]
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
    entidades: list[str] = []         # entidades IA


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
    parent_id: Optional[int] = None
    code: Optional[str] = None

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
    roles: list[FilterOption] = []
    beneficios: list[FilterOption] = []
    sedes_campus: list[FilterOption] = []
    sedes: list[FilterOption] = []
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


# ─────────────────────────────────────────
# Autocompletado léxico (#)
# ─────────────────────────────────────────

class LexicalSuggestionItem(BaseModel):
    documentid: str
    numero: str
    titulo: str
    nommetadato: str
    matched_field: str      # "titulo" o "nommetadato"
    suggestion: str         # Texto exacto para autocompletar


class AutocompleteResponse(BaseModel):
    query: str
    is_lexical: bool
    suggestions: list[LexicalSuggestionItem] = []
