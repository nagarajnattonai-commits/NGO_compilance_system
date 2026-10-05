"""Existing security, register saved-view and workflow priority contracts."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from test_auth_experience import signup, login, HEADERS
from test_phase13_search import search_client
from test_phase14_workflows import workflow_client, payload


def test_revoking_other_session_keeps_current_session_and_redacts_security_data():
    with TestClient(app) as current, TestClient(app) as other:
        assert signup(current).status_code == 201
        assert login(other).status_code == 200
        sessions = current.get("/api/v1/auth/sessions").json()
        assert len(sessions) == 2 and sum(row["current"] for row in sessions) == 1
        assert all(set(row) == {"id", "current", "created_at", "expires_at"} for row in sessions)
        target = next(row for row in sessions if not row["current"])
        assert current.delete(f"/api/v1/auth/sessions/{target['id']}", headers=HEADERS).status_code == 204
        assert current.get("/api/v1/auth/me").status_code == 200
        assert other.get("/api/v1/auth/me").status_code == 401
        assert all(row["current"] for row in current.get("/api/v1/auth/sessions").json())
        events = current.get("/api/v1/auth/security-events").json()
        assert events and all(set(row) == {"id", "event", "method", "audience", "created_at"} for row in events)


@pytest.mark.parametrize("scope", ["COMPLIANCES", "TASKS", "REPORTS"])
def test_register_saved_views_preserve_filters_defaults_and_personal_scope(scope):
    with search_client(role="VIEWER") as (client, _):
        body = {"name":"My register", "scope":scope, "is_default":True,
                "filters":{"organization_id":"org-aarohan", "status":"OPEN" if scope == "TASKS" else "IN_PROGRESS"},
                "visible_columns":[], "sorting":{"by":"relevance", "direction":"asc"}}
        created = client.post("/api/v1/saved-views", json=body)
        assert created.status_code == 201, created.text
        view = created.json()
        assert client.post("/api/v1/saved-views", json=body).status_code == 409
        assert client.post("/api/v1/saved-views", json={**body,"name":"Replacement default"}).status_code == 201
        rows = client.get(f"/api/v1/saved-views?scope={scope}").json()
        assert len(rows) == 2 and sum(row["is_default"] for row in rows) == 1
        assert all(row["scope"] == scope and row["filters"]["organization_id"] == "org-aarohan" for row in rows)
        with search_client(role="VIEWER") as (stranger, _):
            assert stranger.get(f"/api/v1/saved-views?scope={scope}").json() == []
            assert stranger.delete(f"/api/v1/saved-views/{view['id']}").status_code == 404
        assert client.delete(f"/api/v1/saved-views/{view['id']}").status_code == 204


@pytest.mark.parametrize("priority", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
def test_task_action_priority_round_trips_and_delete_retains_disabled_definition(priority):
    with workflow_client() as (client, user):
        body = payload(user.id); body["actions"][0]["parameters"]["priority"] = priority
        created = client.post("/api/v1/automations", json=body)
        assert created.status_code == 201, created.text
        definition = created.json()
        assert definition["actions"][0]["parameters"]["priority"] == priority
        assert client.delete(f"/api/v1/automations/{definition['id']}").status_code == 204
        retained = next(row for row in client.get("/api/v1/automations").json() if row["id"] == definition["id"])
        assert retained["enabled"] is False
