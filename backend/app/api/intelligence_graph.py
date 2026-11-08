from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import (
    Membership,
    User,
    Asset,
    AssetAuthorization,
    AuthorizationLifecycleEvent,
    Mission,
    ActionRequest,
    ActionApproval,
    ExecutionRecord,
    ExecutionLifecycleEvent,
)
from app.security.dependencies import get_current_membership

router = APIRouter(prefix="/intelligence-graph", tags=["Intelligence Graph"])


@router.get("")
def get_intelligence_graph(
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
):
    """Return a read-only graph of records belonging to the active organization."""
    org_id = membership.organization_id
    nodes = []
    edges = []

    def add_node(node_id, node_type, label, status=None, metadata=None):
        nodes.append({
            "id": node_id,
            "type": node_type,
            "label": label,
            "status": status,
            "metadata": metadata or {},
        })

    def add_edge(source, target, relationship):
        edges.append({
            "id": f"{source}|{relationship}|{target}",
            "source": source,
            "target": target,
            "relationship": relationship,
        })

    org_node = f"organization:{org_id}"
    add_node(org_node, "organization", "Active organization",
             metadata={"organization_id": org_id})

    memberships = (
        db.query(Membership, User)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.organization_id == org_id)
        .order_by(User.email.asc())
        .all()
    )
    for item, user in memberships:
        node_id = f"member:{user.id}"
        add_node(node_id, "member", user.email,
                 status=item.role,
                 metadata={"user_id": user.id, "role": item.role})
        add_edge(org_node, node_id, "has_member")

    assets = (
        db.query(Asset)
        .filter(Asset.organization_id == org_id)
        .order_by(Asset.created_at.asc(), Asset.id.asc())
        .all()
    )
    asset_ids = {asset.id for asset in assets}
    for asset in assets:
        node_id = f"asset:{asset.id}"
        add_node(node_id, "asset", asset.name,
                 status=asset.authorization_status,
                 metadata={
                     "asset_id": asset.id,
                     "asset_type": asset.asset_type,
                     "identifier": asset.identifier,
                     "assessment_enabled": asset.assessment_enabled,
                 })
        add_edge(org_node, node_id, "owns_asset")

    authorizations = (
        db.query(AssetAuthorization)
        .filter(
            AssetAuthorization.organization_id == org_id,
            AssetAuthorization.asset_id.in_(asset_ids),
        )
        .order_by(AssetAuthorization.created_at.asc(), AssetAuthorization.id.asc())
        .all()
    ) if asset_ids else []
    authorization_ids = {item.id for item in authorizations}
    for item in authorizations:
        node_id = f"authorization:{item.id}"
        add_node(node_id, "authorization", "Asset authorization",
                 status=item.status,
                 metadata={
                     "authorization_id": item.id,
                     "asset_id": item.asset_id,
                     "evidence_type": item.evidence_type,
                     "valid_from": item.valid_from.isoformat(),
                     "expires_at": item.expires_at.isoformat(),
                 })
        add_edge(f"asset:{item.asset_id}", node_id, "has_authorization")

    auth_events = (
        db.query(AuthorizationLifecycleEvent)
        .filter(
            AuthorizationLifecycleEvent.organization_id == org_id,
            AuthorizationLifecycleEvent.authorization_id.in_(authorization_ids),
        )
        .order_by(AuthorizationLifecycleEvent.created_at.asc(), AuthorizationLifecycleEvent.id.asc())
        .all()
    ) if authorization_ids else []
    for event in auth_events:
        node_id = f"authorization_event:{event.id}"
        add_node(node_id, "authorization_event", event.event_type,
                 metadata={"event_id": event.id, "created_at": event.created_at.isoformat()})
        add_edge(f"authorization:{event.authorization_id}", node_id, "has_lifecycle_event")

    missions = (
        db.query(Mission)
        .filter(Mission.organization_id == org_id)
        .order_by(Mission.created_at.asc(), Mission.id.asc())
        .all()
    )
    mission_ids = {item.id for item in missions}
    for item in missions:
        node_id = f"mission:{item.id}"
        add_node(node_id, "mission", item.title, status=item.status,
                 metadata={"mission_id": item.id, "priority": item.priority,
                           "execution_mode": "planning_only"})
        add_edge(org_node, node_id, "contains_mission")
        if item.asset_id and item.asset_id in asset_ids:
            add_edge(node_id, f"asset:{item.asset_id}", "references_asset")

    actions = (
        db.query(ActionRequest)
        .filter(
            ActionRequest.organization_id == org_id,
            ActionRequest.mission_id.in_(mission_ids),
        )
        .order_by(ActionRequest.created_at.asc(), ActionRequest.id.asc())
        .all()
    ) if mission_ids else []
    action_ids = {item.id for item in actions}
    for item in actions:
        node_id = f"action:{item.id}"
        add_node(node_id, "action", item.action_type, status=item.status,
                 metadata={"action_id": item.id, "risk_level": item.risk_level,
                           "target_type": item.target_type})
        add_edge(f"mission:{item.mission_id}", node_id, "proposes_action")
        if item.target_type == "asset" and item.target_id in asset_ids:
            add_edge(node_id, f"asset:{item.target_id}", "targets_asset")

    approvals = (
        db.query(ActionApproval)
        .filter(
            ActionApproval.organization_id == org_id,
            ActionApproval.action_request_id.in_(action_ids),
        )
        .order_by(ActionApproval.created_at.asc(), ActionApproval.id.asc())
        .all()
    ) if action_ids else []
    for item in approvals:
        node_id = f"approval:{item.id}"
        add_node(node_id, "approval", f"Action {item.decision}",
                 status=item.decision,
                 metadata={"approval_id": item.id, "created_at": item.created_at.isoformat()})
        add_edge(f"action:{item.action_request_id}", node_id, "has_decision")

    executions = (
        db.query(ExecutionRecord)
        .filter(
            ExecutionRecord.organization_id == org_id,
            ExecutionRecord.action_request_id.in_(action_ids),
        )
        .order_by(ExecutionRecord.created_at.asc(), ExecutionRecord.id.asc())
        .all()
    ) if action_ids else []
    execution_ids = {item.id for item in executions}
    for item in executions:
        node_id = f"execution:{item.id}"
        add_node(node_id, "execution", "Execution record",
                 status=item.status,
                 metadata={"execution_id": item.id, "verified": item.verified,
                           "execution_started": item.started_at is not None})
        add_edge(f"action:{item.action_request_id}", node_id, "created_execution_record")

    execution_events = (
        db.query(ExecutionLifecycleEvent)
        .filter(
            ExecutionLifecycleEvent.organization_id == org_id,
            ExecutionLifecycleEvent.execution_id.in_(execution_ids),
        )
        .order_by(ExecutionLifecycleEvent.created_at.asc(), ExecutionLifecycleEvent.id.asc())
        .all()
    ) if execution_ids else []
    for event in execution_events:
        node_id = f"execution_event:{event.id}"
        add_node(node_id, "execution_event", event.event_type,
                 status=event.to_status,
                 metadata={"event_id": event.id, "created_at": event.created_at.isoformat(),
                           "from_status": event.from_status, "to_status": event.to_status})
        add_edge(f"execution:{event.execution_id}", node_id, "has_lifecycle_event")

    return {
        "organization_id": org_id,
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "assets": len(assets),
            "authorizations": len(authorizations),
            "missions": len(missions),
            "actions": len(actions),
            "executions": len(executions),
        },
    }
