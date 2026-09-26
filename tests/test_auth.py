"""Who may read and write which tenant's runs."""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from agentic_base.auth import (
    AccessPolicy,
    Grant,
    caller_access,
    get_access_policy,
    parse_tokens,
)
from agentic_base.config import Settings, get_settings
from agentic_base.domain.outcomes import LabelSource
from agentic_base.routers.health import router as health_router
from agentic_base.routers.runs import router as runs_router

TEAM_A = "token-for-team-a-000001"
OPERATOR = "operator-token-00000001"
SCORER = "token-for-harness-00001"
POLICY = AccessPolicy(
    enabled=True,
    tokens={
        TEAM_A: Grant(tenants=frozenset({"team-a"})),
        OPERATOR: Grant(tenants=None),
        SCORER: Grant(
            tenants=frozenset({"team-a"}),
            label_sources=frozenset({LabelSource.OFFICIAL_HARNESS}),
        ),
    },
)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _run(tenant: str, item: str = "task-1") -> dict:
    return {"tenant": tenant, "code_revision": "abc1234", "item": item}


@pytest.fixture()
def secured(app, test_client):
    app.dependency_overrides[get_access_policy] = lambda: POLICY
    try:
        yield test_client
    finally:
        app.dependency_overrides.pop(get_access_policy)


def test_a_request_without_a_token_is_refused_and_told_how_to_authenticate(
    secured,
) -> None:
    response = secured.get("/runs/export", params={"tenant": "team-a"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_an_unknown_token_is_refused(secured) -> None:
    response = secured.post("/runs", json=_run("team-a"), headers=_bearer("x" * 24))

    assert response.status_code == 401


def test_a_token_writes_its_own_tenant_and_not_another(secured) -> None:
    assert (
        secured.post("/runs", json=_run("team-a"), headers=_bearer(TEAM_A)).status_code
        == 201
    )
    assert (
        secured.post("/runs", json=_run("team-b"), headers=_bearer(TEAM_A)).status_code
        == 403
    )


def test_another_tenants_run_is_not_found_rather_than_forbidden(secured) -> None:
    """A 403 would confirm that the run exists."""
    theirs = secured.post(
        "/runs", json=_run("team-b"), headers=_bearer(OPERATOR)
    ).json()
    mine = secured.post("/runs", json=_run("team-a"), headers=_bearer(TEAM_A)).json()

    assert (
        secured.get(f"/runs/{mine['run_id']}", headers=_bearer(TEAM_A)).status_code
        == 200
    )
    for method, path, body in (
        ("get", f"/runs/{theirs['run_id']}", None),
        ("get", f"/runs/{theirs['run_id']}/provenance", None),
        (
            "post",
            f"/runs/{theirs['run_id']}/label",
            {"resolved": True, "label_source": "human"},
        ),
        (
            "post",
            f"/runs/{theirs['run_id']}/approvals",
            {"action": "a", "decision": "approved", "by": "b", "at": "2026-09-14"},
        ),
    ):
        if method == "get":
            response = secured.get(path, headers=_bearer(TEAM_A))
        else:
            response = secured.post(path, json=body, headers=_bearer(TEAM_A))
        assert response.status_code == 404, path


@pytest.mark.parametrize(
    "path", ["/runs/export", "/runs/integrity", "/runs/validity/report"]
)
def test_a_tenant_wide_read_is_limited_to_the_tokens_tenants(secured, path) -> None:
    assert (
        secured.get(
            path, params={"tenant": "team-a"}, headers=_bearer(TEAM_A)
        ).status_code
        == 200
    )
    assert (
        secured.get(
            path, params={"tenant": "team-b"}, headers=_bearer(TEAM_A)
        ).status_code
        == 403
    )


def test_an_operator_token_reaches_every_tenant(secured) -> None:
    for tenant in ("team-a", "team-b"):
        response = secured.get(
            "/runs/export", params={"tenant": tenant}, headers=_bearer(OPERATOR)
        )
        assert response.status_code == 200


def test_a_citable_outcome_from_a_token_without_the_grant_is_refused(secured) -> None:
    """The scorer's standing must come from the deployment, not from the writer's own claim."""
    response = secured.post(
        "/runs",
        json={**_run("team-a"), "resolved": True, "label_source": "official_harness"},
        headers=_bearer(TEAM_A),
    )

    assert response.status_code == 403
    assert "official_harness" in response.json()["detail"]
    assert "label_sources" in response.json()["detail"]


def test_a_token_granted_a_citable_source_may_assert_it(secured) -> None:
    response = secured.post(
        "/runs",
        json={**_run("team-a"), "resolved": True, "label_source": "official_harness"},
        headers=_bearer(SCORER),
    )

    assert response.status_code == 201
    assert response.json()["label_source"] == "official_harness"


def test_a_grant_covers_only_the_sources_it_names(secured) -> None:
    response = secured.post(
        "/runs",
        json={**_run("team-a"), "resolved": True, "label_source": "human"},
        headers=_bearer(SCORER),
    )

    assert response.status_code == 403
    assert "human" in response.json()["detail"]


def test_labelling_needs_the_same_grant_as_creating(secured) -> None:
    run_id = secured.post("/runs", json=_run("team-a"), headers=_bearer(TEAM_A)).json()[
        "run_id"
    ]
    label = {"resolved": True, "label_source": "official_harness"}

    ungranted = secured.post(
        f"/runs/{run_id}/label", json=label, headers=_bearer(TEAM_A)
    )
    granted = secured.post(f"/runs/{run_id}/label", json=label, headers=_bearer(SCORER))

    assert ungranted.status_code == 403
    assert "official_harness" in ungranted.json()["detail"]
    assert granted.status_code == 200


def test_a_diagnostic_outcome_needs_no_grant(secured) -> None:
    """The grant guards what may be cited, not what may be observed."""
    created = secured.post(
        "/runs",
        json={**_run("team-a"), "resolved": False, "label_source": "self_reported"},
        headers=_bearer(TEAM_A),
    )
    labelled = secured.post(
        f"/runs/{created.json()['run_id']}/label",
        json={"resolved": True, "label_source": "model_judge"},
        headers=_bearer(TEAM_A),
    )

    assert created.status_code == 201
    assert labelled.status_code == 200


def test_health_needs_no_token(secured) -> None:
    paths = [r.path for r in health_router.routes if isinstance(r, APIRoute)]

    assert paths
    for path in paths:
        assert secured.get(path).status_code == 200, path


def test_with_no_tokens_configured_every_data_route_refuses_and_names_the_setting(
    app, test_client
) -> None:
    app.dependency_overrides[get_access_policy] = lambda: AccessPolicy(
        enabled=True, tokens={}
    )
    try:
        response = test_client.get("/runs/export", params={"tenant": "team-a"})
    finally:
        app.dependency_overrides.pop(get_access_policy)

    assert response.status_code == 401
    assert "API_TOKENS" in response.json()["detail"]


def test_every_runs_route_asks_who_is_calling() -> None:
    """A route added without the check would serve every tenant's runs to anyone."""

    def depends_on_access(dependant) -> bool:
        return any(
            d.call is caller_access or depends_on_access(d)
            for d in dependant.dependencies
        )

    routes = [r for r in runs_router.routes if isinstance(r, APIRoute)]
    unguarded = [r.path for r in routes if not depends_on_access(r.dependant)]

    assert len(routes) >= 8
    assert unguarded == []


def test_the_service_refuses_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AUTH", raising=False)

    assert Settings().auth == "tokens"


def test_a_wrong_auth_mode_fails_the_start(monkeypatch) -> None:
    monkeypatch.setenv("AUTH", "maybe")
    get_settings.cache_clear()
    get_access_policy.cache_clear()
    try:
        with pytest.raises(ValueError, match="AUTH must be"):
            get_access_policy()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        get_access_policy.cache_clear()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("{not json", "not valid JSON"),
        ('["a"]', "JSON object"),
        ('{"short": ["team-a"]}', "at least 16 characters"),
        ('{"long-enough-token-1": "team-a"}', "list of tenant names"),
        ('{"long-enough-token-1": {"tenants": "team-a"}}', "list of tenant names"),
        (
            '{"long-enough-token-1": {"tenants": ["team-a"], "label_sources": "human"}}',
            "list of label source names",
        ),
        (
            '{"long-enough-token-1": {"tenants": ["team-a"], "scorers": ["human"]}}',
            "knows 'tenants' and 'label_sources'",
        ),
    ],
)
def test_a_malformed_token_setting_is_refused(raw, message) -> None:
    with pytest.raises(ValueError, match=message):
        parse_tokens(raw)


