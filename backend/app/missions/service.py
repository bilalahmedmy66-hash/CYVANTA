from sqlalchemy.orm import Session

from app.models import Mission, MissionTask


def build_initial_plan():
    return [
        {
            "title": "Verify asset authorization",
            "description": (
                "Review the registered asset, its authorization "
                "reference and permitted assessment scope."
            ),
            "agent": "scope_agent",
        },
        {
            "title": "Collect asset information",
            "description": (
                "Prepare a plan to collect approved, read-only "
                "asset inventory information."
            ),
            "agent": "recon_agent",
        },
        {
            "title": "Review security configuration",
            "description": (
                "Prepare a configuration review using approved "
                "security baselines."
            ),
            "agent": "analysis_agent",
        },
        {
            "title": "Prepare security findings",
            "description": (
                "Organize evidence, potential weaknesses and "
                "recommended remediation steps."
            ),
            "agent": "reporting_agent",
        },
    ]


def create_mission_plan(
    db: Session,
    mission: Mission,
):
    plan = build_initial_plan()

    tasks = []

    for index, item in enumerate(plan, start=1):
        task = MissionTask(
            mission_id=mission.id,
            title=item["title"],
            description=item["description"],
            assigned_agent=item["agent"],
            status="pending",
            sequence=index,
        )

        db.add(task)
        tasks.append(task)

    db.flush()

    return tasks


def get_mission_tasks(db: Session, mission_id: str):
    return (
        db.query(MissionTask)
        .filter(MissionTask.mission_id == mission_id)
        .order_by(MissionTask.sequence.asc())
        .all()
    )
