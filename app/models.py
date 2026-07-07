"""
app/models.py

SQLAlchemy ORM models defining the relational schema for the Revenue
Intelligence Platform.

DESIGN DECISIONS:

1. Surrogate integer primary keys (autoincrement) rather than natural keys
   (e.g. email as PK for contacts). Surrogate keys are stable even if
   "real world" attributes change (a contact changes email, a company
   renames) and this is the standard OLTP schema convention this dataset
   simulates.

2. All foreign keys use ON DELETE behavior appropriate to the business
   rule:
   - Deleting a sales rep should NOT cascade-delete their historical
     opportunities/activities (that would destroy audit history), so we
     use ON DELETE SET NULL for rep_id where the relationship models
     "who currently owns this", and rely on rep reassignment in practice.
   - Deleting an account SHOULD cascade to its contacts and opportunities,
     since those records are meaningless without the parent account.
     Activities cascade from opportunities for the same reason.

3. Enums are modeled as indexed String columns rather than native SQL
   ENUM types. SQLite has no real ENUM type, and this keeps the schema
   trivially portable to PostgreSQL (native ENUM in Postgres requires
   explicit CREATE TYPE + migrations whenever a new stage is added,
   which is painful in a fast-moving sales org). Validity is enforced in
   the application layer (see STAGE_CHOICES etc. below) instead.

4. Money is stored as Numeric(12, 2), not Float. Floats introduce binary
   rounding error that is unacceptable for financial data (ARR/MRR must
   reconcile to the penny). Numeric maps to DECIMAL in Postgres/SQLite.

5. Every table has created_at/updated_at audit timestamps in addition to
   the business-meaningful dates (created_date, close_date, hire_date)
   requested in the spec. This mirrors real CRM systems (Salesforce,
   HubSpot) where "record created in the system" and "business event
   date" are tracked separately and often differ (e.g. an opportunity is
   backfilled into the CRM days after it was actually created).

6. Indexes are added on every foreign key and on columns used heavily in
   analytics filtering (stage, close_date, industry, region) since the
   analytics layer will do a lot of GROUP BY / WHERE on these.
"""

from datetime import datetime, date

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    Date,
    DateTime,
    ForeignKey,
    Text,
    Index,
    CheckConstraint,
)
from sqlalchemy.orm import relationship, validates

from app.extensions import db

# ---------------------------------------------------------------------------
# Controlled vocabularies (enforced in the application layer -- see design
# decision #3 above). Centralizing these here means the ETL, API validation,
# and dashboard all import from one source of truth.
# ---------------------------------------------------------------------------

STAGE_CHOICES = [
    "Prospecting",
    "Qualification",
    "Needs Analysis",
    "Proposal",
    "Negotiation",
    "Closed Won",
    "Closed Lost",
]

CLOSED_STAGES = {"Closed Won", "Closed Lost"}
OPEN_STAGES = [s for s in STAGE_CHOICES if s not in CLOSED_STAGES]

COMPANY_SIZE_CHOICES = ["SMB", "Mid-Market", "Enterprise"]

ACTIVITY_TYPE_CHOICES = ["Call", "Email", "Meeting", "Demo", "Proposal Sent", "Contract Sent"]