def test_a_star_grants_every_tenant_and_a_list_grants_those_and_no_scorer() -> None:
    grants = parse_tokens(
        '{"operator-token-000001": ["*"], "token-for-team-a-01": ["team-a"]}'
    )

    assert grants == {
        "operator-token-000001": Grant(tenants=None),
        "token-for-team-a-01": Grant(tenants=frozenset({"team-a"})),
    }
    assert grants["operator-token-000001"].label_sources == frozenset()


def test_the_object_shape_grants_the_citable_sources_it_names() -> None:
    grants = parse_tokens(
        '{"token-for-harness-01": {"tenants": ["team-a"], '
        '"label_sources": ["official_harness", "human"]}}'
    )

    assert grants == {
        "token-for-harness-01": Grant(
            tenants=frozenset({"team-a"}),
            label_sources=frozenset({LabelSource.OFFICIAL_HARNESS, LabelSource.HUMAN}),
        )
    }


def test_a_grant_naming_an_unknown_source_is_refused() -> None:
    with pytest.raises(ValueError, match="names no known source"):
        parse_tokens(
            '{"token-for-harness-01": {"tenants": ["a"], "label_sources": ["harness"]}}'
        )


def test_a_grant_naming_a_diagnostic_source_is_refused() -> None:
    """Granting a source that needs no grant would only read as if it did something."""
    with pytest.raises(ValueError, match="only grant citable sources"):
        parse_tokens(
            '{"token-for-agent-0001": {"tenants": ["a"], '
            '"label_sources": ["self_reported"]}}'
        )


def test_the_tokens_never_appear_in_the_settings_dump(monkeypatch) -> None:
    monkeypatch.setenv("API_TOKENS", '{"a-very-secret-token-1": ["team-a"]}')

    assert "a-very-secret-token-1" not in str(Settings().model_dump())
