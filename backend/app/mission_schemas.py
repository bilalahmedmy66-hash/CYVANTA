from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class MissionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    objective: str = Field(min_length=10, max_length=3000)
    priority: Literal["low", "normal", "high"] = "normal"
    asset_id: str | None = None


class MissionTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    assigned_agent: str | None
    status: str
    sequence: int


class MissionResponse(BaseModel):
    id: str
    title: str
    objective: str
    priority: str
    status: str
    asset_id: str | None
    execution_mode: str = "planning_only"
    tasks: list[MissionTaskResponse] = []


class ActionProposalCreate(BaseModel):
    action_type: Literal[
        "collect_inventory",
        "review_configuration",
        "inspect_processes",
        "run_authorized_vulnerability_scan",
        "isolate_endpoint",
        "quarantine_file",
    ]
    target_id: str
    description: str = Field(min_length=10, max_length=2000)


class ActionProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    mission_id: str
    action_type: str
    target_type: str
    target_id: str | None
    description: str
    risk_level: str
    status: str


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=5, max_length=1000)


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_request_id: str
    decision: str
    reason: str
