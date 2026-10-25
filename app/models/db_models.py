"""Modelos de base de datos relacionales (tablas SQLModel) para el sistema GIRU."""

from datetime import date, datetime
from uuid import UUID as pyUUID, uuid4
from sqlalchemy import Column, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlmodel import Field, Relationship, SQLModel

FK_DOCUMENTO_ID = "documento.iddocumento"


# =============================================================================
# 1. CATÁLOGOS BASE (ON DELETE RESTRICT)
# =============================================================================

class TipoArea(SQLModel, table=True):
    """Catálogo de tipos de áreas institucionales."""

    __tablename__ = "tipoarea"

    idtipoarea: int | None = Field(default=None, primary_key=True)
    nombrearea: str = Field(max_length=100)
    siglaarea: str = Field(max_length=20, unique=True)

    sub_areas: list["SubAreas"] = Relationship(back_populates="tipo_area")


class MacroCategoria(SQLModel, table=True):
    """Catálogo de macro-categorías documentales."""

    __tablename__ = "macrocategoria"

    idmacrocategoria: int | None = Field(default=None, primary_key=True)
    siglamacro: str = Field(max_length=2, unique=True)
    nombrecategoria: str = Field(max_length=100)

    categorias: list["Categoria"] = Relationship(back_populates="macro_categoria")


class TipoDocumento(SQLModel, table=True):
    """Catálogo de tipos de documentos (Decreto, Resolución, etc.)."""

    __tablename__ = "tipodocumento"

    idtipodocumento: int | None = Field(default=None, primary_key=True)
    nombretipodocumento: str = Field(max_length=100, unique=True)
    isactive: bool = Field(default=True)

    documentos: list["Documento"] = Relationship(back_populates="tipo_documento")


class EstadoVigencia(SQLModel, table=True):
    """Catálogo de estados de vigencia jurídica de documentos."""

    __tablename__ = "estadovigencia"

    idestadovigencia: int | None = Field(default=None, primary_key=True)
    estadovigencia: str = Field(max_length=50, unique=True)

    documentos: list["Documento"] = Relationship(back_populates="estado_vigencia")


class RespaldoLegal(SQLModel, table=True):
    """Catálogo de respaldos legales para relaciones documentales."""

    __tablename__ = "respaldolegal"

    idrespaldolegal: int | None = Field(default=None, primary_key=True)
    respaldolegal: str = Field(max_length=255)

    relaciones_documentales: list["RelacionDocumental"] = Relationship(back_populates="respaldo_legal")


class RolInstitucional(SQLModel, table=True):
    """Catálogo de roles institucionales asociados a documentos."""

    __tablename__ = "rolinstitucional"

    idrol: int | None = Field(default=None, primary_key=True)
    nombrerol: str = Field(max_length=100, unique=True)

    documento_roles: list["DocumentoRol"] = Relationship(back_populates="rol")


class BeneficioInterno(SQLModel, table=True):
    """Catálogo de beneficios internos otorgados por normativa."""

    __tablename__ = "beneficiointerno"

    idbeneficio: int | None = Field(default=None, primary_key=True)
    nombrebeneficio: str = Field(max_length=150, unique=True)

    documento_beneficios: list["DocumentoBeneficio"] = Relationship(back_populates="beneficio")


class Jornada(SQLModel, table=True):
    """Catálogo de jornadas laborales y académicas."""

    __tablename__ = "jornada"

    idjornada: int | None = Field(default=None, primary_key=True)
    nombrejornada: str = Field(max_length=50, unique=True)

    documento_jornadas: list["DocumentoJornada"] = Relationship(back_populates="jornada")


class SedeCampus(SQLModel, table=True):
    """Catálogo de recintos universitarios, sedes y campus."""

    __tablename__ = "sedecampus"

    idrecintouniversitario: int | None = Field(default=None, primary_key=True)
    nombrerecinto: str = Field(max_length=100, unique=True)

    documento_sedes: list["DocumentoSedeCampus"] = Relationship(back_populates="sede_campus")


