"""A figure grouped with dots reads as thousands; a decimal stays a decimal.

Wipro's audited consolidated balance sheet renders the thousands separator as a
period in some cells and a comma in others, cell by cell, and sometimes both
inside one figure: "77.224" beside "320,346", and the page's own total as
"1.414,077". Reading the dot as a decimal point publishes 77.224 against a true
77,224, a thousand times too small wearing a parsed one. The digits are intact
and only the glyph is wrong, so the token is read under the grouping convention
and the page foots: 587,723 + 826,354 = 1,414,077, which is what the
comma-printed total prints.

The shape separates the two readings, and these tests state the boundary: whole
units with at most two decimals is what an Indian statement prints (the
earnings-per-share rows carry two), so exactly-three-digit dot groups have one
reading and two-digit groups have the other. A first group of bare zero is a
genuine decimal (par values print "0.005") and is left alone; this same Wipro
page prints its cash cell as "I 05.555", which the reader already refuses as a
whole.
"""

import pytest

from backend.data.parsers.pdf_tables import _num


class TestDotGroupedFiguresReadAsThousands:
    def test_a_single_dot_group_is_thousands(self):
        assert _num("77.224") == 77224.0

    def test_repeated_dot_groups_are_thousands(self):
        assert _num("1.414.077") == 1414077.0

    def test_mixed_dot_and_comma_groups_are_thousands(self):
        # The page's own total token: dot groups with a comma behind them.
        assert _num("1.414,077") == 1414077.0
        assert _num("1,414.077") == 1414077.0

    def test_a_wrapped_dot_grouped_figure_keeps_its_sign(self):
        assert _num("(2.685)") == -2685.0

    def test_a_dot_group_with_a_comma_sibling_shape_still_reads(self):
        # The same page mixes separators inside one row.
        assert _num("437.680") == 437680.0
        assert _num("382,214") == 382214.0

    def test_two_fractional_digits_stay_a_decimal(self):
        # Earnings-per-share figures print two decimals and are never grouping.
        assert _num("2.13") == 2.13
        assert _num("16.98") == 16.98

    def test_one_fractional_digit_stays_a_decimal(self):
        assert _num("0.5") == 0.5

    def test_a_leading_zero_group_is_a_decimal(self):
        # Par values print "0.005"; the grouped read leaves leading-zero first
        # groups on the decimal path. The damaged cash cell "I 05.555" refuses
        # as a whole before any of this sees it.
        assert _num("0.005") == 0.005
        assert _num("0.001") == 0.001

    def test_the_existing_refusals_are_untouched(self):
        # Leading-dot damage (Reliance FY26) and unreadable comma grouping
        # (HCLTech "28,1139") still refuse rather than guess.
        assert _num(".158842") is None
        assert _num("1,96-1") is None
        assert _num("28,1139") is None

    def test_comma_grouping_still_parses_in_both_conventions(self):
        assert _num("281,139") == 281139.0
        assert _num("2,81,139") == 281139.0
