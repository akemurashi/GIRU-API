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
    Nota: 'urlarchivooriginals3' se omite intencionalmente del panel administrativo.
    """
    numero: Optional[str] = Field(None, min_length=1, max_length=50)
    titulo: Optional[str] = Field(None, min_length=1, max_length=255)
    idtipodocumento: Optional[int] = None
    descripcion: Optional[str] = Field(None, max_length=5000)
    idcategoria: Optional[int] = None
    nommetadato: Optional[str] = Field(None, max_length=255)
    idtipodecision: Optional[int] = None
    idtiposesion: Optional[int] = None
    numsesion: Optional[int] = Field(None, ge=0)
    numacuerdo: Optional[int] = Field(None, ge=0)
    limpiar_sesion: bool = False
    idestadovigencia: Optional[int] = None
    creacion: Optional[date] = None
    derogacion: Optional[date] = None
    limpiar_derogacion: bool = False
    aplicacioninmediata: Optional[bool] = None
    isactive: Optional[bool] = None
    sedesids: Optional[List[int]] = None
    carrerasids: Optional[List[int]] = None
    beneficiosids: Optional[List[int]] = None
    nombramientosids: Optional[List[int]] = None
    departamentosids: Optional[List[int]] = None
    jornadasids: Optional[List[int]] = None
    nivelesids: Optional[List[int]] = None
    rolesids: Optional[List[int]] = None
    areaseemisorasids: Optional[List[int]] = None

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
