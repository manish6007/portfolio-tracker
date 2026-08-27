"""Request bodies, typed.

Every endpoint used to take `payload: dict` and hand-roll its own checks --
`float(payload["amount"])` raising KeyError became a 500 rather than a
useful error, a misspelled field was silently ignored, and /docs described
every request body as "object". These models do the same checks in one
declarative place, reject unknown fields instead of dropping them, and give
the API a real schema.

Two conventions worth knowing:

* **PUT models are all-optional and read with `model_dump(exclude_unset=True)`.**
  A partial update must touch only the fields that were actually sent;
  "absent" and "sent as null" are different instructions, and Pydantic's
  exclude_unset is what tells them apart.
* **`extra="forbid"` nearly everywhere.** A typo like `assetClass` should be
  an error, not a field that quietly does nothing. The exception is import
  rows, which carry whatever the parser produced.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from analytics import FREQUENCY_MONTHS
from db import ASSET_CLASSES


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Loose(BaseModel):
    """For bodies that legitimately carry fields we do not model.

    Extras are dropped -- used where the sender echoes back more than the
    endpoint needs.
    """
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Open(BaseModel):
    """Like Loose, but the extras are kept and readable via model_extra.

    For bodies that are a bag of keys by design: the endpoint, not the
    schema, knows which ones are meaningful.
    """
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


# ---------------- owners ----------------
class OwnerIn(Strict):
    name: str = Field(min_length=1, max_length=60)


# ---------------- holdings ----------------
class HoldingIn(Strict):
    asset_class: str
    name: str = Field(min_length=1, max_length=200)
    owner_id: Optional[int] = None
    identifier: Optional[str] = Field(default=None, max_length=80)
    units: Optional[float] = Field(default=None, ge=0)
    avg_cost: Optional[float] = Field(default=None, ge=0)
    manual_value: Optional[float] = Field(default=None, ge=0)
    last_price: Optional[float] = Field(default=None, ge=0)
    rate: Optional[float] = Field(default=None, ge=-100, le=100)
    notes: Optional[str] = None
    start_date: Optional[str] = None
    value_date: Optional[str] = None
    price_date: Optional[str] = None
    # Free-form on purpose: category, bucket, splits, nominee, folio, ISIN.
    # An empty value clears that key, which is why values are not typed.
    meta: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def check(self):
        if self.asset_class not in ASSET_CLASSES:
            raise ValueError("asset_class must be one of: %s"
                             % ", ".join(ASSET_CLASSES))
        return self


class HoldingUpdate(Strict):
    """Every field optional: only what was sent is applied.

    invested and current_value are not columns -- they are units × cost and
    units × price. Sending them is the natural way to keep a holding up to
    date after a month of SIPs, so the endpoint solves back for the units
    rather than making anyone work them out.
    """
    invested: Optional[float] = Field(default=None, ge=0)
    current_value: Optional[float] = Field(default=None, ge=0)
    asset_class: Optional[str] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    owner_id: Optional[int] = None
    identifier: Optional[str] = Field(default=None, max_length=80)
    units: Optional[float] = Field(default=None, ge=0)
    avg_cost: Optional[float] = Field(default=None, ge=0)
    manual_value: Optional[float] = Field(default=None, ge=0)
    last_price: Optional[float] = Field(default=None, ge=0)
    rate: Optional[float] = Field(default=None, ge=-100, le=100)
    notes: Optional[str] = None
    start_date: Optional[str] = None
    value_date: Optional[str] = None
    price_date: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class TransactionIn(Strict):
    date: str
    amount: float = Field(gt=0)
    type: str = "buy"
    units: float = 0.0


# ---------------- import ----------------
class ImportRow(Loose):
    """One row from the preview, confirmed by the user.

    Loose because the CAS and CSV parsers attach whatever they found -- ISIN,
    registrar, nominee, scheme code, transactions -- and the preview hands
    the rows back verbatim.
    """
    name: str = Field(min_length=1, max_length=200)
    asset_class: Optional[str] = None
    owner: Optional[str] = None
    identifier: Optional[str] = None
    units: float = 0.0
    avg_cost: float = 0.0
    last_price: float = 0.0
    purchase_date: Optional[str] = None
    category: Optional[str] = None
    isin: Optional[str] = None
    registrar: Optional[str] = None
    nominee: Optional[str] = None
    scheme_code: Optional[str] = None
    transactions: List[Dict[str, Any]] = Field(default_factory=list)


class ImportCommit(Strict):
    rows: List[ImportRow] = Field(default_factory=list)
    owner: Optional[str] = None


# ---------------- cashflow ----------------
class EntryIn(Strict):
    amount: float
    owner_id: Optional[int] = None
    date: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None
    fixed: Optional[bool] = None          # expenses only; ignored on income


class RecurringIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "sip"
    amount: Optional[float] = None
    amount_monthly: Optional[float] = None    # legacy clients
    frequency: str = "monthly"
    next_due: Optional[str] = None
    counts_as_investment: Optional[bool] = None

    @model_validator(mode="after")
    def check(self):
        if self.frequency not in FREQUENCY_MONTHS:
            raise ValueError("frequency must be one of: %s"
                             % ", ".join(FREQUENCY_MONTHS))
        if self.amount is None and self.amount_monthly is None:
            raise ValueError("give an amount")
        return self


class RecurringUpdate(Strict):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    kind: Optional[str] = None
    amount: Optional[float] = None
    amount_monthly: Optional[float] = None
    frequency: Optional[str] = None
    next_due: Optional[str] = None
    counts_as_investment: Optional[bool] = None

    @model_validator(mode="after")
    def check(self):
        if self.frequency is not None and self.frequency not in FREQUENCY_MONTHS:
            raise ValueError("frequency must be one of: %s"
                             % ", ".join(FREQUENCY_MONTHS))
        return self


# ---------------- loans ----------------
class LoanIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    principal_outstanding: float = Field(ge=0)
    annual_rate: float = Field(ge=0, le=100)
    kind: str = "home"
    owner_id: Optional[int] = None
    emi: float = Field(default=0.0, ge=0)
    tenure_months_remaining: int = Field(default=0, ge=0, le=600)
    notes: Optional[str] = None


class LoanUpdate(Strict):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    kind: Optional[str] = None
    principal_outstanding: Optional[float] = Field(default=None, ge=0)
    annual_rate: Optional[float] = Field(default=None, ge=0, le=100)
    emi: Optional[float] = Field(default=None, ge=0)
    tenure_months_remaining: Optional[int] = Field(default=None, ge=0, le=600)
    notes: Optional[str] = None


class PrepayIn(Strict):
    principal: float = Field(gt=0)
    annual_rate: float = Field(ge=0, le=100)
    emi: float = Field(gt=0)
    lumpsum: float = Field(gt=0)
    invest_return_pct: float = Field(default=12.0, ge=0, le=40)


# ---------------- insurance ----------------
class PolicyIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "term"
    owner_id: Optional[int] = None
    insurer: Optional[str] = None
    policy_number: Optional[str] = None
    covered: Optional[str] = None
    sum_assured: float = Field(default=0.0, ge=0)
    premium: float = Field(default=0.0, ge=0)
    frequency: str = "yearly"
    next_due: Optional[str] = None
    valid_till: Optional[str] = None
    nominee: Optional[str] = None
    notes: Optional[str] = None


class PolicyUpdate(Strict):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    kind: Optional[str] = None
    insurer: Optional[str] = None
    policy_number: Optional[str] = None
    covered: Optional[str] = None
    sum_assured: Optional[float] = Field(default=None, ge=0)
    premium: Optional[float] = Field(default=None, ge=0)
    frequency: Optional[str] = None
    next_due: Optional[str] = None
    valid_till: Optional[str] = None
    nominee: Optional[str] = None
    notes: Optional[str] = None


# ---------------- goals ----------------
class GoalIn(Strict):
    name: str = Field(min_length=1, max_length=120)
    amount_today: float = Field(gt=0)
    target_year: int = Field(default=0, ge=0, le=60)
    inflation_pct: Optional[float] = Field(default=None, ge=0, le=30)
    notes: Optional[str] = None


# ---------------- settings ----------------
class SettingsIn(Open):
    """The keys are SETTING_KEYS, filtered by the endpoint.

    Open rather than Strict because the frontend sends the whole settings
    object back, read-only fields like targets_customized included, so
    forbidding extras would reject a perfectly ordinary save. Open rather
    than Loose because the settings themselves arrive as those extras --
    dropping them would silently save nothing.
    """
    targets: Optional[Dict[str, float]] = None


class UnitFix(Strict):
    """Give the units, or the value they are currently worth.

    Nobody reads unit counts off a screen, but everybody can see what a
    holding is worth today. units = value / NAV is arithmetic, so asking for
    whichever number is to hand costs nothing.
    """
    holding_id: int
    units: Optional[float] = Field(default=None, gt=0)
    current_value: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check(self):
        if self.units is None and self.current_value is None:
            raise ValueError("give either the units or the current value")
        return self


class SetUnits(Strict):
    units: List[UnitFix] = Field(default_factory=list)


class CodeAssignment(Strict):
    holding_id: int
    scheme_code: str = Field(min_length=1, max_length=12)
    # Offered for holdings whose recorded name is a placeholder rather than
    # a fund. Never the default: a name is the user's own label.
    adopt_name: bool = False


class ApplyCodes(Strict):
    assignments: List[CodeAssignment] = Field(default_factory=list)


# ---------------- privacy, profiles, danger ----------------
class OfflineIn(Strict):
    offline: bool


class DataDirIn(Strict):
    path: Optional[str] = None
    reset: bool = False


class ProfileIn(Strict):
    name: str = Field(min_length=1, max_length=60)
    demo: bool = False


class ProfileRename(Strict):
    name: str = Field(min_length=1, max_length=60)


class ConfirmIn(Strict):
    confirm: str = ""


class SealedRecordIn(Strict):
    password: str = ""
