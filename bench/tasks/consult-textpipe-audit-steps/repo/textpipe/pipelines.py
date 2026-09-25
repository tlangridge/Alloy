from textpipe.stages import Dedupe, Normalize, Redact, Truncate


class ExportPipeline(Redact, Dedupe):
    """Cleaning applied before exporting transcripts to customers."""


class SearchPipeline(Normalize):
    """Cleaning applied before indexing for search."""


class AuditPipeline(Truncate, Redact, Dedupe):
    """Cleaning applied before writing to the audit log."""

    def steps(self):
        return super().steps() + ['audit']


PIPELINES = {
    'audit': AuditPipeline,
    'export': ExportPipeline,
    'search': SearchPipeline,
}
