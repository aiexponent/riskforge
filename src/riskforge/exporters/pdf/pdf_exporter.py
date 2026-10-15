"""PDF exporter: renders RMF to PDF via WeasyPrint and Jinja2."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from riskforge.exporters.base import Exporter
from riskforge.models.risk import RiskDimension
from riskforge.models.rmf import RiskManagementFile

TEMPLATE_DIR = Path(__file__).parent / "templates"


def report_css() -> str:
    """The report stylesheet, read from package data so any install layout finds it."""
    return files("riskforge.exporters.pdf").joinpath("templates", "report.css").read_text("utf-8")


class PDFExporter(Exporter):
    """Renders the RiskManagementFile to a PDF using WeasyPrint.

    The HTML template lives at exporters/pdf/templates/report.html.
    Brand changes are CSS-only: edit templates/report.css.
    No LibreOffice or wkhtmltopdf required, pure Python.
    """

    def __init__(self) -> None:
        self._env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )

    def render_html(self, rmf: RiskManagementFile) -> str:
        """Return the report HTML that :meth:`render` turns into a PDF."""
        # Imported here: the engine package loads the exporters through the plugin registry.
        from riskforge import __version__
        from riskforge.engine.validate import GateStatus, ValidateEngine

        register = rmf.register
        gates = ValidateEngine().run(register)
        failing = [gate.gate_id for gate in gates if gate.status == GateStatus.FAIL]
        system_id = str(register.system.id)
        category = register.system.annex_iii_category
        return self._env.get_template("report.html").render(
            rmf=rmf,
            register=register,
            system=register.system,
            items=register.items,
            dimensions=[dimension.value for dimension in RiskDimension],
            gates=gates,
            status_line=(
                "All FAIL gates pass"
                if not failing
                else "Exported with failing gates: " + ", ".join(failing)
            ),
            category_label=(
                category.value.replace("_", " ").title() if category else "Not classified"
            ),
            patterns_used=sorted(
                {
                    tag.split(":", 1)[1]
                    for item in register.items
                    for tag in item.tags
                    if tag.startswith("pattern:")
                }
            ),
            change_log=(
                [e for e in rmf.chain_proof.entries if e.system_id in (system_id, "")]
                if rmf.chain_proof
                else []
            ),
            riskforge_version=__version__,
        )

    def render(self, rmf: RiskManagementFile) -> bytes:
        html_content = self.render_html(rmf)
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

            from weasyprint import CSS, HTML
        except ImportError as e:
            raise RuntimeError(
                "WeasyPrint is required for PDF export. "
                "Install with: pip install riskforge  (WeasyPrint is a core dependency)"
            ) from e
        # No base_url: the report loads nothing by URL, so nothing resolves against one.
        return HTML(string=html_content).write_pdf(stylesheets=[CSS(string=report_css())])
