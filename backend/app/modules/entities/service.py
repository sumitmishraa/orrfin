"""Legal entities and exchange rates: who may change them and what is refused (BUILD_PLAN §5, §6d, §9).

An entity carries the tax regime that the matching engine uses for its invoices, so a change
here changes how invoices are checked: only an admin may make it, and every change is audited.
Exchange rates are typed in by finance or an admin, never set by AI, and never overwritten:
a payment can always be traced to the rate that was in the table on its day.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import Conflict, Forbidden, Invalid, NotFound
from app.models import EntityMembership, ErpConnection, FxRate, Invoice, LegalEntity, Org, PurchaseOrder, User
from app.modules.audit.service import record_event
from app.modules.entities.fx import CURRENCIES
from app.modules.matching.tax import GSTIN_FORMAT, TAX_REGIMES, TRN_FORMAT

EDITOR_ROLES = ("admin",)
FX_ROLES = ("finance", "admin")
# A regime belongs to one country: GST rules are never applied to a UAE company, or the reverse.
REGIME_COUNTRY = {"in_gst": "IN", "ae_vat": "AE"}
DEFAULT_REGIME = "in_gst"


def as_dict(entity: LegalEntity) -> dict[str, Any]:
    return {"id": entity.id, "name": entity.name, "country": entity.country, "base_currency": entity.base_currency,
            "tax_regime": entity.tax_regime, "tax_id": entity.tax_id, "state_code": entity.state_code,
            "erp_connection_id": entity.erp_connection_id, "is_default": entity.is_default, "active": entity.active}


def _audit(db: Session, entity: LegalEntity, actor_id: uuid.UUID | None, action: str, payload: dict[str, Any]) -> None:
    record_event(db, org_id=entity.org_id, entity_type="legal_entity", entity_id=entity.id, actor_id=actor_id,
                 action=action, payload=payload)


def _require_editor(user: User) -> None:
    if user.role not in EDITOR_ROLES:
        raise Forbidden("Only an admin can change legal entities.")


def list_entities(db: Session, org_id: uuid.UUID) -> list[LegalEntity]:
    return list(db.scalars(select(LegalEntity).where(LegalEntity.org_id == org_id)
                           .order_by(LegalEntity.is_default.desc(), LegalEntity.name)))


def ensure_default(db: Session, org_id: uuid.UUID) -> LegalEntity:
    """The org's default entity. An org made after the v3.0 migration gets one the first time it is needed."""
    existing = db.scalar(select(LegalEntity).where(LegalEntity.org_id == org_id, LegalEntity.is_default))
    if existing is not None:
        return existing
    org = db.get(Org, org_id)
    entity = LegalEntity(id=uuid.uuid4(), org_id=org_id, name=org.name, country="IN", base_currency="INR",
                         tax_regime=DEFAULT_REGIME, is_default=True)
    db.add(entity)
    db.flush()
    _audit(db, entity, None, "created", {"default": True, "tax_regime": entity.tax_regime})
    return entity


