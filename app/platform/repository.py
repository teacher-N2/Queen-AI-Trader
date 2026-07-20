import json
import os
from pathlib import Path
from threading import RLock
from typing import Generic, TypeVar

from pydantic import BaseModel

from ..config import settings

T = TypeVar("T", bound=BaseModel)


class JsonRepository(Generic[T]):
    schema_version = "platform-repository-v1"

    def __init__(self, filename: str, model: type[T], storage_dir: Path = settings.storage_dir / "platform"):
        self.path = storage_dir / filename
        self.model = model
        self._lock = RLock()

    def all(self) -> list[T]:
        with self._lock:
            if not self.path.exists():
                return []
            data = json.loads(self.path.read_text(encoding="utf-8"))
            records = data.get("records", [])
            return [self.model.model_validate(record) for record in records]

    def replace_all(self, records: list[T]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": self.schema_version,
                "records": [record.model_dump(mode="json") for record in records],
            }
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
