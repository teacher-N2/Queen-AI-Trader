from .models import PlatformSetting
from .repository import JsonRepository


class SettingsRepository:
    def __init__(self, repo: JsonRepository[PlatformSetting] | None = None):
        self.repo = repo or JsonRepository("settings.json", PlatformSetting)

    def list(self) -> list[PlatformSetting]:
        return self.repo.all()

    def get(self, key: str) -> PlatformSetting | None:
        for setting in self.repo.all():
            if setting.key == key:
                return setting
        return None

    def set(self, setting: PlatformSetting) -> PlatformSetting:
        settings = self.repo.all()
        for index, existing in enumerate(settings):
            if existing.key == setting.key:
                settings[index] = setting
                self.repo.replace_all(settings)
                return setting
        settings.append(setting)
        self.repo.replace_all(settings)
        return setting


settings_repository = SettingsRepository()
