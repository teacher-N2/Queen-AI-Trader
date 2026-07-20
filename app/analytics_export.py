import csv
import io
import json
from pathlib import Path

from .analytics_errors import ExportError
from .analytics_models import AnalyticsReport
from .analytics_storage import AnalyticsStorage, analytics_storage


class AnalyticsExportService:
    def __init__(self, storage: AnalyticsStorage = analytics_storage):
        self.storage = storage

    def to_json(self, report: AnalyticsReport) -> str:
        return json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2)

    def to_csv(self, report: AnalyticsReport) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["section", "group", "metric", "value"])
        self._write_model(writer, "overall", "all", report.overall.model_dump())
        self._write_model(writer, "risk", "all", report.risk.model_dump())
        self._write_model(writer, "lifecycle", "all", report.lifecycle.model_dump())
        self._write_model(writer, "quality", "all", report.quality.model_dump())
        for group in report.sessions:
            self._write_model(writer, "session", group.group, group.overall.model_dump())
            self._write_model(writer, "session_risk", group.group, group.risk.model_dump())
        for group in report.symbols:
            self._write_model(writer, "symbol", group.group, group.overall.model_dump())
            self._write_model(writer, "symbol_risk", group.group, group.risk.model_dump())
        for group in report.timeframes:
            self._write_model(writer, "timeframe", group.group, group.overall.model_dump())
            self._write_model(writer, "timeframe_risk", group.group, group.risk.model_dump())
        return output.getvalue()

    def export(self, report: AnalyticsReport, export_format: str) -> Path:
        normalized = export_format.lower()
        if normalized == "json":
            report.export_format = "json"
            return self.storage.write_export("analytics_report.json", self.to_json(report))
        if normalized == "csv":
            report.export_format = "csv"
            return self.storage.write_export("analytics_report.csv", self.to_csv(report))
        raise ExportError("unsupported analytics export format")

    def _write_model(self, writer: csv.writer, section: str, group: str, payload: dict) -> None:
        for metric, value in payload.items():
            writer.writerow([section, group, metric, value])


analytics_export_service = AnalyticsExportService()
