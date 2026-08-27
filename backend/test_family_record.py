"""Tests for the family record documents."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import family_record as fr  # noqa: E402

HOLDINGS = [
    {"owner": "Me", "asset_class": "mutual_fund", "name": "Flexi Cap Fund",
     "identifier": "122639", "units": 100, "last_price": 90, "avg_cost": 50,
     "meta": {"nominee": "Spouse", "category": "equity"}},
    {"owner": "Wife", "asset_class": "savings", "name": "HDFC savings",
     "identifier": "50100123456", "manual_value": 240000, "meta": {}},
]
POLICIES = [{"kind": "term", "insurer": "Axis Max", "name": "Term Plan",
             "policy_number": "AX99123", "covered": "Self",
             "sum_assured": 10000000, "nominee": "Spouse"}]
LOANS = [{"name": "HDFC Home Loan", "kind": "home",
          "principal_outstanding": 3200000, "annual_rate": 7.0, "emi": 23300}]


def test_sealed_record_is_a_pdf_containing_the_identifiers():
    pdf = fr.build_sealed_record(HOLDINGS, POLICIES, LOANS, ["Me", "Wife"])
    assert pdf[:4] == b"%PDF"
    from pypdf import PdfReader
    import io
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "122639" in text and "50100123456" in text and "AX99123" in text
    assert "NOT SET" in text          # the savings account has no nominee
    assert "not a will" in text.lower()


def test_locator_sheet_names_institutions_but_no_numbers():
    pdf = fr.build_locator_sheet(HOLDINGS, POLICIES, LOANS,
                                 stored_at="Bank locker",
                                 password_held_by="My brother")
    from pypdf import PdfReader
    import io
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Flexi Cap Fund" in text and "HDFC savings" in text
    assert "Bank locker" in text and "My brother" in text
    # the whole point: no account numbers on the open sheet
    assert "122639" not in text
    assert "50100123456" not in text
    assert "AX99123" not in text


def test_institutions_lists_every_source_without_crashing():
    names = fr._institutions(HOLDINGS, POLICIES, LOANS)
    assert any("Flexi Cap Fund" in n for n in names)
    assert any("Insurance" in n for n in names)
    assert any("Loan" in n for n in names)
    assert all(isinstance(n, str) for n in names)


def test_encryption_produces_aes256_and_needs_the_password():
    import io

    from pypdf import PdfReader
    plain = fr.build_sealed_record(HOLDINGS, POLICIES, LOANS, ["Me"])
    enc = fr.encrypt_pdf(plain, "a-strong-family-password")
    assert b"AESV3" in enc                 # AES-256, not RC4
    assert b"122639" not in enc            # identifiers not in plaintext
    assert PdfReader(io.BytesIO(enc)).is_encrypted
    assert PdfReader(io.BytesIO(enc)).decrypt("wrong-one") == 0
    r = PdfReader(io.BytesIO(enc))
    assert r.decrypt("a-strong-family-password")
    assert "122639" in "".join(p.extract_text() for p in r.pages)


def test_short_passwords_are_refused():
    plain = fr.build_sealed_record(HOLDINGS, POLICIES, LOANS, ["Me"])
    for bad in ("", "short", "123456789"):
        with pytest.raises(ValueError):
            fr.encrypt_pdf(plain, bad)


def test_empty_household_still_produces_both_documents():
    assert fr.build_sealed_record([], [], [], [])[:4] == b"%PDF"
    assert fr.build_locator_sheet([], [], [])[:4] == b"%PDF"


def test_locator_leaves_blanks_when_storage_is_unknown():
    import io

    from pypdf import PdfReader
    pdf = fr.build_locator_sheet(HOLDINGS, [], [])
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "____" in text          # blanks to fill in by hand
