from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List
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
    iddocumentoorigen: int
    iddocumentodestino: int
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
    iddocumento: int
    numero: str
    titulo: str
    nommetadato: str
    tipodocumento: Optional[str]
    tipodecision: Optional[str]
    tiposesion: Optional[str]
    estadovigencia: Optional[str]
    numacuerdo: Optional[int]
    numsesion: Optional[int]
    descripcion: Optional[str]
    creacion: Optional[date]
    derogacion: Optional[date]
    aplicacioninmediata: Optional[bool]
    isactive: bool
    sedes: list[SedeCampusOut] = []
    categorias: list[CategoriaOut] = []

    class Config:
        from_attributes = True


class DocumentoDetail(DocumentoOut):
    """Vista completa incluyendo todas las relaciones"""
    cant_paginas: int
    urlarchivooriginals3: str
    carreras: list[CarreraOut] = []
    beneficios: list[BeneficioOut] = []
    nombramientos: list[NombramientoOut] = []
    departamentos: list[DepartamentoOut] = []
    chunkcount: int = 0


class DocumentoUpdate(BaseModel):
    """Lo que el admin puede editar"""
    titulo: Optional[str] = Field(None, min_length=1, max_length=255)
    descripcion: Optional[str] = Field(None, max_length=5000)
    idcategoria: Optional[int] = None
    idtipodecision: Optional[int] = None
    idtiposesion: Optional[int] = None
    idestadovigencia: Optional[int] = None
    derogacion: Optional[date] = None
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

    @field_validator('idcategoria', 'idtipodecision', 'idtiposesion', 'idestadovigencia')
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
            if not v:  # Empty list
                raise ValueError('Lista de IDs no puede estar vacía')
            if any(id_val <= 0 for id_val in v):
                raise ValueError('Todos los IDs deben ser enteros positivos')
        return v
