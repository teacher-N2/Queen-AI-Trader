from .analytics_models import AnalyticsFilter, AnalyticsReport
from .analytics_reports import AnalyticsReportBuilder, analytics_report_builder
from .analytics_storage import AnalyticsStorage, analytics_storage


class AnalyticsEngine:
    def __init__(
        self,
        storage: AnalyticsStorage = analytics_storage,
        report_builder: AnalyticsReportBuilder = analytics_report_builder,
    ):
        self.storage = storage
        self.report_builder = report_builder

    def generate_report(self, filters: AnalyticsFilter | None = None, *, use_cache: bool = True) -> AnalyticsReport:
        fingerprint = self.storage.source_fingerprint()
        cache_key = {
            "fingerprint": fingerprint,
            "filters": (filters or AnalyticsFilter()).model_dump(mode="json"),
        }
        if use_cache:
            cached = self.storage.read_cache()
            if cached and cached.get("cache_key") == cache_key and isinstance(cached.get("report"), dict):
                return AnalyticsReport.model_validate(cached["report"])

        report = self.report_builder.build(
            self.storage.load_trades(),
            audit_records=self.storage.load_audit_history(),
            delivery_records=self.storage.load_delivery_history(),
            filters=filters,
        )
        self.storage.write_cache({"cache_key": cache_key, "report": report.model_dump(mode="json")})
        return report


analytics_engine = AnalyticsEngine()
