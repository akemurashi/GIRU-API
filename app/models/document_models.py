"""Modelos de datos para documentos, relaciones documentales y edición administrativa."""

from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SedeCampusOut(BaseModel):
    """Representación de una sede o campus universitario."""

    idrecintouniversitario: int
    nombrerecinto: str


class CategoriaOut(BaseModel):
    """Representación de una categoría documental."""

    idcategoria: int
    nombrecategoria: str
    numcategoria: str | None = None
    macrocategoria: str | None = None


class CarreraOut(BaseModel):
    """Representación de una carrera académica y su departamento asociado."""

    idcarrera: int
    nombrecarrera: str
    codigocarrera: str | None = None
    nombrenivel: str | None = None
    nombredepartamento: str | None = None


class BeneficioOut(BaseModel):
    """Representación de un beneficio interno."""

    idbeneficio: int
    nombrebeneficio: str


class NombramientoOut(BaseModel):
    """Representación de un tipo de nombramiento."""

    idtiponombramiento: int
    nombrenombramiento: str


class DepartamentoOut(BaseModel):
    """Representación de un departamento universitario."""

    iddepartamento: int
    nombredepartamento: str


class FuenteDeteccionOut(BaseModel):
    """Fuente de detección de una relación documental."""

    idfuente: int
    nomfuente: str


class TipoPaginaOut(BaseModel):
    """Tipo o clasificación de página de un documento."""

    idtipopagina: int
    tipopagina: str


class RelacionDocumentalOut(BaseModel):
    """Detalle de una relación documental existente entre dos documentos."""

    model_config = ConfigDict(from_attributes=True)

    idrelacion: int
    iddocumentoorigen: UUID | str
    iddocumentodestino: UUID | str
    idtiporelacion: int
    idrespaldolegal: int
    idfuentedeteccion: int | None = None
    detallemodificacion: str | None = None
    fechaefecto: date
    confianza: float | None = None
    verificada: bool
    textoevidencia: str | None = None

    @field_validator('confianza')
    @classmethod
    def validate_confianza(cls, v: float | None) -> float | None:
        """Valida que la confianza esté en el rango de 0.0 a 1.0."""
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('confianza debe estar entre 0.00 y 1.00')
        return v


class RelacionDocumentalCreate(BaseModel):
    """Payload para crear o modificar una relación documental vía sp_modificar_o_crear_relacion_documental."""

    iddocumentoorigen: UUID | str
    iddocumentodestino: UUID | str
    idtiporelacion: int | None = None
    nombretiporelacion: str | None = Field(None, description="Ej: 'Deroga', 'Modifica', 'Complementa', 'Reemplaza'")
    detallemodificacion: str | None = Field(None, max_length=255)
    fechaefecto: date | None = None
    verificada: bool = True
    confianza: float = Field(1.00, ge=0.0, le=1.0)
    textoevidencia: str | None = None
    idfuentedeteccion: int | None = None
    idrespaldolegal: int | None = None
    idrelacion: int | None = Field(None, description="ID de relación existente si se desea modificar directamente")

    @field_validator('confianza')
    @classmethod
    def validate_confianza(cls, v: float | None) -> float | None:
        """Valida que la confianza esté en el rango de 0.0 a 1.0."""
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('confianza debe estar entre 0.00 y 1.00')
        return v


class RelacionDocumentalDelete(BaseModel):
    """Payload para eliminar una relación documental vía sp_eliminar_relacion_documental."""

    idrelacion: int | None = Field(None, description="ID directo de la relación a eliminar")
    iddocumentoorigen: UUID | str | None = None
    iddocumentodestino: UUID | str | None = None
    idtiporelacion: int | None = None


class DocumentoOut(BaseModel):
    """Vista resumida para listados y resultados de búsqueda."""

    model_config = ConfigDict(from_attributes=True)

    iddocumento: UUID | str
    numero: str
    titulo: str
    nommetadato: str
    tipodocumento: str | None = None
    tipodecision: str | None = None
    tiposesion: str | None = None
    estadovigencia: str | None = None
    numacuerdo: int | None = None
    numsesion: int | None = None
    descripcion: str | None = None
    creacion: date | None = None
    derogacion: date | None = None
    aplicacioninmediata: bool | None = None
    isactive: bool
    ultima_modificacion: datetime | None = None
    sedes: list[SedeCampusOut] = Field(default_factory=list)
    categorias: list[CategoriaOut] = Field(default_factory=list)


class DocumentoDetail(DocumentoOut):
    """Vista completa incluyendo todas las relaciones para consulta y visualización de documento."""

    cant_paginas: int
    urlarchivooriginals3: str | None = None
    carreras: list[CarreraOut] = Field(default_factory=list)
    beneficios: list[BeneficioOut] = Field(default_factory=list)
    nombramientos: list[NombramientoOut] = Field(default_factory=list)
    departamentos: list[DepartamentoOut] = Field(default_factory=list)
    chunkcount: int = 0


