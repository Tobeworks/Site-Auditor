__version__ = "1.2.0"

from auditor.runner import run_audit
from auditor.report import build as build_report

__all__ = ["run_audit", "build_report", "__version__"]