class Departamento(SQLModel, table=True):
    """Catálogo de departamentos académicos y administrativos."""

    __tablename__ = "departamento"

    iddepartamento: int | None = Field(default=None, primary_key=True)
    nombredepartamento: str = Field(max_length=100, unique=True)

    carreras: list["Carrera"] = Relationship(back_populates="departamento")
    documento_departamentos: list["DocumentoDepartamento"] = Relationship(back_populates="departamento")


class TipoDecision(SQLModel, table=True):
    """Catálogo de tipos de decisión (Aprobación, Promulgación, etc.)."""

    __tablename__ = "tipodecision"

    idtipodecision: int | None = Field(default=None, primary_key=True)
    tipodecision: str = Field(max_length=50, unique=True)

    documentos: list["Documento"] = Relationship(back_populates="tipo_decision")


class TipoSesion(SQLModel, table=True):
    """Catálogo de tipos de sesión (Ordinaria, Extraordinaria, etc.)."""

    __tablename__ = "tiposesion"

    idtiposesion: int | None = Field(default=None, primary_key=True)
    tiposesion: str = Field(max_length=50, unique=True)

    documentos: list["Documento"] = Relationship(back_populates="tipo_sesion")


class TipoNombramiento(SQLModel, table=True):
    """Catálogo de tipos de nombramiento institucional."""

    __tablename__ = "tiponombramiento"

    idtiponombramiento: int | None = Field(default=None, primary_key=True)
    nombrenombramiento: str = Field(max_length=100, unique=True)

    documento_nombramientos: list["DocumentoNombramiento"] = Relationship(back_populates="tipo_nombramiento")


class TipoRelacion(SQLModel, table=True):
    """Catálogo de tipos de relaciones jurídicas entre documentos."""

    __tablename__ = "tiporelacion"

    idtiporelacion: int | None = Field(default=None, primary_key=True)
    tiporelacion: str = Field(max_length=50, unique=True)

    relaciones_documentales: list["RelacionDocumental"] = Relationship(back_populates="tipo_relacion")


class TipoPrograma(SQLModel, table=True):
    """Catálogo de tipos de programa académico."""

    __tablename__ = "tipoprograma"

    idtipoprograma: int | None = Field(default=None, primary_key=True)
    nombretipoprograma: str = Field(max_length=50, unique=True)

    niveles_academicos: list["NivelAcademico"] = Relationship(back_populates="tipo_programa")


class FuenteDeteccion(SQLModel, table=True):
    """Catálogo de fuentes de detección de relaciones documentales."""

    __tablename__ = "fuentedeteccion"

    idfuente: int | None = Field(default=None, primary_key=True)
    nomfuente: str = Field(max_length=60, unique=True)

    relaciones_documentales: list["RelacionDocumental"] = Relationship(back_populates="fuente_deteccion")


class TipoPagina(SQLModel, table=True):
    """Catálogo de clasificación de páginas en documentos."""

    __tablename__ = "tipopagina"

    idtipopagina: int | None = Field(default=None, primary_key=True)
    tipopagina: str = Field(max_length=50, unique=True)

    chunks: list["DocumentoChunk"] = Relationship(back_populates="tipo_pagina")


# =============================================================================
# 2. ENTIDADES JERÁRQUICAS (PADRE-HIJO)
# =============================================================================

class SubAreas(SQLModel, table=True):
    """Sub-áreas administrativas dependientes de un área tipo."""

    __tablename__ = "subarea"

    idsubarea: int | None = Field(default=None, primary_key=True)
    idtipoarea: int = Field(foreign_key="tipoarea.idtipoarea")
    nombre: str = Field(max_length=150)
    siglasubarea: str = Field(max_length=50, unique=True)

    tipo_area: TipoArea = Relationship(back_populates="sub_areas")
    areas_emisoras: list["AreaEmisora"] = Relationship(back_populates="sub_area")


