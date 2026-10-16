import re
import json
from uuid import UUID
from fastapi import HTTPException, status
from sqlmodel import SQLModel, select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict, Union
from datetime import datetime, timezone, date
from app.models.db_models import (
    Documento, DocumentoChunk, DocumentoSedeCampus, DocumentoCarrera,
    DocumentoBeneficio, DocumentoNombramiento, DocumentoDepartamento,
    DocumentoJornada, DocumentoNivel, DocumentoRol, AreaEmisora,
    TipoArea, MacroCategoria, TipoDocumento, EstadoVigencia, RespaldoLegal,
    RolInstitucional, BeneficioInterno, SedeCampus, TipoNombramiento,
    Jornada, TipoPrograma, Departamento, TipoSesion, TipoDecision,
    TipoRelacion, FuenteDeteccion, TipoPagina, SubAreas, 
    Categoria, 
    NivelAcademico, Carrera, RelacionDocumental
)
from app.models.document_models import (
    DocumentoUpdate, DocumentoDetail, DocumentoEditableOut, SedeCampusOut, CategoriaOut,
    CarreraOut, BeneficioOut, NombramientoOut, DepartamentoOut
)
from app.models.search_models import FilterOptions, FilterOption
from app.core.database import get_session
from app.core.exceptions import (
    DocumentNotFoundError,
    DatabaseError,
    UniqueConstraintError,
    DAGCycleError,
    CatalogNotFoundError,
    ValidationError as AppValidationError
)



