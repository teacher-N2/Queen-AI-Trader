from .models import MessageEnvelope, RoutedEvent


class MessageBuilder:
    def build(self, routed_event: RoutedEvent, output_format: str = "telegram_markdown") -> MessageEnvelope:
        signal = routed_event.payload
        targets = ", ".join(f"{target.name}: {target.price:g}" for target in signal.targets) or "-"
        reason_codes = ", ".join(signal.reason_codes) or "-"
        lines = [
            "*Queen Engine*",
            f"*Event:* `{signal.event.value}`",
            f"*Symbol:* `{signal.symbol}` | `{signal.timeframe}`",
            f"*Direction:* `{signal.direction.value}`",
            f"*Action:* `{signal.action.value}`",
            f"*Actionability:* `{signal.actionability.value}`",
            f"*Signal:* `{signal.signal_id}`",
            f"*Trade:* `{signal.trade_id or '-'}`",
            f"*Entry:* `{signal.entry_price if signal.entry_price is not None else '-'}`",
            f"*Stop:* `{signal.stop_price if signal.stop_price is not None else '-'}`",
            f"*Targets:* `{targets}`",
            f"*Remaining:* `{signal.remaining_position if signal.remaining_position is not None else '-'}`",
            f"*Session:* `{signal.session or '-'}`",
            f"*Reasons:* `{reason_codes}`",
        ]
        if signal.message:
            lines.append("")
            lines.append(signal.message)
        lines.append("")
        lines.append("_Notification only. No broker execution is performed._")
        return MessageEnvelope(
            payload=signal,
            route=routed_event.route,
            format="telegram_markdown",
            body="\n".join(lines),
        )


message_builder = MessageBuilder()
