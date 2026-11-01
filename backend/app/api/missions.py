from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import (
    Mission,
    MissionTask,
    Asset,
    ActionRequest,
    ActionApproval,
    AuditLog,
    User,
    Membership,
)
from app.security.dependencies import (
    get_current_user,
    get_current_membership,
)
from app.missions.service import (
    create_mission_plan,
    get_mission_tasks,
)
from app.mission_schemas import (
    MissionCreate,
    MissionResponse,
    ActionProposalCreate,
    ActionProposalResponse,
    ApprovalDecision,
    ApprovalResponse,
)

router = APIRouter(tags=["Mission Controller"])


ACTION_RISKS = {
    "collect_inventory": "low",
    "review_configuration": "low",
    "inspect_processes": "medium",
    "run_authorized_vulnerability_scan": "high",
    "isolate_endpoint": "critical",
    "quarantine_file": "high",
}


def write_audit(
    db,
    user_id,
    organization_id,
    action,
    target_type,
    target_id=None,
    details=None,
    request=None,
):
    ip_address = (
        request.client.host
        if request and request.client
        else None
    )

    db.add(
        AuditLog(
            user_id=user_id,
            organization_id=organization_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details or {},
            ip_address=ip_address,
        )
    )


def require_admin(membership):
    if membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Organization owner or admin permission required.",
        )


def mission_response(db, mission):
    tasks = get_mission_tasks(db, mission.id)

    return MissionResponse(
        id=mission.id,
        title=mission.title,
        objective=mission.objective,
        priority=mission.priority,
        status=mission.status,
        asset_id=mission.asset_id,
        execution_mode="planning_only",
        tasks=tasks,
    )


@router.post(
    "/api/v1/missions",
    response_model=MissionResponse,
    status_code=201,
)
def create_mission(
    data: MissionCreate,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    if data.asset_id:
        asset = db.query(Asset).filter(
            Asset.id == data.asset_id,
            Asset.organization_id == membership.organization_id,
        ).first()

        if asset is None:
            raise HTTPException(
                status_code=404,
                detail="Asset not found in this organization.",
            )

    mission = Mission(
        organization_id=membership.organization_id,
        created_by=user.id,
        asset_id=data.asset_id,
        title=data.title,
        objective=data.objective,
        priority=data.priority,
        status="planned",
    )

    db.add(mission)
    db.flush()

    create_mission_plan(db, mission)

    write_audit(
        db,
        user.id,
        membership.organization_id,
        "mission.created",
        "mission",
        mission.id,
        {"priority": mission.priority},
        request,
    )

    db.commit()
    db.refresh(mission)

    return mission_response(db, mission)


@router.get(
    "/api/v1/missions",
    response_model=list[MissionResponse],
)
def list_missions(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    missions = (
        db.query(Mission)
        .filter(
            Mission.organization_id == membership.organization_id
        )
        .order_by(Mission.created_at.desc())
        .all()
    )

    return [
        mission_response(db, mission)
        for mission in missions
    ]


@router.get(
    "/api/v1/missions/{mission_id}",
    response_model=MissionResponse,
)
def get_mission(
    mission_id: str,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.organization_id == membership.organization_id,
    ).first()

    if mission is None:
        raise HTTPException(
            status_code=404,
            detail="Mission not found.",
        )

    return mission_response(db, mission)


@router.post(
    "/api/v1/missions/{mission_id}/actions",
    response_model=ActionProposalResponse,
    status_code=201,
)
def propose_action(
    mission_id: str,
    data: ActionProposalCreate,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.organization_id == membership.organization_id,
    ).first()

    if mission is None:
        raise HTTPException(
            status_code=404,
            detail="Mission not found.",
        )

    asset = db.query(Asset).filter(
        Asset.id == data.target_id,
        Asset.organization_id == membership.organization_id,
    ).first()

    if asset is None:
        raise HTTPException(
            status_code=404,
            detail="Target asset not found in this organization.",
        )

    if mission.asset_id and mission.asset_id != asset.id:
        raise HTTPException(
            status_code=400,
            detail="Target asset is outside the mission's registered scope.",
        )

    action = ActionRequest(
        mission_id=mission.id,
        organization_id=membership.organization_id,
        requested_by=user.id,
        action_type=data.action_type,
        target_type="asset",
        target_id=asset.id,
        description=data.description,
        risk_level=ACTION_RISKS[data.action_type],
        status="pending_approval",
    )

    db.add(action)
    db.flush()

    write_audit(
        db,
        user.id,
        membership.organization_id,
        "action.proposed",
        "action_request",
        action.id,
        {
            "action_type": action.action_type,
            "risk_level": action.risk_level,
        },
        request,
    )

    db.commit()
    db.refresh(action)

    return action


@router.get(
    "/api/v1/missions/{mission_id}/actions",
    response_model=list[ActionProposalResponse],
)
def list_actions(
    mission_id: str,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    mission = db.query(Mission).filter(
        Mission.id == mission_id,
        Mission.organization_id == membership.organization_id,
    ).first()

    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found.")

    return (
        db.query(ActionRequest)
        .filter(
            ActionRequest.mission_id == mission.id,
            ActionRequest.organization_id == membership.organization_id,
        )
        .order_by(ActionRequest.created_at.desc())
        .all()
    )


@router.post(
    "/api/v1/actions/{action_id}/decision",
    response_model=ApprovalResponse,
)
def decide_action(
    action_id: str,
    data: ApprovalDecision,
    request: Request,
    user: User = Depends(get_current_user),
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    require_admin(membership)

    action = db.query(ActionRequest).filter(
        ActionRequest.id == action_id,
        ActionRequest.organization_id == membership.organization_id,
    ).first()

    if action is None:
        raise HTTPException(status_code=404, detail="Action not found.")

    if action.status != "pending_approval":
        raise HTTPException(
            status_code=409,
            detail="This action has already been decided or is not awaiting approval.",
        )

    approval = ActionApproval(
        action_request_id=action.id,
        organization_id=membership.organization_id,
        decided_by=user.id,
        decision=data.decision,
        reason=data.reason,
    )

    action.status = (
        "approved"
        if data.decision == "approve"
        else "rejected"
    )

    db.add(approval)

    write_audit(
        db,
        user.id,
        membership.organization_id,
        "action.decision_recorded",
        "action_request",
        action.id,
        {"decision": data.decision},
        request,
    )

    db.commit()
    db.refresh(approval)

    return approval
