from .enums import WorkspaceStatus
from .errors import WorkspaceAlreadyExistsError, WorkspaceNotFoundError
from .models import Workspace, now_iso
from .repository import JsonRepository


class WorkspaceRepository:
    def __init__(self, repo: JsonRepository[Workspace] | None = None):
        self.repo = repo or JsonRepository("workspaces.json", Workspace)

    def create(self, workspace: Workspace) -> Workspace:
        workspaces = self.repo.all()
        if any(existing.slug == workspace.slug and existing.status != WorkspaceStatus.DELETED for existing in workspaces):
            raise WorkspaceAlreadyExistsError("workspace already exists")
        workspaces.append(workspace)
        self.repo.replace_all(workspaces)
        return workspace

    def get_by_id(self, workspace_id: str) -> Workspace:
        for workspace in self.repo.all():
            if workspace.workspace_id == workspace_id:
                return workspace
        raise WorkspaceNotFoundError("workspace not found")

    def get_by_slug(self, slug: str) -> Workspace | None:
        for workspace in self.repo.all():
            if workspace.slug == slug and workspace.status != WorkspaceStatus.DELETED:
                return workspace
        return None

    def list(self, *, limit: int = 50, offset: int = 0) -> list[Workspace]:
        return self.repo.all()[offset : offset + min(limit, 100)]

    def update(self, workspace: Workspace) -> Workspace:
        workspaces = self.repo.all()
        for index, existing in enumerate(workspaces):
            if existing.workspace_id == workspace.workspace_id:
                workspace.updated_at = now_iso()
                workspace.version += 1
                workspaces[index] = workspace
                self.repo.replace_all(workspaces)
                return workspace
        raise WorkspaceNotFoundError("workspace not found")


workspace_repository = WorkspaceRepository()
