"""The two documents a family needs if you are not around to explain.

Most unclaimed financial assets go unclaimed for one reason: nobody knew the
account existed. A nominee helps only on an account somebody thinks to look
for. So this produces:

  * a SEALED RECORD (AES-256): every account, folio, policy and loan in full,
    with nominees and contacts -- what exists and who to approach;
  * a LOCATOR SHEET (unencrypted, one page): where the sealed record is kept
    and who holds the password, plus the *institutions only*, no numbers, so
    a family that never opens the sealed file still knows which doors to
    knock on.

The second is the point. A sealed file nobody knows about recreates exactly
the problem it was meant to solve.

Neither document contains a username, password, PIN, or security answer, and
neither ever will: this exists so a family can claim what is theirs, not so
an account can be logged into.
"""
import io
from datetime import date

import analytics
from db import ASSET_CLASS_LABELS

MIN_PASSWORD_LENGTH = 10

NOT_A_WILL = (
    "This is a record, not a will. It transfers nothing and overrides "
    "nothing. In India a nominee is often only a trustee for the legal "
    "heirs rather than the owner of the asset, so nomination and "
    "inheritance are not the same thing — take proper succession advice."
)
NO_CREDENTIALS = (
    "By design this document contains no usernames, passwords, PINs or "
    "security answers. Finding it does not let anyone operate an account."
)


class EncryptionUnavailable(RuntimeError):
    """Raised rather than silently falling back to weaker encryption.

    ReportLab's own password protection is RC4, which is broken. A document
    labelled 'protected' that is not protected is worse than none, so if
    AES-256 is unavailable this refuses to produce a file at all.
    """


def encrypt_pdf(pdf_bytes, password):
    """Wrap a PDF in AES-256. Never downgrades."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError("password must be at least %d characters"
                         % MIN_PASSWORD_LENGTH)
    try:
        from pypdf import PdfWriter
    except ImportError as exc:      # pragma: no cover - environment specific
        raise EncryptionUnavailable(
            "AES-256 needs the 'pypdf' and 'cryptography' packages. Install "
            "them (pip install -r requirements.txt) — the record will not be "
            "written with weaker encryption.") from exc
    writer = PdfWriter(clone_from=io.BytesIO(pdf_bytes))
    try:
        writer.encrypt(password, algorithm="AES-256")
    except Exception as exc:        # pragma: no cover - environment specific
        raise EncryptionUnavailable(
            "AES-256 encryption failed (%s). Refusing to fall back to a "
            "weaker cipher." % exc) from exc
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _institutions(holdings, policies, loans):
    """Institution names only -- no numbers. Safe for the open sheet."""
    names = set()
    for h in holdings:
        label = ASSET_CLASS_LABELS.get(h["asset_class"], h["asset_class"])
        names.add("%s — %s" % (label, (h.get("name") or "").strip()))
    for p in policies:
        names.add(("Insurance — %s %s" % (p.get("insurer") or "",
                                          p.get("kind") or "")).strip())
    for loan in loans:
        names.add("Loan — %s" % (loan.get("name") or ""))
    return sorted(n for n in names if n and n.strip(" —"))


def _styles():
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("Small", parent=s["BodyText"], fontSize=8,
                         leading=10, textColor="#444444"))
    s.add(ParagraphStyle("Lead", parent=s["BodyText"], fontSize=10,
                         leading=14))
    return s


def _table(story, styles, title, header, rows, widths=None):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    if not rows:
        return
    story.append(Paragraph(title, styles["Heading2"]))
    data = [header] + rows
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f4f6f7")]),
    ]))
    story.append(t)
    story.append(Spacer(1, 5))


def build_sealed_record(holdings, policies, loans, owners, contacts=None,
                        as_of=None, household=""):
    """The full record. Returns unencrypted bytes; caller must encrypt."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                    Spacer)
    as_of = as_of or date.today()
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm,
                            rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm,
                            title="Family Financial Record")
    story = [
        Paragraph("Family Financial Record", styles["Title"]),
        Paragraph("%s%s — prepared %s" % (
            household, " " if household else "", as_of.strftime("%d %B %Y")),
            styles["Normal"]),
        Spacer(1, 6),
        Paragraph("<b>What this is.</b> A list of everything this household "
                  "owns and owes, so that it can be found and claimed. "
                  + NO_CREDENTIALS, styles["Lead"]),
        Spacer(1, 4),
        Paragraph("<b>What this is not.</b> " + NOT_A_WILL, styles["Lead"]),
        Spacer(1, 4),
        Paragraph("Values are as at %s and will drift. The account numbers "
                  "and contacts are the durable part." % as_of.isoformat(),
                  styles["Small"]),
        Spacer(1, 8),
    ]

    def fmt(x):
        try:
            return "{:,.0f}".format(float(x))
        except (TypeError, ValueError):
            return str(x or "")

    by_owner = {}
    for h in holdings:
        by_owner.setdefault(h.get("owner") or "Unassigned", []).append(h)
    for owner, hs in sorted(by_owner.items()):
        _table(story, styles, "Investments — %s" % owner,
               ["Type", "Name", "Folio / account no.", "Value (₹)", "Nominee"],
               [[ASSET_CLASS_LABELS.get(h["asset_class"], h["asset_class"]),
                 Paragraph(str(h.get("name") or ""), styles["Small"]),
                 h.get("identifier") or "—",
                 fmt(analytics.holding_value(h, as_of)),
                 (h.get("meta") or {}).get("nominee") or "NOT SET"]
                for h in sorted(hs, key=lambda x: x["asset_class"])],
               widths=[26 * mm, 52 * mm, 40 * mm, 26 * mm, 28 * mm])

    _table(story, styles, "Insurance policies",
           ["Type", "Insurer / policy", "Policy no.", "Covers",
            "Sum assured (₹)", "Nominee"],
           [[p.get("kind") or "", Paragraph("%s %s" % (p.get("insurer") or "",
                                                       p.get("name") or ""),
                                            styles["Small"]),
             p.get("policy_number") or "—", p.get("covered") or "",
             fmt(p.get("sum_assured")), p.get("nominee") or "NOT SET"]
            for p in policies],
           widths=[18 * mm, 48 * mm, 30 * mm, 24 * mm, 26 * mm, 26 * mm])

    _table(story, styles, "Loans outstanding",
           ["Loan", "Type", "Outstanding (₹)", "Rate %", "EMI (₹)"],
           [[loan.get("name") or "", loan.get("kind") or "",
             fmt(loan.get("principal_outstanding")),
             fmt(loan.get("annual_rate")), fmt(loan.get("emi"))]
            for loan in loans])

    if contacts:
        _table(story, styles, "People to contact",
               ["Role", "Name", "Phone", "Email"],
               [[c.get("role", ""), c.get("name", ""), c.get("phone", ""),
                 c.get("email", "")] for c in contacts])

    story.append(PageBreak())
    story.append(Paragraph("Notes for whoever is reading this",
                           styles["Heading2"]))
    for line in (
        "Nothing here can be acted on by phone or online. Each institution "
        "will ask for a death certificate, proof of identity, and its own "
        "claim form.",
        "Where a nominee is shown as NOT SET, expect the institution to ask "
        "for succession documents instead. That is normal, and slower.",
        "A joint holder is not the same as a nominee, and neither is the "
        "same as an heir under a will.",
        NOT_A_WILL,
        NO_CREDENTIALS,
    ):
        story.append(Paragraph("• " + line, styles["Lead"]))
        story.append(Spacer(1, 3))
    doc.build(story)
    return buf.getvalue()