class DocumentRepository:
    """
    Acceso a PostgreSQL para la tabla Documento y sus relaciones.
    Implementado con SQLModel async.
    """

    # Devuelve solo la ruta del PDF en S3 (sin cargar sedes, carreras, chunks, etc.)
    async def get_s3_key(self, document_id: str) -> str:
        # Abre una sesión con la BD; se cierra sola al salir del bloque
        async with get_session() as session:
            stmt = select(Documento.urlarchivooriginals3).where(
                Documento.iddocumento == document_id
            )
            result = await session.execute(stmt)
            # Trae el único valor, o None si no existe ese documento
            s3_key = result.scalar_one_or_none()

            # Si no existe, el middleware lo convierte en respuesta 404
            if s3_key is None:
                raise DocumentNotFoundError(document_id)

            return s3_key

    async def get_by_id(self, document_id: str) -> DocumentoDetail:
        """
        Obtiene un documento por ID con todas sus relaciones consumiendo
        la función consolidada `public.fn_obtener_documento_detalle`.
        Ejecuta la recuperación en un único viaje de red (round-trip) a PostgreSQL.
        """
        raw = await self.get_raw_detail(document_id)
        doc_data = raw.get("documento") or {}
        if not doc_data:
            raise DocumentNotFoundError(document_id)

        sesion = doc_data.get("sesion") or {}
        tipo_doc = doc_data.get("tipodocumento") or {}
        estado_vig = doc_data.get("estadovigencia") or {}
        macro = doc_data.get("macrocategoria") or {}
        cat = doc_data.get("categoria") or {}

        categorias = []
        if cat and cat.get("id"):
            categorias.append(CategoriaOut(
                idcategoria=cat.get("id"),
                nombrecategoria=cat.get("nombre") or "",
                numcategoria=cat.get("num"),
                macrocategoria=macro.get("nombre") if macro else None
            ))

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
            sedes=[
                SedeCampusOut(
                    idrecintouniversitario=s["id"],
                    nombrerecinto=s["nombre"]
                ) for s in raw.get("sedes_campus", []) if s.get("id")
            ],
            categorias=categorias,
            carreras=[
                CarreraOut(
                    idcarrera=c["id"],
                    nombrecarrera=c["nombre"],
                    codigocarrera=c.get("codigo"),
                    nombrenivel=c.get("nivel"),
                    nombredepartamento=c.get("departamento")
                ) for c in raw.get("carreras", []) if c.get("id")
            ],
            beneficios=[
                BeneficioOut(
                    idbeneficio=b["id"],
                    nombrebeneficio=b["nombre"]
                ) for b in raw.get("beneficios_internos", []) if b.get("id")
            ],
            nombramientos=[
                NombramientoOut(
                    idtiponombramiento=n["id"],
                    nombrenombramiento=n["nombre"]
                ) for n in raw.get("nombramientos", []) if n.get("id")
            ],
            departamentos=[
                DepartamentoOut(
                    iddepartamento=d["id"],
                    nombredepartamento=d["nombre"]
                ) for d in raw.get("departamentos", []) if d.get("id")
            ],
            chunkcount=0
        )

    async def list_documents(self, skip: int = 0, limit: int = 50) -> List[DocumentoDetail]:
        """
        Lista documentos con paginación.
        Retorna documentos básicos sin todas las relaciones cargadas.
        """
        async with get_session() as session:
            stmt = (
                select(Documento)
                .options(
                    selectinload(Documento.tipo_documento),
                    selectinload(Documento.tipo_decision),
                    selectinload(Documento.tipo_sesion),
                    selectinload(Documento.estado_vigencia)
                )
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
                    tipodocumento=doc.tipo_documento.nombretipodocumento if doc.tipo_documento else None,
                    tipodecision=doc.tipo_decision.tipodecision if doc.tipo_decision else None,
                    tiposesion=doc.tipo_sesion.tiposesion if doc.tipo_sesion else None,
                    estadovigencia=doc.estado_vigencia.estadovigencia if doc.estado_vigencia else None,
                    numacuerdo=doc.numacuerdo,
                    numsesion=doc.numsesion,
                    descripcion=doc.descripcion,
                    creacion=doc.creacion,
                    derogacion=doc.derogacion,
                    aplicacioninmediata=doc.aplicacioninmediata,
                    isactive=doc.isactive,
                    ultima_modificacion=doc.ultima_modificacion,
                    cant_paginas=doc.cant_paginas,
                    urlarchivooriginals3=doc.urlarchivooriginals3,
                    sedes=[],
                    categorias=[],
                    carreras=[],
                    beneficios=[],
                    nombramientos=[],
                    departamentos=[],
                    chunkcount=0
                )
                for doc in docs
            ]

    def _handle_sp_error(self, e: Exception, document_id: str) -> None:
        """
        Captura y clasifica excepciones generadas por procedimientos almacenados en PostgreSQL,
        traduciéndolas a excepciones semánticas de la aplicación.
        """
        msg = str(e)
        orig = getattr(e, 'orig', None)
        if orig:
            msg = str(orig)

        match = re.search(r"(?:RaiseError|RaiseException)'>:\s*(.*?)(\n|\[SQL:|$)", msg, re.DOTALL)
        clean_msg = match.group(1).strip() if match else msg

        if "No se encontró el documento" in clean_msg:
            raise DocumentNotFoundError(document_id)
        elif "Unicidad:" in clean_msg:
            raise UniqueConstraintError(clean_msg, {"document_id": document_id})
        elif "Violación de Grafo Acíclico (DAG)" in clean_msg:
            raise DAGCycleError(clean_msg, {"document_id": document_id})
        elif "Catálogo:" in clean_msg:
            raise CatalogNotFoundError(clean_msg, {"document_id": document_id})
        elif "Validación:" in clean_msg or "Parámetro:" in clean_msg:
            raise AppValidationError(clean_msg, details={"document_id": document_id})
        else:
            raise DatabaseError(
                f"Error al procesar la actualización del documento: {clean_msg}",
                {"document_id": document_id}
            )

    async def get_raw_detail(self, document_id: str) -> dict:
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
        canónico `public.sp_modificar_documento_completo`,
        garantizando atomicidad, bloqueos pesimistas para correlativos,
        integridad referencial en tablas puente y actualización de 'ultima_modificacion'.
        """
        try:
            uuid_obj = UUID(str(document_id))
        except ValueError:
            raise DocumentNotFoundError(document_id)

        # Si viene nommetadato manual explícito, recalcular_nommetadato es False a menos que se indique True
        recalcular = data.recalcular_nommetadato
        if data.nommetadato is not None and not data.recalcular_nommetadato:
            recalcular = False

        rel_destino_uuid = None
        if data.relacion_destino_id:
            try:
                rel_destino_uuid = UUID(str(data.relacion_destino_id))
            except ValueError:
                raise AppValidationError("relacion_destino_id debe ser un UUID válido", field="relacion_destino_id")

        sp_params = {
            "p_iddocumento": uuid_obj,
            "p_numero": data.numero,
            "p_titulo": data.titulo,
            "p_descripcion": data.descripcion,
            "p_urlarchivooriginals3": None,  # Omitido para el panel de administración
            "p_idtipodocumento": data.idtipodocumento,
            "p_nombretipodocumento": data.tipo_documento_nombre,
            "p_idcategoria": data.idcategoria,
            "p_nombrecategoria": data.nombrecategoria,
            "p_numcategoria": data.categoria_num,
            "p_nommetadato": data.nommetadato,
            "p_recalcular_nommetadato": recalcular,
            "p_idestadovigencia": data.idestadovigencia,
            "p_nombreestadovigencia": data.estado_vigencia_nombre,
            "p_creacion": data.creacion,
            "p_derogacion": data.derogacion,
            "p_limpiar_derogacion": data.limpiar_derogacion,
            "p_isactive": data.isactive,
            "p_idtiposesion": data.idtiposesion,
            "p_nombretiposesion": data.tipo_sesion_nombre,
            "p_numsesion": data.numsesion,
            "p_numacuerdo": data.numacuerdo,
            "p_idtipodecision": data.idtipodecision,
            "p_nombretipodecision": data.tipo_decision_nombre,
            "p_limpiar_sesion": data.limpiar_sesion,
            "p_areas_emisoras_ids": data.areaseemisorasids,
            "p_areas_emisoras_nombres": data.areas_emisoras_nombres,
            "p_niveles_ids": data.nivelesids,
            "p_niveles_nombres": data.niveles_nombres,
            "p_jornadas_ids": data.jornadasids,
            "p_jornadas_nombres": data.jornadas_nombres,
            "p_sedes_ids": data.sedesids,
            "p_sedes_nombres": data.sedes_nombres,
            "p_carreras_ids": data.carrerasids,
            "p_carreras_nombres": data.carreras_nombres,
            "p_departamentos_ids": data.departamentosids,
            "p_departamentos_nombres": data.departamentos_nombres,
            "p_roles_ids": data.rolesids,
            "p_roles_nombres": data.roles_nombres,
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

                # Si aplicacioninmediata viene explícitamente definida, actualizar en la misma transacción
                if data.aplicacioninmediata is not None:
                    await session.execute(
                        text("UPDATE public.documento SET aplicacioninmediata = :val WHERE iddocumento = :id"),
                        {"val": data.aplicacioninmediata, "id": uuid_obj}
                    )

                await session.commit()
        except Exception as e:
            self._handle_sp_error(e, document_id)

        # Retornar el detalle del documento actualizado
        return await self.get_by_id(document_id)

    async def toggle_active(self, document_id: str) -> DocumentoDetail:
        """
        Invierte el valor de is_active en la tabla Documento y actualiza 'ultima_modificacion'
        mediante el procedimiento almacenado public.sp_modificar_documento_vigencia.
        """
        try:
            uuid_obj = UUID(str(document_id))
        except ValueError:
            raise DocumentNotFoundError(document_id)

        try:
            async with get_session() as session:
                res = await session.execute(
                    text("SELECT isactive FROM public.documento WHERE iddocumento = :id"),
                    {"id": uuid_obj}
                )
                curr_active = res.scalar()
                if curr_active is None:
                    raise DocumentNotFoundError(document_id)

                new_active = not curr_active
                await session.execute(
                    text("""
                        CALL public.sp_modificar_documento_vigencia(
                            p_iddocumento => :id,
                            p_isactive => :isactive
                        )
                    """),
                    {"id": uuid_obj, "isactive": new_active}
                )
                await session.commit()
        except Exception as e:
            self._handle_sp_error(e, document_id)

        return await self.get_by_id(document_id)

    def _build_search_filter_clauses(self, filters: Dict) -> tuple[List[str], Dict]:
        """
        Construye cláusulas WHERE parametrizadas y diccionario de parámetros para filtros
        compartidos entre búsqueda general, búsqueda semántica y búsqueda léxica.
        Soporta enteros individuales o listas de enteros para selección facetada.
        """
        clauses: List[str] = []
        params: Dict = {}

        # 1. Vigencia (EstadoVigencia)
        id_vig = filters.get("idestadovigencia")
        if id_vig:
            if isinstance(id_vig, list):
                clauses.append("d.idestadovigencia = ANY(:idestadovigencia)")
                params["idestadovigencia"] = id_vig
            else:
                clauses.append("d.idestadovigencia = :idestadovigencia")
                params["idestadovigencia"] = id_vig

        # 2. Tipo documento (TipoDocumento)
        id_tipo = filters.get("idtipodocumento")
        if id_tipo:
            if isinstance(id_tipo, list):
                clauses.append("d.idtipodocumento = ANY(:idtipodocumento)")
                params["idtipodocumento"] = id_tipo
            else:
                clauses.append("d.idtipodocumento = :idtipodocumento")
                params["idtipodocumento"] = id_tipo

        # 3. Tipo decisión (TipoDecision)
        id_dec = filters.get("idtipodecision")
        if id_dec:
            if isinstance(id_dec, list):
                clauses.append("d.idtipodecision = ANY(:idtipodecision)")
                params["idtipodecision"] = id_dec
            else:
                clauses.append("d.idtipodecision = :idtipodecision")
                params["idtipodecision"] = id_dec

        # 4. Tipo sesión (TipoSesion)
        id_ses = filters.get("idtiposesion")
        if id_ses:
            if isinstance(id_ses, list):
                clauses.append("d.idtiposesion = ANY(:idtiposesion)")
                params["idtiposesion"] = id_ses
            else:
                clauses.append("d.idtiposesion = :idtiposesion")
                params["idtiposesion"] = id_ses

        # 5. Categoría (Categoria)
        id_cat = filters.get("idcategoria")
        if id_cat:
            if isinstance(id_cat, list):
                clauses.append("d.idcategoria = ANY(:idcategoria)")
                params["idcategoria"] = id_cat
            else:
                clauses.append("d.idcategoria = :idcategoria")
                params["idcategoria"] = id_cat

        # 6. Macrocategoría (MacroCategoria)
        id_macro = filters.get("idmacrocategoria")
        if id_macro:
            if isinstance(id_macro, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM categoria cat
                        WHERE cat.idcategoria = d.idcategoria
                        AND cat.idmacrocategoria = ANY(:idmacrocategoria)
                    )
                """)
                params["idmacrocategoria"] = id_macro
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM categoria cat
                        WHERE cat.idcategoria = d.idcategoria
                        AND cat.idmacrocategoria = :idmacrocategoria
                    )
                """)
                params["idmacrocategoria"] = id_macro

        # 7. Años específicos
        anios = filters.get("anios")
        if anios:
            if isinstance(anios, int):
                anios = [anios]
            clauses.append("EXTRACT(YEAR FROM d.creacion)::int = ANY(:anios)")
            params["anios"] = [int(a) for a in anios]

        # 8. Rangos de fecha de creación (creaciondesde / creacionhasta o fechadesde / fechahasta)
        f_desde = filters.get("creaciondesde") or filters.get("fechadesde")
        if f_desde:
            if isinstance(f_desde, str):
                try:
                    f_desde = date.fromisoformat(f_desde[:10])
                except Exception:
                    f_desde = None
            if f_desde:
                clauses.append("d.creacion >= :fecha_desde")
                params["fecha_desde"] = f_desde

        f_hasta = filters.get("creacionhasta") or filters.get("fechahasta")
        if f_hasta:
            if isinstance(f_hasta, str):
                try:
                    f_hasta = date.fromisoformat(f_hasta[:10])
                except Exception:
                    f_hasta = None
            if f_hasta:
                clauses.append("d.creacion <= :fecha_hasta")
                params["fecha_hasta"] = f_hasta

        # 9. Aplicación inmediata
        if filters.get("aplicacioninmediata") is not None:
            clauses.append("d.aplicacioninmediata = :aplicacion_inmediata")
            params["aplicacion_inmediata"] = filters["aplicacioninmediata"]

        # 10. Documento activo
        if filters.get("isactive") is not None:
            clauses.append("d.isactive = :is_active")
            params["is_active"] = filters["isactive"]

        # 11. Área (TipoArea -> subarea -> areaemisora)
        id_area = filters.get("idtipoarea")
        if id_area:
            if isinstance(id_area, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM areaemisora ae
                        JOIN subarea sa ON ae.idareaadministrativa = sa.idsubarea
                        WHERE ae.iddocumento = d.iddocumento
                        AND sa.idtipoarea = ANY(:idtipoarea)
                    )
                """)
                params["idtipoarea"] = id_area
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM areaemisora ae
                        JOIN subarea sa ON ae.idareaadministrativa = sa.idsubarea
                        WHERE ae.iddocumento = d.iddocumento
                        AND sa.idtipoarea = :idtipoarea
                    )
                """)
                params["idtipoarea"] = id_area

        # 12. Subárea administrativa (SubAreas -> areaemisora)
        id_sub = filters.get("idsubarea")
        if id_sub:
            if isinstance(id_sub, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM areaemisora ae
                        WHERE ae.iddocumento = d.iddocumento
                        AND ae.idareaadministrativa = ANY(:idsubarea)
                    )
                """)
                params["idsubarea"] = id_sub
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM areaemisora ae
                        WHERE ae.iddocumento = d.iddocumento
                        AND ae.idareaadministrativa = :idsubarea
                    )
                """)
                params["idsubarea"] = id_sub

        # 13. Sede / Campus (SedeCampus -> documentosedecampus)
        id_sede = filters.get("idrecintouniversitario")
        if id_sede:
            if isinstance(id_sede, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentosedecampus dsc
                        WHERE dsc.iddocumento = d.iddocumento
                        AND dsc.idrecintouniversitario = ANY(:idrecintouniversitario)
                    )
                """)
                params["idrecintouniversitario"] = id_sede
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentosedecampus dsc
                        WHERE dsc.iddocumento = d.iddocumento
                        AND dsc.idrecintouniversitario = :idrecintouniversitario
                    )
                """)
                params["idrecintouniversitario"] = id_sede

        # 14. Carrera (Carrera -> documentocarrera)
        id_carr = filters.get("idcarrera")
        if id_carr:
            if isinstance(id_carr, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentocarrera dcarr
                        WHERE dcarr.iddocumento = d.iddocumento
                        AND dcarr.idcarrera = ANY(:idcarrera)
                    )
                """)
                params["idcarrera"] = id_carr
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentocarrera dcarr
                        WHERE dcarr.iddocumento = d.iddocumento
                        AND dcarr.idcarrera = :idcarrera
                    )
                """)
                params["idcarrera"] = id_carr

        # 15. Departamento (Departamento -> documentodepartamento)
        id_dep = filters.get("iddepartamento")
        if id_dep:
            if isinstance(id_dep, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentodepartamento dd
                        WHERE dd.iddocumento = d.iddocumento
                        AND dd.iddepartamento = ANY(:iddepartamento)
                    )
                """)
                params["iddepartamento"] = id_dep
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentodepartamento dd
                        WHERE dd.iddocumento = d.iddocumento
                        AND dd.iddepartamento = :iddepartamento
                    )
                """)
                params["iddepartamento"] = id_dep

        # 16. Beneficio interno
        id_ben = filters.get("idbeneficio")
        if id_ben:
            if isinstance(id_ben, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentobeneficio db
                        WHERE db.iddocumento = d.iddocumento
                        AND db.idbeneficio = ANY(:idbeneficio)
                    )
                """)
                params["idbeneficio"] = id_ben
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentobeneficio db
                        WHERE db.iddocumento = d.iddocumento
                        AND db.idbeneficio = :idbeneficio
                    )
                """)
                params["idbeneficio"] = id_ben

        # 17. Tipo nombramiento
        id_nom = filters.get("idtiponombramiento")
        if id_nom:
            if isinstance(id_nom, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentonombramiento dn
                        WHERE dn.iddocumento = d.iddocumento
                        AND dn.idtiponombramiento = ANY(:idtiponombramiento)
                    )
                """)
                params["idtiponombramiento"] = id_nom
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentonombramiento dn
                        WHERE dn.iddocumento = d.iddocumento
                        AND dn.idtiponombramiento = :idtiponombramiento
                    )
                """)
                params["idtiponombramiento"] = id_nom

        # 18. Jornada
        id_jorn = filters.get("idjornada")
        if id_jorn:
            if isinstance(id_jorn, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentojornada dj
                        WHERE dj.iddocumento = d.iddocumento
                        AND dj.idjornada = ANY(:idjornada)
                    )
                """)
                params["idjornada"] = id_jorn
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentojornada dj
                        WHERE dj.iddocumento = d.iddocumento
                        AND dj.idjornada = :idjornada
                    )
                """)
                params["idjornada"] = id_jorn

        # 19. Nivel académico
        id_niv = filters.get("idnivel")
        if id_niv:
            if isinstance(id_niv, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentonivel dnl
                        WHERE dnl.iddocumento = d.iddocumento
                        AND dnl.idnivel = ANY(:idnivel)
                    )
                """)
                params["idnivel"] = id_niv
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentonivel dnl
                        WHERE dnl.iddocumento = d.iddocumento
                        AND dnl.idnivel = :idnivel
                    )
                """)
                params["idnivel"] = id_niv

        # 20. Rol institucional
        id_rol = filters.get("idrol")
        if id_rol:
            if isinstance(id_rol, list):
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentorol dr
                        WHERE dr.iddocumento = d.iddocumento
                        AND dr.idrol = ANY(:idrol)
                    )
                """)
                params["idrol"] = id_rol
            else:
                clauses.append("""
                    EXISTS (
                        SELECT 1 FROM documentorol dr
                        WHERE dr.iddocumento = d.iddocumento
                        AND dr.idrol = :idrol
                    )
                """)
                params["idrol"] = id_rol

        return clauses, params

    async def filter_only_search(self, top_k: Optional[int] = None,
                                   filters: Optional[Dict] = None,
                                   titles: Optional[List[str]] = None,
                                   page: int = 1,
                                   page_size: Optional[int] = None) -> Union[List[Dict], tuple[List[Dict], int]]:
        """
        Búsqueda solo por filtros de metadata (sin similitud vectorial).
        Se usa cuando la query está vacía y no hay chunks/embeddings.
        Soporta paginación SQL con count(*) OVER() cuando se provee page_size.
        """
        async with get_session() as session:
            # Build the base query on documento table
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
            
            # Apply filters if provided
            params = {}
            if filters:
                filter_clauses, filter_params = self._build_search_filter_clauses(filters)
                for clause in filter_clauses:
                    query += f" AND {clause}"
                params.update(filter_params)
            
            # Filter by titles if provided FROM AI (case-insensitive and trimmed)
            if titles:
                title_placeholders = []
                for i, t in enumerate(titles):
                    key = f'title_{i}'
                    title_placeholders.append(f':{key}')
                    params[key] = t.strip()
                in_clause = ', '.join([f'LOWER({p})' for p in title_placeholders])
                query += f" AND LOWER(TRIM(d.titulo)) IN ({in_clause})"
            
            # Order by creation date (most recent first) and limit/offset
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
            
            docs = [
                {
                    "document_id": row.iddocumento,
                    "chunk_id": None,  # No chunks in document-level search
                    "texto_fragmento": row.descripcion if row.descripcion else row.titulo,  # Use description or title as excerpt
                    "numero_pagina": None,
                    "secuencia": None,
                    "nombre_titulo": None,
                    "numero_articulo": None,
                    "numero_inciso": None,
                    "numero": row.numero,
                    "titulo": row.titulo,
                    "nom_meta_dato": row.nommetadato,
                    "id_tipo_documento": row.idtipodocumento,
                    "id_estado_vigencia": row.idestadovigencia,
                    "id_categoria": row.idcategoria,
                    "creacion": row.creacion,
                    "derogacion": row.derogacion,
                    "aplicacion_inmediata": row.aplicacioninmediata,
                    "is_active": row.isactive,
                    "ultima_modificacion": getattr(row, 'ultima_modificacion', None),
                    "numacuerdo": row.numacuerdo,
                    "numsesion": row.numsesion,
                    "tipodocumento": getattr(row, 'nombretipodocumento', None),
                    "estadovigencia": getattr(row, 'estadovigencia', None),
                    "tipodecision": getattr(row, 'tipodecision', None),
                    "tiposesion": getattr(row, 'tiposesion', None),
                    "score": float(row.score)
                }
                for row in rows
            ]
            
            if page_size is not None:
                return docs, total_count
            return docs

    async def lexical_search(self, query_text: str, top_k: Optional[int] = None,
                             filters: Optional[Dict] = None,
                             page: int = 1,
                             page_size: Optional[int] = None) -> Union[List[Dict], tuple[List[Dict], int]]:
        """
        Búsqueda léxica directa para encontrar el documento más cercano por título o nommetadato.
        Se activa cuando el usuario antepone '#' a su búsqueda.
        Aprovecha coincidencia exacta, de prefijo y el índice funcional unificado trigrama GIN.
        Soporta paginación SQL con count(*) OVER() cuando se provee page_size.
        """
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

            params = {
                "exact_query": clean_q,
                "starts_query": f"{clean_q}%",
                "like_query": like_pattern
            }

            # Apply additional metadata filters if any
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

            docs = [
                {
                    "document_id": row.iddocumento,
                    "chunk_id": None,
                    "texto_fragmento": row.descripcion if row.descripcion else row.titulo,
                    "numero_pagina": None,
                    "secuencia": None,
                    "nombre_titulo": None,
                    "numero_articulo": None,
                    "numero_inciso": None,
                    "numero": row.numero,
                    "titulo": row.titulo,
                    "nom_meta_dato": row.nommetadato,
                    "id_tipo_documento": row.idtipodocumento,
                    "id_estado_vigencia": row.idestadovigencia,
                    "id_categoria": row.idcategoria,
                    "creacion": row.creacion,
                    "derogacion": row.derogacion,
                    "aplicacion_inmediata": row.aplicacioninmediata,
                    "is_active": row.isactive,
                    "ultima_modificacion": getattr(row, 'ultima_modificacion', None),
                    "numacuerdo": row.numacuerdo,
                    "numsesion": row.numsesion,
                    "tipodocumento": getattr(row, 'nombretipodocumento', None),
                    "estadovigencia": getattr(row, 'estadovigencia', None),
                    "tipodecision": getattr(row, 'tipodecision', None),
                    "tiposesion": getattr(row, 'tiposesion', None),
                    "score": float(row.match_boost)
                }
                for row in rows
            ]

            if page_size is not None:
                return docs, total_count
            return docs

    async def get_filter_options(self, only_active_tipos_documento: bool = True) -> FilterOptions:
        """
        Consulta los valores únicos de cada dimensión para poblar los dropdowns.
        Incluye todos los catálogos base (15 tablas) y entidades jerárquicas (4 tablas).
        """
        async with get_session() as session:
            # Catálogos base (15 tablas)
            tipos_area_result = await session.execute(select(TipoArea))
            tipos_area = [FilterOption(id=t.idtipoarea, nombre=t.nombrearea) for t in tipos_area_result.scalars().all()]
            
            macro_categorias_result = await session.execute(select(MacroCategoria))
            macro_categorias = [FilterOption(id=m.idmacrocategoria, nombre=m.nombrecategoria, code=m.siglamacro) for m in macro_categorias_result.scalars().all()]
            
            tipos_doc_stmt = select(TipoDocumento)
            if only_active_tipos_documento:
                tipos_doc_stmt = tipos_doc_stmt.where(TipoDocumento.isactive == True)
            tipos_doc_result = await session.execute(tipos_doc_stmt)
            tipos_documento = [FilterOption(id=t.idtipodocumento, nombre=t.nombretipodocumento) for t in tipos_doc_result.scalars().all()]
            
            estados_vigencia_result = await session.execute(select(EstadoVigencia))
            estados_vigencia = [FilterOption(id=e.idestadovigencia, nombre=e.estadovigencia) for e in estados_vigencia_result.scalars().all()]
            
            respaldos_legales_result = await session.execute(select(RespaldoLegal))
            respaldos_legales = [FilterOption(id=r.idrespaldolegal, nombre=r.respaldolegal) for r in respaldos_legales_result.scalars().all()]
            
            roles_result = await session.execute(select(RolInstitucional))
            roles = [FilterOption(id=r.idrol, nombre=r.nombrerol) for r in roles_result.scalars().all()]
            
            beneficios_result = await session.execute(select(BeneficioInterno))
            beneficios = [FilterOption(id=b.idbeneficio, nombre=b.nombrebeneficio) for b in beneficios_result.scalars().all()]
            
            sedes_result = await session.execute(select(SedeCampus))
            sedes = [FilterOption(id=s.idrecintouniversitario, nombre=s.nombrerecinto) for s in sedes_result.scalars().all()]
            
            tipos_nombramiento_result = await session.execute(select(TipoNombramiento))
            tipos_nombramiento = [FilterOption(id=t.idtiponombramiento, nombre=t.nombrenombramiento) for t in tipos_nombramiento_result.scalars().all()]
            
            jornadas_result = await session.execute(select(Jornada))
            jornadas = [FilterOption(id=j.idjornada, nombre=j.nombrejornada) for j in jornadas_result.scalars().all()]
            
            tipos_programa_result = await session.execute(select(TipoPrograma))
            tipos_programa = [FilterOption(id=t.idtipoprograma, nombre=t.nombretipoprograma) for t in tipos_programa_result.scalars().all()]
            
            departamentos_result = await session.execute(select(Departamento))
            departamentos = [FilterOption(id=d.iddepartamento, nombre=d.nombredepartamento) for d in departamentos_result.scalars().all()]
            
            tipos_sesion_result = await session.execute(select(TipoSesion))
            tipos_sesion = [FilterOption(id=t.idtiposesion, nombre=t.tiposesion) for t in tipos_sesion_result.scalars().all()]
            
            tipos_decision_result = await session.execute(select(TipoDecision))
            tipos_decision = [FilterOption(id=t.idtipodecision, nombre=t.tipodecision) for t in tipos_decision_result.scalars().all()]
            
            tipos_relacion_result = await session.execute(select(TipoRelacion))
            tipos_relacion = [FilterOption(id=t.idtiporelacion, nombre=t.tiporelacion) for t in tipos_relacion_result.scalars().all()]
            
            fuentes_deteccion_result = await session.execute(select(FuenteDeteccion))
            fuentes_deteccion = [FilterOption(id=f.idfuente, nombre=f.nomfuente) for f in fuentes_deteccion_result.scalars().all()]
            
            # Entidades jerárquicas (4 tablas)
            sub_areas_result = await session.execute(select(SubAreas))
            sub_areas = [FilterOption(id=s.idsubarea, nombre=s.nombre, parent_id=s.idtipoarea) for s in sub_areas_result.scalars().all()]
            
            categorias_result = await session.execute(select(Categoria))
            categorias = [FilterOption(id=c.idcategoria, nombre=c.nombrecategoria, parent_id=c.idmacrocategoria, code=c.numcategoria) for c in categorias_result.scalars().all()]
            
            niveles_result = await session.execute(select(NivelAcademico))
            niveles_academicos = [FilterOption(id=n.idnivel, nombre=n.nombrenivel, parent_id=n.idtipoprograma) for n in niveles_result.scalars().all()]
            
            carreras_result = await session.execute(select(Carrera))
            carreras = [FilterOption(id=c.idcarrera, nombre=c.nombrecarrera, parent_id=c.idnivel, code=c.codigocarrera) for c in carreras_result.scalars().all()]
            
            return FilterOptions(
                tipos_area=tipos_area,
                macro_categorias=macro_categorias,
                tipos_documento=tipos_documento,
                estados_vigencia=estados_vigencia,
                respaldos_legales=respaldos_legales,
                roles_institucionales=roles,
                roles=roles,
                beneficios=beneficios,
                sedes_campus=sedes,
                sedes=sedes,
                tipos_nombramiento=tipos_nombramiento,
                jornadas=jornadas,
                tipos_programa=tipos_programa,
                departamentos=departamentos,
                tipos_sesion=tipos_sesion,
                tipos_decision=tipos_decision,
                tipos_relacion=tipos_relacion,
                fuentes_deteccion=fuentes_deteccion,
                sub_areas=sub_areas,
                categorias=categorias,
                niveles_academicos=niveles_academicos,
                carreras=carreras,
            )

    async def get_editable_by_id(self, document_id: str) -> DocumentoEditableOut:
        """
        Retorna la representación canónica con todos los campos editables y listas de IDs para el formulario de administración.
        Omite urlarchivooriginals3 ya que no se utiliza en el panel de admin.
        """
        async with get_session() as session:
            stmt = (
                select(Documento)
                .where(Documento.iddocumento == document_id)
                .options(
                    selectinload(Documento.sedes),
                    selectinload(Documento.carreras),
                    selectinload(Documento.beneficios),
                    selectinload(Documento.nombramientos),
                    selectinload(Documento.departamentos),
                    selectinload(Documento.jornadas),
                    selectinload(Documento.niveles),
                    selectinload(Documento.roles),
                    selectinload(Documento.areas_emisoras),
                )
            )
            result = await session.execute(stmt)
            doc = result.scalar_one_or_none()
            if not doc:
                raise DocumentNotFoundError(document_id)
                
            return DocumentoEditableOut(
                iddocumento=doc.iddocumento,
                numero=doc.numero,
                idtipodocumento=doc.idtipodocumento,
                titulo=doc.titulo,
                nommetadato=doc.nommetadato,
                descripcion=doc.descripcion,
                idcategoria=doc.idcategoria,
                idtiposesion=doc.idtiposesion,
                numsesion=doc.numsesion,
                numacuerdo=doc.numacuerdo,
                idtipodecision=doc.idtipodecision,
                idestadovigencia=doc.idestadovigencia,
                creacion=doc.creacion,
                derogacion=doc.derogacion,
                aplicacioninmediata=doc.aplicacioninmediata,
                isactive=doc.isactive,
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

    async def get_lexical_suggestions(self, term: str, limit: int = 10) -> List[Dict]:
        """
        Búsqueda de sugerencias/autocompletado léxico en PostgreSQL.
        Aprovecha el índice funcional unificado GIN con trigramas sobre (titulo || ' ' || nommetadato).
        Busca coincidencias en 'titulo' y 'nommetadato' de documentos activos.
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
                {"contains": contains, "limit": limit}
            )
            rows = result.fetchall()
            return [
                {
                    "documentid": str(row.iddocumento),
                    "numero": row.numero,
                    "titulo": row.titulo,
                    "nommetadato": row.nommetadato or "",
                    "matched_field": row.matched_field,
                    "suggestion": row.titulo if row.matched_field == "titulo" else (row.nommetadato or row.titulo)
                }
                for row in rows
            ]