class DocumentoUpdate(BaseModel):
    """
    Payload para la edición administrativa.
    Representa todos los campos modificables por el administrador según las reglas de negocio.
    Soporta tanto identificadores numéricos directos como nombres canónicos
    para resolución dinámica en catálogo mediante sp_modificar_documento_completo.
    Nota: 'urlarchivooriginals3' se omite intencionalmente del panel administrativo.
    """

    numero: str | None = Field(None, min_length=1, max_length=50)
    titulo: str | None = Field(None, min_length=1, max_length=255)
    descripcion: str | None = Field(None, max_length=5000)
    idtipodocumento: int | None = None
    tipo_documento_nombre: str | None = Field(None, description="Ej: 'Decreto', 'Reglamento', 'Resolución'")
    idcategoria: int | None = None
    nombrecategoria: str | None = Field(None, description="Nombre de la categoría")
    categoria_num: str | None = Field(None, description="Código de categoría (ej: 'GI-01')")
    nommetadato: str | None = Field(None, max_length=255)
    recalcular_nommetadato: bool = Field(True, description="Indica si se debe recalcular nommetadato")
    idtipodecision: int | None = None
    tipo_decision_nombre: str | None = Field(None, description="Ej: 'Aprobación', 'Promulgación'")
    idtiposesion: int | None = None
    tipo_sesion_nombre: str | None = Field(None, description="Ej: 'Ordinaria', 'Extraordinaria'")
    numsesion: int | None = Field(None, ge=0)
    numacuerdo: int | None = Field(None, ge=0)
    limpiar_sesion: bool = False
    idestadovigencia: int | None = None
    estado_vigencia_nombre: str | None = Field(None, description="Ej: 'Vigente', 'Derogado', 'Modificado'")
    creacion: date | None = None
    derogacion: date | None = None
    limpiar_derogacion: bool = False
    aplicacioninmediata: bool | None = None
    isactive: bool | None = None

    # Listas de IDs para tablas puente
    sedesids: list[int] | None = None
    carrerasids: list[int] | None = None
    beneficiosids: list[int] | None = None
    nombramientosids: list[int] | None = None
    departamentosids: list[int] | None = None
    jornadasids: list[int] | None = None
    nivelesids: list[int] | None = None
    rolesids: list[int] | None = None
    areaseemisorasids: list[int] | None = None

    # Listas de nombres canónicos para tablas puente
    areas_emisoras_nombres: list[str] | None = Field(None, description="Nombres de subáreas")
    sedes_nombres: list[str] | None = Field(None, description="Nombres de sedes")
    carreras_nombres: list[str] | None = Field(None, description="Nombres de carreras")
    departamentos_nombres: list[str] | None = Field(None, description="Nombres de departamentos")
    roles_nombres: list[str] | None = Field(None, description="Nombres de roles")
    jornadas_nombres: list[str] | None = Field(None, description="Nombres de jornadas")
    niveles_nombres: list[str] | None = Field(None, description="Nombres de niveles")
    beneficios_nombres: list[str] | None = Field(None, description="Nombres de beneficios")
    nombramientos_nombres: list[str] | None = Field(None, description="Nombres de nombramientos")

    # Modo para tablas puente
    modo_puentes: str | None = Field("REEMPLAZAR", pattern="^(REEMPLAZAR|AGREGAR|ELIMINAR)$")

    # Relación jurídica opcional
    relacion_destino_id: UUID | str | None = None
    relacion_tipo_id: int | None = None
    relacion_tipo_nombre: str | None = Field(None, description="Ej: 'Deroga', 'Modifica', 'Complementa'")
    relacion_detalle: str | None = None
    relacion_fecha: date | None = None
    relacion_verificada: bool = True

    @field_validator('idtipodocumento', 'idcategoria', 'idtipodecision', 'idtiposesion', 'idestadovigencia')
    @classmethod
    def validate_id(cls, v: int | None) -> int | None:
        """Valida que los IDs sean enteros positivos."""
        if v is not None and v <= 0:
            raise ValueError('ID debe ser un entero positivo')
        return v

    @field_validator(
        'sedesids', 'carrerasids', 'beneficiosids', 'nombramientosids',
        'departamentosids', 'jornadasids', 'nivelesids', 'rolesids',
        'areaseemisorasids'
    )
    @classmethod
    def validate_ids_list(cls, v: list[int] | None) -> list[int] | None:
        """Valida que todos los IDs de la lista sean enteros positivos."""
        if v is not None and any(id_val <= 0 for id_val in v):
            raise ValueError('Todos los IDs deben ser enteros positivos')
        return v


class DocumentoEditableOut(BaseModel):
    """
    Representación completa para poblar el formulario de administración en una sola petición.
    Omite 'urlarchivooriginals3' ya que no se utiliza en el panel de admin.
    """

    model_config = ConfigDict(from_attributes=True)

    iddocumento: UUID | str
    numero: str
    idtipodocumento: int | None = None
    titulo: str
    nommetadato: str
    descripcion: str | None = None
    idcategoria: int | None = None
    idtiposesion: int | None = None
    numsesion: int | None = None
    numacuerdo: int | None = None
    idtipodecision: int | None = None
    idestadovigencia: int | None = None
    creacion: date | None = None
    derogacion: date | None = None
    aplicacioninmediata: bool | None = None
    isactive: bool
    ultima_modificacion: datetime | None = None

    # Listas de IDs para los selectores múltiples del frontend
    areaseemisorasids: list[int] = Field(default_factory=list)
    sedesids: list[int] = Field(default_factory=list)
    carrerasids: list[int] = Field(default_factory=list)
    departamentosids: list[int] = Field(default_factory=list)
    rolesids: list[int] = Field(default_factory=list)
    jornadasids: list[int] = Field(default_factory=list)
    nivelesids: list[int] = Field(default_factory=list)
    beneficiosids: list[int] = Field(default_factory=list)
    nombramientosids: list[int] = Field(default_factory=list)


class DocumentoUrlOut(BaseModel):
    """URL prefirmada de S3 con su tiempo de expiración."""

    url: str
    expires_in: int
