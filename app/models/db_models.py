from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List
from datetime import date


# =============================================================================
# 1. CATÁLOGOS BASE (ON DELETE RESTRICT)
# =============================================================================

class TipoArea(SQLModel, table=True):
    __tablename__ = "tipoarea"
    
    idtipoarea: Optional[int] = Field(default=None, primary_key=True)
    nombrearea: str = Field(max_length=100)
    siglaarea: str = Field(max_length=20, unique=True)
    
    # Relationships
    sub_areas: List["SubAreas"] = Relationship(back_populates="tipo_area")


class MacroCategoria(SQLModel, table=True):
    __tablename__ = "macrocategoria"
    
    idmacrocategoria: Optional[int] = Field(default=None, primary_key=True)
    siglamacro: str = Field(max_length=2, unique=True)
    nombrecategoria: str = Field(max_length=100)
    
    # Relationships
    categorias: List["Categoria"] = Relationship(back_populates="macro_categoria")


class TipoDocumento(SQLModel, table=True):
    __tablename__ = "tipodocumento"
    
    idtipodocumento: Optional[int] = Field(default=None, primary_key=True)
    nombretipodocumento: str = Field(max_length=100, unique=True)
    
    # Relationships
    documentos: List["Documento"] = Relationship(back_populates="tipo_documento")


class EstadoVigencia(SQLModel, table=True):
    __tablename__ = "estadovigencia"
    
    idestadovigencia: Optional[int] = Field(default=None, primary_key=True)
    estadovigencia: str = Field(max_length=50, unique=True)
    
    # Relationships
    documentos: List["Documento"] = Relationship(back_populates="estado_vigencia")


class RespaldoLegal(SQLModel, table=True):
    __tablename__ = "respaldolegal"
    
    idrespaldolegal: Optional[int] = Field(default=None, primary_key=True)
    respaldolegal: str = Field(max_length=255)
    
    # Relationships
    relaciones_documentales: List["RelacionDocumental"] = Relationship(back_populates="respaldo_legal")


class RolInstitucional(SQLModel, table=True):
    __tablename__ = "rolinstitucional"
    
    idrol: Optional[int] = Field(default=None, primary_key=True)
    nombrerol: str = Field(max_length=100, unique=True)
    
    # Relationships
    documento_roles: List["DocumentoRol"] = Relationship(back_populates="rol")


class BeneficioInterno(SQLModel, table=True):
    __tablename__ = "beneficiointerno"
    
    idbeneficio: Optional[int] = Field(default=None, primary_key=True)
    nombrebeneficio: str = Field(max_length=150, unique=True)
    
    # Relationships
    documento_beneficios: List["DocumentoBeneficio"] = Relationship(back_populates="beneficio")


class SedeCampus(SQLModel, table=True):
    __tablename__ = "sedecampus"
    
    idrecintouniversitario: Optional[int] = Field(default=None, primary_key=True)
    nombrerecinto: str = Field(max_length=100, unique=True)
    
    # Relationships
    documento_sedes: List["DocumentoSedeCampus"] = Relationship(back_populates="sede_campus")


class TipoNombramiento(SQLModel, table=True):
    __tablename__ = "tiponombramiento"
    
    idtiponombramiento: Optional[int] = Field(default=None, primary_key=True)
    nombrenombramiento: str = Field(max_length=100)
    
    # Relationships
    documento_nombramientos: List["DocumentoNombramiento"] = Relationship(back_populates="tipo_nombramiento")


class Jornada(SQLModel, table=True):
    __tablename__ = "jornada"
    
    idjornada: Optional[int] = Field(default=None, primary_key=True)
    nombrejornada: str = Field(max_length=50, unique=True)
    
    # Relationships
    documento_jornadas: List["DocumentoJornada"] = Relationship(back_populates="jornada")


class TipoPrograma(SQLModel, table=True):
    __tablename__ = "tipoprograma"
    
    idtipoprograma: Optional[int] = Field(default=None, primary_key=True)
    nombretipoprograma: str = Field(max_length=100)
    
    # Relationships
    niveles_academicos: List["NivelAcademico"] = Relationship(back_populates="tipo_programa")


class Departamento(SQLModel, table=True):
    __tablename__ = "departamento"
    
    iddepartamento: Optional[int] = Field(default=None, primary_key=True)
    nombredepartamento: str = Field(max_length=150)
    
    # Relationships
    carreras: List["Carrera"] = Relationship(back_populates="departamento")
    documento_departamentos: List["DocumentoDepartamento"] = Relationship(back_populates="departamento")


