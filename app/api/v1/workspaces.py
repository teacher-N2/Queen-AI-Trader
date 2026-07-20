from fastapi import APIRouter, Depends

from ...platform.authorization import authorization_service
from ...platform.dependencies import require_authenticated_principal, require_platform_permission
from ...platform.permissions import WORKSPACES_CREATE, WORKSPACES_READ, WORKSPACES_UPDATE
from ...platform.schemas import PageParams, WorkspaceCreateRequest, WorkspacePatchRequest, WorkspacePublic, envelope
from ...platform.services import workspace_service
from ...platform.workspace_repository import workspace_repository

router = APIRouter()


def public(workspace):
    return WorkspacePublic.model_validate(workspace.model_dump()).model_dump(mode="json")


@router.get("", summary="List workspaces")
def list_workspaces(params: PageParams = Depends(), principal=Depends(require_authenticated_principal)):
    if "platform.read" not in principal.permissions:
        workspace_ids = {membership.workspace_id for membership in workspace_service.memberships.list_by_user(principal.user_id or "") if membership.status.value == "ACTIVE"}
        return envelope([public(workspace) for workspace in workspace_repository.list(limit=100) if workspace.workspace_id in workspace_ids][params.offset : params.offset + params.limit])
    return envelope([public(workspace) for workspace in workspace_repository.list(limit=params.limit, offset=params.offset)])


@router.post("", summary="Create workspace")
def create_workspace(payload: WorkspaceCreateRequest, principal=Depends(require_platform_permission(WORKSPACES_CREATE))):
    user_id = principal.user_id or "internal"
    return envelope(public(workspace_service.create_workspace(name=payload.name, slug=payload.slug, created_by_user_id=user_id)))


@router.get("/{workspace_id}", summary="Get workspace")
def get_workspace(workspace_id: str, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, WORKSPACES_READ, workspace_id)
    return envelope(public(workspace_repository.get_by_id(workspace_id)))


@router.patch("/{workspace_id}", summary="Update workspace")
def update_workspace(workspace_id: str, payload: WorkspacePatchRequest, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, WORKSPACES_UPDATE, workspace_id)
    workspace = workspace_repository.get_by_id(workspace_id)
    if payload.name is not None:
        workspace.name = payload.name
    if payload.status is not None:
        workspace.status = payload.status
    return envelope(public(workspace_repository.update(workspace)))


@router.post("/{workspace_id}/archive", summary="Archive workspace")
def archive_workspace(workspace_id: str, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, WORKSPACES_UPDATE, workspace_id)
    return envelope(public(workspace_service.archive_workspace(workspace_id, principal.user_id or principal.principal_id)))
