"""Data models for validation and recovery results."""
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Issue:
    severity: Severity
    message: str
    detail: str = ""


@dataclass
class ValidationResult:
    path: Path
    issues: list[Issue] = field(default_factory=list)
    rocksdb_readable: bool = False
    world_json_valid: bool = False

    @property
    def healthy(self) -> bool:
        return not any(i.severity in (Severity.ERROR, Severity.CRITICAL) for i in self.issues)

    @property
    def severity(self) -> Severity:
        if not self.issues:
            return Severity.OK
        return max(self.issues, key=lambda i: list(Severity).index(i.severity)).severity


@dataclass
class RecoveryResult:
    success: bool
    operations: list[str] = field(default_factory=list)
    recovered_path: Path | None = None
    error: str = ""