def _checked(db: Session, org_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
    """Clean one entity's fields, or refuse with the reason an admin can act on."""
    name = (data.get("name") or "").strip()
    country = (data.get("country") or "").strip().upper()
    regime = data.get("tax_regime")
    currency = (data.get("base_currency") or "").strip().upper()
    tax_id = (data.get("tax_id") or "").strip().upper()
    state_code = (data.get("state_code") or "").strip() or None
    if not name:
        raise Invalid("Give the entity a name.")
    if regime not in TAX_REGIMES:
        raise Invalid("The tax regime must be India GST or UAE VAT.")
    if country != REGIME_COUNTRY[regime]:
        raise Invalid("India GST needs the country IN; UAE VAT needs the country AE.")
    if currency not in CURRENCIES:
        raise Invalid(f"The base currency must be one of {', '.join(CURRENCIES)}.")
    if regime == "in_gst":
        if not GSTIN_FORMAT.match(tax_id):
            raise Invalid("Enter the entity's GSTIN (15 characters, for example 27AAACO1234F1Z5).")
        if state_code is None:
            state_code = tax_id[:2]
        if state_code != tax_id[:2]:
            raise Invalid("The state code must be the first two digits of the GSTIN.")
    else:
        if not TRN_FORMAT.match(tax_id):
            raise Invalid("Enter the entity's TRN (15 digits starting with 100).")
        if state_code is not None:
            raise Invalid("A UAE entity has no GST state code.")
    connection_id = data.get("erp_connection_id")
    if connection_id is not None:
        # Looked up inside this org only: another org's connection id is "not found", never linked.
        if db.scalar(select(ErpConnection.id).where(ErpConnection.id == connection_id,
                                                    ErpConnection.org_id == org_id)) is None:
            raise NotFound("That ERP connection was not found.")
    return {"name": name[:200], "country": country, "tax_regime": regime, "base_currency": currency,
            "tax_id": tax_id, "state_code": state_code, "erp_connection_id": connection_id}


def _name_taken(db: Session, org_id: uuid.UUID, name: str, *, except_id: uuid.UUID | None = None) -> bool:
    query = select(LegalEntity.id).where(LegalEntity.org_id == org_id, LegalEntity.name == name)
    if except_id is not None:
        query = query.where(LegalEntity.id != except_id)
    return db.scalar(query) is not None


def create_entity(db: Session, user: User, data: dict[str, Any]) -> LegalEntity:
    _require_editor(user)
    ensure_default(db, user.org_id)
    values = _checked(db, user.org_id, data)
    if _name_taken(db, user.org_id, values["name"]):
        raise Conflict("An entity with this name already exists.")
    entity = LegalEntity(id=uuid.uuid4(), org_id=user.org_id, **values)
    db.add(entity)
    db.flush()
    _audit(db, entity, user.id, "created", values)
    return entity


def load_entity(db: Session, org_id: uuid.UUID, entity_id: uuid.UUID, *, lock: bool = False) -> LegalEntity:
    query = select(LegalEntity).where(LegalEntity.id == entity_id, LegalEntity.org_id == org_id)
    entity = db.scalar(query.with_for_update() if lock else query)
    if entity is None:
        raise NotFound("Entity not found.")
    return entity


def update_entity(db: Session, user: User, entity_id: uuid.UUID, data: dict[str, Any]) -> LegalEntity:
    _require_editor(user)
    entity = load_entity(db, user.org_id, entity_id, lock=True)
    values = _checked(db, user.org_id, data)
    active = bool(data.get("active", True))
    if entity.is_default and not active:
        raise Conflict("The default entity cannot be switched off. Make another entity the default first.")
    if _name_taken(db, user.org_id, values["name"], except_id=entity.id):
        raise Conflict("An entity with this name already exists.")
    changed = {k: {"old": getattr(entity, k), "new": v} for k, v in {**values, "active": active}.items()
               if getattr(entity, k) != v}
    if not changed:
        return entity
    for field, change in changed.items():
        setattr(entity, field, change["new"])
    db.flush()
    _audit(db, entity, user.id, "updated", changed)
    return entity


def make_default(db: Session, user: User, entity_id: uuid.UUID) -> LegalEntity:
    _require_editor(user)
    entity = load_entity(db, user.org_id, entity_id, lock=True)
    if not entity.active:
        raise Conflict("Switch the entity on before making it the default.")
    if entity.is_default:
        return entity
    previous = db.scalar(select(LegalEntity).where(LegalEntity.org_id == user.org_id, LegalEntity.is_default)
                         .with_for_update())
    if previous is not None:
        previous.is_default = False
        db.flush()  # the one-default index allows only one at a time
    entity.is_default = True
    db.flush()
    _audit(db, entity, user.id, "made_default", {"previous": previous.id if previous else None})
    return entity


def set_members(db: Session, user: User, entity_id: uuid.UUID, user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Who works for this entity. No members listed means everyone in the org does."""
    _require_editor(user)
    entity = load_entity(db, user.org_id, entity_id, lock=True)
    wanted = set(user_ids)
    known = set(db.scalars(select(User.id).where(User.org_id == user.org_id, User.id.in_(wanted)))) if wanted else set()
    if known != wanted:
        raise NotFound("One of those people was not found.")
    current = {m.user_id: m for m in db.scalars(select(EntityMembership).where(EntityMembership.entity_id == entity.id))}
    for user_id in wanted - current.keys():
        db.add(EntityMembership(org_id=user.org_id, entity_id=entity.id, user_id=user_id))
    for user_id in current.keys() - wanted:
        db.delete(current[user_id])
    db.flush()
    if wanted != current.keys():
        _audit(db, entity, user.id, "members_changed", {"members": sorted(str(u) for u in wanted)})
    return sorted(wanted)


def members_of(db: Session, entity: LegalEntity) -> list[uuid.UUID]:
    return list(db.scalars(select(EntityMembership.user_id).where(EntityMembership.entity_id == entity.id)))


# --- Which entity an invoice belongs to ----------------------------------------------------------

def entity_for_invoice(db: Session, invoice: Invoice, po: PurchaseOrder | None) -> LegalEntity | None:
    """The entity an invoice is billed to, which decides its tax regime (§6d).

    In order: the one entity mapped to the PO's ERP connection; the entity whose tax number is
    printed as the buyer; the default entity. None only for an org with no entities yet.
    The printed buyer number can pick the entity but cannot weaken a check: the supplier's tax
    number must still be well formed for that regime and equal the PO vendor's.
    """
    entities = [e for e in list_entities(db, invoice.org_id) if e.active]
    if po is not None:
        mapped = [e for e in entities if e.erp_connection_id == po.erp_connection_id]
        if len(mapped) == 1:
            return mapped[0]
    buyer = (invoice.buyer_gstin or "").strip().upper()
    if buyer:
        billed = [e for e in entities if e.tax_id == buyer]
        if len(billed) == 1:
            return billed[0]
    return next((e for e in entities if e.is_default), None)


def regime_of(entity: LegalEntity | None) -> str:
    return entity.tax_regime if entity is not None else DEFAULT_REGIME


# --- Exchange rates ------------------------------------------------------------------------------

def rate_as_dict(rate: FxRate, entered_by_name: str | None = None) -> dict[str, Any]:
    return {"id": rate.id, "base_currency": rate.base_currency, "quote_currency": rate.quote_currency,
            "rate": rate.rate, "as_of": rate.as_of, "entered_by": rate.entered_by, "entered_by_name": entered_by_name}


def list_rates(db: Session, org_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(select(FxRate, User.full_name).join(User, User.id == FxRate.entered_by)
                      .where(FxRate.org_id == org_id)
                      .order_by(FxRate.as_of.desc(), FxRate.base_currency, FxRate.quote_currency).limit(500)).all()
    return [rate_as_dict(rate, name) for rate, name in rows]


def add_rate(db: Session, user: User, *, base: str, quote: str, rate: Decimal, as_of: date) -> FxRate:
    """One typed-in rate: 1 `base` = `rate` `quote` on `as_of`. A pair and date is entered once."""
    if user.role not in FX_ROLES:
        raise Forbidden("Only finance or an admin can enter an exchange rate.")
    base, quote = base.strip().upper(), quote.strip().upper()
    if base not in CURRENCIES or quote not in CURRENCIES:
        raise Invalid(f"Currencies must be among {', '.join(CURRENCIES)}.")
    if base == quote:
        raise Invalid("Choose two different currencies.")
    if rate <= 0:
        raise Invalid("The rate must be greater than zero.")
    if as_of > date.today():
        raise Invalid("A rate cannot be entered for a future date.")
    if db.scalar(select(FxRate.id).where(FxRate.org_id == user.org_id, FxRate.base_currency == base,
                                         FxRate.quote_currency == quote, FxRate.as_of == as_of)) is not None:
        raise Conflict("A rate for this pair and date is already in the table. Rates are never overwritten.")
    row = FxRate(id=uuid.uuid4(), org_id=user.org_id, base_currency=base, quote_currency=quote, rate=rate,
                 as_of=as_of, entered_by=user.id)
    db.add(row)
    db.flush()
    record_event(db, org_id=user.org_id, entity_type="fx_rate", entity_id=row.id, actor_id=user.id,
                 action="entered", payload={"base": base, "quote": quote, "rate": str(rate), "as_of": as_of.isoformat()})
    return row


def rate_on(db: Session, org_id: uuid.UUID, base: str, quote: str, day: date) -> FxRate | None:
    """The latest rate entered for this pair on or before `day`. Never a later rate, never an estimate."""
    return db.scalar(select(FxRate).where(FxRate.org_id == org_id, FxRate.base_currency == base,
                                          FxRate.quote_currency == quote, FxRate.as_of <= day)
                     .order_by(FxRate.as_of.desc()).limit(1))
