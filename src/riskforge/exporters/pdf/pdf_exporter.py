"""PDF exporter — renders RMF to PDF via WeasyPrint and Jinja2."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from riskforge.exporters.base import Exporter
from riskforge.models.rmf import RiskManagementFile


class PDFExporter(Exporter):
    """Renders the RiskManagementFile to a PDF using WeasyPrint.

    The HTML template lives at exporters/pdf/templates/report.html.
    Brand changes are CSS-only: edit templates/report.css.
    No LibreOffice or wkhtmltopdf required — pure Python.
    """

    def __init__(self) -> None:
        template_dir = Path(__file__).parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html"]),
        )

    def render(self, rmf: RiskManagementFile) -> bytes:
        template = self._env.get_template("report.html")
        html_content = template.render(
            rmf=rmf,
            register=rmf.register,
            system=rmf.register.system,
            items=rmf.register.items,
            risk_band_colour={
                "low": "#22c55e",
                "medium": "#eab308",
                "high": "#f97316",
                "critical": "#ef4444",
            },
        )

        try:
            import os
            import sys

            if sys.platform == "darwin":
                # Ensure Homebrew library paths are available for dyld / ctypes / cffi
                for path in ("/opt/homebrew/lib", "/usr/local/lib"):
                    if os.path.isdir(path):
                        curr = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
                        if path not in curr.split(":"):
                            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
                                f"{path}:{curr}" if curr else path
                            )

            from weasyprint import HTML

            return HTML(string=html_content).write_pdf()
        except ImportError as e:
            raise RuntimeError(
                "WeasyPrint is required for PDF export. "
                "Install with: pip install riskforge  (WeasyPrint is a core dependency)"
            ) from e
