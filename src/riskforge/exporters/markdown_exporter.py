"""Markdown exporter: produces a human-readable RMF summary."""

from __future__ import annotations

from riskforge.exporters.base import Exporter
from riskforge.models.rmf import RiskManagementFile


class MarkdownExporter(Exporter):
    """Exports the RiskManagementFile as a Markdown document.

    Suitable for inclusion in GitHub repositories, Confluence pages,
    or any system that renders Markdown.
    """

    def render(self, rmf: RiskManagementFile) -> bytes:
        reg = rmf.register
        sys = reg.system
        lines: list[str] = []

        lines.append(f"# Risk Management File: {sys.name} v{sys.version}")
        lines.append("")
        lines.append(f"**Provider:** {sys.provider_name}")
        lines.append(f"**Purpose:** {sys.purpose}")
        lines.append(f"**Generated:** {rmf.generated_at.date().isoformat()}")
        lines.append(f"**RMF Schema Version:** {rmf.rmf_schema_version}")
        lines.append(f"**SHA-256:** `{rmf.sha256_hash}`")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Assessor")
        lines.append(f"- **Name:** {reg.assessor_name}")
        lines.append(f"- **Role:** {reg.assessor_role}")
        lines.append(f"- **Assessment Date:** {reg.assessment_date.date().isoformat()}")
        lines.append(f"- **Review Date:** {reg.review_date.date().isoformat()}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"## Risk Items ({len(reg.items)} total)")
        lines.append("")

        # Group by dimension
        from riskforge.models.risk import RiskDimension

        for dim in RiskDimension:
            dim_items = [i for i in reg.items if i.dimension == dim]
            if not dim_items:
                continue
            lines.append(f"### {dim.value.replace('_', ' ').title()}")
            lines.append("")
            for item in dim_items:
                band_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(
                    item.risk_band, "⚪"
                )
                lines.append(
                    f"**{band_emoji} {item.title}** "
                    f"(Score: {item.risk_score} → Residual: {item.residual_risk_score})"
                )
                lines.append(f"> {item.description}")
                if item.article_refs:
                    lines.append(f"> *Article refs: {', '.join(item.article_refs)}*")
                if item.accepted:
                    lines.append(f"> *Accepted: {item.acceptance_rationale}*")
                lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Disclosure")
        lines.append("")
        lines.append(f"*{rmf.disclosure}*")
        lines.append("")

        return "\n".join(lines).encode("utf-8")
