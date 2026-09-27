from sqlmodel import SQLModel, select, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from typing import Optional, List, Dict
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
    DocumentoUpdate, DocumentoDetail, SedeCampusOut, CategoriaOut,
    CarreraOut, BeneficioOut, NombramientoOut, DepartamentoOut
)
from app.models.search_models import FilterOptions, FilterOption
from app.core.database import get_session
from app.core.exceptions import DocumentNotFoundError, DatabaseError


class DocumentRepository:
    """
    Acceso a PostgreSQL para la tabla Documento y sus relaciones.
    Implementado con SQLModel async.
    """

    async def get_by_id(self, document_id: int) -> DocumentoDetail:
        """
        Obtiene un documento por ID con todas sus relaciones.
        JOIN con todas las tablas relacionadas.
        """
        async with get_session() as session:
            # Get the document with basic foreign key relationships
            stmt = (
                select(Documento)
                .where(Documento.iddocumento == document_id)
                .options(
                    selectinload(Documento.tipo_documento),
                    selectinload(Documento.tipo_decision),
                    selectinload(Documento.tipo_sesion),
                    selectinload(Documento.estado_vigencia),
                    selectinload(Documento.chunks),
                    
                    # Relación directa 1:N (Categoría -> MacroCategoría)
                    selectinload(Documento.categoria).selectinload(Categoria.macro_categoria),
                    
                    # Relaciones N:M (Tablas puente -> Tabla final)
                    selectinload(Documento.sedes).selectinload(DocumentoSedeCampus.sede_campus),
                    selectinload(Documento.carreras).selectinload(DocumentoCarrera.carrera).selectinload(Carrera.nivel_academico),
                    selectinload(Documento.carreras).selectinload(DocumentoCarrera.carrera).selectinload(Carrera.departamento),
                    selectinload(Documento.beneficios).selectinload(DocumentoBeneficio.beneficio),
                    selectinload(Documento.nombramientos).selectinload(DocumentoNombramiento.tipo_nombramiento),
                    selectinload(Documento.departamentos).selectinload(DocumentoDepartamento.departamento)
                )
            )
            
            result = await session.execute(stmt)
            doc = result.scalar_one_or_none()
            
            if not doc:
                raise DocumentNotFoundError(document_id)
            
            # Convert to DocumentoDetail
            return DocumentoDetail(
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
                cant_paginas=doc.cant_paginas,
                urlarchivooriginals3=doc.urlarchivooriginals3,
                sedes=[
                    SedeCampusOut(
                        idrecintouniversitario=s.sede_campus.idrecintouniversitario,
                        nombrerecinto=s.sede_campus.nombrerecinto
                    ) for s in doc.sedes if s.sede_campus
                ],
                categorias=[
                    CategoriaOut(
                        idcategoria=doc.categoria.idcategoria,
                        nombrecategoria=doc.categoria.nombrecategoria,
                        numcategoria=doc.categoria.numcategoria,
                        macrocategoria=doc.categoria.macro_categoria.nombrecategoria if doc.categoria.macro_categoria else None
                    )
                ] if doc.categoria else [],
                carreras=[
                    CarreraOut(
                        idcarrera=c.carrera.idcarrera,
                        nombrecarrera=c.carrera.nombrecarrera,
                        codigocarrera=c.carrera.codigocarrera,
                        nombrenivel=c.carrera.nivel_academico.nombrenivel if c.carrera.nivel_academico else None,
                        nombredepartamento=c.carrera.departamento.nombredepartamento if c.carrera.departamento else None
                    ) for c in doc.carreras if c.carrera
                ],
                beneficios=[
                    BeneficioOut(
                        idbeneficio=b.beneficio.idbeneficio,
                        nombrebeneficio=b.beneficio.nombrebeneficio
                    ) for b in doc.beneficios if b.beneficio
                ],
                nombramientos=[
                    NombramientoOut(
                        idtiponombramiento=n.tipo_nombramiento.idtiponombramiento,
                        nombrenombramiento=n.tipo_nombramiento.nombrenombramiento
                    ) for n in doc.nombramientos if n.tipo_nombramiento
                ],
                departamentos=[
                    DepartamentoOut(
                        iddepartamento=d.departamento.iddepartamento,
                        nombredepartamento=d.departamento.nombredepartamento
                    ) for d in doc.departamentos if d.departamento
                ],
                chunkcount=len(doc.chunks) if doc.chunks else 0
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

    async def update(self, document_id: int, data: DocumentoUpdate) -> DocumentoDetail:
        """
        Actualiza campos editables por el admin.
        Para relaciones muchos a muchos: elimina las anteriores e inserta las nuevas.
        """
        async with get_session() as session:
            # Get the document
            stmt = select(Documento).where(Documento.iddocumento == document_id)
            result = await session.execute(stmt)
            doc = result.scalar_one_or_none()
            
            if not doc:
                raise DocumentNotFoundError(document_id)
            
            # Update basic fields
            if data.titulo is not None:
                doc.titulo = data.titulo
            if data.descripcion is not None:
                doc.descripcion = data.descripcion
            if data.idcategoria is not None:
                doc.idcategoria = data.idcategoria
            if data.idtipodecision is not None:
                doc.idtipodecision = data.idtipodecision
            if data.idtiposesion is not None:
                doc.idtiposesion = data.idtiposesion
            if data.idestadovigencia is not None:
                doc.idestadovigencia = data.idestadovigencia
            if data.derogacion is not None:
                doc.derogacion = data.derogacion
            if data.aplicacioninmediata is not None:
                doc.aplicacioninmediata = data.aplicacioninmediata
            if data.isactive is not None:
                doc.isactive = data.isactive
            
            # Update many-to-many relationships
            # Delete existing relations and add new ones
            
            if data.sedesids is not None:
                # Delete existing
                await session.execute(
                    delete(DocumentoSedeCampus).where(DocumentoSedeCampus.iddocumento == document_id)
                )
                for sede_id in data.sedesids:
                    session.add(DocumentoSedeCampus(iddocumento=document_id, idrecintouniversitario=sede_id))
            
            if data.carrerasids is not None:
                await session.execute(
                    delete(DocumentoCarrera).where(DocumentoCarrera.iddocumento == document_id)
                )
                for carrera_id in data.carrerasids:
                    session.add(DocumentoCarrera(iddocumento=document_id, idcarrera=carrera_id))
            
            if data.beneficiosids is not None:
                await session.execute(
                    delete(DocumentoBeneficio).where(DocumentoBeneficio.iddocumento == document_id)
                )
                for beneficio_id in data.beneficiosids:
                    session.add(DocumentoBeneficio(iddocumento=document_id, idbeneficio=beneficio_id))
            
            if data.nombramientosids is not None:
                await session.execute(
                    delete(DocumentoNombramiento).where(DocumentoNombramiento.iddocumento == document_id)
                )
                for nombramiento_id in data.nombramientosids:
                    session.add(DocumentoNombramiento(iddocumento=document_id, idtiponombramiento=nombramiento_id))
            
            if data.departamentosids is not None:
                await session.execute(
                    delete(DocumentoDepartamento).where(DocumentoDepartamento.iddocumento == document_id)
                )
                for departamento_id in data.departamentosids:
                    session.add(DocumentoDepartamento(iddocumento=document_id, iddepartamento=departamento_id))
            
            if data.jornadasids is not None:
                await session.execute(
                    delete(DocumentoJornada).where(DocumentoJornada.iddocumento == document_id)
                )
                for jornada_id in data.jornadasids:
                    session.add(DocumentoJornada(iddocumento=document_id, idjornada=jornada_id))
            
            if data.nivelesids is not None:
                await session.execute(
                    delete(DocumentoNivel).where(DocumentoNivel.iddocumento == document_id)
                )
                for nivel_id in data.nivelesids:
                    session.add(DocumentoNivel(iddocumento=document_id, idnivel=nivel_id))
            
            if data.rolesids is not None:
                await session.execute(
                    delete(DocumentoRol).where(DocumentoRol.iddocumento == document_id)
                )
                for rol_id in data.rolesids:
                    session.add(DocumentoRol(iddocumento=document_id, idrol=rol_id))
            
            if data.areaseemisorasids is not None:
                await session.execute(
                    delete(AreaEmisora).where(AreaEmisora.iddocumento == document_id)
                )
                for area_id in data.areaseemisorasids:
                    session.add(AreaEmisora(iddocumento=document_id, idareaadministrativa=area_id))
            
            await session.commit()
            await session.refresh(doc)
            
            return await self.get_by_id(document_id)

    async def toggle_active(self, document_id: int) -> DocumentoDetail:
        """Invierte el valor de is_active en la tabla Documento."""
        async with get_session() as session:
            stmt = select(Documento).where(Documento.iddocumento == document_id)
            result = await session.execute(stmt)
            doc = result.scalar_one_or_none()
            
            if not doc:
                raise DocumentNotFoundError(document_id)
            
            doc.isactive = not doc.isactive
            await session.commit()
            await session.refresh(doc)
            
            return await self.get_by_id(document_id)

    async def filter_only_search(self, top_k: int,
                                   filters: Optional[Dict] = None) -> List[Dict]:
        """
        Búsqueda solo por filtros de metadata (sin similitud vectorial).
        Se usa cuando la query está vacía y no hay chunks/embeddings.
        
        Busca directamente en la tabla documento (no documentochunk).
        Ordena por fecha de creación (más recientes primero).
        """
        async with get_session() as session:
            # Build the base query on documento table
            query = """
                SELECT 
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
            
            params = {}
            
            # Apply filters (same logic as similarity_search but on documento table)
            if filters:
                # Estado de vigencia
                if filters.get("idestadovigencia"):
                    query += " AND d.idestadovigencia = :estado_vigencia"
                    params["estado_vigencia"] = filters["idestadovigencia"]
                
                # Tipo de documento
                if filters.get("idtipodocumento"):
                    query += " AND d.idtipodocumento = :tipo_documento"
                    params["tipo_documento"] = filters["idtipodocumento"]
                
                # Tipo de decisión
                if filters.get("idtipodecision"):
                    query += " AND d.idtipodecision = :tipo_decision"
                    params["tipo_decision"] = filters["idtipodecision"]
                
                # Tipo de sesión
                if filters.get("idtiposesion"):
                    query += " AND d.idtiposesion = :tipo_sesion"
                    params["tipo_sesion"] = filters["idtiposesion"]
                
                # Categoría
                if filters.get("idcategoria"):
                    query += " AND d.idcategoria = :categoria"
                    params["categoria"] = filters["idcategoria"]
                
                # Fechas
                if filters.get("creaciondesde"):
                    query += " AND d.creacion >= :creacion_desde"
                    params["creacion_desde"] = filters["creaciondesde"]
                
                if filters.get("creacionhasta"):
                    query += " AND d.creacion <= :creacion_hasta"
                    params["creacion_hasta"] = filters["creacionhasta"]
                
                if filters.get("derogaciondesde"):
                    query += " AND d.derogacion >= :derogacion_desde"
                    params["derogacion_desde"] = filters["derogaciondesde"]
                
                if filters.get("derogacionhasta"):
                    query += " AND d.derogacion <= :derogacion_hasta"
                    params["derogacion_hasta"] = filters["derogacionhasta"]
                
                # Boolean filters
                if filters.get("aplicacioninmediata") is not None:
                    query += " AND d.aplicacioninmediata = :aplicacion_inmediata"
                    params["aplicacion_inmediata"] = filters["aplicacioninmediata"]
                
                if filters.get("isactive") is not None:
                    query += " AND d.isactive = :is_active"
                    params["is_active"] = filters["isactive"]
                
                # Many-to-many filters via EXISTS
                if filters.get("idrecintouniversitario"):
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM documentosedecampus dsc
                            WHERE dsc.iddocumento = d.iddocumento
                            AND dsc.idrecintouniversitario = :sede
                        )
                    """
                    params["sede"] = filters["idrecintouniversitario"]
                
                if filters.get("idcarrera"):
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM documentocarrera dcarr
                            WHERE dcarr.iddocumento = d.iddocumento
                            AND dcarr.idcarrera = :carrera
                        )
                    """
                    params["carrera"] = filters["idcarrera"]
                
                if filters.get("idbeneficio"):
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM documentobeneficio db
                            WHERE db.iddocumento = d.iddocumento
                            AND db.idbeneficio = :beneficio
                        )
                    """
                    params["beneficio"] = filters["idbeneficio"]
                
                if filters.get("idtiponombramiento"):
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM documentonombramiento dn
                            WHERE dn.iddocumento = d.iddocumento
                            AND dn.idtiponombramiento = :nombramiento
                        )
                    """
                    params["nombramiento"] = filters["idtiponombramiento"]
                
                if filters.get("iddepartamento"):
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM documentodepartamento dd
                            WHERE dd.iddocumento = d.iddocumento
                            AND dd.iddepartamento = :departamento
                        )
                    """
                    params["departamento"] = filters["iddepartamento"]
                
                if filters.get("idjornada"):
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM documentojornada dj
                            WHERE dj.iddocumento = d.iddocumento
                            AND dj.idjornada = :jornada
                        )
                    """
                    params["jornada"] = filters["idjornada"]
                
                if filters.get("idnivel"):
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM documentonivel dnl
                            WHERE dnl.iddocumento = d.iddocumento
                            AND dnl.idnivel = :nivel
                        )
                    """
                    params["nivel"] = filters["idnivel"]
                
                if filters.get("idrol"):
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM documentorol dr
                            WHERE dr.iddocumento = d.iddocumento
                            AND dr.idrol = :rol
                        )
                    """
                    params["rol"] = filters["idrol"]
                
                if filters.get("idsubarea"):
                    query += """
                        AND EXISTS (
                            SELECT 1 FROM areaemisora ae
                            WHERE ae.iddocumento = d.iddocumento
                            AND ae.idareaadministrativa = :sub_area
                        )
                    """
                    params["sub_area"] = filters["idsubarea"]
            
            # Order by creation date (most recent first) and limit
            query += " ORDER BY d.creacion DESC LIMIT :top_k"
            params["top_k"] = top_k
            
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [
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

    async def get_filter_options(self) -> FilterOptions:
        """
        Consulta los valores únicos de cada dimensión para poblar los dropdowns.
        Incluye todos los catálogos base (15 tablas) y entidades jerárquicas (4 tablas).
        """
        async with get_session() as session:
            # Catálogos base (15 tablas)
            tipos_area_result = await session.execute(select(TipoArea))
            tipos_area = [FilterOption(id=t.idtipoarea, nombre=t.nombrearea) for t in tipos_area_result.scalars().all()]
            
            macro_categorias_result = await session.execute(select(MacroCategoria))
            macro_categorias = [FilterOption(id=m.idmacrocategoria, nombre=m.nombrecategoria) for m in macro_categorias_result.scalars().all()]
            
            tipos_documento_result = await session.execute(select(TipoDocumento))
            tipos_documento = [FilterOption(id=t.idtipodocumento, nombre=t.nombretipodocumento) for t in tipos_documento_result.scalars().all()]
            
            estados_vigencia_result = await session.execute(select(EstadoVigencia))
            estados_vigencia = [FilterOption(id=e.idestadovigencia, nombre=e.estadovigencia) for e in estados_vigencia_result.scalars().all()]
            
            respaldos_legales_result = await session.execute(select(RespaldoLegal))
            respaldos_legales = [FilterOption(id=r.idrespaldolegal, nombre=r.respaldolegal) for r in respaldos_legales_result.scalars().all()]
            
            roles_institucionales_result = await session.execute(select(RolInstitucional))
            roles_institucionales = [FilterOption(id=r.idrol, nombre=r.nombrerol) for r in roles_institucionales_result.scalars().all()]
            
            beneficios_result = await session.execute(select(BeneficioInterno))
            beneficios = [FilterOption(id=b.idbeneficio, nombre=b.nombrebeneficio) for b in beneficios_result.scalars().all()]
            
            sedes_campus_result = await session.execute(select(SedeCampus))
            sedes_campus = [FilterOption(id=s.idrecintouniversitario, nombre=s.nombrerecinto) for s in sedes_campus_result.scalars().all()]
            
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
            
            tipos_pagina_result = await session.execute(select(TipoPagina))
            tipos_pagina = [FilterOption(id=t.idtipopagina, nombre=t.tipopagina) for t in tipos_pagina_result.scalars().all()]
            
            # Entidades jerárquicas (4 tablas)
            # sub_areas_result = await session.execute(select(SubAreas))
            # sub_areas = [FilterOption(id=s.idsubarea, nombre=s.nombre) for s in sub_areas_result.scalars().all()]
            sub_areas = []
            
            categorias_result = await session.execute(select(Categoria))
            categorias = [FilterOption(id=c.idcategoria, nombre=c.nombrecategoria) for c in categorias_result.scalars().all()]
            
            niveles_academicos_result = await session.execute(select(NivelAcademico))
            niveles_academicos = [FilterOption(id=n.idnivel, nombre=n.nombrenivel) for n in niveles_academicos_result.scalars().all()]
            
            carreras_result = await session.execute(select(Carrera))
            carreras = [FilterOption(id=c.idcarrera, nombre=c.nombrecarrera) for c in carreras_result.scalars().all()]
            
            return FilterOptions(
                tipos_area=tipos_area,
                macro_categorias=macro_categorias,
                tipos_documento=tipos_documento,
                estados_vigencia=estados_vigencia,
                respaldos_legales=respaldos_legales,
                roles_institucionales=roles_institucionales,
                beneficios=beneficios,
                sedes_campus=sedes_campus,
                tipos_nombramiento=tipos_nombramiento,
                jornadas=jornadas,
                tipos_programa=tipos_programa,
                departamentos=departamentos,
                tipos_sesion=tipos_sesion,
                tipos_decision=tipos_decision,
                tipos_relacion=tipos_relacion,
                fuentes_deteccion=fuentes_deteccion,
                tipos_pagina=tipos_pagina,
                sub_areas=sub_areas,
                categorias=categorias,
                niveles_academicos=niveles_academicos,
                carreras=carreras
            )
