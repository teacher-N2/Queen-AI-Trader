from fastapi import APIRouter, Depends

from ...platform.authorization import authorization_service
from ...platform.dependencies import require_authenticated_principal
from ...platform.memberships import membership_repository
from ...platform.models import WorkspaceMembership
from ...platform.permissions import WORKSPACES_MEMBERS_MANAGE, WORKSPACES_MEMBERS_READ
from ...platform.schemas import MembershipCreateRequest, MembershipPatchRequest, MembershipPublic, envelope

router = APIRouter()


def public(membership):
    return MembershipPublic.model_validate(membership.model_dump()).model_dump(mode="json")


@router.get("/{workspace_id}/members", summary="List workspace members")
def list_members(workspace_id: str, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, WORKSPACES_MEMBERS_READ, workspace_id)
    return envelope([public(item) for item in membership_repository.list_by_workspace(workspace_id)])


@router.post("/{workspace_id}/members", summary="Add workspace member")
def add_member(workspace_id: str, payload: MembershipCreateRequest, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, WORKSPACES_MEMBERS_MANAGE, workspace_id)
    membership = membership_repository.create(WorkspaceMembership(workspace_id=workspace_id, user_id=payload.user_id, role=payload.role, invited_by_user_id=principal.user_id))
    return envelope(public(membership))


@router.patch("/{workspace_id}/members/{membership_id}", summary="Update workspace member")
def update_member(workspace_id: str, membership_id: str, payload: MembershipPatchRequest, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, WORKSPACES_MEMBERS_MANAGE, workspace_id)
    membership = membership_repository.get(membership_id)
    if payload.role is not None:
        membership.role = payload.role
    if payload.status is not None:
        membership.status = payload.status
    return envelope(public(membership_repository.update(membership)))


@router.delete("/{workspace_id}/members/{membership_id}", summary="Remove workspace member")
def remove_member(workspace_id: str, membership_id: str, principal=Depends(require_authenticated_principal)):
    authorization_service.authorize(principal, WORKSPACES_MEMBERS_MANAGE, workspace_id)
    return envelope(public(membership_repository.remove(membership_id)))
