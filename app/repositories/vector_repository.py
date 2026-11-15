"""Repositorio de persistencia y búsqueda vectorial y semántica con pgvector."""

from sqlmodel import text

from app.core.database import get_session
from app.models.db_models import DocumentoChunk


class VectorRepository(object):
    """
    Acceso a pgvector para búsqueda semántica.
    Tabla DocumentoChunk: id_chunk, id_documento (FK), numero_pagina, secuencia,
    texto_fragmento, nombre_titulo, numero_articulo, numero_inciso, id_tipo_pagina,
    hash_sha256, is_active.
    """

    @staticmethod
    def _map_row_to_dict(row: object) -> dict[str, object]:
        """Convierte una fila de base de datos a diccionario estandarizado de resultado."""
        return {
            "document_id": getattr(row, "iddocumento", None),
            "chunk_id": getattr(row, "idchunk", None),
            "texto_fragmento": getattr(row, "textofragmento", None),
            "numero_pagina": getattr(row, "numeropagina", None),
            "secuencia": getattr(row, "secuencia", None),
            "nombre_titulo": getattr(row, "nombretitulo", None),
            "numero_articulo": getattr(row, "numeroarticulo", None),
            "numero_inciso": getattr(row, "numeroinciso", None),
            "numero": getattr(row, "numero", None),
            "titulo": getattr(row, "titulo", None),
            "nom_meta_dato": getattr(row, "nommetadato", None),
            "id_tipo_documento": getattr(row, "idtipodocumento", None),
            "id_estado_vigencia": getattr(row, "idestadovigencia", None),
            "id_categoria": getattr(row, "idcategoria", None),
            "creacion": getattr(row, "creacion", None),
            "derogacion": getattr(row, "derogacion", None),
            "aplicacion_inmediata": getattr(row, "aplicacioninmediata", None),
            "is_active": getattr(row, "isactive", None),
            "numacuerdo": getattr(row, "numacuerdo", None),
            "numsesion": getattr(row, "numsesion", None),
            "tipodocumento": getattr(row, "nombretipodocumento", None),
            "estadovigencia": getattr(row, "estadovigencia", None),
            "tipodecision": getattr(row, "tipodecision", None),
            "tiposesion": getattr(row, "tiposesion", None),
            "score": float(getattr(row, "score", 0.0)),
        }

    @staticmethod
    def _apply_direct_filters(
        filters: dict[str, object],
        clauses: list[str],
        params: dict[str, object],
    ) -> None:
        """Aplica filtros relacionales directos sobre la tabla documento y chunk."""
        direct_maps = [
            ("idestadovigencia", "d.idestadovigencia =", "estado_vigencia"),
            ("idtipodocumento", "d.idtipodocumento =", "tipo_documento"),
            ("idtipodecision", "d.idtipodecision =", "tipo_decision"),
            ("idtiposesion", "d.idtiposesion =", "tipo_sesion"),
            ("idcategoria", "d.idcategoria =", "categoria"),
            ("creaciondesde", "d.creacion >=", "creacion_desde"),
            ("creacionhasta", "d.creacion <=", "creacion_hasta"),
            ("derogaciondesde", "d.derogacion >=", "derogacion_desde"),
            ("derogacionhasta", "d.derogacion <=", "derogacion_hasta"),
            ("aplicacioninmediata", "d.aplicacioninmediata =", "aplicacion_inmediata"),
            ("isactive", "d.isactive =", "is_active"),
            ("idtipopagina", "dc.idtipopagina =", "tipo_pagina"),
        ]
        for key, expr, param_name in direct_maps:
            val = filters.get(key)
            if val is not None:
                clauses.append(f"AND {expr} :{param_name}")
                params[param_name] = val

    @staticmethod
    def _apply_bridge_filters(
        filters: dict[str, object],
        clauses: list[str],
        params: dict[str, object],
    ) -> None:
        """Aplica filtros mediante tablas puente y EXISTS."""
        exists_mappings = [
            ("idrecintouniversitario", "documentosedecampus", "idrecintouniversitario", "sede"),
            ("idcarrera", "documentocarrera", "idcarrera", "carrera"),
            ("idbeneficio", "documentobeneficio", "idbeneficio", "beneficio"),
            ("idtiponombramiento", "documentonombramiento", "idtiponombramiento", "nombramiento"),
            ("iddepartamento", "documentodepartamento", "iddepartamento", "departamento"),
            ("idjornada", "documentojornada", "idjornada", "jornada"),
            ("idnivel", "documentonivel", "idnivel", "nivel"),
            ("idrol", "documentorol", "idrol", "rol"),
        ]

        for filter_key, table, col, param_name in exists_mappings:
            val = filters.get(filter_key)
            if val:
                clauses.append(
                    f"AND EXISTS (SELECT 1 FROM {table} bridge "
                    f"WHERE bridge.iddocumento = d.iddocumento AND bridge.{col} = :{param_name})"
                )
                params[param_name] = val

        if filters.get("idsubarea"):
            clauses.append(
                "AND EXISTS (SELECT 1 FROM areaemisora ae "
                "WHERE ae.iddocumento = d.iddocumento AND ae.idareaadministrativa = :sub_area)"
            )
            params["sub_area"] = filters["idsubarea"]

    @classmethod
    def _apply_common_filters(cls, filters: dict[str, object] | None) -> tuple[str, dict[str, object]]:
        """Construye fragmentos de cláusula WHERE y parámetros para filtros relacionales."""
        if not filters:
            return "", {}

        clauses: list[str] = []
        params: dict[str, object] = {}
        cls._apply_direct_filters(filters, clauses, params)
        cls._apply_bridge_filters(filters, clauses, params)
        return " " + " ".join(clauses) if clauses else "", params

    @staticmethod
    async def save_chunk(
        document_id: int,
        chunk_index: int,
        chunk_text: str,
        vector: list[float],
        numero_pagina: int,
        secuencia: int,
        hash_sha256: str,
        nombre_titulo: str | None = None,
        numero_articulo: str | None = None,
        numero_inciso: str | None = None,
        id_tipo_pagina: int | None = None,
    ) -> DocumentoChunk | None:
        """Guarda un chunk con su embedding vector y metadatos de citación legal."""
        async with get_session() as session:
            await session.execute(
                text("""
                    INSERT INTO documentochunk
                    (iddocumento, numeropagina, secuencia, textofragmento,
                     nombretitulo, numeroarticulo, numeroinciso, idtipopagina,
                     hashsha256, isactive, embedding)
                    VALUES (:doc_id, :num_pag, :seq, :texto, :titulo, :articulo,
                            :inciso, :tipo_pag, :hash, :active, :vector)
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
                    "vector": vector,
                },
            )
            await session.commit()

            return DocumentoChunk(
                iddocumento=document_id,
                numeropagina=numero_pagina,
                secuencia=secuencia,
                textofragmento=chunk_text,
                nombretitulo=nombre_titulo,
                numeroarticulo=numero_articulo,
                numeroinciso=numero_inciso,
                idtipopagina=id_tipo_pagina,
                hashsha256=hash_sha256,
                isactive=True,
            )

    async def similarity_search(
        self,
        vector: list[float],
        top_k: int,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        """
        Búsqueda por similitud coseno con pgvector.
        Aplica filtros de metadata mediante JOIN con tablas puente.
        """
        async with get_session() as session:
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

            params: dict[str, object] = {"vector": vector}
            filter_clause, filter_params = self._apply_common_filters(filters)
            query += filter_clause
            params.update(filter_params)

            query += " ORDER BY dc.embedding <=> :vector LIMIT :top_k"
            params["top_k"] = top_k

            result = await session.execute(text(query), params)
            return [self._map_row_to_dict(row) for row in result.fetchall()]

    async def filter_only_search(
        self,
        top_k: int,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        """
        Búsqueda solo por filtros de metadata (sin similitud vectorial).
        Ordena por fecha de creación (más recientes primero).
        """
        async with get_session() as session:
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

            params: dict[str, object] = {}
            filter_clause, filter_params = self._apply_common_filters(filters)
            query += filter_clause
            params.update(filter_params)

            query += " ORDER BY d.creacion DESC LIMIT :top_k"
            params["top_k"] = top_k

            result = await session.execute(text(query), params)
            return [self._map_row_to_dict(row) for row in result.fetchall()]

    async def hybrid_search(
        self,
        query_text: str,
        vector: list[float],
        top_k: int,
        filters: dict[str, object] | None = None,
        vector_weight: float = 0.7,
        tsvector_weight: float = 0.3,
    ) -> list[dict[str, object]]:
        """Búsqueda híbrida combinando pgvector (semántica) y TSVECTOR (búsqueda de texto completo)."""
        async with get_session() as session:
            vector_results = await self.similarity_search(vector, top_k * 2, filters)

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

            ts_params: dict[str, object] = {"query": query_text}
            filter_clause, filter_params = self._apply_common_filters(filters)
            tsvector_query += filter_clause
            ts_params.update(filter_params)

            tsvector_query += " ORDER BY ts_rank(dc.indicelexico, plainto_tsquery(:query)) DESC LIMIT :top_k"
            ts_params["top_k"] = top_k * 2

            ts_result = await session.execute(text(tsvector_query), ts_params)
            ts_rows = ts_result.fetchall()

            combined_scores: dict[int, dict[str, object]] = {}

            max_vector_score = max([float(r["score"]) for r in vector_results]) if vector_results else 1.0
            for result in vector_results:
                chunk_id = int(result["chunk_id"])
                normalized_vector_score = float(result["score"]) / max_vector_score
                combined_scores[chunk_id] = {
                    "result": result,
                    "vector_score": normalized_vector_score,
                    "ts_score": 0.0,
                    "combined_score": normalized_vector_score * vector_weight,
                }

            max_ts_score = max([float(row.ts_score) for row in ts_rows]) if ts_rows else 1.0
            for row in ts_rows:
                chunk_id = row.idchunk
                normalized_ts_score = float(row.ts_score) / max_ts_score
                if chunk_id in combined_scores:
                    combined_scores[chunk_id]["ts_score"] = normalized_ts_score
                    combined_scores[chunk_id]["combined_score"] += normalized_ts_score * tsvector_weight
                else:
                    combined_scores[chunk_id] = {
                        "result": {
                            "document_id": row.iddocumento,
                            "chunk_id": row.idchunk,
                            "texto_fragmento": row.textofragmento,
                            "numero_pagina": row.numeropagina,
                            "secuencia": row.secuencia,
                            "numero": row.numero,
                            "titulo": row.titulo,
                            "nom_meta_dato": row.nommetadato,
                            "score": 0.0,
                        },
                        "vector_score": 0.0,
                        "ts_score": normalized_ts_score,
                        "combined_score": normalized_ts_score * tsvector_weight,
                    }

            sorted_results = sorted(
                combined_scores.values(),
                key=lambda x: x["combined_score"],
                reverse=True,
            )[:top_k]

            for item in sorted_results:
                item["result"]["score"] = item["combined_score"]

            return [item["result"] for item in sorted_results]
