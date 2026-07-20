from .enums import MembershipStatus, PlatformRole
from .errors import FinalWorkspaceOwnerError, MembershipConflictError, MembershipNotFoundError
from .models import WorkspaceMembership, now_iso
from .repository import JsonRepository


class MembershipRepository:
    def __init__(self, repo: JsonRepository[WorkspaceMembership] | None = None):
        self.repo = repo or JsonRepository("memberships.json", WorkspaceMembership)

    def create(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        memberships = self.repo.all()
        if any(item.workspace_id == membership.workspace_id and item.user_id == membership.user_id and item.status == MembershipStatus.ACTIVE for item in memberships):
            raise MembershipConflictError("active membership already exists")
        if membership.role in {PlatformRole.PLATFORM_OWNER, PlatformRole.PLATFORM_ADMIN}:
            raise MembershipConflictError("platform roles cannot be granted as memberships")
        memberships.append(membership)
        self.repo.replace_all(memberships)
        return membership

    def get(self, membership_id: str) -> WorkspaceMembership:
        for membership in self.repo.all():
            if membership.membership_id == membership_id:
                return membership
        raise MembershipNotFoundError("membership not found")

    def list_by_workspace(self, workspace_id: str) -> list[WorkspaceMembership]:
        return [membership for membership in self.repo.all() if membership.workspace_id == workspace_id]

    def list_by_user(self, user_id: str) -> list[WorkspaceMembership]:
        return [membership for membership in self.repo.all() if membership.user_id == user_id]

    def update(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        memberships = self.repo.all()
        for index, existing in enumerate(memberships):
            if existing.membership_id == membership.membership_id:
                membership.updated_at = now_iso()
                memberships[index] = membership
                self.repo.replace_all(memberships)
                return membership
        raise MembershipNotFoundError("membership not found")

    def remove(self, membership_id: str) -> WorkspaceMembership:
        membership = self.get(membership_id)
        if membership.role == PlatformRole.WORKSPACE_OWNER:
            owners = [
                item
                for item in self.list_by_workspace(membership.workspace_id)
                if item.role == PlatformRole.WORKSPACE_OWNER and item.status == MembershipStatus.ACTIVE and item.membership_id != membership_id
            ]
            if not owners:
                raise FinalWorkspaceOwnerError("cannot remove final workspace owner")
        membership.status = MembershipStatus.REMOVED
        membership.disabled_at = now_iso()
        return self.update(membership)


membership_repository = MembershipRepository()