def build_locator_sheet(holdings, policies, loans, as_of=None, household="",
                        stored_at="", password_held_by=""):
    """One unencrypted page: where the sealed record is, and who to ask.

    Deliberately lists institutions with no account numbers, so it can be
    left with a will or in a locker without becoming a target itself.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    as_of = as_of or date.today()
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm,
                            rightMargin=18 * mm, topMargin=18 * mm,
                            title="Where our financial records are")
    blank = "_" * 46
    story = [
        Paragraph("Where our financial records are", styles["Title"]),
        Paragraph("%s%s — %s" % (household, " " if household else "",
                                 as_of.strftime("%d %B %Y")), styles["Normal"]),
        Spacer(1, 8),
        Paragraph("<b>Print this page and keep it where your family will "
                  "look — with the will, in the locker, with the passbooks. "
                  "It has no account numbers on it.</b>", styles["Lead"]),
        Spacer(1, 8),
        Paragraph("A sealed PDF listing every account, folio, policy and "
                  "loan this household holds is kept at:", styles["Lead"]),
        Paragraph("<b>%s</b>" % (stored_at or blank), styles["Lead"]),
        Spacer(1, 6),
        Paragraph("The password to open it is held by:", styles["Lead"]),
        Paragraph("<b>%s</b>" % (password_held_by or blank), styles["Lead"]),
        Spacer(1, 10),
        Paragraph("If that file cannot be found or opened, the institutions "
                  "below still hold our money. Approach each one with a "
                  "death certificate and proof of identity and ask what is "
                  "held in our name.", styles["Lead"]),
        Spacer(1, 6),
    ]
    for name in _institutions(holdings, policies, loans):
        story.append(Paragraph("• " + name, styles["Lead"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph(NOT_A_WILL, styles["Small"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(NO_CREDENTIALS + " Never write a password on this "
                           "sheet.", styles["Small"]))
    doc.build(story)
    return buf.getvalue()
