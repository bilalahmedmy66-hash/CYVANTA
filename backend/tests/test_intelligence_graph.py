import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database.base import Base
from app.database.session import get_db


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def register_and_login(client, email, organization):
    response = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "StrongPassphrase123!",
        "organization_name": organization,
    })
    assert response.status_code == 201
    login = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "StrongPassphrase123!",
    })
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def create_asset(client, headers, name):
    response = client.post("/api/v1/assets", headers=headers, json={
        "name": name,
        "asset_type": "server",
        "identifier": f"{name.lower().replace(' ', '-')}.local",
        "authorization_reference": "LOCAL-TEST-AUTH-001",
        "authorization_confirmed": True,
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_graph_requires_authentication(client):
    response = client.get("/api/v1/intelligence-graph")
    assert response.status_code == 401


def test_graph_returns_empty_organization_graph(client):
    headers = register_and_login(client, "graph-empty@example.com", "Empty Graph Org")
    response = client.get("/api/v1/intelligence-graph", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["organization_id"]
    assert payload["summary"]["nodes"] == 2
    assert payload["summary"]["edges"] == 1
    assert payload["nodes"][0]["type"] == "organization"


def test_graph_includes_real_asset_and_mission_relationships(client):
    headers = register_and_login(client, "graph-data@example.com", "Graph Data Org")
    asset_id = create_asset(client, headers, "Graph Test Server")
    mission = client.post("/api/v1/missions", headers=headers, json={
        "title": "Graph relationship test",
        "objective": "Confirm graph relationships use persisted records only.",
        "priority": "normal",
        "asset_id": asset_id,
    })
    assert mission.status_code == 201

    response = client.get("/api/v1/intelligence-graph", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    node_ids = {node["id"] for node in payload["nodes"]}
    edge_pairs = {(edge["source"], edge["target"], edge["relationship"]) for edge in payload["edges"]}

    assert f"asset:{asset_id}" in node_ids
    assert f"mission:{mission.json()['id']}" in node_ids
    assert (
        f"mission:{mission.json()['id']}",
        f"asset:{asset_id}",
        "references_asset",
    ) in edge_pairs
    mission_node = next(node for node in payload["nodes"] if node["id"] == f"mission:{mission.json()['id']}")
    assert mission_node["metadata"]["execution_mode"] == "planning_only"


def test_graph_is_isolated_between_organizations(client):
    headers_a = register_and_login(client, "graph-a@example.com", "Organization A")
    headers_b = register_and_login(client, "graph-b@example.com", "Organization B")
    asset_id = create_asset(client, headers_a, "Organization A Server")

    response = client.get("/api/v1/intelligence-graph", headers=headers_b)
    assert response.status_code == 200
    payload = response.json()
    assert f"asset:{asset_id}" not in {node["id"] for node in payload["nodes"]}
    assert all("Organization A" not in node["label"] for node in payload["nodes"])
