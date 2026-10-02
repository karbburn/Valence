"""A caption must not become a line of a statement it was not printed in.

Infosys prints the same words in two statements, meaning opposite things:

    p.104  Consolidated Statement of Cash Flows
           "Prepayments and other assets        (2,312)"     a MOVEMENT
    p.100  Consolidated Balance Sheet
           "Prepayments and other current assets 15,703"     a STOCK

Both reached the taxonomy as the bare label "Prepayments and other assets",
because `RawDatapoint` carried no record of which statement it came from -- every
reader passed `section` into its datapoint-id hash and then discarded it. The
cash-flow page was parsed second, so the movement overwrote the stock and the model
published **-2,312 as a balance-sheet asset where the filing says +15,703**. A
movement published as a balance, and negative where an asset cannot be.

Knowing the statement is the minimum needed to tell them apart. ORDER ALONE IS NOT
THE FIX: it would only change which of the two wins, and a year of restatements or a
re-ordered page list would flip it back. The caption is refused outright for the
statement it was not printed in, and routed to review so a filer whose own balance
sheet genuinely prints that caption still reaches the key.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import shutil
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.data.store import RawDatapoint  # noqa: E402
from backend.normalization.financials import mapper  # noqa: E402


class TestTheStatementIsCarried:
    """Every reader already knew this and threw it away at the boundary."""

    def test_a_raw_datapoint_can_record_its_statement(self):
        assert "section" in RawDatapoint.model_fields, (
            "RawDatapoint has no `section`, so a caption cannot say which statement "
            "it was printed in -- the knowledge every reader already has"
        )

    def test_the_section_defaults_to_unknown_rather_than_being_required(self):
        """Existing callers must not break.

        The field is optional so readers with no notion of statements keep working;
        absence of evidence is treated as absence of a claim, not as disagreement.
        """
        assert RawDatapoint.model_fields["section"].is_required() is False

    def test_the_column_exists_in_the_schema(self):
        src = (REPO / "backend" / "data" / "store.py").read_text(encoding="utf-8")
        schema = re.search(
            r"CREATE TABLE IF NOT EXISTS raw_datapoints.*?\);", src, re.S
        )
        assert schema, "the raw_datapoints schema could not be located"
        assert "section TEXT" in schema.group(0), (
            "the column is absent from the schema, so the value is written and "
            "discarded -- or the INSERT fails on arity"
        )

    def test_the_insert_writes_the_same_number_of_values_as_columns(self):
        """The failure mode of adding a column is a silent arity mismatch."""
        src = (REPO / "backend" / "data" / "store.py").read_text(encoding="utf-8")
        schema = re.search(r"raw_datapoints \((.*?)\n\);", src, re.S)
        cols = [c for c in schema.group(1).split(",") if c.strip()]
        placeholders = re.search(
            r"INSERT OR REPLACE INTO raw_datapoints VALUES \((.*?)\)", src
        )
        assert placeholders, "the INSERT statement could not be located"
        n_ph = placeholders.group(1).count("?")
        assert n_ph == len(cols), (
            "the INSERT has %d placeholders for %d columns; a mismatch either "
            "raises or silently writes values into the wrong fields"
            % (n_ph, len(cols))
        )
        assert "d.section" in src, (
            "the section value is never written, so the column stays NULL and the "
            "refusal in the mapper can never fire"
        )

    def test_an_existing_database_is_migrated_not_left_stale(self):
        """`CREATE TABLE IF NOT EXISTS` cannot add a column, and says nothing.

        Observed 2026-10-02: the local store kept 13 columns after `section` was
        added to `_SCHEMA`, so the 14-value INSERT failed and FIVE tests failed in
        a full suite while passing in isolation. The schema was correct and the
        database was not, and nothing said so.

        So the column must be added to an existing table explicitly.
        """
        src = (REPO / "backend" / "data" / "store.py").read_text(encoding="utf-8")
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert "ALTER TABLE" in code, (
            "no migration exists, so every database created before a column was "
            "added silently lacks it. `_connect` runs _SCHEMA, and "
            "CREATE TABLE IF NOT EXISTS does nothing for a table that already exists."
        )
        # And it must run on connect, or it only helps whoever happens to call it.
        i_schema = code.find("executescript(_SCHEMA)")
        i_migrate = code.find("_migrate(conn)", i_schema)
        assert i_schema != -1, "the schema is never applied on connect"
        assert i_migrate != -1 and i_migrate > i_schema, (
            "_connect does not run the migration after the schema, so opening the "
            "database does not bring an existing one up to date"
        )

    def test_migrating_an_older_database_adds_the_column(self):
        """The behaviour, not the source text.

        The migration builds its ALTER by interpolation, so the table name never
        appears literally -- and a test that greps for it passes against code that
        migrates nothing. So an old-shaped database is built here and opened.
        """
        import sqlite3
        import tempfile

        from backend.data.store import _connect

        tmpdir = tempfile.mkdtemp()
        try:
            path = pathlib.Path(tmpdir) / "old.db"
            con = sqlite3.connect(str(path))
            con.executescript(
                "CREATE TABLE raw_datapoints ("
                "id TEXT PRIMARY KEY, company_id TEXT NOT NULL, metric_raw TEXT NOT NULL,"
                " period_label TEXT NOT NULL, period_end_date TEXT NOT NULL,"
                " value REAL NOT NULL, currency TEXT NOT NULL, units TEXT NOT NULL,"
                " source TEXT NOT NULL, source_location TEXT NOT NULL,"
                " status TEXT NOT NULL, update_date TEXT NOT NULL,"
                " superseded_by_id TEXT)"
            )
            con.commit()
            con.close()
            probe = sqlite3.connect(str(path))
            assert "section" not in {
                r[1] for r in probe.execute("PRAGMA table_info(raw_datapoints)")
            }, "the fixture did not reproduce a pre-migration database"
            probe.close()

            con = _connect(path)
            cols = {r[1] for r in con.execute("PRAGMA table_info(raw_datapoints)")}
            con.close()
            assert "section" in cols, (
                "opening a pre-migration database left it without the section "
                "column, so the mapper's check can never fire against existing data"
            )
        finally:
            # Explicit removal: on Windows a TemporaryDirectory cleanup that loses
            # the race against a just-closed handle raises PermissionError, and the
            # failure then looks like a product fault rather than a teardown one.
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestTheMapperRefusesACrossStatementMapping:
    """The behaviour, in the exact call the mapper makes."""

    @pytest.mark.parametrize(
        "section,statement,expected",
        [
            # the defect: a cash-flow movement reaching a balance-sheet line
            ("CASH FLOW", "bs", False),
            ("CASH FLOW:", "bs", False),
            # the same caption on the right statement is fine
            ("BALANCE SHEET", "bs", True),
            ("CASH FLOW:", "cf", True),
            ("PROFIT & LOSS", "is", True),
            # and other crossings
            ("PROFIT & LOSS", "bs", False),
            ("BALANCE SHEET", "cf", False),
            ("BALANCE SHEET", "is", False),
            # no claim either way is not a disagreement
            (None, "bs", True),
            ("BALANCE SHEET", None, True),
            (None, None, True),
        ],
    )
    def test_agreement(self, section, statement, expected):
        assert mapper._statement_agrees(section, statement) is expected

    def test_the_registry_codes_are_lowercase_and_are_compared_as_such(self):
        """A case mismatch here is not cosmetic.

        Upper-casing the statement turned "bs" into "BS" while the table keys stayed
        lower, so every POSITIVE case failed: the gate refused every mapping of the
        kind it was built to allow, and would have emptied balance sheets rather
        than protecting them -- the exact inverse of its intent, and silent.
        """
        from backend.normalization.taxonomy.registry import RAW_METRIC_MAP

        codes = {stmt for _k, stmt in RAW_METRIC_MAP.values()}
        assert codes, "no statement codes found in the registry"
        assert all(c == c.lower() for c in codes), (
            "registry statement codes are not uniformly lower case: %r -- the "
            "comparison lower-cases its input, so a mixed table would silently "
            "refuse valid mappings" % sorted(codes)
        )
        for code in codes:
            assert mapper._statement_agrees("BALANCE SHEET", code) is (code == "bs")

    def test_substring_matching_is_not_used(self):
        """Two-letter codes make substring tests dangerous.

        "is" is a substring of nothing useful and "cf" neither, but a reader that
        tried `code in section` would accept "PROFIT & LOSS" for "bs" only by luck,
        and would accept a mangled header for whatever happened to contain it.
        """
        src = inspect.getsource(mapper._statement_agrees)
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert not re.search(r"\bin\s+left\b|\bleft\s+in\b|\bin\s+right\b|\bright\s+in\b", code), (
            "the comparison is doing substring matching on statement names, which "
            "two-letter codes make unsafe"
        )

    def test_the_mapper_consults_the_helper_before_writing(self):
        src = inspect.getsource(mapper.map_raw_datapoints)
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        i_check = code.find("_statement_agrees(")
        assert i_check != -1, (
            "map_raw_datapoints never consults the statement, so a cash-flow "
            "caption still becomes a balance-sheet line"
        )
        i_key = code.find("canonical_key, statement = mapping")
        i_build = code.find("CanonicalDatapoint(")
        assert -1 < i_key < i_check < i_build, (
            "the statement check must sit between reading the mapping and building "
            "the canonical datapoint; it is currently at %r" % i_check
        )


class TestBothReadersRecordIt:
    @pytest.mark.parametrize(
        "relpath",
        ["backend/data/parsers/pdf_tables.py", "backend/data/ingestion/screener.py"],
    )
    def test_the_reader_sets_section(self, relpath):
        src = (REPO / relpath).read_text(encoding="utf-8")
        code = re.sub(r'""".*?"""', "", src, flags=re.S)
        code = re.sub(r"#.*$", "", code, flags=re.M)
        assert re.search(r"section=section", code), (
            "%s builds RawDatapoints without recording the section it was handed, "
            "so the mapper's check can never fire for this reader" % relpath
        )