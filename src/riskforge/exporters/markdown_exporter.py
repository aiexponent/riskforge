"""Markdown exporter: produces a human-readable RMF summary."""

from __future__ import annotations

import re

from riskforge.exporters.base import Exporter
from riskforge.models.rmf import RiskManagementFile

_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]#|~!])")
_LINE_BREAKS = re.compile(r"\s*[\r\n\u0085\u2028\u2029]+\s*")
_LIST_MARKER = re.compile(r"^(\s*\d*)([-+]|(?<=\d)[.)])(?=\s|$)")


def _md(text: str) -> str:
    """Return user text as literal Markdown: no markup, HTML or line structure of its own.

    Line breaks become one space so a field cannot end the block quote it sits in, and a
    leading list marker is escaped. The register keeps the text as entered.
    """
    text = _LINE_BREAKS.sub(" ", text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = _MARKDOWN_SPECIAL.sub(r"\\\1", text)
    # CommonMark reads a backslash before a digit literally: escape only the punctuation.
    return _LIST_MARKER.sub(r"\1\\\2", text)


class MarkdownExporter(Exporter):
    """Exports the RiskManagementFile as a Markdown document.

    Suitable for inclusion in GitHub repositories, Confluence pages,
    or any system that renders Markdown.
    """

    def render(self, rmf: RiskManagementFile) -> bytes:
        reg = rmf.register
        sys = reg.system
        lines: list[str] = []

        lines.append(f"# Risk Management File: {_md(sys.name)} v{_md(sys.version)}")
        lines.append("")
        lines.append(f"**Provider:** {_md(sys.provider_name)}")
        lines.append(f"**Purpose:** {_md(sys.purpose)}")
        lines.append(f"**Generated:** {rmf.generated_at.date().isoformat()}")
        lines.append(f"**RMF Schema Version:** {rmf.rmf_schema_version}")
        lines.append(f"**SHA-256:** `{rmf.sha256_hash}`")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Assessor")
        lines.append(f"- **Name:** {_md(reg.assessor_name)}")
        lines.append(f"- **Role:** {_md(reg.assessor_role)}")
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
                    f"**{band_emoji} {_md(item.title)}** "
                    f"(Score: {item.risk_score} → Residual: {item.residual_risk_score})"
                )
                lines.append(f"> {_md(item.description)}")
                if item.article_refs:
                    lines.append(f"> *Article refs: {_md(', '.join(item.article_refs))}*")
                for m in item.mitigations:
                    vague = " (flagged: generic language)" if m.is_vague else ""
                    who = f"Owner: {_md(m.owner)}"
                    if m.recorded_by:
                        who += f"; Recorded by: {_md(m.recorded_by)}"
                    lines.append(
                        f"> - *Mitigation ({m.control_type}, {m.status}):* "
                        f"{_md(m.description)}{vague} ({who})"
                    )
                if item.accepted:
                    lines.append(f"> *Accepted: {_md(item.acceptance_rationale)}*")
                    lines.append(f"> *Accepted by: {_md(item.accepted_by or 'not recorded')}*")
                lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("## Disclosure")
        lines.append("")
        lines.append(f"*{rmf.disclosure}*")
        lines.append("")

        return "\n".join(lines).encode("utf-8")
