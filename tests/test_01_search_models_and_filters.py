"""
Suite 1: Validación de contratos DTO y Filtrado Facetado (RF-03, RF-05).
"""

from datetime import date
import unittest
from pydantic import ValidationError as PydanticValidationError

import tests.base  # noqa: F401
from app.models.search_models import SearchFilters, SearchRequest


class TestSuite1SearchModelsAndFacetedFilters(unittest.TestCase):
    """Suite 1: Validación de contratos DTO y Filtrado Facetado (RF-03, RF-05)."""

    def test_01_search_filters_valid_single_and_multi_facets(self):
        """Verifica soporte polimórfico (int y List[int]) en las dimensiones de filtrado facetado."""
        filters = SearchFilters(
            idestadovigencia=1,
            idtipodocumento=[1, 2],
            idrecintouniversitario=[1, 3, 5],
            idcarrera=[10, 20],
            iddepartamento=4,
            creaciondesde="2020-01-01",
            creacionhasta="2025-12-31",
            isactive=True,
        )
        self.assertEqual(filters.idestadovigencia, 1)
        self.assertEqual(filters.idtipodocumento, [1, 2])
        self.assertEqual(filters.idrecintouniversitario, [1, 3, 5])

    def test_02_search_filters_reject_non_positive_ids(self):
        """Verifica que SearchFilters rechace IDs menores o iguales a 0 (individuales o en listas)."""
        with self.assertRaises(PydanticValidationError):
            SearchFilters(idtipodocumento=0)

        with self.assertRaises(PydanticValidationError):
            SearchFilters(idcarrera=[1, -3, 5])

    def test_03_search_filters_reject_inverted_creation_dates(self):
        """Verifica que validate_date_ranges rechace creaciondesde > creacionhasta (HTTP 422)."""
        with self.assertRaises(PydanticValidationError) as ctx:
            SearchFilters(creaciondesde="2025-06-01", creacionhasta="2024-01-01")
        self.assertIn("creaciondesde debe ser menor o igual a creacionhasta", str(ctx.exception))

    def test_04_search_filters_reject_inverted_derogation_dates_and_negative_session(self):
        """Verifica rechazo de derogaciondesde > derogacionhasta y numsesion negativo."""
        with self.assertRaises(PydanticValidationError) as ctx:
            SearchFilters(derogaciondesde=date(2025, 10, 1), derogacionhasta=date(2023, 5, 1))
        self.assertIn("derogaciondesde debe ser menor o igual a derogacionhasta", str(ctx.exception))

        with self.assertRaises(PydanticValidationError):
            SearchFilters(numsesion=-1)

    def test_05_search_request_pagination_bounds(self):
        """Verifica restricciones de frontera en paginación (page >= 1, page_size <= 100)."""
        req = SearchRequest(query="reglamento académico", page=2, page_size=25)
        self.assertEqual(req.page, 2)
        self.assertEqual(req.page_size, 25)

        with self.assertRaises(PydanticValidationError):
            SearchRequest(query="test", page=0)

        with self.assertRaises(PydanticValidationError):
            SearchRequest(query="test", page_size=250)

    def test_06_search_filters_date_range_support_iso_strings_and_date_instances(self):
        """Verifica interoperabilidad de fechas tanto como string ISO como instancias datetime.date."""
        filters_str = SearchFilters(
            creaciondesde="2022-03-01",
            creacionhasta="2022-12-31"
        )
        self.assertEqual(str(filters_str.creaciondesde)[:10], "2022-03-01")
        self.assertEqual(str(filters_str.creacionhasta)[:10], "2022-12-31")

        filters_obj = SearchFilters(
            creaciondesde=date(2022, 3, 1),
            creacionhasta=date(2022, 12, 31)
        )
        self.assertEqual(filters_obj.creaciondesde, date(2022, 3, 1))
        self.assertEqual(filters_obj.creacionhasta, date(2022, 12, 31))

    def test_07_search_filters_confianza_range_bounds(self):
        """Verifica que confianzamin y confianzamax estén estrictamente en el intervalo [0.0, 1.0]."""
        valid_filters = SearchFilters(confianzamin=0.1, confianzamax=0.9)
        self.assertEqual(valid_filters.confianzamin, 0.1)
        self.assertEqual(valid_filters.confianzamax, 0.9)

        with self.assertRaises(PydanticValidationError):
            SearchFilters(confianzamin=-0.05)

        with self.assertRaises(PydanticValidationError):
            SearchFilters(confianzamax=1.05)

    def test_08_search_request_query_max_length_bound(self):
        """Verifica que SearchRequest rechace consultas que excedan el límite de 500 caracteres."""
        valid_req = SearchRequest(query="A" * 500)
        self.assertEqual(len(valid_req.query), 500)

        with self.assertRaises(PydanticValidationError):
            SearchRequest(query="A" * 501)


if __name__ == "__main__":
    unittest.main()
