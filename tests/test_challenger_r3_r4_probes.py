"""
Adversarial Verification & Stress Harness: Requirements R3 and R4
Author: teamwork_challenger_2 (Empirical Challenger)

Authoritative Requirements:
- R3: Production Database Error Redaction (ORIGINAL_REQUEST.md §R3, PROJECT.md §R3.1)
  - Verify that when APP_ENV="production", NO raw SQL queries, column names, table names,
    connection strings, or credentials leak in response body.
  - Verify synthetic requests missing "app" key in ASGI scope fail safely without raising KeyError.
- R4: Search Wildcard Sanitization (ORIGINAL_REQUEST.md §R4, PROJECT.md §R4.1)
  - Inject complex wildcard patterns ("%", "_", "%%", "__", "%_%_\\%_\\_%", "\\") into lexical_search
    and get_lexical_suggestions.
  - Verify literal matching without broadening the search or causing SQL syntax errors.
  - Verify exact_query equality match works as expected.
"""

import json
import sqlite3
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import Request
from sqlalchemy.exc import (
    DataError,
    DatabaseError,
    IntegrityError,
    InternalError,
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)

import tests.base  # noqa: F401 - test environment setup
from app.core.config import settings
from app.core.middleware import (
    _is_development,
    general_exception_handler,
    sqlalchemy_exception_handler,
)
from app.repositories.document_repository import DocumentRepository


