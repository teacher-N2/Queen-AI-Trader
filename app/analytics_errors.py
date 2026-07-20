from .errors import QueenGatewayError


class AnalyticsError(QueenGatewayError):
    status_code = 500
    code = "analytics_error"


class MissingDataError(AnalyticsError):
    status_code = 404
    code = "analytics_missing_data"


class InvalidMetricError(AnalyticsError):
    status_code = 422
    code = "analytics_invalid_metric"


class ExportError(AnalyticsError):
    code = "analytics_export_error"