class Categoria(SQLModel, table=True):
    """Categorías documentales dependientes de una macro-categoría."""

    __tablename__ = "categoria"

    idcategoria: int | None = Field(default=None, primary_key=True)
    idmacrocategoria: int = Field(foreign_key="macrocategoria.idmacrocategoria")
    numcategoria: str = Field(max_length=20, unique=True)
    nombrecategoria: str = Field(max_length=150)

    macro_categoria: MacroCategoria = Relationship(back_populates="categorias")
    documentos: list["Documento"] = Relationship(back_populates="categoria")


class NivelAcademico(SQLModel, table=True):
    """Niveles académicos dependientes de un tipo de programa."""

    __tablename__ = "nivelacademico"

    idnivel: int | None = Field(default=None, primary_key=True)
    idtipoprograma: int = Field(foreign_key="tipoprograma.idtipoprograma")
    nombrenivel: str = Field(max_length=100)

    tipo_programa: TipoPrograma = Relationship(back_populates="niveles_academicos")
    carreras: list["Carrera"] = Relationship(back_populates="nivel_academico")
    documento_niveles: list["DocumentoNivel"] = Relationship(back_populates="nivel_academico")


class Carrera(SQLModel, table=True):
    """Carreras universitarias vinculadas a nivel y departamento."""

    __tablename__ = "carrera"

    idcarrera: int | None = Field(default=None, primary_key=True)
    idnivel: int = Field(foreign_key="nivelacademico.idnivel")
    iddepartamento: int = Field(foreign_key="departamento.iddepartamento")
    codigocarrera: str | None = Field(max_length=50, unique=True, default=None)
    nombrecarrera: str = Field(max_length=150)

    nivel_academico: NivelAcademico = Relationship(back_populates="carreras")
    departamento: Departamento = Relationship(back_populates="carreras")
    documento_carreras: list["DocumentoCarrera"] = Relationship(back_populates="carrera")


# =============================================================================
# 3. NÚCLEO TRANSACCIONAL Y RAG
# =============================================================================

class Documento(SQLModel, table=True):
    """Entidad principal que representa un documento normativo institucional."""

    __tablename__ = "documento"

    iddocumento: pyUUID = Field(
        default_factory=uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    )
    idtipodocumento: int = Field(foreign_key="tipodocumento.idtipodocumento")
    idcategoria: int = Field(foreign_key="categoria.idcategoria")
    idtiposesion: int | None = Field(default=None, foreign_key="tiposesion.idtiposesion")
    idestadovigencia: int = Field(foreign_key="estadovigencia.idestadovigencia")
    idtipodecision: int | None = Field(default=None, foreign_key="tipodecision.idtipodecision")
    numsesion: int | None = Field(default=None)
    numacuerdo: int | None = Field(default=None)
    numero: str = Field(max_length=50, unique=True)
    titulo: str = Field(max_length=255)
    nommetadato: str = Field(max_length=255, unique=True)
    descripcion: str | None = Field(default=None)
    urlarchivooriginals3: str | None = Field(default=None, max_length=500)
    cant_paginas: int = Field(gt=0)
    creacion: date
    derogacion: date | None = Field(default=None)
    aplicacioninmediata: bool | None = Field(default=None)
    isactive: bool = Field(default=True)
    ultima_modificacion: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=True
        )
    )

    tipo_documento: TipoDocumento = Relationship(back_populates="documentos")
    categoria: Categoria = Relationship(back_populates="documentos")
    tipo_sesion: TipoSesion | None = Relationship(back_populates="documentos")
    estado_vigencia: EstadoVigencia = Relationship(back_populates="documentos")
    tipo_decision: TipoDecision | None = Relationship(back_populates="documentos")

    chunks: list["DocumentoChunk"] = Relationship(back_populates="documento")
    areas_emisoras: list["AreaEmisora"] = Relationship(back_populates="documento")
    nombramientos: list["DocumentoNombramiento"] = Relationship(back_populates="documento")
    jornadas: list["DocumentoJornada"] = Relationship(back_populates="documento")
    niveles: list["DocumentoNivel"] = Relationship(back_populates="documento")
    roles: list["DocumentoRol"] = Relationship(back_populates="documento")
    beneficios: list["DocumentoBeneficio"] = Relationship(back_populates="documento")
    sedes: list["DocumentoSedeCampus"] = Relationship(back_populates="documento")
    departamentos: list["DocumentoDepartamento"] = Relationship(back_populates="documento")
    carreras: list["DocumentoCarrera"] = Relationship(back_populates="documento")

    relaciones_origen: list["RelacionDocumental"] = Relationship(
        back_populates="documento_origen",
        sa_relationship_kwargs={
            "foreign_keys": "RelacionDocumental.iddocumentoorigen"
        },
    )
    relaciones_destino: list["RelacionDocumental"] = Relationship(
        back_populates="documento_destino",
        sa_relationship_kwargs={
            "foreign_keys": "RelacionDocumental.iddocumentodestino"
        },
    )