class TipoSesion(SQLModel, table=True):
    __tablename__ = "tiposesion"
    
    idtiposesion: Optional[int] = Field(default=None, primary_key=True)
    tiposesion: str = Field(max_length=50)
    
    # Relationships
    documentos: List["Documento"] = Relationship(back_populates="tipo_sesion")


class TipoDecision(SQLModel, table=True):
    __tablename__ = "tipodecision"
    
    idtipodecision: Optional[int] = Field(default=None, primary_key=True)
    tipodecision: str = Field(max_length=50)
    
    # Relationships
    documentos: List["Documento"] = Relationship(back_populates="tipo_decision")


class TipoRelacion(SQLModel, table=True):
    __tablename__ = "tiporelacion"
    
    idtiporelacion: Optional[int] = Field(default=None, primary_key=True)
    tiporelacion: str = Field(max_length=50)
    
    # Relationships
    relaciones_documentales: List["RelacionDocumental"] = Relationship(back_populates="tipo_relacion")


class FuenteDeteccion(SQLModel, table=True):
    __tablename__ = "fuentedeteccion"
    
    idfuente: Optional[int] = Field(default=None, primary_key=True)
    nomfuente: str = Field(max_length=60, unique=True)
    
    # Relationships
    relaciones_documentales: List["RelacionDocumental"] = Relationship(back_populates="fuente_deteccion")


class TipoPagina(SQLModel, table=True):
    __tablename__ = "tipopagina"
    
    idtipopagina: Optional[int] = Field(default=None, primary_key=True)
    tipopagina: str = Field(max_length=50, unique=True)
    
    # Relationships
    chunks: List["DocumentoChunk"] = Relationship(back_populates="tipo_pagina")


# =============================================================================
# 2. ENTIDADES JERÁRQUICAS (PADRE-HIJO)
# =============================================================================

class SubAreas(SQLModel, table=True):
    __tablename__ = "subareas"
    
    idsubarea: Optional[int] = Field(default=None, primary_key=True)
    idtipoarea: int = Field(foreign_key="tipoarea.idtipoarea")
    nombre: str = Field(max_length=150)
    siglasubarea: str = Field(max_length=50, unique=True)
    
    # Relationships
    tipo_area: TipoArea = Relationship(back_populates="sub_areas")
    areas_emisoras: List["AreaEmisora"] = Relationship(back_populates="sub_area")


class Categoria(SQLModel, table=True):
    __tablename__ = "categoria"
    
    idcategoria: Optional[int] = Field(default=None, primary_key=True)
    idmacrocategoria: int = Field(foreign_key="macrocategoria.idmacrocategoria")
    numcategoria: str = Field(max_length=20, unique=True)
    nombrecategoria: str = Field(max_length=150)
    
    # Relationships
    macro_categoria: MacroCategoria = Relationship(back_populates="categorias")
    documentos: List["Documento"] = Relationship(back_populates="categoria")


class NivelAcademico(SQLModel, table=True):
    __tablename__ = "nivelacademico"
    
    idnivel: Optional[int] = Field(default=None, primary_key=True)
    idtipoprograma: int = Field(foreign_key="tipoprograma.idtipoprograma")
    nombrenivel: str = Field(max_length=100)
    
    # Relationships
    tipo_programa: TipoPrograma = Relationship(back_populates="niveles_academicos")
    carreras: List["Carrera"] = Relationship(back_populates="nivel_academico")
    documento_niveles: List["DocumentoNivel"] = Relationship(back_populates="nivel_academico")


class Carrera(SQLModel, table=True):
    __tablename__ = "carrera"
    
    idcarrera: Optional[int] = Field(default=None, primary_key=True)
    idnivel: int = Field(foreign_key="nivelacademico.idnivel")
    iddepartamento: int = Field(foreign_key="departamento.iddepartamento")
    codigocarrera: Optional[str] = Field(max_length=50, unique=True, default=None)
    nombrecarrera: str = Field(max_length=150)
    
    # Relationships
    nivel_academico: NivelAcademico = Relationship(back_populates="carreras")
    departamento: Departamento = Relationship(back_populates="carreras")
    documento_carreras: List["DocumentoCarrera"] = Relationship(back_populates="carrera")


# =============================================================================
# 3. NÚCLEO TRANSACCIONAL Y RAG
# =============================================================================

