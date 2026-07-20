from .config import settings
from .models import Actionability, QueenSignalPayload, RoutedEvent, SignalEvent


class RoutingService:
    def route(self, signal: QueenSignalPayload, correlation_id: str) -> RoutedEvent:
        if signal.actionability == Actionability.ACTIONABLE:
            route = "actionable"
            priority = 90
        elif signal.actionability == Actionability.MANAGEMENT:
            route = "management"
            priority = 70
        elif signal.actionability == Actionability.TERMINAL:
            route = "terminal"
            priority = 95
        elif signal.event in {SignalEvent.SETUP_QUALIFIED_SIGNAL, SignalEvent.ENTRY_READY_SIGNAL}:
            route = "preparation"
            priority = 40
        else:
            route = "informational"
            priority = 20

        return RoutedEvent(
            payload=signal,
            route=route,
            destinations=list(settings.telegram_chat_ids),
            priority=priority,
            correlation_id=correlation_id,
        )


routing_service = RoutingService()