class DocumentoChunk(SQLModel, table=True):
    """Fragmento textual extraído de un documento para búsqueda semántica."""

    __tablename__ = "documentochunk"

    idchunk: int | None = Field(default=None, primary_key=True)
    iddocumento: pyUUID = Field(sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID)))
    idtipopagina: int | None = Field(default=None, foreign_key="tipopagina.idtipopagina")
    numeropagina: int
    nombretitulo: str | None = Field(default=None, max_length=255)
    numeroarticulo: str | None = Field(default=None, max_length=50)
    numeroinciso: str | None = Field(default=None, max_length=50)
    secuencia: int
    textofragmento: str
    hashsha256: str = Field(max_length=64)
    isactive: bool = Field(default=True)

    documento: Documento = Relationship(back_populates="chunks")
    tipo_pagina: TipoPagina | None = Relationship(back_populates="chunks")


# =============================================================================
# 4. TRAZABILIDAD (LINAJE JURÍDICO)
# =============================================================================

class RelacionDocumental(SQLModel, table=True):
    """Relación jurídica formal entre un documento origen y uno destino."""

    __tablename__ = "relaciondocumental"

    idrelacion: int | None = Field(default=None, primary_key=True)
    idfuentedeteccion: int = Field(foreign_key="fuentedeteccion.idfuente")
    idrespaldolegal: int = Field(foreign_key="respaldolegal.idrespaldolegal")
    idtiporelacion: int = Field(foreign_key="tiporelacion.idtiporelacion")
    iddocumentoorigen: pyUUID = Field(sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID)))
    iddocumentodestino: pyUUID = Field(sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID)))
    detallemodificacion: str | None = Field(default=None)
    confianza: float | None = Field(default=1.00, ge=0.0, le=1.0)
    verificada: bool = Field(default=False)
    textoevidencia: str | None = Field(default=None)
    fechaefecto: date

    respaldo_legal: RespaldoLegal = Relationship(back_populates="relaciones_documentales")
    tipo_relacion: TipoRelacion = Relationship(back_populates="relaciones_documentales")
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

    fuente_deteccion: FuenteDeteccion | None = Relationship(back_populates="relaciones_documentales")


# =============================================================================
# 5. TABLAS PUENTE (RELACIONES N:M) CON LLAVES COMPUESTAS
# =============================================================================

class AreaEmisora(SQLModel, table=True):
    """Tabla puente entre documentos y sub-áreas emisoras."""

    __tablename__ = "areaemisora"

    iddocumento: pyUUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID), primary_key=True)
    )
    idareaadministrativa: int = Field(foreign_key="subarea.idsubarea", primary_key=True)

    documento: Documento = Relationship(back_populates="areas_emisoras")
    sub_area: SubAreas = Relationship(back_populates="areas_emisoras")


