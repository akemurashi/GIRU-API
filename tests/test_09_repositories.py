"""
Test Suite 9: Repositories & Database Layer
(RelacionRepository, VectorRepository, DocumentRepository, check_db_connection, ensure_schema_compatibility)
Cobertura exhaustiva de persistencia PostgreSQL, manejo de SPs, búsquedas vectoriales, filtros relacionales y triggers.
"""

from datetime import date, datetime
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from app.core.database import check_db_connection, ensure_schema_compatibility
from app.core.exceptions import (
    CatalogNotFoundError,
    DAGCycleError,
    DatabaseError,
    DocumentNotFoundError,
    RelationNotFoundError,
    UniqueConstraintError,
    ValidationError as AppValidationError,
)
from app.models.db_models import Documento, DocumentoChunk, RelacionDocumental
from app.models.document_models import (
    DocumentoUpdate,
    HitoNormativo,
    TrazabilidadUpsertRequest,
)
from app.models.search_models import FilterOption, FilterOptions
from app.repositories.document_repository import DocumentRepository
from app.repositories.relacion_repository import RelacionRepository
from app.repositories.trazabilidad_repository import TrazabilidadRepository
from app.repositories.vector_repository import VectorRepository


class TestSuite9RepositoriesAndDatabase(unittest.IsolatedAsyncioTestCase):
    """Pruebas unitarias de repositorios, pgvector, consultas complejas y errores de SP."""

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Database Connection & Schema Compatibility (app/core/database.py)
    # ─────────────────────────────────────────────────────────────────────────

    @patch("app.core.database.async_engine")
    @patch("app.core.database.ensure_schema_compatibility", new_callable=AsyncMock)
    async def test_01_check_db_connection_success(self, mock_ensure_schema, mock_engine):
        """check_db_connection exitoso retorna metadatos de esquema y tablas."""
        mock_conn = AsyncMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        mock_db_res = MagicMock()
        mock_db_res.fetchone.return_value = ("giru_db", "public")

        mock_tbl_res = MagicMock()
        mock_tbl_res.fetchall.return_value = [("public", "Documento")]

        mock_conn.execute.side_effect = [mock_db_res, mock_tbl_res]

        res = await check_db_connection()
        self.assertTrue(res["connected"])
        self.assertEqual(res["database"], "giru_db")
        self.assertEqual(res["current_schema"], "public")
        self.assertEqual(len(res["documento_tables"]), 1)

    @patch("app.core.database.async_engine")
    @patch("app.core.database.ensure_schema_compatibility", new_callable=AsyncMock)
    async def test_02_check_db_connection_error(self, mock_ensure_schema, mock_engine):
        """check_db_connection captura excepciones y retorna connected=False."""
        mock_engine.connect.side_effect = RuntimeError("Conexión rechazada en 5432")
        res = await check_db_connection()
        self.assertFalse(res["connected"])
        self.assertIn("Conexión rechazada", res["error"])

    @patch("app.core.database.async_engine")
    async def test_03_ensure_schema_compatibility_success_and_warning(self, mock_engine):
        """ensure_schema_compatibility ejecuta ALTER TABLE y tolera excepciones sin crash."""
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__.return_value = mock_conn

        # Éxito
        await ensure_schema_compatibility()
        self.assertTrue(mock_conn.execute.called)

        # Fallo simulado
        mock_conn.execute.side_effect = RuntimeError("Permission denied")
        await ensure_schema_compatibility()

    # ─────────────────────────────────────────────────────────────────────────
    # 2. RelacionRepository (SP Error Classification, CRUD & Lineage)
    # ─────────────────────────────────────────────────────────────────────────

    def test_04_relacion_repo_handle_sp_error_classification(self):
        """RelacionRepository._handle_sp_error clasifica todos los mensajes canónicos de error."""
        repo = RelacionRepository()

        # No se encontró el documento
        with self.assertRaises(DocumentNotFoundError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: No se encontró el documento origen"))

        # Unicidad / Duplicate
        with self.assertRaises(UniqueConstraintError):
            repo._handle_sp_error(RuntimeError("RaiseException'>: Unicidad: La relación ya existe"))
        with self.assertRaises(UniqueConstraintError):
            repo._handle_sp_error(RuntimeError("duplicate key value violates unique constraint"))

        # DAG Cycle
        with self.assertRaises(DAGCycleError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: Violación de Grafo Acíclico (DAG): Ciclo detectado"))
        with self.assertRaises(DAGCycleError):
            repo._handle_sp_error(RuntimeError("ciclo detectado en dependencias"))

        # Catálogo
        with self.assertRaises(CatalogNotFoundError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: Catálogo: Tipo de relación inválido"))

        # Validación / Parámetro
        with self.assertRaises(AppValidationError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: Validación: Fechas incoherentes"))
        with self.assertRaises(AppValidationError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: Parámetro: ID requerido"))

        # Base error genérico
        with self.assertRaises(DatabaseError):
            repo._handle_sp_error(RuntimeError("Error desconocido de PostgreSQL"))

        # Excepción con atributo .orig
        class CustomDBError(Exception):
            orig = "RaiseError'>: Catálogo: Sede no encontrada"
        with self.assertRaises(CatalogNotFoundError):
            repo._handle_sp_error(CustomDBError())

    @patch("app.repositories.relacion_repository.get_session")
    async def test_05_relacion_repo_create_via_sp(self, mock_get_session):
        """create_via_sp valida UUIDs, invoca el SP y maneja errores."""
        repo = RelacionRepository()

        with self.assertRaises(AppValidationError):
            await repo.create_via_sp({"iddocumentoorigen": "invalido", "iddocumentodestino": str(uuid4())})

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        doc1 = uuid4()
        doc2 = uuid4()
        res = await repo.create_via_sp({
            "iddocumentoorigen": str(doc1),
            "iddocumentodestino": str(doc2),
            "idtiporelacion": 1,
            "detallemodificacion": "Modifica artículo 5",
        })
        self.assertEqual(res["status"], "ok")
        self.assertTrue(mock_session.execute.called)
        self.assertTrue(mock_session.commit.called)

        mock_session.execute.side_effect = RuntimeError("RaiseError'>: Violación de Grafo Acíclico (DAG)")
        with self.assertRaises(DAGCycleError):
            await repo.create_via_sp({
                "iddocumentoorigen": str(doc1),
                "iddocumentodestino": str(doc2),
            })

    @patch("app.repositories.relacion_repository.get_session")
    async def test_06_relacion_repo_delete_via_sp(self, mock_get_session):
        """delete_via_sp valida parámetros, ejecuta sp_eliminar_relacion_documental."""
        repo = RelacionRepository()

        with self.assertRaises(AppValidationError):
            await repo.delete_via_sp({"iddocumentoorigen": "not-a-uuid"})
        with self.assertRaises(AppValidationError):
            await repo.delete_via_sp({"iddocumentodestino": "not-a-uuid"})

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        res = await repo.delete_via_sp({
            "idrelacion": 10,
            "iddocumentoorigen": str(uuid4()),
            "iddocumentodestino": str(uuid4()),
        })
        self.assertEqual(res["status"], "ok")

        mock_session.execute.side_effect = RuntimeError("RaiseError'>: Catálogo: Tipo no encontrado")
        with self.assertRaises(CatalogNotFoundError):
            await repo.delete_via_sp({"idrelacion": 99})

    @patch("app.repositories.relacion_repository.get_session")
    async def test_07_relacion_repo_get_by_id_and_delete(self, mock_get_session):
        """get_by_id y delete por ID directo."""
        repo = RelacionRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        rel = RelacionDocumental(idrelacion=5, iddocumentoorigen=uuid4(), iddocumentodestino=uuid4(), idtiporelacion=1)
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = rel
        mock_session.execute.return_value = mock_res

        found = await repo.get_by_id(5)
        self.assertEqual(found.idrelacion, 5)

        mock_res.scalar_one_or_none.return_value = None
        with self.assertRaises(RelationNotFoundError):
            await repo.get_by_id(999)

        del_res = MagicMock()
        del_res.rowcount = 1
        mock_session.execute.return_value = del_res
        self.assertTrue(await repo.delete(5))

    @patch("app.repositories.relacion_repository.get_session")
    async def test_08_relacion_repo_lineage_and_related_docs(self, mock_get_session):
        """get_document_lineage, get_related_documents y list_by_document."""
        repo = RelacionRepository()

        with self.assertRaises(DocumentNotFoundError):
            await repo.get_document_lineage("invalido")
        with self.assertRaises(DocumentNotFoundError):
            await repo.get_related_documents("invalido")
        with self.assertRaises(DocumentNotFoundError):
            await repo.list_by_document("invalido")

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        doc_id = uuid4()
        rel1 = RelacionDocumental(idrelacion=1, iddocumentoorigen=doc_id, iddocumentodestino=uuid4(), idtiporelacion=1, confianza=0.95)
        rel2 = RelacionDocumental(idrelacion=2, iddocumentoorigen=uuid4(), iddocumentodestino=doc_id, idtiporelacion=2, confianza=0.88)

        mock_res1 = MagicMock()
        mock_res1.scalars.return_value.all.return_value = [rel1]
        mock_res2 = MagicMock()
        mock_res2.scalars.return_value.all.return_value = [rel2]

        mock_session.execute.side_effect = [mock_res1, mock_res2]
        lineage = await repo.get_document_lineage(str(doc_id))
        self.assertEqual(len(lineage["relaciones_como_origen"]), 1)
        self.assertEqual(len(lineage["relaciones_como_destino"]), 1)

        doc_obj = Documento(iddocumento=uuid4(), numero="10", titulo="Doc Rel", nommetadato="Doc", isactive=True)
        doc_mock_res = MagicMock()
        doc_mock_res.scalar_one_or_none.return_value = doc_obj

        mock_session.execute.side_effect = [mock_res1, mock_res2, doc_mock_res, doc_mock_res]
        related = await repo.get_related_documents(str(doc_id))
        self.assertEqual(len(related), 2)

        mock_res_list = MagicMock()
        mock_res_list.scalars.return_value.all.return_value = [rel1, rel2]
        mock_session.execute.side_effect = None
        mock_session.execute.return_value = mock_res_list
        rels = await repo.list_by_document(doc_id)
        self.assertEqual(len(rels), 2)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. VectorRepository (pgvector, filtering, similarity & hybrid search)
    # ─────────────────────────────────────────────────────────────────────────

    def test_09_vector_repo_filters_and_mapping(self):
        """VectorRepository: _map_row_to_dict y construcción de filtros directos y bridge."""
        repo = VectorRepository()

        row_mock = MagicMock()
        row_mock.iddocumento = uuid4()
        row_mock.idchunk = 12
        row_mock.textofragmento = "Texto legal..."
        row_mock.score = 0.85
        row_mock.numero = "123"
        row_mock.titulo = "Estatuto"
        row_mock.nommetadato = "Estatuto"
        row_mock.idtipodocumento = 1
        row_mock.idestadovigencia = 1
        row_mock.idcategoria = 2
        row_mock.creacion = date(2026, 1, 1)
        row_mock.derogacion = None
        row_mock.aplicacioninmediata = True
        row_mock.isactive = True
        row_mock.numacuerdo = None
        row_mock.numsesion = None
        row_mock.nombretipodocumento = "Decreto"
        row_mock.estadovigencia = "Vigente"
        row_mock.tipodecision = "Acuerdo"
        row_mock.tiposesion = "Ordinaria"
        mapped = repo._map_row_to_dict(row_mock)
        self.assertEqual(mapped["chunk_id"], 12)
        self.assertAlmostEqual(mapped["score"], 0.85)

        empty_clauses, empty_params = repo._apply_common_filters(None)
        self.assertEqual(empty_clauses, "")
        self.assertEqual(empty_params, {})

        all_filters = {
            "idestadovigencia": 1,
            "idtipodocumento": 2,
            "idtipodecision": 3,
            "idtiposesion": 4,
            "idcategoria": 5,
            "creaciondesde": date(2025, 1, 1),
            "creacionhasta": date(2026, 1, 1),
            "derogaciondesde": date(2026, 2, 1),
            "derogacionhasta": date(2026, 3, 1),
            "aplicacioninmediata": True,
            "isactive": True,
            "idtipopagina": 1,
            "idrecintouniversitario": 10,
            "idcarrera": 20,
            "idbeneficio": 30,
            "idtiponombramiento": 40,
            "iddepartamento": 50,
            "idjornada": 60,
            "idnivel": 70,
            "idrol": 80,
            "idsubarea": 90,
        }
        clauses, params = repo._apply_common_filters(all_filters)
        self.assertIn("d.idestadovigencia =", clauses)
        self.assertIn("documentosedecampus", clauses)
        self.assertIn("areaemisora", clauses)
        self.assertEqual(params["sede"], 10)
        self.assertEqual(params["sub_area"], 90)

    @patch("app.repositories.vector_repository.get_session")
    async def test_10_vector_repo_save_chunk(self, mock_get_session):
        """VectorRepository.save_chunk inserta embedding y metadatos de citación legal."""
        repo = VectorRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        chunk = await repo.save_chunk(
            document_id=101,
            chunk_index=0,
            chunk_text="Artículo 1. Objeto de la norma.",
            vector=[0.1, 0.2, 0.3],
            numero_pagina=1,
            secuencia=1,
            hash_sha256="abc123hash",
            nombre_titulo="Título I",
            numero_articulo="1",
            numero_inciso="1",
            id_tipo_pagina=2,
        )
        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.textofragmento, "Artículo 1. Objeto de la norma.")
        self.assertTrue(mock_session.commit.called)

    @patch("app.repositories.vector_repository.get_session")
    async def test_11_vector_repo_similarity_and_filter_search(self, mock_get_session):
        """VectorRepository similarity_search y filter_only_search."""
        repo = VectorRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        row_mock = MagicMock()
        row_mock.iddocumento = uuid4()
        row_mock.idchunk = 1
        row_mock.textofragmento = "Fragmento de prueba"
        row_mock.score = 0.92
        mock_res = MagicMock()
        mock_res.fetchall.return_value = [row_mock]
        mock_session.execute.return_value = mock_res

        sim_results = await repo.similarity_search(
            vector=[0.1] * 768,
            top_k=5,
            filters={"idestadovigencia": 1},
        )
        self.assertEqual(len(sim_results), 1)
        self.assertEqual(sim_results[0]["chunk_id"], 1)

        filter_results = await repo.filter_only_search(
            top_k=5,
            filters={"idcategoria": 2},
        )
        self.assertEqual(len(filter_results), 1)

    @patch("app.repositories.vector_repository.get_session")
    async def test_12_vector_repo_hybrid_search(self, mock_get_session):
        """VectorRepository.hybrid_search combina pgvector y tsvector con pesos configurables."""
        repo = VectorRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        chunk_id_1 = 101
        chunk_id_2 = 102

        sim_res = [
            {"chunk_id": chunk_id_1, "score": 0.9, "texto_fragmento": "Doc 1"},
        ]
        repo.similarity_search = AsyncMock(return_value=sim_res)

        ts_row_1 = MagicMock()
        ts_row_1.idchunk = chunk_id_1
        ts_row_1.ts_score = 0.8
        ts_row_2 = MagicMock()
        ts_row_2.idchunk = chunk_id_2
        ts_row_2.iddocumento = uuid4()
        ts_row_2.textofragmento = "Doc 2"
        ts_row_2.numeropagina = 1
        ts_row_2.secuencia = 1
        ts_row_2.numero = "99"
        ts_row_2.titulo = "Doc 2 Titulo"
        ts_row_2.nommetadato = "Doc 2 Meta"
        ts_row_2.ts_score = 0.5

        mock_ts_result = MagicMock()
        mock_ts_result.fetchall.return_value = [ts_row_1, ts_row_2]
        mock_session.execute.return_value = mock_ts_result

        hybrid_results = await repo.hybrid_search(
            query_text="reglamento académico",
            vector=[0.1] * 768,
            top_k=5,
            filters={"isactive": True},
            vector_weight=0.7,
            tsvector_weight=0.3,
        )
        self.assertEqual(len(hybrid_results), 2)
        self.assertIn("score", hybrid_results[0])

    # ─────────────────────────────────────────────────────────────────────────
    # 4. DocumentRepository (SP Errors, CRUD, Filtering, Catalogs & Helpers)
    # ─────────────────────────────────────────────────────────────────────────

    def test_13_document_repo_handle_sp_error(self):
        """DocumentRepository._handle_sp_error clasifica excepciones del SP de documentos."""
        repo = DocumentRepository()
        doc_id = "doc-uuid-123"

        with self.assertRaises(DocumentNotFoundError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: No se encontró el documento"), doc_id)
        with self.assertRaises(UniqueConstraintError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: Unicidad: Número duplicado"), doc_id)
        with self.assertRaises(DAGCycleError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: Violación de Grafo Acíclico (DAG)"), doc_id)
        with self.assertRaises(CatalogNotFoundError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: Catálogo: Carrera inexistente"), doc_id)
        with self.assertRaises(AppValidationError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: Validación: Fecha incorrecta"), doc_id)
        with self.assertRaises(AppValidationError):
            repo._handle_sp_error(RuntimeError("RaiseError'>: Parámetro: ID vacío"), doc_id)
        with self.assertRaises(DatabaseError):
            repo._handle_sp_error(RuntimeError("Fallo inesperado"), doc_id)

    def test_14_document_repo_helpers(self):
        """DocumentRepository helpers: _parse_categorias, _map_doc_row, _add_in_clause, _build_documento_detail."""
        repo = DocumentRepository()

        # _parse_categorias
        self.assertEqual(repo._parse_categorias({}), [])
        self.assertEqual(repo._parse_categorias(None), [])
        self.assertEqual(repo._parse_categorias({"categoria": {}}), [])

        cat_data = {
            "categoria": {"id": 1, "nombre": "Académica"},
            "macrocategoria": {"id": 10, "nombre": "Institucional"},
        }
        res = repo._parse_categorias(cat_data)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].nombrecategoria, "Académica")
        self.assertEqual(res[0].macrocategoria, "Institucional")

        # _map_doc_row
        row_mock = MagicMock()
        row_mock.iddocumento = uuid4()
        row_mock.numero = "123"
        row_mock.titulo = "Titulo Doc"
        row_mock.nommetadato = "Meta Doc"
        row_mock.isactive = True
        mapped = repo._map_doc_row(row_mock, score=0.99)
        self.assertEqual(mapped["titulo"], "Titulo Doc")
        self.assertAlmostEqual(mapped["score"], 0.99)

        # _add_in_clause
        clauses = []
        params = {}
        repo._add_in_clause(clauses, params, "col_single", "param1", 42)
        self.assertIn("col_single = :param1", clauses)
        self.assertEqual(params["param1"], 42)

        repo._add_in_clause(clauses, params, "col_multi", "param2", [1, 2, 3])
        self.assertIn("col_multi = ANY(:param2)", clauses)
        self.assertEqual(params["param2"], [1, 2, 3])

        # _build_documento_detail
        raw_detail = {
            "documento": {
                "iddocumento": str(uuid4()),
                "numero": "456",
                "titulo": "Reglamento Detalle",
                "nommetadato": "Reglamento Detalle",
                "isactive": True,
                "cant_paginas": 10,
            },
            "categoria": {"id": 1, "nombre": "Docente"},
            "sedes": [{"idrecintouniversitario": 1, "nombrerecinto": "Central"}],
        }
        built_detail = repo._build_documento_detail(raw_detail, "doc-test-123")
        self.assertEqual(built_detail.numero, "456")
        self.assertEqual(built_detail.titulo, "Reglamento Detalle")

    @patch("app.repositories.document_repository.get_session")
    async def test_15_document_repo_get_s3_key_and_raw_detail(self, mock_get_session):
        """get_s3_key y get_raw_detail."""
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        # S3 key found
        doc_uuid = uuid4()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = "documents/norma.pdf"
        mock_session.execute.return_value = mock_res
        s3_key = await repo.get_s3_key(str(doc_uuid))
        self.assertEqual(s3_key, "documents/norma.pdf")

        # S3 key not found
        mock_res.scalar_one_or_none.return_value = None
        with self.assertRaises(DocumentNotFoundError):
            await repo.get_s3_key(str(doc_uuid))

        # Raw detail UUID inválido
        with self.assertRaises(DocumentNotFoundError):
            await repo.get_raw_detail("not-a-uuid")

        # Raw detail found
        raw_json = json.dumps({"iddocumento": str(doc_uuid), "titulo": "Detalle Auditoría"})
        mock_scalar_res = MagicMock()
        mock_scalar_res.scalar.return_value = raw_json
        mock_session.execute.return_value = mock_scalar_res
        detail = await repo.get_raw_detail(str(doc_uuid))
        self.assertEqual(detail["titulo"], "Detalle Auditoría")

        # Raw detail not found
        mock_scalar_res.scalar.return_value = None
        with self.assertRaises(DocumentNotFoundError):
            await repo.get_raw_detail(str(doc_uuid))

    @patch("app.repositories.document_repository.get_session")
    async def test_16_document_repo_get_by_id_and_list_documents(self, mock_get_session):
        """get_by_id y list_documents."""
        repo = DocumentRepository()
        doc_uuid = uuid4()

        # get_by_id found
        raw_data = {
            "documento": {
                "iddocumento": str(doc_uuid),
                "numero": "123",
                "titulo": "Reglamento",
                "nommetadato": "Reglamento",
                "isactive": True,
            }
        }
        repo.get_raw_detail = AsyncMock(return_value=raw_data)
        doc_detail = await repo.get_by_id(str(doc_uuid))
        self.assertEqual(doc_detail.titulo, "Reglamento")

        # list_documents
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        doc_db = MagicMock()
        doc_db.iddocumento = doc_uuid
        doc_db.numero = "123"
        doc_db.titulo = "Reglamento"
        doc_db.nommetadato = "Reglamento"
        doc_db.tipodocumento = None
        doc_db.tipodecision = None
        doc_db.tiposesion = None
        doc_db.estadovigencia = None
        doc_db.numacuerdo = None
        doc_db.numsesion = None
        doc_db.descripcion = None
        doc_db.creacion = None
        doc_db.derogacion = None
        doc_db.aplicacioninmediata = None
        doc_db.isactive = True
        doc_db.ultima_modificacion = None
        doc_db.urlarchivooriginals3 = None

        mock_res_list = MagicMock()
        mock_res_list.scalars.return_value.all.return_value = [doc_db]
        mock_session.execute.return_value = mock_res_list
        docs = await repo.list_documents(skip=0, limit=10)
        self.assertEqual(len(docs), 1)

    @patch("app.repositories.document_repository.get_session")
    async def test_17_document_repo_update_and_toggle_active(self, mock_get_session):
        """update y toggle_active."""
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        doc_uuid = uuid4()
        repo.get_by_id = AsyncMock()

        # Update exitoso
        update_data = DocumentoUpdate(titulo="Título Modificado")
        await repo.update(str(doc_uuid), update_data)
        self.assertTrue(mock_session.execute.called)
        self.assertTrue(mock_session.commit.called)

        # Update con fallo de SP
        mock_session.execute.side_effect = RuntimeError("RaiseError'>: Catálogo: No existe")
        with self.assertRaises(CatalogNotFoundError):
            await repo.update(str(doc_uuid), update_data)

        # Toggle active UUID inválido
        with self.assertRaises(DocumentNotFoundError):
            await repo.toggle_active("invalido")

        # Toggle active exitoso
        mock_session.execute.side_effect = None
        await repo.toggle_active(str(doc_uuid))
        self.assertTrue(mock_session.execute.called)
        self.assertTrue(mock_session.commit.called)

    @patch("app.repositories.document_repository.get_session")
    async def test_18_document_repo_get_editable_by_id(self, mock_get_session):
        """get_editable_by_id retorna DocumentoEditableOut o lanza DocumentNotFoundError."""
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        doc_uuid = uuid4()
        doc = Documento(
            iddocumento=doc_uuid,
            numero="456",
            titulo="Editable Doc",
            nommetadato="Editable Doc",
            isactive=True,
            cantpaginas=3,
        )
        doc.sedes = []
        doc.carreras = []
        doc.beneficios = []
        doc.nombramientos = []
        doc.departamentos = []
        doc.jornadas = []
        doc.niveles = []
        doc.roles = []
        doc.areas_emisoras = []

        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = doc
        mock_session.execute.return_value = mock_res

        editable = await repo.get_editable_by_id(str(doc_uuid))
        self.assertEqual(editable.titulo, "Editable Doc")

        # Not found
        mock_res.scalar_one_or_none.return_value = None
        with self.assertRaises(DocumentNotFoundError):
            await repo.get_editable_by_id(str(doc_uuid))

    @patch("app.repositories.document_repository.get_session")
    async def test_19_document_repo_filter_and_lexical_search(self, mock_get_session):
        """filter_only_search y lexical_search en DocumentRepository."""
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        doc_uuid = uuid4()
        row_mock = MagicMock()
        row_mock.iddocumento = doc_uuid
        row_mock.numero = "777"
        row_mock.titulo = "Doc Filtro"
        row_mock.nommetadato = "Doc Filtro"
        row_mock.score = 1.0
        row_mock.full_count = 1

        mock_res = MagicMock()
        mock_res.fetchall.return_value = [row_mock]
        mock_session.execute.return_value = mock_res

        docs, total = await repo.filter_only_search(
            page=1,
            page_size=10,
            filters={"isactive": True},
        )
        self.assertEqual(total, 1)
        self.assertEqual(len(docs), 1)

        # lexical_search
        lex_docs, lex_total = await repo.lexical_search(
            query_text="reglamento",
            page=1,
            page_size=10,
            filters={"idestadovigencia": 1},
        )
        self.assertEqual(lex_total, 1)
        self.assertEqual(len(lex_docs), 1)

    @patch("app.repositories.document_repository.get_session")
    @patch.object(DocumentRepository, "_fetch_options_part1", new_callable=AsyncMock)
    @patch.object(DocumentRepository, "_fetch_options_part2", new_callable=AsyncMock)
    async def test_20_document_repo_catalogs_and_lexical_suggestions(
        self, mock_fetch_p2, mock_fetch_p1, mock_get_session
    ):
        """get_filter_options y get_lexical_suggestions."""
        repo = DocumentRepository()

        # Mock catalogs via _fetch_options_part1 and part2
        mock_fetch_p1.return_value = {
            "tipos_area": [],
            "macro_categorias": [],
            "tipos_documento": [FilterOption(id=1, nombre="Decreto")],
            "estados_vigencia": [FilterOption(id=1, nombre="Vigente")],
            "respaldos_legales": [],
            "roles": [],
            "beneficios": [],
            "sedes": [FilterOption(id=1, nombre="Casa Central")],
            "tipos_nombramiento": [],
            "jornadas": [],
        }
        mock_fetch_p2.return_value = {
            "tipos_programa": [],
            "departamentos": [],
            "tipos_sesion": [],
            "tipos_decision": [],
            "tipos_relacion": [],
            "fuentes_deteccion": [],
            "sub_areas": [],
            "categorias": [FilterOption(id=1, nombre="Académica")],
            "niveles_academicos": [],
            "carreras": [],
        }

        options = await repo.get_filter_options(only_active_tipos_documento=True)
        self.assertEqual(options.tipos_documento[0].nombre, "Decreto")
        self.assertEqual(options.categorias[0].nombre, "Académica")

        # Mock lexical suggestions
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        sug_row = MagicMock()
        sug_row.iddocumento = uuid4()
        sug_row.numero = "100"
        sug_row.titulo = "Reglamento General"
        sug_row.nommetadato = "Reglamento"
        sug_row.matched_field = "titulo"
        sug_row.similarity = 0.8

        mock_res = MagicMock()
        mock_res.fetchall.return_value = [sug_row]
        mock_session.execute.return_value = mock_res

        suggestions = await repo.get_lexical_suggestions("reg", limit=5)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["suggestion"], "Reglamento General")

    # ─────────────────────────────────────────────────────────────────────────
    # 5. TrazabilidadRepository & DocumentRepository._build_documento_detail
    # ─────────────────────────────────────────────────────────────────────────

    def test_21_trazabilidad_repo_handle_sp_error_and_detail_parsing(self):
        """TrazabilidadRepository._handle_sp_error clasifica 23503/FK/Validación y DocumentRepository parsea trazabilidad."""
        repo = TrazabilidadRepository()
        doc_id = str(uuid4())

        # SQLSTATE 23503 en .orig
        class OrigFKError(object):
            sqlstate = "23503"

            def __str__(self) -> str:
                return "insert or update on table documentotrazabilidad violates foreign key constraint"

        class WrappedFKException(Exception):
            orig = OrigFKError()

        with self.assertRaises(DocumentNotFoundError):
            repo._handle_sp_error(WrappedFKException(), doc_id)

        with self.assertRaises(DocumentNotFoundError):
            repo._handle_sp_error(RuntimeError("RaiseException'>: No se encontró el documento"), doc_id)

        with self.assertRaises(AppValidationError):
            repo._handle_sp_error(RuntimeError("RaiseException'>: Validación: JSONB malformado"), doc_id)

        with self.assertRaises(DatabaseError):
            repo._handle_sp_error(RuntimeError("Fallo interno en disco"), doc_id)

        # DocumentRepository._build_documento_detail hidrata trazabilidad desde fn_obtener_documento_detalle
        raw_jsonb = {
            "documento": {
                "iddocumento": doc_id,
                "numero": "056/2026",
                "titulo": "Reglamento Actualizado",
                "nommetadato": "GI-01-08",
                "cant_paginas": 12,
                "isactive": True,
                "tipodocumento": {"id": 2, "nombre": "Decreto"},
                "estadovigencia": {"id": 1, "nombre": "Vigente"},
            },
            "trazabilidad": {
                "cant_antes": 1,
                "cant_despues": 1,
                "ultima_sincronizacion": "2026-11-02T22:05:55+00:00",
                "antes": [
                    {
                        "decreto": "DECRETO 014/1993",
                        "fecha": "1993-04-01",
                        "anio": 1993,
                        "nombre_archivo": "Decreto_14-93.md",
                    }
                ],
                "despues": [
                    {
                        "decreto": "DECRETO 057/2025",
                        "fecha": "2025-01-20",
                        "anio": 2025,
                        "nombre_archivo": None,
                    }
                ],
            },
        }
        detail = DocumentRepository._build_documento_detail(raw_jsonb, doc_id)
        self.assertEqual(detail.trazabilidad.cant_antes, 1)
        self.assertEqual(detail.trazabilidad.cant_despues, 1)
        self.assertEqual(detail.trazabilidad.antes[0].decreto, "DECRETO 014/1993")
        self.assertIsNone(detail.trazabilidad.despues[0].nombre_archivo)

    @patch("app.repositories.trazabilidad_repository.get_session")
    async def test_22_trazabilidad_repo_get_upsert_and_delete(self, mock_get_session):
        """get_by_document_id, upsert_via_sp y delete_via_sp en TrazabilidadRepository."""
        repo = TrazabilidadRepository()
        doc_uuid = uuid4()

        # UUID inválido lanza DocumentNotFoundError
        with self.assertRaises(DocumentNotFoundError):
            await repo.get_by_document_id("uuid-invalido")
        with self.assertRaises(DocumentNotFoundError):
            await repo.upsert_via_sp("uuid-invalido", TrazabilidadUpsertRequest())
        with self.assertRaises(DocumentNotFoundError):
            await repo.delete_via_sp("uuid-invalido")

        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        sample_payload = {
            "iddocumento": str(doc_uuid),
            "numero": "056/2026",
            "titulo": "DECRETO 056/2026",
            "nommetadato": "GI-01-08",
            "estadovigencia": "Vigente",
            "trazabilidad": {
                "cant_antes": 1,
                "cant_despues": 0,
                "ultima_sincronizacion": "2026-11-02T22:05:55+00:00",
                "antes": [
                    {
                        "decreto": "DECRETO 001/1982",
                        "fecha": "1982-03-19",
                        "anio": 1982,
                        "nombre_archivo": None,
                    }
                ],
                "despues": [],
            },
        }

        # GET con string JSON retornado por el driver
        mock_res = MagicMock()
        mock_res.scalar.return_value = json.dumps(sample_payload)
        mock_session.execute.return_value = mock_res

        out = await repo.get_by_document_id(doc_uuid)
        self.assertEqual(out.numero, "056/2026")
        self.assertEqual(out.trazabilidad.cant_antes, 1)
        self.assertIsNone(out.trazabilidad.antes[0].nombre_archivo)

        # GET documento no encontrado (NULL)
        mock_res.scalar.return_value = None
        with self.assertRaises(DocumentNotFoundError):
            await repo.get_by_document_id(doc_uuid)

        # UPSERT exitoso (CALL + commit + re-lectura)
        mock_call_res = MagicMock()
        mock_get_res = MagicMock()
        mock_get_res.scalar.return_value = sample_payload
        mock_session.execute.side_effect = [mock_call_res, mock_get_res]

        req = TrazabilidadUpsertRequest(
            antes=[HitoNormativo(decreto="DECRETO 001/1982", fecha="1982-03-19", anio=1982, nombre_archivo=None)],
            despues=[],
        )
        upserted = await repo.upsert_via_sp(doc_uuid, req)
        self.assertEqual(upserted.trazabilidad.cant_antes, 1)
        self.assertTrue(mock_session.commit.called)

        # DELETE exitoso
        mock_session.execute.side_effect = None
        mock_session.execute.return_value = MagicMock()
        del_res = await repo.delete_via_sp(doc_uuid)
        self.assertEqual(del_res["status"], "ok")
        self.assertEqual(del_res["iddocumento"], str(doc_uuid))

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Requirement R4: Search Wildcard Sanitization & LIKE / ILIKE Escaping
    # ─────────────────────────────────────────────────────────────────────────

    def test_23_document_repo_escape_like_wildcards_unit(self):
        """Prueba unitaria exhaustiva para _escape_like_wildcards y su alias."""
        repo = DocumentRepository()

        # Input normal sin comodines
        self.assertEqual(repo._escape_like_wildcards("Reglamento 2026"), "Reglamento 2026")
        self.assertEqual(DocumentRepository._escape_like_wildcards("abc-123"), "abc-123")

        # Comodín %
        self.assertEqual(repo._escape_like_wildcards("100%"), "100\\%")
        self.assertEqual(repo._escape_like_wildcards("%"), "\\%")

        # Comodín _
        self.assertEqual(repo._escape_like_wildcards("doc_1"), "doc\\_1")
        self.assertEqual(repo._escape_like_wildcards("_"), "\\_")

        # Carácter de escape \
        self.assertEqual(repo._escape_like_wildcards("path\\to\\file"), "path\\\\to\\\\file")
        self.assertEqual(repo._escape_like_wildcards("\\"), "\\\\")

        # Combinación de todos los comodines: \ % _
        self.assertEqual(
            repo._escape_like_wildcards("100%_val\\done"),
            "100\\%\\_val\\\\done",
        )
        self.assertEqual(
            repo._escape_like_wildcards("C:\\test\\100%_doc.pdf"),
            "C:\\\\test\\\\100\\%\\_doc.pdf",
        )

        # Cadenas vacías o nulas
        self.assertEqual(repo._escape_like_wildcards(""), "")
        self.assertEqual(repo._escape_like_wildcards(None), "")

        # Alias público
        self.assertEqual(
            DocumentRepository.escape_like_wildcards("test_%\\"),
            "test\\_\\%\\\\",
        )

    @patch("app.repositories.document_repository.get_session")
    async def test_24_document_repo_lexical_search_wildcard_escaping(self, mock_get_session):
        """Verifica que lexical_search escape comodines %, _ y \\, incluya ESCAPE '\\' y mantenga exact_query."""
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        row_mock = MagicMock()
        row_mock.iddocumento = uuid4()
        row_mock.numero = "100"
        row_mock.titulo = "Reglamento 100%_Norma\\2026"
        row_mock.nommetadato = "Reglamento"
        row_mock.match_boost = 100.0
        row_mock.full_count = 1

        mock_res = MagicMock()
        mock_res.fetchall.return_value = [row_mock]
        mock_session.execute.return_value = mock_res

        raw_query = "100%_Norma\\2026"
        results = await repo.lexical_search(query_text=raw_query, top_k=5)

        self.assertEqual(len(results), 1)
        self.assertTrue(mock_session.execute.called)

        # Verificar parámetros y consulta SQL
        call_args = mock_session.execute.call_args
        sql_stmt = str(call_args[0][0].text)
        params = call_args[0][1]

        # Comprobar que exact_query NO está escapado (para chequeo exacto de igualdad)
        self.assertEqual(params["exact_query"], raw_query)

        # Comprobar que starts_query y like_query SÍ están debidamente escapados
        self.assertEqual(params["starts_query"], "100\\%\\_Norma\\\\2026%")
        self.assertEqual(params["like_query"], "%100\\%\\_Norma\\\\2026%")

        # Comprobar que todas las cláusulas LIKE / ILIKE especifican ESCAPE '\\'
        self.assertIn("LIKE LOWER(:starts_query) ESCAPE '\\'", sql_stmt)
        self.assertIn("LIKE LOWER(:like_query) ESCAPE '\\'", sql_stmt)
        self.assertIn("ILIKE :like_query ESCAPE '\\'", sql_stmt)

    @patch("app.repositories.document_repository.get_session")
    async def test_25_document_repo_lexical_suggestions_wildcard_escaping(self, mock_get_session):
        """Verifica que get_lexical_suggestions escape comodines %, _ y \\, e incluya ESCAPE '\\'."""
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        sug_row = MagicMock()
        sug_row.iddocumento = uuid4()
        sug_row.numero = "101"
        sug_row.titulo = "Manual_10%_v1"
        sug_row.nommetadato = "Manual_10%_v1"
        sug_row.matched_field = "titulo"

        mock_res = MagicMock()
        mock_res.fetchall.return_value = [sug_row]
        mock_session.execute.return_value = mock_res

        raw_term = "Manual_10%_v1\\test"
        suggestions = await repo.get_lexical_suggestions(raw_term, limit=5)

        self.assertEqual(len(suggestions), 1)
        self.assertTrue(mock_session.execute.called)

        call_args = mock_session.execute.call_args
        sql_stmt = str(call_args[0][0].text)
        params = call_args[0][1]

        # Comprobar que contains está debidamente escapado
        self.assertEqual(params["contains"], "%Manual\\_10\\%\\_v1\\\\test%")

        # Comprobar cláusulas ILIKE con ESCAPE '\\'
        self.assertIn("ILIKE :contains ESCAPE '\\'", sql_stmt)

    def test_26_document_repo_wildcard_literal_matching_in_sqlite(self):
        """Verifica coincidencia literal sin expansión indebida de comodines en un motor SQL real."""
        import sqlite3

        con = sqlite3.connect(":memory:")
        cur = con.cursor()
        cur.execute("CREATE TABLE documento (id INTEGER PRIMARY KEY, titulo TEXT)")
        cur.executemany(
            "INSERT INTO documento (id, titulo) VALUES (?, ?)",
            [
                (1, "Reglamento 100% Vigente"),
                (2, "Reglamento 1000 Vigente"),
                (3, "Doc_1 Version Final"),
                (4, "Doc-1 Version Final"),
                (5, "DocA1 Version Final"),
                (6, "Norma\\Subdirectorio\\Manual"),
                (7, "NormaXSubdirectorioXManual"),
            ],
        )
        con.commit()

        # 1. Búsqueda con '%': Solo debe coincidir '100% Vigente', NO '1000 Vigente'
        term_pct = "100%"
        escaped_pct = DocumentRepository._escape_like_wildcards(term_pct)
        pattern_pct = f"%{escaped_pct}%"
        cur.execute("SELECT id, titulo FROM documento WHERE titulo LIKE ? ESCAPE '\\'", (pattern_pct,))
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(rows[0][1], "Reglamento 100% Vigente")

        # 2. Búsqueda con '_': Solo debe coincidir 'Doc_1', NO 'Doc-1' ni 'DocA1'
        term_und = "Doc_1"
        escaped_und = DocumentRepository._escape_like_wildcards(term_und)
        pattern_und = f"%{escaped_und}%"
        cur.execute("SELECT id, titulo FROM documento WHERE titulo LIKE ? ESCAPE '\\'", (pattern_und,))
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 3)
        self.assertEqual(rows[0][1], "Doc_1 Version Final")

        # 3. Búsqueda con '\\': Solo debe coincidir 'Norma\\Subdirectorio', NO 'NormaXSubdirectorio'
        term_slash = "Norma\\Subdirectorio"
        escaped_slash = DocumentRepository._escape_like_wildcards(term_slash)
        pattern_slash = f"%{escaped_slash}%"
        cur.execute("SELECT id, titulo FROM documento WHERE titulo LIKE ? ESCAPE '\\'", (pattern_slash,))
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 6)
        self.assertEqual(rows[0][1], "Norma\\Subdirectorio\\Manual")

        con.close()
