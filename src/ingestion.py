"""
Ingestion layer — source-agnostic by design.

Every source (local folder, telephony vendor, CRM export) implements the
same Adapter interface and returns the same RawCallRecord shape.
The rest of the pipeline (transcription, analysis, storage) never knows
or cares which vendor a call came from. To add a new vendor: write one
new Adapter subclass, register it, done — no changes anywhere else.
"""
import os
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class RawCallRecord:
    """The common shape every source must normalize into."""
    call_uid: str           # stable idempotency key — same call ingested twice yields same uid
    audio_path: str         # local path to the audio (downloaded if remote)
    advisor_name: str
    customer_ref: str       # pseudonymous id — never raw phone number, PII policy starts here
    call_datetime: datetime
    source: str              # e.g. "local_folder", "exotel", "crm_export"
    source_ref: str          # original identifier from the source system


class SourceAdapter(ABC):
    """All ingestion sources implement this. Nothing else in the pipeline
    is allowed to import a vendor-specific type."""

    @abstractmethod
    def list_new_calls(self) -> List[RawCallRecord]:
        ...


def make_call_uid(*parts: str) -> str:
    """Deterministic id from stable inputs -> re-ingesting the same file
    twice produces the same uid, which is how we get idempotency
    (see storage.py: INSERT ... ON CONFLICT DO NOTHING on call_uid)."""
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


class LocalFolderAdapter(SourceAdapter):
    """
    Stand-in for FitNova's real sources during this prototype: a folder of
    call recordings + a metadata sidecar per file (what a CRM export or a
    telephony vendor's batch API would give you). This is the ONE mocked
    piece named explicitly in the README — everything downstream of this
    (transcription, scoring, storage, dashboard) runs on real data.

    Filename convention used here: {advisor_name}__{customer_ref}__{unixts}.wav
    A real vendor adapter (ExotelAdapter, CRMExportAdapter, etc.) would
    replace filename parsing with an API call / CSV parse, but must still
    return List[RawCallRecord] — that's the whole point of the interface.
    """

    def __init__(self, folder_path: str):
        self.folder_path = folder_path

    def list_new_calls(self) -> List[RawCallRecord]:
        records = []
        for fname in sorted(os.listdir(self.folder_path)):
            if not fname.endswith(".wav"):
                continue
            path = os.path.join(self.folder_path, fname)
            advisor_name, customer_ref = self._parse_filename(fname)
            uid = make_call_uid("local_folder", fname)
            records.append(RawCallRecord(
                call_uid=uid,
                audio_path=path,
                advisor_name=advisor_name,
                customer_ref=customer_ref,
                call_datetime=datetime.fromtimestamp(os.path.getmtime(path)),
                source="local_folder",
                source_ref=fname,
            ))
        return records

    def _parse_filename(self, fname: str):
        # our synthetic files are named call_good_001.wav etc — map them to
        # the advisors we seeded, so the demo has a sensible advisor attached
        stem = fname.replace(".wav", "")
        mapping = {
            "call_good_001": ("Priya", "cust_reham_9821"),
            "call_bad_001": ("Vikram", "cust_sneha_4410"),
            "call_nonsales_001": ("Priya", "cust_wrongnum_0001"),
        }
        return mapping.get(stem, ("Unknown", f"cust_{stem}"))


def get_adapter(source_name: str, **kwargs) -> SourceAdapter:
    """Factory — this is the only place that knows adapter names.
    Adding a vendor: write the class above, add one line here."""
    registry = {
        "local_folder": LocalFolderAdapter,
    }
    if source_name not in registry:
        raise ValueError(f"Unknown source '{source_name}'. Available: {list(registry)}")
    return registry[source_name](**kwargs)