class DocumentoNombramiento(SQLModel, table=True):
    """Tabla puente entre documentos y nombramientos."""

    __tablename__ = "documentonombramiento"

    iddocumento: pyUUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID), primary_key=True)
    )
    idtiponombramiento: int = Field(foreign_key="tiponombramiento.idtiponombramiento", primary_key=True)

    documento: Documento = Relationship(back_populates="nombramientos")
    tipo_nombramiento: TipoNombramiento = Relationship(back_populates="documento_nombramientos")


class DocumentoJornada(SQLModel, table=True):
    """Tabla puente entre documentos y jornadas."""

    __tablename__ = "documentojornada"

    iddocumento: pyUUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID), primary_key=True)
    )
    idjornada: int = Field(foreign_key="jornada.idjornada", primary_key=True)

    documento: Documento = Relationship(back_populates="jornadas")
    jornada: Jornada = Relationship(back_populates="documento_jornadas")


class DocumentoNivel(SQLModel, table=True):
    """Tabla puente entre documentos y niveles académicos."""

    __tablename__ = "documentonivel"

    iddocumento: pyUUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID), primary_key=True)
    )
    idnivel: int = Field(foreign_key="nivelacademico.idnivel", primary_key=True)

    documento: Documento = Relationship(back_populates="niveles")
    nivel_academico: NivelAcademico = Relationship(back_populates="documento_niveles")


class DocumentoRol(SQLModel, table=True):
    """Tabla puente entre documentos y roles institucionales."""

    __tablename__ = "documentorol"

    iddocumento: pyUUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID), primary_key=True)
    )
    idrol: int = Field(foreign_key="rolinstitucional.idrol", primary_key=True)

    documento: Documento = Relationship(back_populates="roles")
    rol: RolInstitucional = Relationship(back_populates="documento_roles")


class DocumentoBeneficio(SQLModel, table=True):
    """Tabla puente entre documentos y beneficios internos."""

    __tablename__ = "documentobeneficio"

    iddocumento: pyUUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID), primary_key=True)
    )
    idbeneficio: int = Field(foreign_key="beneficiointerno.idbeneficio", primary_key=True)

    documento: Documento = Relationship(back_populates="beneficios")
    beneficio: BeneficioInterno = Relationship(back_populates="documento_beneficios")


class DocumentoSedeCampus(SQLModel, table=True):
    """Tabla puente entre documentos y sedes/campus."""

    __tablename__ = "documentosedecampus"

    iddocumento: pyUUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID), primary_key=True)
    )
    idrecintouniversitario: int = Field(foreign_key="sedecampus.idrecintouniversitario", primary_key=True)

    documento: Documento = Relationship(back_populates="sedes")
    sede_campus: SedeCampus = Relationship(back_populates="documento_sedes")


class DocumentoDepartamento(SQLModel, table=True):
    """Tabla puente entre documentos y departamentos."""

    __tablename__ = "documentodepartamento"

    iddocumento: pyUUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID), primary_key=True)
    )
    iddepartamento: int = Field(foreign_key="departamento.iddepartamento", primary_key=True)

    documento: Documento = Relationship(back_populates="departamentos")
    departamento: Departamento = Relationship(back_populates="documento_departamentos")


class DocumentoCarrera(SQLModel, table=True):
    """Tabla puente entre documentos y carreras."""

    __tablename__ = "documentocarrera"

    iddocumento: pyUUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey(FK_DOCUMENTO_ID), primary_key=True)
    )
    idcarrera: int = Field(foreign_key="carrera.idcarrera", primary_key=True)

    documento: Documento = Relationship(back_populates="carreras")
    carrera: Carrera = Relationship(back_populates="documento_carreras")