class Documento(SQLModel, table=True):
    __tablename__ = "documento"
    
    iddocumento: Optional[int] = Field(default=None, primary_key=True)
    idtipodocumento: int = Field(foreign_key="tipodocumento.idtipodocumento")
    idcategoria: int = Field(foreign_key="categoria.idcategoria")
    idtiposesion: Optional[int] = Field(default=None, foreign_key="tiposesion.idtiposesion")
    idestadovigencia: int = Field(foreign_key="estadovigencia.idestadovigencia")
    idtipodecision: Optional[int] = Field(default=None, foreign_key="tipodecision.idtipodecision")
    numsesion: Optional[int] = Field(default=None)
    numacuerdo: Optional[int] = Field(default=None)
    numero: str = Field(max_length=50, unique=True)
    titulo: str = Field(max_length=255)
    nommetadato: str = Field(max_length=255, unique=True)
    descripcion: Optional[str] = Field(default=None)
    urlarchivooriginals3: str = Field(max_length=500)
    cant_paginas: int = Field(gt=0)
    creacion: date
    derogacion: Optional[date] = Field(default=None)
    aplicacioninmediata: Optional[bool] = Field(default=None)
    isactive: bool = Field(default=True)
    
    # Relationships
    tipo_documento: TipoDocumento = Relationship(back_populates="documentos")
    categoria: Categoria = Relationship(back_populates="documentos")
    tipo_sesion: Optional[TipoSesion] = Relationship(back_populates="documentos")
    estado_vigencia: EstadoVigencia = Relationship(back_populates="documentos")
    tipo_decision: Optional[TipoDecision] = Relationship(back_populates="documentos")
    
    chunks: List["DocumentoChunk"] = Relationship(back_populates="documento")
    areas_emisoras: List["AreaEmisora"] = Relationship(back_populates="documento")
    nombramientos: List["DocumentoNombramiento"] = Relationship(back_populates="documento")
    jornadas: List["DocumentoJornada"] = Relationship(back_populates="documento")
    niveles: List["DocumentoNivel"] = Relationship(back_populates="documento")
    roles: List["DocumentoRol"] = Relationship(back_populates="documento")
    beneficios: List["DocumentoBeneficio"] = Relationship(back_populates="documento")
    sedes: List["DocumentoSedeCampus"] = Relationship(back_populates="documento")
    departamentos: List["DocumentoDepartamento"] = Relationship(back_populates="documento")
    carreras: List["DocumentoCarrera"] = Relationship(back_populates="documento")
    
    # Lineage relationships
    #relaciones_origen: List["RelacionDocumental"] = Relationship(back_populates="documento_origen")
    #relaciones_destino: List["RelacionDocumental"] = Relationship(back_populates="documento_destino")
    relaciones_origen: List["RelacionDocumental"] = Relationship(
        back_populates="documento_origen",
        sa_relationship_kwargs={
            "foreign_keys": "RelacionDocumental.iddocumentoorigen"
        },
    )

    relaciones_destino: List["RelacionDocumental"] = Relationship(
        back_populates="documento_destino",
        sa_relationship_kwargs={
            "foreign_keys": "RelacionDocumental.iddocumentodestino"
        },
    )


class DocumentoChunk(SQLModel, table=True):
    __tablename__ = "documentochunk"
    
    idchunk: Optional[int] = Field(default=None, primary_key=True)
    iddocumento: int = Field(foreign_key="documento.iddocumento")
    idtipopagina: Optional[int] = Field(default=None, foreign_key="tipopagina.idtipopagina")
    numeropagina: int
    nombretitulo: Optional[str] = Field(default=None, max_length=255)
    numeroarticulo: Optional[str] = Field(default=None, max_length=50)
    numeroinciso: Optional[str] = Field(default=None, max_length=50)
    secuencia: int
    textofragmento: str
    hashsha256: str = Field(max_length=64)
    isactive: bool = Field(default=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="chunks")
    tipo_pagina: Optional[TipoPagina] = Relationship(back_populates="chunks")


# =============================================================================
# 4. TRAZABILIDAD (LINAJE JURÍDICO)
# =============================================================================