class SalesRep(db.Model):
    """A quota-carrying sales representative (Account Executive)."""

    __tablename__ = "sales_reps"

    rep_id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    region = Column(String(50), nullable=False, index=True)
    hire_date = Column(Date, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    opportunities = relationship("Opportunity", back_populates="rep")
    activities = relationship("Activity", back_populates="rep")

    def __repr__(self):
        return f"<SalesRep {self.rep_id} {self.first_name} {self.last_name} ({self.region})>"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def to_dict(self):
        return {
            "rep_id": self.rep_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "region": self.region,
            "hire_date": self.hire_date.isoformat() if self.hire_date else None,
        }


class Account(db.Model):
    """A customer / prospect company (the B2B buying entity)."""

    __tablename__ = "accounts"

    account_id = Column(Integer, primary_key=True, autoincrement=True)
    company_name = Column(String(150), nullable=False, index=True)
    industry = Column(String(80), nullable=False, index=True)
    company_size = Column(String(20), nullable=False, index=True)
    location = Column(String(100), nullable=False)
    created_date = Column(Date, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    contacts = relationship("Contact", back_populates="account", cascade="all, delete-orphan")
    opportunities = relationship("Opportunity", back_populates="account", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "company_size IN ('SMB', 'Mid-Market', 'Enterprise')", name="ck_account_company_size"
        ),
    )

    def __repr__(self):
        return f"<Account {self.account_id} {self.company_name}>"

    def to_dict(self):
        return {
            "account_id": self.account_id,
            "company_name": self.company_name,
            "industry": self.industry,
            "company_size": self.company_size,
            "location": self.location,
            "created_date": self.created_date.isoformat() if self.created_date else None,
        }


class Contact(db.Model):
    """A person (buyer/champion/decision-maker) at a customer account."""

    __tablename__ = "contacts"

    contact_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    job_title = Column(String(100), nullable=False)
    email = Column(String(150), nullable=False, unique=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    account = relationship("Account", back_populates="contacts")

    def __repr__(self):
        return f"<Contact {self.contact_id} {self.name}>"

    def to_dict(self):
        return {
            "contact_id": self.contact_id,
            "account_id": self.account_id,
            "name": self.name,
            "job_title": self.job_title,
            "email": self.email,
        }


class Opportunity(db.Model):
    """A sales deal (pipeline opportunity) tied to an account and a rep."""

    __tablename__ = "opportunities"

    opportunity_id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("accounts.account_id", ondelete="CASCADE"), nullable=False, index=True)
    rep_id = Column(Integer, ForeignKey("sales_reps.rep_id", ondelete="SET NULL"), nullable=True, index=True)
    opportunity_name = Column(String(200), nullable=False)
    stage = Column(String(30), nullable=False, index=True)
    deal_value = Column(Numeric(12, 2), nullable=False)
    created_date = Column(Date, nullable=False, index=True)
    close_date = Column(Date, nullable=True, index=True)  # NULL while open; set on Closed Won/Lost

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    account = relationship("Account", back_populates="opportunities")
    rep = relationship("SalesRep", back_populates="opportunities")
    activities = relationship("Activity", back_populates="opportunity", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(f"stage IN {tuple(STAGE_CHOICES)}", name="ck_opportunity_stage"),
        CheckConstraint("deal_value >= 0", name="ck_opportunity_deal_value_nonneg"),
        Index("ix_opportunities_stage_close_date", "stage", "close_date"),
    )

    @validates("stage")
    def validate_stage(self, key, value):
        if value not in STAGE_CHOICES:
            raise ValueError(f"Invalid stage '{value}'. Must be one of {STAGE_CHOICES}")
        return value

    @property
    def is_closed(self):
        return self.stage in CLOSED_STAGES

    @property
    def is_won(self):
        return self.stage == "Closed Won"

    def __repr__(self):
        return f"<Opportunity {self.opportunity_id} {self.opportunity_name} [{self.stage}] ${self.deal_value}>"

    def to_dict(self):
        return {
            "opportunity_id": self.opportunity_id,
            "account_id": self.account_id,
            "rep_id": self.rep_id,
            "opportunity_name": self.opportunity_name,
            "stage": self.stage,
            "deal_value": float(self.deal_value) if self.deal_value is not None else None,
            "created_date": self.created_date.isoformat() if self.created_date else None,
            "close_date": self.close_date.isoformat() if self.close_date else None,
        }


class Activity(db.Model):
    """A logged sales touchpoint (call, email, demo, etc.) against a deal."""

    __tablename__ = "activities"

    activity_id = Column(Integer, primary_key=True, autoincrement=True)
    opportunity_id = Column(
        Integer, ForeignKey("opportunities.opportunity_id", ondelete="CASCADE"), nullable=False, index=True
    )
    rep_id = Column(Integer, ForeignKey("sales_reps.rep_id", ondelete="SET NULL"), nullable=True, index=True)
    activity_type = Column(String(30), nullable=False, index=True)
    activity_date = Column(Date, nullable=False, index=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    opportunity = relationship("Opportunity", back_populates="activities")
    rep = relationship("SalesRep", back_populates="activities")

    __table_args__ = (
        CheckConstraint(f"activity_type IN {tuple(ACTIVITY_TYPE_CHOICES)}", name="ck_activity_type"),
    )

    def __repr__(self):
        return f"<Activity {self.activity_id} {self.activity_type} on opp {self.opportunity_id}>"

    def to_dict(self):
        return {
            "activity_id": self.activity_id,
            "opportunity_id": self.opportunity_id,
            "rep_id": self.rep_id,
            "activity_type": self.activity_type,
            "activity_date": self.activity_date.isoformat() if self.activity_date else None,
            "notes": self.notes,
        }
