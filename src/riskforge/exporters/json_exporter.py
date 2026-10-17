"""JSON exporter: serialises RMF to canonical UTF-8 JSON."""

from __future__ import annotations

import json

from riskforge.exporters.base import Exporter
from riskforge.models.rmf import RiskManagementFile, rmf_document


class JSONExporter(Exporter):
    """Exports the RiskManagementFile as a pretty-printed JSON document.

    The output is schema-validated by ExportEngine before this render()
    call, so this exporter only handles serialisation.
    """

    def render(self, rmf: RiskManagementFile) -> bytes:
        data = rmf_document(rmf)
        text = json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False)
        return (text + "\n").encode("utf-8")
