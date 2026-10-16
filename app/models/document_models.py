from uuid import UUID as pyUUID
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Union
from datetime import date, datetime

class SedeCampusOut(BaseModel):
    idrecintouniversitario: int
    nombrerecinto: str

class CategoriaOut(BaseModel):
    idcategoria: int
    nombrecategoria: str
    numcategoria: Optional[str]
    macrocategoria: Optional[str]

class CarreraOut(BaseModel):
    idcarrera: int
    nombrecarrera: str
    codigocarrera: Optional[str]
    nombrenivel: Optional[str]
    nombredepartamento: Optional[str]

class BeneficioOut(BaseModel):
    idbeneficio: int
    nombrebeneficio: str

class NombramientoOut(BaseModel):
    idtiponombramiento: int
    nombrenombramiento: str

class DepartamentoOut(BaseModel):
    iddepartamento: int
    nombredepartamento: str


class FuenteDeteccionOut(BaseModel):
    idfuente: int
    nomfuente: str


class TipoPaginaOut(BaseModel):
    idtipopagina: int
    tipopagina: str


class RelacionDocumentalOut(BaseModel):
    idrelacion: int
    iddocumentoorigen: Union[pyUUID, str]
    iddocumentodestino: Union[pyUUID, str]
    idtiporelacion: int
    idrespaldolegal: int
    idfuentedeteccion: Optional[int]
    detalledemodificacion: Optional[str]
    fechaefecto: date
    confianza: Optional[float]
    verificada: bool
    textoevidencia: Optional[str]

    @field_validator('confianza')
    @classmethod
    def validate_confianza(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('confianza debe estar entre 0.00 y 1.00')
        return v

    class Config:
        from_attributes = True


class RelacionDocumentalCreate(BaseModel):
    """Payload para crear o modificar una relación documental vía sp_modificar_o_crear_relacion_documental."""
    iddocumentoorigen: Union[pyUUID, str]
    iddocumentodestino: Union[pyUUID, str]
    idtiporelacion: Optional[int] = None
    nombretiporelacion: Optional[str] = Field(None, description="Ej: 'Deroga', 'Modifica', 'Complementa', 'Reemplaza'")
    detallemodificacion: Optional[str] = Field(None, max_length=255)
    fechaefecto: Optional[date] = None
    verificada: bool = True
    confianza: float = Field(1.00, ge=0.0, le=1.0)
    textoevidencia: Optional[str] = None
    idfuentedeteccion: Optional[int] = None
    idrespaldolegal: Optional[int] = None
    idrelacion: Optional[int] = Field(None, description="ID de relación existente si se desea modificar directamente")

    @field_validator('confianza')
    @classmethod
    def validate_confianza(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0.0 or v > 1.0):
            raise ValueError('confianza debe estar entre 0.00 y 1.00')
        return v


class RelacionDocumentalDelete(BaseModel):
    """Payload para eliminar una relación documental vía sp_eliminar_relacion_documental."""
    idrelacion: Optional[int] = Field(None, description="ID directo de la relación a eliminar")
    iddocumentoorigen: Optional[Union[pyUUID, str]] = None
    iddocumentodestino: Optional[Union[pyUUID, str]] = None
    idtiporelacion: Optional[int] = None


class DocumentoOut(BaseModel):

    """Vista resumida para listados y resultados de búsqueda"""
    iddocumento: Union[pyUUID, str]
    numero: str
    titulo: str
    nommetadato: str
    tipodocumento: Optional[str] = None
    tipodecision: Optional[str] = None
    tiposesion: Optional[str] = None
    estadovigencia: Optional[str] = None
    numacuerdo: Optional[int] = None
    numsesion: Optional[int] = None
    descripcion: Optional[str] = None
    creacion: Optional[date] = None
    derogacion: Optional[date] = None
    aplicacioninmediata: Optional[bool] = None
    isactive: bool
    ultima_modificacion: Optional[datetime] = None
    sedes: list[SedeCampusOut] = []
    categorias: list[CategoriaOut] = []

    class Config:
        from_attributes = True


class DocumentoDetail(DocumentoOut):
    """Vista completa incluyendo todas las relaciones para consulta y visualización de documento"""
    cant_paginas: int
    urlarchivooriginals3: Optional[str] = None
    carreras: list[CarreraOut] = []
    beneficios: list[BeneficioOut] = []
    nombramientos: list[NombramientoOut] = []
    departamentos: list[DepartamentoOut] = []
    chunkcount: int = 0


class DocumentoUpdate(BaseModel):
    """
    Payload para la edición administrativa.
    Representa todos los campos modificables por el administrador según las reglas de negocio.
    Soporta tanto identificadores numéricos directos como nombres canónicos
    para resolución dinámica en catálogo mediante sp_modificar_documento_completo.
    Nota: 'urlarchivooriginals3' se omite intencionalmente del panel administrativo.
    """
    numero: Optional[str] = Field(None, min_length=1, max_length=50)
    titulo: Optional[str] = Field(None, min_length=1, max_length=255)
    descripcion: Optional[str] = Field(None, max_length=5000)
    idtipodocumento: Optional[int] = None
    tipo_documento_nombre: Optional[str] = Field(None, description="Ej: 'Decreto', 'Reglamento', 'Resolución'")
    idcategoria: Optional[int] = None
    nombrecategoria: Optional[str] = Field(None, description="Nombre de la categoría")
    categoria_num: Optional[str] = Field(None, description="Código de categoría (ej: 'GI-01')")
    nommetadato: Optional[str] = Field(None, max_length=255)
    recalcular_nommetadato: bool = Field(True, description="Indica si se debe recalcular nommetadato")
    idtipodecision: Optional[int] = None
    tipo_decision_nombre: Optional[str] = Field(None, description="Ej: 'Aprobación', 'Promulgación'")
    idtiposesion: Optional[int] = None
    tipo_sesion_nombre: Optional[str] = Field(None, description="Ej: 'Ordinaria', 'Extraordinaria'")
    numsesion: Optional[int] = Field(None, ge=0)
    numacuerdo: Optional[int] = Field(None, ge=0)
    limpiar_sesion: bool = False
    idestadovigencia: Optional[int] = None
    estado_vigencia_nombre: Optional[str] = Field(None, description="Ej: 'Vigente', 'Derogado', 'Modificado'")
    creacion: Optional[date] = None
    derogacion: Optional[date] = None
    limpiar_derogacion: bool = False
    aplicacioninmediata: Optional[bool] = None
    isactive: Optional[bool] = None

    # Listas de IDs para tablas puente
    sedesids: Optional[List[int]] = None
    carrerasids: Optional[List[int]] = None
    beneficiosids: Optional[List[int]] = None
    nombramientosids: Optional[List[int]] = None
    departamentosids: Optional[List[int]] = None
    jornadasids: Optional[List[int]] = None
    nivelesids: Optional[List[int]] = None
    rolesids: Optional[List[int]] = None
    areaseemisorasids: Optional[List[int]] = None

    # Listas de nombres canónicos para tablas puente
    areas_emisoras_nombres: Optional[List[str]] = Field(None, description="Nombres de subáreas")
    sedes_nombres: Optional[List[str]] = Field(None, description="Nombres de sedes")
    carreras_nombres: Optional[List[str]] = Field(None, description="Nombres de carreras")
    departamentos_nombres: Optional[List[str]] = Field(None, description="Nombres de departamentos")
    roles_nombres: Optional[List[str]] = Field(None, description="Nombres de roles")
    jornadas_nombres: Optional[List[str]] = Field(None, description="Nombres de jornadas")
    niveles_nombres: Optional[List[str]] = Field(None, description="Nombres de niveles")
    beneficios_nombres: Optional[List[str]] = Field(None, description="Nombres de beneficios")
    nombramientos_nombres: Optional[List[str]] = Field(None, description="Nombres de nombramientos")

    # Modo para tablas puente
    modo_puentes: Optional[str] = Field("REEMPLAZAR", pattern="^(REEMPLAZAR|AGREGAR|ELIMINAR)$")

    # Relación jurídica opcional
    relacion_destino_id: Optional[Union[pyUUID, str]] = None
    relacion_tipo_id: Optional[int] = None
    relacion_tipo_nombre: Optional[str] = Field(None, description="Ej: 'Deroga', 'Modifica', 'Complementa'")
    relacion_detalle: Optional[str] = None
    relacion_fecha: Optional[date] = None
    relacion_verificada: bool = True

    @field_validator('idtipodocumento', 'idcategoria', 'idtipodecision', 'idtiposesion', 'idestadovigencia')
    @classmethod
    def validate_id(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError('ID debe ser un entero positivo')
        return v


    @field_validator('sedesids', 'carrerasids', 'beneficiosids', 'nombramientosids',
                      'departamentosids', 'jornadasids', 'nivelesids', 'rolesids',
                      'areaseemisorasids')
    @classmethod
    def validate_ids_list(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None:
            if any(id_val <= 0 for id_val in v):
                raise ValueError('Todos los IDs deben ser enteros positivos')
        return v


class DocumentoEditableOut(BaseModel):
    """
    Representación completa para poblar el formulario de administración en una sola petición.
    Oリング 'urlarchivooriginals3' ya que no se utiliza en el panel de admin.
    """
    iddocumento: Union[pyUUID, str]
    numero: str
    idtipodocumento: Optional[int] = None
    titulo: str
    nommetadato: str
    descripcion: Optional[str] = None
    idcategoria: Optional[int] = None
    idtiposesion: Optional[int] = None
    numsesion: Optional[int] = None
    numacuerdo: Optional[int] = None
    idtipodecision: Optional[int] = None
    idestadovigencia: Optional[int] = None
    creacion: Optional[date] = None
    derogacion: Optional[date] = None
    aplicacioninmediata: Optional[bool] = None
    isactive: bool
    ultima_modificacion: Optional[datetime] = None

    # Listas de IDs para los selectores múltiples del frontend
    areaseemisorasids: List[int] = []
    sedesids: List[int] = []
    carrerasids: List[int] = []
    departamentosids: List[int] = []
    rolesids: List[int] = []
    jornadasids: List[int] = []
    nivelesids: List[int] = []
    beneficiosids: List[int] = []
    nombramientosids: List[int] = []

    class Config:
        from_attributes = True


class DocumentoUrlOut(BaseModel):
    url: str          
    expires_in: int   
