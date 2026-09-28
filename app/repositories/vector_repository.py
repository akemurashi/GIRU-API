from sqlmodel import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict
from app.models.db_models import DocumentoChunk, Documento
from app.core.database import get_session
from app.core.config import settings


class VectorRepository:
    """
    Acceso a pgvector para búsqueda semántica.
    Tabla DocumentoChunk: id_chunk, id_documento (FK), numero_pagina, secuencia,
    texto_fragmento, nombre_titulo, numero_articulo, numero_inciso, id_tipo_pagina,
    hash_sha256, is_active.
    """

    async def save_chunk(self, document_id: int, chunk_index: int,
                         chunk_text: str, vector: List[float],
                         numero_pagina: int, secuencia: int,
                         hash_sha256: str,
                         nombre_titulo: Optional[str] = None,
                         numero_articulo: Optional[str] = None,
                         numero_inciso: Optional[str] = None,
                         id_tipo_pagina: Optional[int] = None) -> Optional[DocumentoChunk]:
        """
        Guarda un chunk con su embedding vector y metadatos de citación legal.
        """
        async with get_session() as session:
            # Use raw SQL to insert with embedding (pgvector)
            await session.execute(
                text("""
                    INSERT INTO documentochunk 
                    (iddocumento, numeropagina, secuencia, textofragmento, 
                     nombretitulo, numeroarticulo, numeroinciso, idtipopagina,
                     hashsha256, isactive, embedding)
                    VALUES (:doc_id, :num_pag, :seq, :texto, :titulo, :articulo, :inciso, :tipo_pag, :hash, :active, :vector)
                    RETURNING idchunk
                """),
                {
                    "doc_id": document_id,
                    "num_pag": numero_pagina,
                    "seq": secuencia,
                    "texto": chunk_text,
                    "titulo": nombre_titulo,
                    "articulo": numero_articulo,
                    "inciso": numero_inciso,
                    "tipo_pag": id_tipo_pagina,
                    "hash": hash_sha256,
                    "active": True,
                    "vector": vector  # pgvector will handle this
                }
            )
            await session.commit()
            
            # Return the chunk object (without embedding for SQLModel)
            chunk = DocumentoChunk(
                iddocumento=document_id,
                numeropagina=numero_pagina,
                secuencia=secuencia,
                textofragmento=chunk_text,
                nombretitulo=nombre_titulo,
                numeroarticulo=numero_articulo,
                numeroinciso=numero_inciso,
                idtipopagina=id_tipo_pagina,
                hashsha256=hash_sha256,
                isactive=True
            )
            return chunk

    async def similarity_search(self, vector: List[float], top_k: int,
                                 filters: Optional[Dict] = None) -> List[Dict]:
        """
        Búsqueda por similitud coseno con pgvector.
        
        Aplica filtros de metadata mediante JOIN con tablas puente.
        Soporta búsqueda híbrida (pgvector + TSVECTOR).
        """
        async with get_session() as session:
            # Build the base query with pgvector similarity
            query = """
                SELECT 
                    dc.idchunk,
                    dc.iddocumento,
                    dc.textofragmento,
                    dc.numeropagina,
                    dc.secuencia,
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
                    td.nombretipodocumento,
                    ev.estadovigencia,
                    tdec.tipodecision,
                    ts.tiposesion,
                    1 - (dc.embedding <=> :vector) AS score
                FROM documentochunk dc
                JOIN documento d ON dc.iddocumento = d.iddocumento
                LEFT JOIN tipodocumento td ON d.idtipodocumento = td.idtipodocumento
                LEFT JOIN estadovigencia ev ON d.idestadovigencia = ev.idestadovigencia
                LEFT JOIN tipodecision tdec ON d.idtipodecision = tdec.idtipodecision
                LEFT JOIN tiposesion ts ON d.idtiposesion = ts.idtiposesion
                WHERE dc.isactive = true AND d.isactive = true
            """
            
            params = {"vector": vector}
            
            # Apply filters
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
                
                # Filter by TipoPagina (new field)
                if filters.get("idtipopagina"):
                    query += " AND dc.idtipopagina = :tipo_pagina"
                    params["tipo_pagina"] = filters["idtipopagina"]
            
            # Order by similarity and limit
            query += " ORDER BY dc.embedding <=> :vector LIMIT :top_k"
            params["top_k"] = top_k
            
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [
                {
                    "document_id": row.iddocumento,
                    "chunk_id": row.idchunk,
                    "texto_fragmento": row.textofragmento,
                    "numero_pagina": row.numeropagina,
                    "secuencia": row.secuencia,
                    "nombre_titulo": getattr(row, 'nombretitulo', None),
                    "numero_articulo": getattr(row, 'numeroarticulo', None),
                    "numero_inciso": getattr(row, 'numeroinciso', None),
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
                    "numacuerdo": getattr(row, 'numacuerdo', None),
                    "numsesion": getattr(row, 'numsesion', None),
                    "tipodocumento": getattr(row, 'nombretipodocumento', None),
                    "estadovigencia": getattr(row, 'estadovigencia', None),
                    "tipodecision": getattr(row, 'tipodecision', None),
                    "tiposesion": getattr(row, 'tiposesion', None),
                    "score": float(row.score)
                }
                for row in rows
            ]

    async def filter_only_search(self, top_k: int,
                                   filters: Optional[Dict] = None) -> List[Dict]:
        """
        Búsqueda solo por filtros de metadata (sin similitud vectorial).
        Se usa cuando la query está vacía.
        
        Aplica filtros de metadata mediante JOIN con tablas puente.
        Ordena por fecha de creación (más recientes primero).
        """
        async with get_session() as session:
            # Build the base query without vector similarity
            query = """
                SELECT 
                    dc.idchunk,
                    dc.iddocumento,
                    dc.textofragmento,
                    dc.numeropagina,
                    dc.secuencia,
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
                    td.nombretipodocumento,
                    ev.estadovigencia,
                    tdec.tipodecision,
                    ts.tiposesion,
                    1.0 AS score
                FROM documentochunk dc
                JOIN documento d ON dc.iddocumento = d.iddocumento
                LEFT JOIN tipodocumento td ON d.idtipodocumento = td.idtipodocumento
                LEFT JOIN estadovigencia ev ON d.idestadovigencia = ev.idestadovigencia
                LEFT JOIN tipodecision tdec ON d.idtipodecision = tdec.idtipodecision
                LEFT JOIN tiposesion ts ON d.idtiposesion = ts.idtiposesion
                WHERE dc.isactive = true AND d.isactive = true
            """
            
            params = {}
            
            # Apply filters (same logic as similarity_search)
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
                
                # Filter by TipoPagina
                if filters.get("idtipopagina"):
                    query += " AND dc.idtipopagina = :tipo_pagina"
                    params["tipo_pagina"] = filters["idtipopagina"]
            
            # Order by creation date (most recent first) and limit
            query += " ORDER BY d.creacion DESC LIMIT :top_k"
            params["top_k"] = top_k
            
            result = await session.execute(text(query), params)
            rows = result.fetchall()
            
            return [
                {
                    "document_id": row.iddocumento,
                    "chunk_id": row.idchunk,
                    "texto_fragmento": row.textofragmento,
                    "numero_pagina": row.numeropagina,
                    "secuencia": row.secuencia,
                    "nombre_titulo": getattr(row, 'nombretitulo', None),
                    "numero_articulo": getattr(row, 'numeroarticulo', None),
                    "numero_inciso": getattr(row, 'numeroinciso', None),
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
                    "numacuerdo": getattr(row, 'numacuerdo', None),
                    "numsesion": getattr(row, 'numsesion', None),
                    "tipodocumento": getattr(row, 'nombretipodocumento', None),
                    "estadovigencia": getattr(row, 'estadovigencia', None),
                    "tipodecision": getattr(row, 'tipodecision', None),
                    "tiposesion": getattr(row, 'tiposesion', None),
                    "score": float(row.score)
                }
                for row in rows
            ]

    async def hybrid_search(self, query_text: str, vector: List[float], top_k: int,
                           filters: Optional[Dict] = None,
                           vector_weight: float = 0.7,
                           tsvector_weight: float = 0.3) -> List[Dict]:
        """
        Búsqueda híbrida combinando pgvector (semántica) y TSVECTOR (búsqueda de texto completo).
        
        Combina scores de ambas búsquedas con pesos configurables.
        """
        async with get_session() as session:
            # Get pgvector results
            vector_results = await self.similarity_search(vector, top_k * 2, filters)
            
            # Get TSVECTOR results
            tsvector_query = """
                SELECT 
                    dc.idchunk,
                    dc.iddocumento,
                    dc.textofragmento,
                    dc.numeropagina,
                    dc.secuencia,
                    d.numero,
                    d.titulo,
                    d.nommetadato,
                    ts_rank(dc.indicelexico, plainto_tsquery(:query)) AS ts_score
                FROM documentochunk dc
                JOIN documento d ON dc.iddocumento = d.iddocumento
                WHERE dc.indicelexico IS NOT NULL 
                  AND dc.isactive = true 
                  AND d.isactive = true
                  AND plainto_tsquery(:query) @@ dc.indicelexico
            """
            
            # Apply same filters to TSVECTOR query
            ts_params = {"query": query_text}
            if filters:
                if filters.get("idestadovigencia"):
                    tsvector_query += " AND d.idestadovigencia = :estado_vigencia"
                    ts_params["estado_vigencia"] = filters["idestadovigencia"]
                if filters.get("idtipodocumento"):
                    tsvector_query += " AND d.idtipodocumento = :tipo_documento"
                    ts_params["tipo_documento"] = filters["idtipodocumento"]
                # Add other filters as needed...
            
            tsvector_query += " ORDER BY ts_rank(dc.indicelexico, plainto_tsquery(:query)) DESC LIMIT :top_k"
            ts_params["top_k"] = top_k * 2
            
            ts_result = await session.execute(text(tsvector_query), ts_params)
            ts_rows = ts_result.fetchall()
            
            # Combine and re-rank results
            combined_scores = {}
            
            # Normalize and weight vector scores
            max_vector_score = max([r["score"] for r in vector_results]) if vector_results else 1.0
            for result in vector_results:
                chunk_id = result["chunk_id"]
                normalized_vector_score = result["score"] / max_vector_score
                combined_scores[chunk_id] = {
                    "result": result,
                    "vector_score": normalized_vector_score,
                    "ts_score": 0.0,
                    "combined_score": normalized_vector_score * vector_weight
                }
            
            # Normalize and weight TSVECTOR scores
            max_ts_score = max([float(row.ts_score) for row in ts_rows]) if ts_rows else 1.0
            for row in ts_rows:
                chunk_id = row.id_chunk
                normalized_ts_score = float(row.ts_score) / max_ts_score
                if chunk_id in combined_scores:
                    combined_scores[chunk_id]["ts_score"] = normalized_ts_score
                    combined_scores[chunk_id]["combined_score"] += normalized_ts_score * tsvector_weight
                else:
                    combined_scores[chunk_id] = {
                        "result": {
                            "document_id": row.iddocumento,
                            "chunk_id": row.id_chunk,
                            "texto_fragmento": row.texto_fragmento,
                            "numero_pagina": row.numero_pagina,
                            "secuencia": row.secuencia,
                            "numero": row.numero,
                            "titulo": row.titulo,
                            "nom_meta_dato": row.nom_meta_dato,
                            "score": 0.0
                        },
                        "vector_score": 0.0,
                        "ts_score": normalized_ts_score,
                        "combined_score": normalized_ts_score * tsvector_weight
                    }
            
            # Sort by combined score and return top_k
            sorted_results = sorted(
                combined_scores.values(),
                key=lambda x: x["combined_score"],
                reverse=True
            )[:top_k]
            
            # Update final score in result
            for item in sorted_results:
                item["result"]["score"] = item["combined_score"]
            
            return [item["result"] for item in sorted_results]
