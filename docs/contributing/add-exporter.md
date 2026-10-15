# How to Add a Custom Exporter

Exporters convert the `RiskManagementFile` to a target format (JSON, PDF, Markdown, etc.). Built-in exporters live in `src/riskforge/exporters/`. Custom exporters ship as separate PyPI packages.

## Step 1: Implement the Exporter ABC

```python
from riskforge.exporters.base import Exporter
from riskforge.models.rmf import RiskManagementFile


class MyExporter(Exporter):
    def render(self, rmf: RiskManagementFile) -> bytes:
        # Serialise the RMF to your target format
        # Return bytes — the ExportEngine handles file writing
        return b"..."
```

## Step 2: Register the entry point

In your `pyproject.toml`:

```toml
[project.entry-points."riskforge.exporters"]
myformat = "mypkg.my_exporter:MyExporter"
```

After `pip install mypkg`, RiskForge will discover your exporter automatically:

```bash
riskforge export --system-id <id> --format myformat
```

## Step 3: Test

The ExportEngine calls `render()` after:
1. Computing the content digest (`riskforge.integrity.rmf.content_digest`)
2. Schema validation against RMF schema 1.1.0 (`rmf-1.1.0.schema.json`)

Your exporter only needs to handle serialisation. The `rmf` object passed to `render()` is fully populated and validated.

## Publishing

Name your package `riskforge-<format>` (e.g. `riskforge-docx`, `riskforge-csv`) for discoverability.
