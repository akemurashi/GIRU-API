"""Repositorio de persistencia y consultas para la entidad Documento y su catálogo."""

from datetime import date
import json
import re
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select, text

from app.core.database import get_session
from app.core.exceptions import (
    CatalogNotFoundError,
    DAGCycleError,
    DatabaseError,
    DocumentNotFoundError,
    UniqueConstraintError,
    ValidationError as AppValidationError,
)
from app.models.db_models import (
    BeneficioInterno,
    Carrera,
    Categoria,
    Departamento,
    Documento,
    EstadoVigencia,
    FuenteDeteccion,
    Jornada,
    MacroCategoria,
    NivelAcademico,
    RespaldoLegal,
    RolInstitucional,
    SedeCampus,
    SubAreas,
    TipoArea,
    TipoDecision,
    TipoDocumento,
    TipoNombramiento,
    TipoPrograma,
    TipoRelacion,
    TipoSesion,
)
from app.models.document_models import (
    BeneficioOut,
    CarreraOut,
    CategoriaOut,
    DepartamentoOut,
    DocumentoDetail,
    DocumentoEditableOut,
    DocumentoUpdate,
    NombramientoOut,
    SedeCampusOut,
)
from app.models.search_models import FilterOption, FilterOptions


class DocumentRepository(object):
    """
    Acceso a PostgreSQL para la tabla Documento y sus relaciones.
    Implementado con SQLModel async y procedimientos almacenados canónicos.
    """

    @staticmethod
    def _handle_sp_error(e: Exception, document_id: str) -> None:
        """
        Captura y clasifica excepciones generadas por procedimientos almacenados en PostgreSQL,
        traduciéndolas a excepciones semánticas de la aplicación.
        """
        msg = str(e)
        orig = getattr(e, "orig", None)
        if orig:
            msg = str(orig)

        match = re.search(r"(?:RaiseError|RaiseException)'>:\s*([^\n\[]+)", msg)
        clean_msg = match.group(1).strip() if match else msg

        if "No se encontró el documento" in clean_msg:
            raise DocumentNotFoundError(document_id)
        if "Unicidad:" in clean_msg:
            raise UniqueConstraintError(clean_msg, {"document_id": document_id})
        if "Violación de Grafo Acíclico (DAG)" in clean_msg:
            raise DAGCycleError(clean_msg, {"document_id": document_id})
        if "Catálogo:" in clean_msg:
            raise CatalogNotFoundError(clean_msg, {"document_id": document_id})
        if "Validación:" in clean_msg or "Parámetro:" in clean_msg:
            raise AppValidationError(clean_msg, details={"document_id": document_id})

        raise DatabaseError(
            f"Error al procesar la actualización del documento: {clean_msg}",
            {"document_id": document_id},
        )

    @staticmethod
    def _parse_categorias(doc_data: dict[str, object]) -> list[CategoriaOut]:
        macro = doc_data.get("macrocategoria") or {} if isinstance(doc_data, dict) else {}
        cat = doc_data.get("categoria") or {} if isinstance(doc_data, dict) else {}
        if not (cat and cat.get("id")):
            return []
        return [
            CategoriaOut(
                idcategoria=cat.get("id"),
                nombrecategoria=cat.get("nombre") or "",
                numcategoria=cat.get("num"),
                macrocategoria=macro.get("nombre") if macro else None,
            )
        ]

    @staticmethod
    def _parse_relations(raw: dict[str, object]) -> tuple[
        list[SedeCampusOut],
        list[CarreraOut],
        list[BeneficioOut],
        list[NombramientoOut],
        list[DepartamentoOut],
    ]:
        sedes = [
            SedeCampusOut(idrecintouniversitario=s["id"], nombrerecinto=s["nombre"])
            for s in raw.get("sedes_campus", [])
            if s.get("id")
        ]
        carreras = [
            CarreraOut(
                idcarrera=c["id"],
                nombrecarrera=c["nombre"],
                codigocarrera=c.get("codigo"),
                nombrenivel=c.get("nivel"),
                nombredepartamento=c.get("departamento"),
            )
            for c in raw.get("carreras", [])
            if c.get("id")
        ]
        beneficios = [
            BeneficioOut(idbeneficio=b["id"], nombrebeneficio=b["nombre"])
            for b in raw.get("beneficios_internos", [])
            if b.get("id")
        ]
        nombramientos = [
            NombramientoOut(idtiponombramiento=n["id"], nombrenombramiento=n["nombre"])
            for n in raw.get("nombramientos", [])
            if n.get("id")
        ]
        departamentos = [
            DepartamentoOut(iddepartamento=d["id"], nombredepartamento=d["nombre"])
            for d in raw.get("departamentos", [])
            if d.get("id")
        ]
        return sedes, carreras, beneficios, nombramientos, departamentos

    @classmethod
    def _build_documento_detail(cls, raw: dict[str, object], document_id: str) -> DocumentoDetail:
        """Construye un DocumentoDetail a partir de la representación canónica JSONB."""
        doc_data = raw.get("documento") or {}
        if not doc_data:
            raise DocumentNotFoundError(document_id)

        sesion = doc_data.get("sesion") or {}
        tipo_doc = doc_data.get("tipodocumento") or {}
        estado_vig = doc_data.get("estadovigencia") or {}
        categorias = cls._parse_categorias(doc_data)
        sedes, carreras, beneficios, nombramientos, departamentos = cls._parse_relations(raw)

        return DocumentoDetail(
            iddocumento=doc_data.get("iddocumento") or document_id,
            numero=doc_data.get("numero") or "",
            titulo=doc_data.get("titulo") or "",
            nommetadato=doc_data.get("nommetadato") or "",
            tipodocumento=tipo_doc.get("nombre"),
            tipodecision=sesion.get("tipodecision"),
            tiposesion=sesion.get("tiposesion"),
            estadovigencia=estado_vig.get("nombre"),
            numacuerdo=sesion.get("numacuerdo"),
            numsesion=sesion.get("numsesion"),
            descripcion=doc_data.get("descripcion"),
            creacion=doc_data.get("creacion"),
            derogacion=doc_data.get("derogacion"),
            aplicacioninmediata=doc_data.get("aplicacioninmediata"),
            isactive=doc_data.get("isactive", True),
            ultima_modificacion=doc_data.get("ultima_modificacion"),
            cant_paginas=doc_data.get("cant_paginas", 0) or 0,
            urlarchivooriginals3=doc_data.get("urlarchivooriginals3"),
            sedes=sedes, categorias=categorias, carreras=carreras,
            beneficios=beneficios, nombramientos=nombramientos,
            departamentos=departamentos, chunkcount=0,
        )

    @staticmethod
    def _map_doc_row(row: object, score: float) -> dict[str, object]:
        """Convierte una fila de documento SQL a diccionario estructurado."""
        return {
            "document_id": getattr(row, "iddocumento", None),
            "chunk_id": None,
            "texto_fragmento": getattr(row, "descripcion", None) or getattr(row, "titulo", None),
            "numero_pagina": None, "secuencia": None, "nombre_titulo": None,
            "numero_articulo": None, "numero_inciso": None,
            "numero": getattr(row, "numero", None), "titulo": getattr(row, "titulo", None),
            "nom_meta_dato": getattr(row, "nommetadato", None),
            "id_tipo_documento": getattr(row, "idtipodocumento", None),
            "id_estado_vigencia": getattr(row, "idestadovigencia", None),
            "id_categoria": getattr(row, "idcategoria", None),
            "creacion": getattr(row, "creacion", None), "derogacion": getattr(row, "derogacion", None),
            "aplicacion_inmediata": getattr(row, "aplicacioninmediata", None),
            "is_active": getattr(row, "isactive", None),
            "ultima_modificacion": getattr(row, "ultima_modificacion", None),
            "numacuerdo": getattr(row, "numacuerdo", None), "numsesion": getattr(row, "numsesion", None),
            "tipodocumento": getattr(row, "nombretipodocumento", None),
            "estadovigencia": getattr(row, "estadovigencia", None),
            "tipodecision": getattr(row, "tipodecision", None),
            "tiposesion": getattr(row, "tiposesion", None),
            "score": score,
        }

    @staticmethod
    def _add_in_clause(clauses: list[str], params: dict[str, object], col: str, key: str, val: object) -> None:
        """Agrega cláusula de igualdad o ANY si es lista."""
        if isinstance(val, list):
            clauses.append(f"{col} = ANY(:{key})")
        else:
            clauses.append(f"{col} = :{key}")
        params[key] = val

    @staticmethod
    def _add_exists_clause(
        clauses: list[str],
        params: dict[str, object],
        table: str,
        col: str,
        key: str,
        val: object,
    ) -> None:
        """Agrega cláusula EXISTS para tablas puente."""
        placeholder = f"ANY(:{key})" if isinstance(val, list) else f":{key}"
        clauses.append(
            f"EXISTS (SELECT 1 FROM {table} b "
            f"WHERE b.iddocumento = d.iddocumento AND b.{col} = {placeholder})"
        )
        params[key] = val

    @staticmethod
    def _add_temporal_filter_clauses(
        filters: dict[str, object],
        clauses: list[str],
        params: dict[str, object],
    ) -> None:
        """Agrega filtros por años o rango de fechas de creación."""
        anios = filters.get("anios")
        if anios:
            anios_list = [int(a) for a in ([anios] if isinstance(anios, int) else anios)]
            clauses.append("EXTRACT(YEAR FROM d.creacion)::int = ANY(:anios)")
            params["anios"] = anios_list

        f_desde = filters.get("creaciondesde") or filters.get("fechadesde")
        if f_desde:
            parsed_desde = date.fromisoformat(str(f_desde)[:10]) if isinstance(f_desde, str) else f_desde
            clauses.append("d.creacion >= :fecha_desde")
            params["fecha_desde"] = parsed_desde

        f_hasta = filters.get("creacionhasta") or filters.get("fechahasta")
        if f_hasta:
            parsed_hasta = date.fromisoformat(str(f_hasta)[:10]) if isinstance(f_hasta, str) else f_hasta
            clauses.append("d.creacion <= :fecha_hasta")
            params["fecha_hasta"] = parsed_hasta

        if filters.get("aplicacioninmediata") is not None:
            clauses.append("d.aplicacioninmediata = :aplicacion_inmediata")
            params["aplicacion_inmediata"] = filters["aplicacioninmediata"]

        if filters.get("isactive") is not None:
            clauses.append("d.isactive = :is_active")
            params["is_active"] = filters["isactive"]

    @classmethod
    def _add_area_filter_clauses(
        cls,
        filters: dict[str, object],
        clauses: list[str],
        params: dict[str, object],
    ) -> None:
        """Agrega filtros por área emisora y subárea administrativa."""
        id_area = filters.get("idtipoarea")
        if id_area is not None:
            placeholder = "ANY(:idtipoarea)" if isinstance(id_area, list) else ":idtipoarea"
            clauses.append(
                f"EXISTS (SELECT 1 FROM areaemisora ae JOIN subarea sa ON ae.idareaadministrativa = sa.idsubarea "
                f"WHERE ae.iddocumento = d.iddocumento AND sa.idtipoarea = {placeholder})"
            )
            params["idtipoarea"] = id_area

        id_sub = filters.get("idsubarea")
        if id_sub is not None:
            placeholder = "ANY(:idsubarea)" if isinstance(id_sub, list) else ":idsubarea"
            clauses.append(
                f"EXISTS (SELECT 1 FROM areaemisora ae "
                f"WHERE ae.iddocumento = d.iddocumento AND ae.idareaadministrativa = {placeholder})"
            )
            params["idsubarea"] = id_sub

    @classmethod
    def _add_bridge_filter_clauses(
        cls,
        filters: dict[str, object],
        clauses: list[str],
        params: dict[str, object],
    ) -> None:
        """Agrega filtros por relaciones secundarias en tablas puente."""
        bridge_fields = [
            ("idrecintouniversitario", "documentosedecampus", "idrecintouniversitario"),
            ("idcarrera", "documentocarrera", "idcarrera"),
            ("iddepartamento", "documentodepartamento", "iddepartamento"),
            ("idbeneficio", "documentobeneficio", "idbeneficio"),
            ("idtiponombramiento", "documentonombramiento", "idtiponombramiento"),
            ("idjornada", "documentojornada", "idjornada"),
            ("idnivel", "documentonivel", "idnivel"),
            ("idrol", "documentorol", "idrol"),
        ]
        for key, table, col in bridge_fields:
            val = filters.get(key)
            if val is not None:
                cls._add_exists_clause(clauses, params, table, col, key, val)

    def _build_search_filter_clauses(self, filters: dict[str, object]) -> tuple[list[str], dict[str, object]]:
        """
        Construye cláusulas WHERE parametrizadas y diccionario de parámetros para filtros
        compartidos entre búsqueda general, búsqueda semántica y búsqueda léxica.
        """
        clauses: list[str] = []
        params: dict[str, object] = {}

        direct_fields = [
            ("idestadovigencia", "d.idestadovigencia"),
            ("idtipodocumento", "d.idtipodocumento"),
            ("idtipodecision", "d.idtipodecision"),
            ("idtiposesion", "d.idtiposesion"),
            ("idcategoria", "d.idcategoria"),
        ]
        for key, col in direct_fields:
            val = filters.get(key)
            if val is not None:
                self._add_in_clause(clauses, params, col, key, val)

        id_macro = filters.get("idmacrocategoria")
        if id_macro is not None:
            placeholder = "ANY(:idmacrocategoria)" if isinstance(id_macro, list) else ":idmacrocategoria"
            clauses.append(
                f"EXISTS (SELECT 1 FROM categoria cat "
                f"WHERE cat.idcategoria = d.idcategoria AND cat.idmacrocategoria = {placeholder})"
            )
            params["idmacrocategoria"] = id_macro

        self._add_temporal_filter_clauses(filters, clauses, params)
        self._add_area_filter_clauses(filters, clauses, params)
        self._add_bridge_filter_clauses(filters, clauses, params)

        return clauses, params

    @staticmethod
    def _build_update_params(data: DocumentoUpdate, uuid_obj: UUID) -> tuple[dict[str, object], UUID | None]:
        """Construye el diccionario de parámetros para el SP sp_modificar_documento_completo."""
        recalcular = data.recalcular_nommetadato
        if data.nommetadato is not None and not data.recalcular_nommetadato:
            recalcular = False

        rel_destino_uuid = None
        if data.relacion_destino_id:
            try:
                rel_destino_uuid = UUID(str(data.relacion_destino_id))
            except ValueError:
                raise AppValidationError(
                    "relacion_destino_id debe ser un UUID válido",
                    field="relacion_destino_id",
                )

        sp_params = {
            "p_iddocumento": uuid_obj, "p_numero": data.numero, "p_titulo": data.titulo,
            "p_descripcion": data.descripcion, "p_urlarchivooriginals3": None,
            "p_idtipodocumento": data.idtipodocumento,
            "p_nombretipodocumento": data.tipo_documento_nombre,
            "p_idcategoria": data.idcategoria, "p_nombrecategoria": data.nombrecategoria,
            "p_numcategoria": data.categoria_num, "p_nommetadato": data.nommetadato,
            "p_recalcular_nommetadato": recalcular, "p_idestadovigencia": data.idestadovigencia,
            "p_nombreestadovigencia": data.estado_vigencia_nombre, "p_creacion": data.creacion,
            "p_derogacion": data.derogacion, "p_limpiar_derogacion": data.limpiar_derogacion,
            "p_isactive": data.isactive, "p_idtiposesion": data.idtiposesion,
            "p_nombretiposesion": data.tipo_sesion_nombre, "p_numsesion": data.numsesion,
            "p_numacuerdo": data.numacuerdo, "p_idtipodecision": data.idtipodecision,
            "p_nombretipodecision": data.tipo_decision_nombre,
            "p_limpiar_sesion": data.limpiar_sesion,
            "p_areas_emisoras_ids": data.areaseemisorasids,
            "p_areas_emisoras_nombres": data.areas_emisoras_nombres,
            "p_niveles_ids": data.nivelesids, "p_niveles_nombres": data.niveles_nombres,
            "p_jornadas_ids": data.jornadasids, "p_jornadas_nombres": data.jornadas_nombres,
            "p_sedes_ids": data.sedesids, "p_sedes_nombres": data.sedes_nombres,
            "p_carreras_ids": data.carrerasids, "p_carreras_nombres": data.carreras_nombres,
            "p_departamentos_ids": data.departamentosids,
            "p_departamentos_nombres": data.departamentos_nombres,
            "p_roles_ids": data.rolesids, "p_roles_nombres": data.roles_nombres,
            "p_beneficios_ids": data.beneficiosids,
            "p_beneficios_nombres": data.beneficios_nombres,
            "p_nombramientos_ids": data.nombramientosids,
            "p_nombramientos_nombres": data.nombramientos_nombres,
            "p_modo_puentes": data.modo_puentes or "REEMPLAZAR",
            "p_relacion_destino_id": rel_destino_uuid,
            "p_relacion_tipo_id": data.relacion_tipo_id,
            "p_relacion_tipo_nombre": data.relacion_tipo_nombre,
            "p_relacion_detalle": data.relacion_detalle,
            "p_relacion_fecha": data.relacion_fecha,
            "p_relacion_verificada": data.relacion_verificada,
        }
        return sp_params, rel_destino_uuid

    @staticmethod
    async def get_s3_key(document_id: str) -> str:
        """Devuelve solo la ruta del PDF en S3 (sin cargar sedes, carreras, chunks, etc.)."""
        async with get_session() as session:
            stmt = select(Documento.urlarchivooriginals3).where(
                Documento.iddocumento == document_id,
                Documento.isactive == True,
            )
            result = await session.execute(stmt)
            s3_key = result.scalar_one_or_none()
            if s3_key is None:
                raise DocumentNotFoundError(document_id)
            return s3_key

    async def get_by_id(self, document_id: str) -> DocumentoDetail:
        """
        Obtiene un documento por ID con todas sus relaciones consumiendo
        la función consolidada `public.fn_obtener_documento_detalle`.
        """
        raw = await self.get_raw_detail(document_id)
        return self._build_documento_detail(raw, document_id)

    @staticmethod
    async def list_documents(skip: int = 0, limit: int = 50) -> list[DocumentoDetail]:
        """Obtiene lista paginada de documentos con sus relaciones cargadas."""
        async with get_session() as session:
            stmt = (
                select(Documento)
                .where(Documento.isactive == True)
                .offset(skip)
                .limit(limit)
                .order_by(Documento.creacion.desc())
            )
            result = await session.execute(stmt)
            docs = result.scalars().all()

            return [
                DocumentoDetail(
                    iddocumento=doc.iddocumento,
                    numero=doc.numero,
                    titulo=doc.titulo,
                    nommetadato=doc.nommetadato,
                    tipodocumento=doc.tipodocumento.nombretipodocumento if doc.tipodocumento else None,
                    tipodecision=doc.tipodecision.tipodecision if doc.tipodecision else None,
                    tiposesion=doc.tiposesion.tiposesion if doc.tiposesion else None,
                    estadovigencia=doc.estadovigencia.estadovigencia if doc.estadovigencia else None,
                    numacuerdo=doc.numacuerdo,
                    numsesion=doc.numsesion,
                    descripcion=doc.descripcion,
                    creacion=doc.creacion,
                    derogacion=doc.derogacion,
                    aplicacioninmediata=doc.aplicacioninmediata,
                    isactive=doc.isactive,
                    ultima_modificacion=doc.ultima_modificacion,
                    cant_paginas=0,
                    urlarchivooriginals3=doc.urlarchivooriginals3,
                    sedes=[],
                    categorias=[],
                    carreras=[],
                    beneficios=[],
                    nombramientos=[],
                    departamentos=[],
                    chunkcount=0,
                )
                for doc in docs
            ]

    @staticmethod
    async def get_raw_detail(document_id: str) -> dict[str, object]:
        """
        Retorna la representación canónica en JSONB del documento ejecutando
        la función almacenada consolidada `public.fn_obtener_documento_detalle`.
        """
        try:
            uuid_obj = UUID(str(document_id))
        except ValueError:
            raise DocumentNotFoundError(document_id)

        async with get_session() as session:
            stmt = text("SELECT public.fn_obtener_documento_detalle(:id) AS detalle")
            result = await session.execute(stmt, {"id": uuid_obj})
            detalle = result.scalar()
            if not detalle:
                raise DocumentNotFoundError(document_id)
            if isinstance(detalle, str):
                return json.loads(detalle)
            return detalle

    async def update(self, document_id: str, data: DocumentoUpdate) -> DocumentoDetail:
        """
        Actualiza un documento normativo consumiendo el procedimiento maestro
        canónico `public.sp_modificar_documento_completo`.
        """
        try:
            uuid_obj = UUID(str(document_id))
        except ValueError:
            raise DocumentNotFoundError(document_id)

        sp_params, _ = self._build_update_params(data, uuid_obj)

        call_stmt = text("""
            CALL public.sp_modificar_documento_completo(
                p_iddocumento => :p_iddocumento,
                p_numero => :p_numero,
                p_titulo => :p_titulo,
                p_descripcion => :p_descripcion,
                p_urlarchivooriginals3 => :p_urlarchivooriginals3,
                p_idtipodocumento => :p_idtipodocumento,
                p_nombretipodocumento => :p_nombretipodocumento,
                p_idcategoria => :p_idcategoria,
                p_nombrecategoria => :p_nombrecategoria,
                p_numcategoria => :p_numcategoria,
                p_nommetadato => :p_nommetadato,
                p_recalcular_nommetadato => :p_recalcular_nommetadato,
                p_idestadovigencia => :p_idestadovigencia,
                p_nombreestadovigencia => :p_nombreestadovigencia,
                p_creacion => :p_creacion,
                p_derogacion => :p_derogacion,
                p_limpiar_derogacion => :p_limpiar_derogacion,
                p_isactive => :p_isactive,
                p_idtiposesion => :p_idtiposesion,
                p_nombretiposesion => :p_nombretiposesion,
                p_numsesion => :p_numsesion,
                p_numacuerdo => :p_numacuerdo,
                p_idtipodecision => :p_idtipodecision,
                p_nombretipodecision => :p_nombretipodecision,
                p_limpiar_sesion => :p_limpiar_sesion,
                p_areas_emisoras_ids => :p_areas_emisoras_ids,
                p_areas_emisoras_nombres => :p_areas_emisoras_nombres,
                p_niveles_ids => :p_niveles_ids,
                p_niveles_nombres => :p_niveles_nombres,
                p_jornadas_ids => :p_jornadas_ids,
                p_jornadas_nombres => :p_jornadas_nombres,
                p_sedes_ids => :p_sedes_ids,
                p_sedes_nombres => :p_sedes_nombres,
                p_carreras_ids => :p_carreras_ids,
                p_carreras_nombres => :p_carreras_nombres,
                p_departamentos_ids => :p_departamentos_ids,
                p_departamentos_nombres => :p_departamentos_nombres,
                p_roles_ids => :p_roles_ids,
                p_roles_nombres => :p_roles_nombres,
                p_beneficios_ids => :p_beneficios_ids,
                p_beneficios_nombres => :p_beneficios_nombres,
                p_nombramientos_ids => :p_nombramientos_ids,
                p_nombramientos_nombres => :p_nombramientos_nombres,
                p_modo_puentes => :p_modo_puentes,
                p_relacion_destino_id => :p_relacion_destino_id,
                p_relacion_tipo_id => :p_relacion_tipo_id,
                p_relacion_tipo_nombre => :p_relacion_tipo_nombre,
                p_relacion_detalle => :p_relacion_detalle,
                p_relacion_fecha => :p_relacion_fecha,
                p_relacion_verificada => :p_relacion_verificada
            )
        """)

        try:
            async with get_session() as session:
                await session.execute(call_stmt, sp_params)

                if data.aplicacioninmediata is not None:
                    await session.execute(
                        text("UPDATE public.documento SET aplicacioninmediata = :val WHERE iddocumento = :id"),
                        {"val": data.aplicacioninmediata, "id": uuid_obj},
                    )

                await session.commit()
        except Exception as e:
            self._handle_sp_error(e, document_id)

        return await self.get_by_id(document_id)

    async def toggle_active(self, document_id: str) -> DocumentoDetail:
        """
        Modifica la vigencia/visibilidad de un documento mediante el procedimiento canónico
        `public.sp_modificar_documento_vigencia`.
        """
        try:
            uuid_obj = UUID(str(document_id))
        except ValueError:
            raise DocumentNotFoundError(document_id)

        call_stmt = text("""
            CALL public.sp_modificar_documento_vigencia(
                p_iddocumento => :p_iddocumento
            )
        """)

        try:
            async with get_session() as session:
                await session.execute(call_stmt, {"p_iddocumento": uuid_obj})
                await session.commit()
        except Exception as e:
            self._handle_sp_error(e, document_id)

        return await self.get_by_id(document_id)

    async def filter_only_search(
        self,
        top_k: int | None = None,
        filters: dict[str, object] | None = None,
        titles: list[str] | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, object]] | tuple[list[dict[str, object]], int]:
        """Búsqueda solo por filtros de metadata (sin similitud vectorial)."""
        async with get_session() as session:
            query = """
                SELECT
                    count(*) OVER() as full_count,
                    d.iddocumento,
                    d.numero,
                    d.titulo,
                    d.nommetadato,
                    d.idtipodocumento,
                    d.idestadovigencia,
                    d.idcategoria,
                    d.creacion,
                    d.derogacion,
                    d.aplicacioninmediata,
                    d.isactive,
                    d.ultima_modificacion,
                    d.numacuerdo,
                    d.numsesion,
                    d.descripcion,
                    td.nombretipodocumento,
                    ev.estadovigencia,
                    tdec.tipodecision,
                    ts.tiposesion,
                    1.0 AS score
                FROM documento d
                LEFT JOIN tipodocumento td ON d.idtipodocumento = td.idtipodocumento
                LEFT JOIN estadovigencia ev ON d.idestadovigencia = ev.idestadovigencia
                LEFT JOIN tipodecision tdec ON d.idtipodecision = tdec.idtipodecision
                LEFT JOIN tiposesion ts ON d.idtiposesion = ts.idtiposesion
                WHERE d.isactive = true
            """

            params: dict[str, object] = {}
            if filters:
                filter_clauses, filter_params = self._build_search_filter_clauses(filters)
                for clause in filter_clauses:
                    query += f" AND {clause}"
                params.update(filter_params)

            if titles:
                title_placeholders = []
                for i, t in enumerate(titles):
                    key = f"title_{i}"
                    title_placeholders.append(f":{key}")
                    params[key] = t.strip()
                in_clause = ", ".join([f"LOWER({p})" for p in title_placeholders])
                query += f" AND LOWER(TRIM(d.titulo)) IN ({in_clause})"

            query += " ORDER BY d.creacion DESC"
            if page_size is not None:
                offset = (max(1, page) - 1) * page_size
                query += " LIMIT :limit OFFSET :offset"
                params["limit"] = page_size
                params["offset"] = offset
            elif top_k is not None:
                query += " LIMIT :top_k"
                params["top_k"] = top_k

            result = await session.execute(text(query), params)
            rows = result.fetchall()
            total_count = rows[0].full_count if rows else 0

            docs = [self._map_doc_row(row, float(row.score)) for row in rows]

            if page_size is not None:
                return docs, total_count
            return docs

    async def lexical_search(
        self,
        query_text: str,
        top_k: int | None = None,
        filters: dict[str, object] | None = None,
        page: int = 1,
        page_size: int | None = None,
    ) -> list[dict[str, object]] | tuple[list[dict[str, object]], int]:
        """Búsqueda léxica directa para encontrar el documento más cercano por título o nommetadato."""
        async with get_session() as session:
            clean_q = query_text.strip()
            like_pattern = f"%{clean_q}%"

            base_query = """
                SELECT
                    count(*) OVER() as full_count,
                    d.iddocumento,
                    d.numero,
                    d.titulo,
                    d.nommetadato,
                    d.idtipodocumento,
                    d.idestadovigencia,
                    d.idcategoria,
                    d.creacion,
                    d.derogacion,
                    d.aplicacioninmediata,
                    d.isactive,
                    d.ultima_modificacion,
                    d.numacuerdo,
                    d.numsesion,
                    d.descripcion,
                    td.nombretipodocumento,
                    ev.estadovigencia,
                    tdec.tipodecision,
                    ts.tiposesion,
                    CASE
                        WHEN LOWER(TRIM(d.titulo)) = LOWER(:exact_query) THEN 100.0
                        WHEN LOWER(TRIM(d.nommetadato)) = LOWER(:exact_query) THEN 95.0
                        WHEN LOWER(d.titulo) LIKE LOWER(:starts_query) THEN 75.0
                        WHEN LOWER(d.nommetadato) LIKE LOWER(:starts_query) THEN 70.0
                        WHEN LOWER(d.titulo) LIKE LOWER(:like_query) THEN 50.0
                        WHEN LOWER(d.nommetadato) LIKE LOWER(:like_query) THEN 45.0
                        ELSE 10.0
                    END as match_boost
                FROM documento d
                LEFT JOIN tipodocumento td ON d.idtipodocumento = td.idtipodocumento
                LEFT JOIN estadovigencia ev ON d.idestadovigencia = ev.idestadovigencia
                LEFT JOIN tipodecision tdec ON d.idtipodecision = tdec.idtipodecision
                LEFT JOIN tiposesion ts ON d.idtiposesion = ts.idtiposesion
                WHERE d.isactive = true
                  AND (
                      LOWER(d.titulo) LIKE LOWER(:like_query)
                      OR LOWER(d.nommetadato) LIKE LOWER(:like_query)
                      OR (((d.titulo)::text || ' '::text) || (d.nommetadato)::text) ILIKE :like_query
                  )
            """

            params: dict[str, object] = {
                "exact_query": clean_q,
                "starts_query": f"{clean_q}%",
                "like_query": like_pattern,
            }

            if filters:
                filter_clauses, filter_params = self._build_search_filter_clauses(filters)
                for clause in filter_clauses:
                    base_query += f" AND {clause}"
                params.update(filter_params)

            base_query += " ORDER BY match_boost DESC, d.creacion DESC"
            if page_size is not None:
                offset = (max(1, page) - 1) * page_size
                base_query += " LIMIT :limit OFFSET :offset"
                params["limit"] = page_size
                params["offset"] = offset
            elif top_k is not None:
                base_query += " LIMIT :top_k"
                params["top_k"] = top_k

            result = await session.execute(text(base_query), params)
            rows = result.fetchall()
            total_count = rows[0].full_count if rows else 0

            docs = [self._map_doc_row(row, float(row.match_boost)) for row in rows]

            if page_size is not None:
                return docs, total_count
            return docs

    @staticmethod
    async def _fetch_options_part1(
        session: AsyncSession,
        only_active_tipos_doc: bool,
    ) -> dict[str, list[FilterOption]]:
        """Recupera opciones de catálogos institucionales y organizacionales."""
        tipos_doc_stmt = select(TipoDocumento)
        if only_active_tipos_doc:
            tipos_doc_stmt = tipos_doc_stmt.where(TipoDocumento.isactive == True)

        q_areas = await session.execute(select(TipoArea))
        q_macro = await session.execute(select(MacroCategoria))
        q_docs = await session.execute(tipos_doc_stmt)
        q_vig = await session.execute(select(EstadoVigencia))
        q_leg = await session.execute(select(RespaldoLegal))
        q_rol = await session.execute(select(RolInstitucional))
        q_ben = await session.execute(select(BeneficioInterno))
        q_sed = await session.execute(select(SedeCampus))
        q_nomb = await session.execute(select(TipoNombramiento))
        q_jorn = await session.execute(select(Jornada))

        roles = [FilterOption(id=r.idrol, nombre=r.nombrerol) for r in q_rol.scalars().all()]
        sedes = [FilterOption(id=s.idrecintouniversitario, nombre=s.nombrerecinto) for s in q_sed.scalars().all()]

        return {
            "tipos_area": [FilterOption(id=t.idtipoarea, nombre=t.nombrearea) for t in q_areas.scalars().all()],
            "macro_categorias": [
                FilterOption(id=m.idmacrocategoria, nombre=m.nombrecategoria, code=m.siglamacro)
                for m in q_macro.scalars().all()
            ],
            "tipos_documento": [
                FilterOption(id=t.idtipodocumento, nombre=t.nombretipodocumento) for t in q_docs.scalars().all()
            ],
            "estados_vigencia": [
                FilterOption(id=e.idestadovigencia, nombre=e.estadovigencia) for e in q_vig.scalars().all()
            ],
            "respaldos_legales": [
                FilterOption(id=r.idrespaldolegal, nombre=r.respaldolegal) for r in q_leg.scalars().all()
            ],
            "roles": roles,
            "beneficios": [FilterOption(id=b.idbeneficio, nombre=b.nombrebeneficio) for b in q_ben.scalars().all()],
            "sedes": sedes,
            "tipos_nombramiento": [
                FilterOption(id=t.idtiponombramiento, nombre=t.nombrenombramiento) for t in q_nomb.scalars().all()
            ],
            "jornadas": [FilterOption(id=j.idjornada, nombre=j.nombrejornada) for j in q_jorn.scalars().all()],
        }

    @staticmethod
    async def _fetch_options_part2(session: AsyncSession) -> dict[str, list[FilterOption]]:
        """Recupera opciones de programas, sesiones, decisiones, categorías y áreas."""
        q_prog = await session.execute(select(TipoPrograma))
        q_dep = await session.execute(select(Departamento))
        q_ses = await session.execute(select(TipoSesion))
        q_dec = await session.execute(select(TipoDecision))
        q_rel = await session.execute(select(TipoRelacion))
        q_fnt = await session.execute(select(FuenteDeteccion))
        q_sub = await session.execute(select(SubAreas))
        q_cat = await session.execute(select(Categoria))
        q_niv = await session.execute(select(NivelAcademico))
        q_car = await session.execute(select(Carrera))

        return {
            "tipos_programa": [
                FilterOption(id=t.idtipoprograma, nombre=t.nombretipoprograma) for t in q_prog.scalars().all()
            ],
            "departamentos": [
                FilterOption(id=d.iddepartamento, nombre=d.nombredepartamento) for d in q_dep.scalars().all()
            ],
            "tipos_sesion": [FilterOption(id=t.idtiposesion, nombre=t.tiposesion) for t in q_ses.scalars().all()],
            "tipos_decision": [
                FilterOption(id=t.idtipodecision, nombre=t.tipodecision) for t in q_dec.scalars().all()
            ],
            "tipos_relacion": [
                FilterOption(id=t.idtiporelacion, nombre=t.tiporelacion) for t in q_rel.scalars().all()
            ],
            "fuentes_deteccion": [FilterOption(id=f.idfuente, nombre=f.nomfuente) for f in q_fnt.scalars().all()],
            "sub_areas": [
                FilterOption(id=s.idsubarea, nombre=s.nombre, parent_id=s.idtipoarea) for s in q_sub.scalars().all()
            ],
            "categorias": [
                FilterOption(
                    id=c.idcategoria, nombre=c.nombrecategoria, parent_id=c.idmacrocategoria, code=c.numcategoria
                )
                for c in q_cat.scalars().all()
            ],
            "niveles_academicos": [
                FilterOption(id=n.idnivel, nombre=n.nombrenivel, parent_id=n.idtipoprograma)
                for n in q_niv.scalars().all()
            ],
            "carreras": [
                FilterOption(id=c.idcarrera, nombre=c.nombrecarrera, parent_id=c.idnivel, code=c.codigocarrera)
                for c in q_car.scalars().all()
            ],
        }

    @classmethod
    async def get_filter_options(cls, only_active_tipos_documento: bool = True) -> FilterOptions:
        """Consulta los valores únicos de cada dimensión para poblar los dropdowns."""
        async with get_session() as session:
            p1 = await cls._fetch_options_part1(session, only_active_tipos_documento)
            p2 = await cls._fetch_options_part2(session)

            return FilterOptions(
                tipos_area=p1["tipos_area"], macro_categorias=p1["macro_categorias"],
                tipos_documento=p1["tipos_documento"], estados_vigencia=p1["estados_vigencia"],
                respaldos_legales=p1["respaldos_legales"], roles_institucionales=p1["roles"],
                roles=p1["roles"], beneficios=p1["beneficios"], sedes_campus=p1["sedes"],
                sedes=p1["sedes"], tipos_nombramiento=p1["tipos_nombramiento"],
                jornadas=p1["jornadas"], tipos_programa=p2["tipos_programa"],
                departamentos=p2["departamentos"], tipos_sesion=p2["tipos_sesion"],
                tipos_decision=p2["tipos_decision"], tipos_relacion=p2["tipos_relacion"],
                fuentes_deteccion=p2["fuentes_deteccion"], sub_areas=p2["sub_areas"],
                categorias=p2["categorias"], niveles_academicos=p2["niveles_academicos"],
                carreras=p2["carreras"],
            )

    @staticmethod
    async def get_editable_by_id(document_id: str) -> DocumentoEditableOut:
        """
        Retorna la representación canónica con todos los campos editables y listas
        de IDs para el formulario de administración.
        """
        async with get_session() as session:
            stmt = (
                select(Documento)
                .where(Documento.iddocumento == document_id)
                .options(
                    selectinload(Documento.sedes), selectinload(Documento.carreras),
                    selectinload(Documento.beneficios), selectinload(Documento.nombramientos),
                    selectinload(Documento.departamentos), selectinload(Documento.jornadas),
                    selectinload(Documento.niveles), selectinload(Documento.roles),
                    selectinload(Documento.areas_emisoras),
                )
            )
            result = await session.execute(stmt)
            doc = result.scalar_one_or_none()
            if not doc:
                raise DocumentNotFoundError(document_id)

            return DocumentoEditableOut(
                iddocumento=doc.iddocumento, numero=doc.numero, idtipodocumento=doc.idtipodocumento,
                titulo=doc.titulo, nommetadato=doc.nommetadato, descripcion=doc.descripcion,
                idcategoria=doc.idcategoria, idtiposesion=doc.idtiposesion, numsesion=doc.numsesion,
                numacuerdo=doc.numacuerdo, idtipodecision=doc.idtipodecision,
                idestadovigencia=doc.idestadovigencia, creacion=doc.creacion, derogacion=doc.derogacion,
                aplicacioninmediata=doc.aplicacioninmediata, isactive=doc.isactive,
                ultima_modificacion=doc.ultima_modificacion,
                sedesids=[x.idrecintouniversitario for x in doc.sedes],
                carrerasids=[x.idcarrera for x in doc.carreras],
                beneficiosids=[x.idbeneficio for x in doc.beneficios],
                nombramientosids=[x.idtiponombramiento for x in doc.nombramientos],
                departamentosids=[x.iddepartamento for x in doc.departamentos],
                jornadasids=[x.idjornada for x in doc.jornadas],
                nivelesids=[x.idnivel for x in doc.niveles],
                rolesids=[x.idrol for x in doc.roles],
                areaseemisorasids=[x.idareaadministrativa for x in doc.areas_emisoras],
            )

    @staticmethod
    async def get_lexical_suggestions(term: str, limit: int = 10) -> list[dict[str, object]]:
        """
        Búsqueda de sugerencias/autocompletado léxico en PostgreSQL.
        Aprovecha el índice funcional unificado GIN con trigramas sobre (titulo || ' ' || nommetadato).
        """
        async with get_session() as session:
            clean = term.strip()
            contains = f"%{clean}%"

            query = """
                SELECT
                    d.iddocumento,
                    d.numero,
                    d.titulo,
                    d.nommetadato,
                    CASE
                        WHEN d.titulo ILIKE :contains THEN 'titulo'
                        ELSE 'nommetadato'
                    END as matched_field
                FROM documento d
                WHERE d.isactive = true
                  AND (d.titulo || ' ' || COALESCE(d.nommetadato, '')) ILIKE :contains
                ORDER BY d.titulo ASC
                LIMIT :limit;
            """
            result = await session.execute(
                text(query),
                {"contains": contains, "limit": limit},
            )
            rows = result.fetchall()
            return [
                {
                    "documentid": str(row.iddocumento),
                    "numero": row.numero,
                    "titulo": row.titulo,
                    "nommetadato": row.nommetadato or "",
                    "matched_field": row.matched_field,
                    "suggestion": row.titulo if row.matched_field == "titulo" else (row.nommetadato or row.titulo),
                }
                for row in rows
            ]
