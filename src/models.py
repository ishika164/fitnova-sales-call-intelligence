"""
Data model for FitNova Sales-Call Intelligence.

Design principle: org structure (Org -> Team -> Advisor) is DATA, not config.
Adding a new team or advisor is a row insert, never a code change.
"""
from datetime import datetime
from sqlalchemy import ( # type: ignore
    create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker # type: ignore

Base = declarative_base()


class Org(Base):
    __tablename__ = "orgs"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    teams = relationship("Team", back_populates="org")


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("orgs.id"), nullable=False)
    name = Column(String, nullable=False)
    team_leader_name = Column(String)
    org = relationship("Org", back_populates="teams")
    advisors = relationship("Advisor", back_populates="team")


class Advisor(Base):
    __tablename__ = "advisors"
    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    name = Column(String, nullable=False)
    team = relationship("Team", back_populates="advisors")
    calls = relationship("Call", back_populates="advisor")


class Call(Base):
    __tablename__ = "calls"
    id = Column(Integer, primary_key=True)
    call_uid = Column(String, unique=True, nullable=False)  # idempotency key (e.g. source filename/hash)
    advisor_id = Column(Integer, ForeignKey("advisors.id"), nullable=False)
    source = Column(String)              # e.g. "local_folder", "exotel", "crm_export"
    source_ref = Column(String)          # original file path / vendor call id
    customer_ref = Column(String)        # anonymized/pseudonymous customer id, never raw phone number
    call_datetime = Column(DateTime, default=datetime.utcnow)
    duration_seconds = Column(Float)
    status = Column(String, default="ingested")  # ingested -> transcribing -> scoring -> done -> failed
    is_sales_call = Column(Boolean, default=True)  # false for non-sales edge case (wrong number, internal)
    diarization_method = Column(String)  # "pyannote" | "heuristic_fallback"
    pii_redacted = Column(Boolean, default=False)
    processing_error = Column(Text)

    advisor = relationship("Advisor", back_populates="calls")
    segments = relationship("TranscriptSegment", back_populates="call")
    score = relationship("CallScore", back_populates="call", uselist=False)
    flags = relationship("IssueFlag", back_populates="call")


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    id = Column(Integer, primary_key=True)
    call_id = Column(Integer, ForeignKey("calls.id"), nullable=False)
    speaker = Column(String)   # "Advisor" | "Customer" | "Unknown"
    start_time = Column(Float)
    end_time = Column(Float)
    text = Column(Text)
    call = relationship("Call", back_populates="segments")


class CallScore(Base):
    __tablename__ = "call_scores"
    id = Column(Integer, primary_key=True)
    call_id = Column(Integer, ForeignKey("calls.id"), unique=True, nullable=False)
    needs_discovery = Column(Float)
    product_knowledge = Column(Float)
    objection_handling = Column(Float)
    compliance = Column(Float)
    next_step_booking = Column(Float)
    overall_score = Column(Float)
    model_used = Column(String)
    scored_at = Column(DateTime, default=datetime.utcnow)
    call = relationship("Call", back_populates="score")


class IssueFlag(Base):
    __tablename__ = "issue_flags"
    id = Column(Integer, primary_key=True)
    call_id = Column(Integer, ForeignKey("calls.id"), nullable=False)
    tag = Column(String, nullable=False)       # e.g. "over_promising"
    severity = Column(String, nullable=False)  # "low" | "medium" | "high"
    quoted_line = Column(Text)
    timestamp = Column(Float)
    reason = Column(Text)
    status = Column(String, default="open")    # open | contested | upheld | dismissed
    call = relationship("Call", back_populates="flags")
    contest = relationship("FlagContest", back_populates="flag", uselist=False)


class FlagContest(Base):
    __tablename__ = "flag_contests"
    id = Column(Integer, primary_key=True)
    flag_id = Column(Integer, ForeignKey("issue_flags.id"), unique=True, nullable=False)
    advisor_comment = Column(Text)
    contested_at = Column(DateTime, default=datetime.utcnow)
    resolution = Column(String, default="pending")  # pending | upheld | dismissed
    leader_comment = Column(Text)
    flag = relationship("IssueFlag", back_populates="contest")


def get_engine(db_path="data/fitnova.db"):
    return create_engine(f"sqlite:///{db_path}")


def init_db(db_path="data/fitnova.db"):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def get_session(db_path="data/fitnova.db"):
    engine = get_engine(db_path)
    Session = sessionmaker(bind=engine)
    return Session()