class RelacionDocumental(SQLModel, table=True):
    __tablename__ = "relaciondocumental"
    
    idrelacion: Optional[int] = Field(default=None, primary_key=True)
    idfuentedeteccion: int = Field(foreign_key="fuentedeteccion.idfuente")
    idrespaldolegal: int = Field(foreign_key="respaldolegal.idrespaldolegal")
    idtiporelacion: int = Field(foreign_key="tiporelacion.idtiporelacion")
    iddocumentoorigen: int = Field(foreign_key="documento.iddocumento")
    iddocumentodestino: int = Field(foreign_key="documento.iddocumento")
    detalledemodificacion: Optional[str] = Field(default=None)
    confianza: Optional[float] = Field(default=1.00, ge=0.0, le=1.0)
    verificada: bool = Field(default=False)
    textoevidencia: Optional[str] = Field(default=None)
    fechaefecto: date
    
    # Relationships
    respaldo_legal: RespaldoLegal = Relationship(back_populates="relaciones_documentales")
    tipo_relacion: TipoRelacion = Relationship(back_populates="relaciones_documentales")
    #documento_origen: Documento = Relationship(back_populates="relaciones_origen")
    #documento_destino: Documento = Relationship(back_populates="relaciones_destino")
    documento_origen: Documento = Relationship(
        back_populates="relaciones_origen",
        sa_relationship_kwargs={
            "foreign_keys": "RelacionDocumental.iddocumentoorigen"
        },
    )

    documento_destino: Documento = Relationship(
        back_populates="relaciones_destino",
        sa_relationship_kwargs={
            "foreign_keys": "RelacionDocumental.iddocumentodestino"
        },
    )


    fuente_deteccion: Optional[FuenteDeteccion] = Relationship(back_populates="relaciones_documentales")


# =============================================================================
# 5. TABLAS PUENTE (RELACIONES N:M) CON LLAVES COMPUESTAS
# =============================================================================

class AreaEmisora(SQLModel, table=True):
    __tablename__ = "areaemisora"
    
    iddocumento: int = Field(foreign_key="documento.iddocumento", primary_key=True)
    idareaadministrativa: int = Field(foreign_key="subareas.idsubarea", primary_key=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="areas_emisoras")
    sub_area: SubAreas = Relationship(back_populates="areas_emisoras")


class DocumentoNombramiento(SQLModel, table=True):
    __tablename__ = "documentonombramiento"
    
    iddocumento: int = Field(foreign_key="documento.iddocumento", primary_key=True)
    idtiponombramiento: int = Field(foreign_key="tiponombramiento.idtiponombramiento", primary_key=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="nombramientos")
    tipo_nombramiento: TipoNombramiento = Relationship(back_populates="documento_nombramientos")


class DocumentoJornada(SQLModel, table=True):
    __tablename__ = "documentojornada"
    
    iddocumento: int = Field(foreign_key="documento.iddocumento", primary_key=True)
    idjornada: int = Field(foreign_key="jornada.idjornada", primary_key=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="jornadas")
    jornada: Jornada = Relationship(back_populates="documento_jornadas")


class DocumentoNivel(SQLModel, table=True):
    __tablename__ = "documentonivel"
    
    iddocumento: int = Field(foreign_key="documento.iddocumento", primary_key=True)
    idnivel: int = Field(foreign_key="nivelacademico.idnivel", primary_key=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="niveles")
    nivel_academico: NivelAcademico = Relationship(back_populates="documento_niveles")


class DocumentoRol(SQLModel, table=True):
    __tablename__ = "documentorol"
    
    iddocumento: int = Field(foreign_key="documento.iddocumento", primary_key=True)
    idrol: int = Field(foreign_key="rolinstitucional.idrol", primary_key=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="roles")
    rol: RolInstitucional = Relationship(back_populates="documento_roles")


class DocumentoBeneficio(SQLModel, table=True):
    __tablename__ = "documentobeneficio"
    
    iddocumento: int = Field(foreign_key="documento.iddocumento", primary_key=True)
    idbeneficio: int = Field(foreign_key="beneficiointerno.idbeneficio", primary_key=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="beneficios")
    beneficio: BeneficioInterno = Relationship(back_populates="documento_beneficios")


class DocumentoSedeCampus(SQLModel, table=True):
    __tablename__ = "documentosedecampus"
    
    iddocumento: int = Field(foreign_key="documento.iddocumento", primary_key=True)
    idrecintouniversitario: int = Field(foreign_key="sedecampus.idrecintouniversitario", primary_key=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="sedes")
    sede_campus: SedeCampus = Relationship(back_populates="documento_sedes")


class DocumentoDepartamento(SQLModel, table=True):
    __tablename__ = "documentodepartamento"
    
    iddocumento: int = Field(foreign_key="documento.iddocumento", primary_key=True)
    iddepartamento: int = Field(foreign_key="departamento.iddepartamento", primary_key=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="departamentos")
    departamento: Departamento = Relationship(back_populates="documento_departamentos")


class DocumentoCarrera(SQLModel, table=True):
    __tablename__ = "documentocarrera"
    
    iddocumento: int = Field(foreign_key="documento.iddocumento", primary_key=True)
    idcarrera: int = Field(foreign_key="carrera.idcarrera", primary_key=True)
    
    # Relationships
    documento: Documento = Relationship(back_populates="carreras")
    carrera: Carrera = Relationship(back_populates="documento_carreras")