class TestChallengerR3ProductionDatabaseErrorRedaction(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial Stress Test Suite for Requirement R3 (Production Database Error Redaction).
    Tests for information leakage, credential exposure, and ASGI scope resilience.
    """

    def setUp(self):
        super().setUp()
        self.sensitive_database_errors = [
            (
                "PostgreSQL Syntax Error leaking confidential schema and query",
                ProgrammingError(
                    statement="SELECT ssn, credit_card_num, cvv_hash, master_password FROM users_vault WHERE email = 'ceo@usm.cl'",
                    params={"email": "ceo@usm.cl"},
                    orig=Exception(
                        "psycopg2.errors.SyntaxError: syntax error at or near 'ssn' "
                        "[SQL: SELECT ssn, credit_card_num, cvv_hash, master_password FROM users_vault WHERE email = 'ceo@usm.cl']"
                    ),
                ),
                ["ssn", "credit_card_num", "cvv_hash", "master_password", "users_vault", "ceo@usm.cl"],
            ),
            (
                "PostgreSQL Unique Violation leaking secret API keys",
                IntegrityError(
                    statement="INSERT INTO api_tokens (token_id, secret_jwt_token) VALUES ('tok-1', 'sk_live_supersecret_key_9999')",
                    params={"token_id": "tok-1", "secret_jwt_token": "sk_live_supersecret_key_9999"},
                    orig=Exception(
                        "(psycopg2.errors.UniqueViolation) duplicate key value violates unique constraint 'tokens_pkey'\n"
                        "DETAIL: Key (secret_jwt_token)=(sk_live_supersecret_key_9999) already exists."
                    ),
                ),
                ["sk_live_supersecret_key_9999", "secret_jwt_token", "tokens_pkey", "INSERT INTO api_tokens"],
            ),
            (
                "PostgreSQL Foreign Key Violation leaking internal accounts",
                IntegrityError(
                    statement="INSERT INTO transactions (acct_id, amount) VALUES ('private_bank_acct_888', 5000000)",
                    params={"acct_id": "private_bank_acct_888", "amount": 5000000},
                    orig=Exception(
                        "insert or update on table 'transactions' violates foreign key constraint 'fk_secret_acct'\n"
                        "DETAIL: Key (acct_id)=(private_bank_acct_888) is not present in table 'accounts'."
                    ),
                ),
                ["private_bank_acct_888", "fk_secret_acct", "5000000", "transactions"],
            ),
            (
                "PostgreSQL Operational Error leaking database connection URI and plaintext password",
                OperationalError(
                    statement="SELECT 1",
                    params={},
                    orig=Exception(
                        "could not connect to server: connection to server at '10.240.15.89', port 5432 failed: "
                        "FATAL: password authentication failed for user 'db_superuser_adm', "
                        "password: 'SuperSecretDBPassword!2026#' in URI 'postgresql://db_superuser_adm:SuperSecretDBPassword!2026#@10.240.15.89:5432/giru_db'"
                    ),
                ),
                ["SuperSecretDBPassword!2026#", "db_superuser_adm", "10.240.15.89", "giru_db"],
            ),
            (
                "PostgreSQL DataError leaking internal binary dump or private customer data",
                DataError(
                    statement="UPDATE customers SET national_id = 'CHILE_ID_99887766K' WHERE id = 1",
                    params={"national_id": "CHILE_ID_99887766K", "id": 1},
                    orig=Exception(
                        "value too long for type character varying(8): 'CHILE_ID_99887766K' in table 'customers'"
                    ),
                ),
                ["CHILE_ID_99887766K", "customers", "UPDATE customers"],
            ),
            (
                "PostgreSQL InternalError leaking backend deadlocks and memory addresses",
                InternalError(
                    statement="VACUUM FULL confidential_records",
                    params={},
                    orig=Exception(
                        "internal worker crash at memory address 0x7fffbeef1234 on relation confidential_records"
                    ),
                ),
                ["0x7fffbeef1234", "confidential_records", "VACUUM FULL"],
            ),
            (
                "Generic DatabaseError with arbitrary internal diagnostics",
                DatabaseError(
                    statement="SELECT secret_salt FROM auth_salts",
                    params={},
                    orig=Exception("asyncpg.InternalServerError: disk failure on volume /var/lib/postgresql/secret_data"),
                ),
                ["secret_salt", "auth_salts", "/var/lib/postgresql/secret_data"],
            ),
        ]

    async def test_r3_adv_01_sqlalchemy_handler_production_blocks_all_sensitive_leakage(self):
        """
        Adversarially probe: In APP_ENV="production", verify that under ALL categories of database errors
        (syntax error, unique constraint, foreign key, connection/auth failure, data error, internal error),
        zero raw SQL queries, column names, passwords, or connection strings leak in response body.
        """
        scope_prod = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/documents",
            "headers": [],
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="production")),
        }
        request = Request(scope_prod)
        request.state.request_id = "req-challenger-prod-r3"

        for desc, exc, sensitive_tokens in self.sensitive_database_errors:
            with self.subTest(description=desc):
                response = await sqlalchemy_exception_handler(request, exc)
                self.assertEqual(
                    response.status_code,
                    500,
                    f"Expected HTTP 500 for {desc}, got {response.status_code}",
                )

                raw_body = response.body.decode("utf-8")
                body_json = json.loads(raw_body)

                # Verify response structure
                self.assertEqual(body_json.get("error"), "database_error")
                self.assertEqual(body_json.get("message"), "Error en la base de datos")
                self.assertEqual(
                    body_json.get("details"),
                    {},
                    f"Information leak detected in details for {desc}: {body_json.get('details')}",
                )
                self.assertEqual(body_json.get("request_id"), "req-challenger-prod-r3")

                # Adversarial verification: scan raw payload byte-by-byte for sensitive tokens
                for token in sensitive_tokens:
                    self.assertNotIn(
                        token,
                        raw_body,
                        f"CRITICAL VULNERABILITY: Sensitive token '{token}' leaked in production response body for {desc}",
                    )

    async def test_r3_adv_02_general_handler_production_blocks_all_sensitive_leakage(self):
        """
        Adversarially probe: In APP_ENV="production", verify that general_exception_handler
        redacts details and never leaks internal exceptions or sensitive data.
        """
        scope_prod = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/query",
            "headers": [],
            "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV="production")),
        }
        request = Request(scope_prod)
        request.state.request_id = "req-challenger-general-r3"

        sensitive_exc = RuntimeError(
            "Fatal database crash: user 'prod_admin', password 'SuperSecret123!' failed to bind to 10.0.0.1:5432"
        )
        response = await general_exception_handler(request, sensitive_exc)
        self.assertEqual(response.status_code, 500)

        raw_body = response.body.decode("utf-8")
        body_json = json.loads(raw_body)

        self.assertEqual(body_json.get("error"), "internal_error")
        self.assertEqual(body_json.get("details"), {})
        self.assertNotIn("SuperSecret123!", raw_body)
        self.assertNotIn("prod_admin", raw_body)
        self.assertNotIn("10.0.0.1", raw_body)

    async def test_r3_adv_03_non_development_environments_default_to_redaction(self):
        """
        Adversarially probe: Any environment name other than literal lowercase 'development'
        (e.g., staging, test, testing, qa, uat, PRODUCTION, empty string, None) must redact details.
        """
        non_dev_envs = [
            "production",
            "staging",
            "test",
            "testing",
            "qa",
            "uat",
            "pre-prod",
            "PRODUCTION",
            "Development",  # Uppercase D
            "development ",  # Trailing space
            "",
            None,
        ]

        exc = SQLAlchemyError("CRITICAL: SELECT credit_card FROM payments")

        for env in non_dev_envs:
            with self.subTest(env=env):
                scope = {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/v1/docs",
                    "headers": [],
                    "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV=env)),
                }
                request = Request(scope)
                request.state.request_id = f"req-{env}"

                response = await sqlalchemy_exception_handler(request, exc)
                self.assertEqual(response.status_code, 500)

                body = json.loads(response.body.decode("utf-8"))
                self.assertEqual(
                    body.get("details"),
                    {},
                    f"Environment '{env}' failed to redact details: {body.get('details')}",
                )
                self.assertNotIn("credit_card", response.body.decode("utf-8"))

    async def test_r3_adv_04_synthetic_requests_missing_app_key_resilience(self):
        """
        Adversarially probe: Synthetic ASGI requests missing the 'app' key, having malformed scopes,
        or having None/non-standard attributes must fail safely WITHOUT raising KeyError or AttributeError.
        """
        # Valid ASGI scopes missing "app" or having malformed/unconventional app objects
        scopes_missing_app = [
            ("Minimal ASGI HTTP scope without app key", {"type": "http", "method": "GET", "path": "/test", "headers": []}),
            ("Scope with app=None", {"type": "http", "method": "GET", "path": "/test", "headers": [], "app": None}),
            ("Scope with app as string", {"type": "http", "method": "GET", "path": "/test", "headers": [], "app": "invalid_app"}),
            ("Scope with app without state attribute", {"type": "http", "method": "GET", "path": "/test", "headers": [], "app": types.SimpleNamespace()}),
            ("Scope with app.state=None", {"type": "http", "method": "GET", "path": "/test", "headers": [], "app": types.SimpleNamespace(state=None)}),
            ("Scope with app.state without APP_ENV", {"type": "http", "method": "GET", "path": "/test", "headers": [], "app": types.SimpleNamespace(state=types.SimpleNamespace())}),
        ]

        exc = SQLAlchemyError("Synthetic database disconnection")

        for desc, scope in scopes_missing_app:
            with self.subTest(scenario=desc):
                request = Request(scope)
                request.state.request_id = "req-synthetic-safe"

                # 1. When settings.APP_ENV is production -> details MUST be redacted
                with patch.object(settings, "APP_ENV", "production"):
                    resp_prod = await sqlalchemy_exception_handler(request, exc)
                    self.assertEqual(resp_prod.status_code, 500)
                    body_prod = json.loads(resp_prod.body.decode("utf-8"))
                    self.assertEqual(body_prod.get("error"), "database_error")
                    self.assertEqual(body_prod.get("details"), {})
                    self.assertNotIn("Synthetic database disconnection", resp_prod.body.decode("utf-8"))

                # 2. When settings.APP_ENV is development -> fallback exposes details
                with patch.object(settings, "APP_ENV", "development"):
                    resp_dev = await sqlalchemy_exception_handler(request, exc)
                    self.assertEqual(resp_dev.status_code, 500)
                    body_dev = json.loads(resp_dev.body.decode("utf-8"))
                    self.assertEqual(body_dev.get("error"), "database_error")
                    self.assertIn("Synthetic database disconnection", body_dev.get("details", {}).get("detail", ""))

                # 3. Test general_exception_handler as well (zero KeyError)
                with patch.object(settings, "APP_ENV", "production"):
                    resp_gen = await general_exception_handler(request, RuntimeError("General crash"))
                    self.assertEqual(resp_gen.status_code, 500)
                    body_gen = json.loads(resp_gen.body.decode("utf-8"))
                    self.assertEqual(body_gen.get("error"), "internal_error")
                    self.assertEqual(body_gen.get("details"), {})

        # Scopes where app.state.APP_ENV is explicitly defined but non-development (None or 999)
        # These MUST evaluate to non-development and redact details even if settings.APP_ENV is development!
        explicit_non_dev_scopes = [
            ("Scope with app.state.APP_ENV=None", {"type": "http", "method": "GET", "path": "/test", "headers": [], "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV=None))}),
            ("Scope with app.state.APP_ENV non-string integer", {"type": "http", "method": "GET", "path": "/test", "headers": [], "app": types.SimpleNamespace(state=types.SimpleNamespace(APP_ENV=999))}),
        ]
        for desc, scope in explicit_non_dev_scopes:
            with self.subTest(scenario=desc):
                request = Request(scope)
                request.state.request_id = "req-explicit-non-dev"
                # Even if global settings.APP_ENV is development, the explicit scope state overrides and redacts
                with patch.object(settings, "APP_ENV", "development"):
                    resp = await sqlalchemy_exception_handler(request, exc)
                    self.assertEqual(resp.status_code, 500)
                    body = json.loads(resp.body.decode("utf-8"))
                    self.assertEqual(body.get("details"), {}, f"Details leaked for {desc}")

        # Duck-typed request with completely empty scope dict {}
        duck_request = types.SimpleNamespace(
            scope={},
            state=types.SimpleNamespace(request_id="req-duck-empty"),
        )
        with patch.object(settings, "APP_ENV", "production"):
            self.assertFalse(_is_development(duck_request))
            duck_resp = await sqlalchemy_exception_handler(duck_request, exc)
            self.assertEqual(duck_resp.status_code, 500)
            duck_body = json.loads(duck_resp.body.decode("utf-8"))
            self.assertEqual(duck_body.get("details"), {})


class TestChallengerR4SearchWildcardSanitization(unittest.IsolatedAsyncioTestCase):
    """
    Adversarial Stress Test Suite for Requirement R4 (Search Wildcard Sanitization).
    Tests unit wildcard transformation, SQL injection resistance, literal SQL execution,
    and exact_query equality matching.
    """

    def test_r4_adv_01_escape_like_wildcards_adversarial_matrix(self):
        """
        Adversarially probe: Test _escape_like_wildcards against a comprehensive matrix of
        metacharacters, repetition, multi-backslash sequences, and SQL injection syntax.
        """
        matrix = [
            ("%", "\\%"),
            ("_", "\\_"),
            ("%%", "\\%\\%"),
            ("__", "\\_\\_"),
            ("%_%_\\%_\\_%", "\\%\\_\\%\\_\\\\\\%\\_\\\\\\_\\%"),
            ("%_%_\\%_\\_\\%", "\\%\\_\\%\\_\\\\\\%\\_\\\\\\_\\\\\\%"),
            ("\\", "\\\\"),
            ("\\\\\\\\", "\\\\\\\\\\\\\\\\"),
            ("\\%\\_", "\\\\\\%\\\\\\_"),
            ("%_%", "\\%\\_\\%"),
            ("100%_arancel\\test", "100\\%\\_arancel\\\\test"),
            ("", ""),
            (None, ""),
            ("   ", "   "),
            ("normal text without wildcards", "normal text without wildcards"),
            ("Robert'); DROP TABLE documento;--", "Robert'); DROP TABLE documento;--"),
            ("Robert'); DROP TABLE documento;-- %", "Robert'); DROP TABLE documento;-- \\%"),
            ("Resolución_100%_Año_2026", "Resolución\\_100\\%\\_Año\\_2026"),
            ("\\\\\\%\\_\\%\\_", "\\\\\\\\\\\\\\%\\\\\\_\\\\\\%\\\\\\_"),
        ]

        for raw_input, expected in matrix:
            with self.subTest(raw_input=raw_input):
                actual = DocumentRepository._escape_like_wildcards(raw_input)
                self.assertEqual(
                    actual,
                    expected,
                    f"Mismatch for input '{raw_input}': expected '{expected}', got '{actual}'",
                )

    @patch("app.repositories.document_repository.get_session")
    async def test_r4_adv_02_lexical_search_all_wildcard_patterns_parameters_and_sql(self, mock_get_session):
        """
        Adversarially probe: In lexical_search, inject complex wildcard patterns
        ("%", "_", "%%", "__", "%_%_\\%_\\_%", "\\").
        Verify:
        - exact_query retains literal string (NOT escaped) for exact '=' match.
        - starts_query and like_query have escaped wildcards with proper bounding '%'.
        - SQL query text contains ESCAPE '\\' on ALL LIKE/ILIKE clauses.
        """
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        mock_res = MagicMock()
        mock_res.fetchall.return_value = []
        mock_session.execute.return_value = mock_res

        adversarial_patterns = [
            "%",
            "_",
            "%%",
            "__",
            "%_%_\\%_\\_%",
            "\\",
            "\\\\\\\\",
            "100%_arancel\\v1",
        ]

        for pattern in adversarial_patterns:
            mock_session.reset_mock()
            await repo.lexical_search(query_text=pattern, page=1, page_size=10)

            self.assertTrue(mock_session.execute.called)
            call_args = mock_session.execute.call_args
            sql_clause = str(call_args[0][0])
            params = call_args[0][1]

            # 1. exact_query must match literal pattern.strip()
            self.assertEqual(
                params["exact_query"],
                pattern.strip(),
                f"exact_query corrupted for pattern '{pattern}'",
            )

            # 2. starts_query and like_query must contain the escaped pattern
            expected_escaped = DocumentRepository._escape_like_wildcards(pattern.strip())
            self.assertEqual(params["starts_query"], f"{expected_escaped}%")
            self.assertEqual(params["like_query"], f"%{expected_escaped}%")

            # 3. ESCAPE '\\' clause must be present on LIKE/ILIKE expressions
            self.assertIn("LIKE LOWER(:starts_query) ESCAPE '\\'", sql_clause)
            self.assertIn("LIKE LOWER(:like_query) ESCAPE '\\'", sql_clause)
            self.assertIn("ILIKE :like_query ESCAPE '\\'", sql_clause)

    @patch("app.repositories.document_repository.get_session")
    async def test_r4_adv_03_get_lexical_suggestions_all_wildcard_patterns(self, mock_get_session):
        """
        Adversarially probe: In get_lexical_suggestions, inject complex wildcard patterns.
        Verify that :contains is escaped and ILIKE query includes ESCAPE '\\'.
        """
        repo = DocumentRepository()
        mock_session = AsyncMock()
        mock_get_session.return_value.__aenter__.return_value = mock_session

        mock_res = MagicMock()
        mock_res.fetchall.return_value = []
        mock_session.execute.return_value = mock_res

        adversarial_patterns = [
            "%",
            "_",
            "%%",
            "__",
            "%_%_\\%_\\_%",
            "\\",
            "100%_aprobado",
        ]

        for pattern in adversarial_patterns:
            mock_session.reset_mock()
            await repo.get_lexical_suggestions(term=pattern, limit=10)

            self.assertTrue(mock_session.execute.called)
            call_args = mock_session.execute.call_args
            sql_clause = str(call_args[0][0])
            params = call_args[0][1]

            expected_escaped = DocumentRepository._escape_like_wildcards(pattern.strip())
            self.assertEqual(params["contains"], f"%{expected_escaped}%")
            self.assertIn("ESCAPE '\\'", sql_clause)

    def test_r4_adv_04_empirical_sql_matching_accuracy_in_sqlite(self):
        """
        Adversarially probe: Execute actual SQL LIKE queries with ESCAPE '\\' in an in-memory SQL database
        against an adversarial dataset. Verify that wildcards match LITERALLY and do NOT broaden the search.
        """
        con = sqlite3.connect(":memory:")
        cur = con.cursor()
        cur.execute("CREATE TABLE test_docs (id INTEGER PRIMARY KEY, titulo TEXT, nommetadato TEXT)")

        dataset = [
            (1, "Reglamento 100% Vigente", "Meta 100%"),
            (2, "Reglamento 1000 Vigente", "Meta 1000"),
            (3, "Reglamento 100A Vigente", "Meta 100A"),
            (4, "Doc_1 Version Final", "Meta_1"),
            (5, "Doc-1 Version Final", "Meta-1"),
            (6, "DocA1 Version Final", "MetaA1"),
            (7, "%%", "Double percent symbol"),
            (8, "%", "Single percent symbol"),
            (9, "_", "Single underscore symbol"),
            (10, "__", "Double underscore symbol"),
            (11, "%_%_\\%_\\_%", "Complex nested wildcards and slashes"),
            (12, "Path\\To\\Confidential\\Doc", "Windows Path"),
            (13, "PathXToXConfidentialXDoc", "Path with X"),
            (14, "Ordinary Title", "Ordinary Meta"),
            (15, "Secret Admin Manual", "Secret"),
        ]

        cur.executemany("INSERT INTO test_docs (id, titulo, nommetadato) VALUES (?, ?, ?)", dataset)
        con.commit()

        # Helper function simulating DocumentRepository lexical match
        def run_search(search_term: str):
            clean = search_term.strip()
            escaped = DocumentRepository._escape_like_wildcards(clean)
            like_pat = f"%{escaped}%"
            cur.execute(
                """
                SELECT id, titulo FROM test_docs
                WHERE titulo LIKE ? ESCAPE '\\' OR nommetadato LIKE ? ESCAPE '\\'
                ORDER BY id
                """,
                (like_pat, like_pat),
            )
            return cur.fetchall()

        # Probe 1: Search for "%"
        # Without escape, '%' would match ALL 15 rows.
        # With escape, it must match ONLY rows with a literal '%':
        # Rows: 1 ("Reglamento 100% Vigente"), 7 ("%%"), 8 ("%"), 11 ("%_%_\\%_\\_%")
        res_pct = run_search("%")
        matched_ids_pct = [r[0] for r in res_pct]
        self.assertEqual(
            matched_ids_pct,
            [1, 7, 8, 11],
            f"Search for '%' broadened improperly. Expected [1, 7, 8, 11], got {matched_ids_pct}",
        )

        # Probe 2: Search for "_"
        # Without escape, '_' would match all non-empty titles (all 15 rows).
        # With escape, it must match ONLY rows with a literal '_':
        # Rows: 4 ("Doc_1"), 9 ("_"), 10 ("__"), 11 ("%_%_\\%_\\_%")
        res_und = run_search("_")
        matched_ids_und = [r[0] for r in res_und]
        self.assertEqual(
            matched_ids_und,
            [4, 9, 10, 11],
            f"Search for '_' broadened improperly. Expected [4, 9, 10, 11], got {matched_ids_und}",
        )

        # Probe 3: Search for "%%"
        # Must match ONLY rows with literal "%%":
        # Rows: 7 ("%%")
        res_pct2 = run_search("%%")
        matched_ids_pct2 = [r[0] for r in res_pct2]
        self.assertEqual(
            matched_ids_pct2,
            [7],
            f"Search for '%%' failed. Expected [7], got {matched_ids_pct2}",
        )

        # Probe 4: Search for "__"
        # Must match ONLY rows with literal "__":
        # Rows: 10 ("__")
        res_und2 = run_search("__")
        matched_ids_und2 = [r[0] for r in res_und2]
        self.assertEqual(
            matched_ids_und2,
            [10],
            f"Search for '__' failed. Expected [10], got {matched_ids_und2}",
        )

        # Probe 5: Search for "%_%_\\%_\\_%"
        # Must match ONLY row 11
        res_complex = run_search("%_%_\\%_\\_%")
        matched_ids_complex = [r[0] for r in res_complex]
        self.assertEqual(
            matched_ids_complex,
            [11],
            f"Search for complex pattern failed. Expected [11], got {matched_ids_complex}",
        )

        # Probe 6: Search for "\\"
        # Must match ONLY rows with literal backslash:
        # Rows: 11 (has \), 12 ("Path\\To\\Confidential\\Doc")
        res_slash = run_search("\\")
        matched_ids_slash = [r[0] for r in res_slash]
        self.assertEqual(
            matched_ids_slash,
            [11, 12],
            f"Search for '\\' failed. Expected [11, 12], got {matched_ids_slash}",
        )

        # Probe 7: Search for "Doc_1"
        # Must match ONLY Row 4 ("Doc_1"), NOT Row 5 ("Doc-1") or Row 6 ("DocA1")
        res_doc = run_search("Doc_1")
        matched_ids_doc = [r[0] for r in res_doc]
        self.assertEqual(
            matched_ids_doc,
            [4],
            f"Search for 'Doc_1' broadened improperly. Expected [4], got {matched_ids_doc}",
        )

        # Probe 8: Search for "100%"
        # Must match ONLY Row 1 ("Reglamento 100% Vigente"), NOT Row 2 ("1000") or Row 3 ("100A")
        res_100 = run_search("100%")
        matched_ids_100 = [r[0] for r in res_100]
        self.assertEqual(
            matched_ids_100,
            [1],
            f"Search for '100%' broadened improperly. Expected [1], got {matched_ids_100}",
        )

        # Probe 9: Exact query equality verification
        # When query is "Reglamento 100% Vigente", exact_query must equal it literally
        clean_q = "Reglamento 100% Vigente"
        cur.execute(
            "SELECT id, titulo FROM test_docs WHERE LOWER(TRIM(titulo)) = LOWER(?)",
            (clean_q,),
        )
        exact_rows = cur.fetchall()
        self.assertEqual(len(exact_rows), 1)
        self.assertEqual(exact_rows[0][0], 1)
        self.assertEqual(exact_rows[0][1], "Reglamento 100% Vigente")

    def test_r4_adv_05_exact_match_score_precedence_with_wildcards(self):
        """
        Adversarially probe: Verify that an exact match on a string containing wildcards
        receives maximum score (100.0) and ranks ahead of partial starts/like matches,
        while completely filtering out unescaped false positives.
        """
        con = sqlite3.connect(":memory:")
        cur = con.cursor()
        cur.execute("CREATE TABLE rank_docs (id INTEGER PRIMARY KEY, titulo TEXT, nommetadato TEXT)")

        dataset = [
            (1, "100%_Approved", "Exact Match Document"),
            (2, "100%_Approved_Extended_Document", "Starts With Match"),
            (3, "Leading_Text_100%_Approved_Trailing", "Contains Like Match"),
            (4, "1000XApproved", "False Positive if Wildcards Unescaped"),
        ]
        cur.executemany("INSERT INTO rank_docs VALUES (?, ?, ?)", dataset)
        con.commit()

        query_text = "100%_Approved"
        clean_q = query_text.strip()
        escaped_q = DocumentRepository._escape_like_wildcards(clean_q)
        starts_query = f"{escaped_q}%"
        like_query = f"%{escaped_q}%"

        # Simulating the exact CASE statement and WHERE filtering from lexical_search
        sql = """
            SELECT
                id, titulo,
                CASE
                    WHEN LOWER(TRIM(titulo)) = LOWER(?) THEN 100.0
                    WHEN LOWER(TRIM(nommetadato)) = LOWER(?) THEN 95.0
                    WHEN LOWER(titulo) LIKE LOWER(?) ESCAPE '\\' THEN 75.0
                    WHEN LOWER(nommetadato) LIKE LOWER(?) ESCAPE '\\' THEN 70.0
                    WHEN LOWER(titulo) LIKE LOWER(?) ESCAPE '\\' THEN 50.0
                    WHEN LOWER(nommetadato) LIKE LOWER(?) ESCAPE '\\' THEN 45.0
                    ELSE 10.0
                END as match_boost
            FROM rank_docs
            WHERE LOWER(titulo) LIKE LOWER(?) ESCAPE '\\'
               OR LOWER(nommetadato) LIKE LOWER(?) ESCAPE '\\'
            ORDER BY match_boost DESC
        """
        cur.execute(sql, (
            clean_q, clean_q,
            starts_query, starts_query,
            like_query, like_query,
            like_query, like_query
        ))
        rows = cur.fetchall()

        # Rows must be:
        # Row 1 (id=1): match_boost = 100.0 (exact match)
        # Row 2 (id=2): match_boost = 75.0 (starts with)
        # Row 3 (id=3): match_boost = 50.0 (like contains)
        # Row 4 (id=4): NOT RETURNED (WHERE clause correctly eliminates it)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(rows[0][2], 100.0)
        self.assertEqual(rows[1][0], 2)
        self.assertEqual(rows[1][2], 75.0)
        self.assertEqual(rows[2][0], 3)
        self.assertEqual(rows[2][2], 50.0)


if __name__ == "__main__":
    unittest.main()

