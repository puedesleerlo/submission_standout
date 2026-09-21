from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from backend.engine import assess, public_context, select
from backend.schemas import DraftInput, EvidenceInput, PolicyInput, ProjectInput, RevisionInput, RunInput
from backend.seed import seed_demo
from backend.service import ConflictError, Service
from backend.settings import load_keys
from backend.store import Store, digest
from backend.agents import Agents, decide
from backend.agent_contracts import AgentRequest, Judgment
from backend.llm import Moonshot, ModelError


def create_app(data_dir=None, keys=None, seed=True, model=None):
    root = Path(data_dir or os.environ.get("STANDOUT_DATA_DIR", ".local"))
    keys = keys or load_keys(root)
    store = Store(root / "standout.sqlite3")
    service = Service(store)
    agents = Agents(store, model or Moonshot(store))
    allowed_origins = {f"http://{host}:{port}" for host in ("127.0.0.1", "localhost")
                       for port in (os.environ.get("STANDOUT_WEB_PORT", "5173"), os.environ.get("STANDOUT_API_PORT", "8000"))}

    @asynccontextmanager
    async def lifespan(app):
        if seed:
            seed_demo(service)
        agents.recover()
        yield
        agents.executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Submission Standout", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.service = store, service
    app.state.agents = agents

    @app.middleware("http")
    async def local_origin_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ["GET", "HEAD", "OPTIONS"] and origin and origin not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "This local workspace does not accept requests from that origin."})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def role(request: Request):
        authorization = request.headers.get("authorization", "")
        if authorization:
            token = authorization.removeprefix("Bearer ")
            for name, expected in keys.items():
                if hmac.compare_digest(token, expected):
                    return name
        elif hmac.compare_digest(request.cookies.get("standout_observer", ""), keys["observer"]):
            return "observer"
        raise HTTPException(401, "Sign in with the local access link. Run pnpm access to get it.")

    def observer(identity=Depends(role)):
        if identity != "observer":
            raise HTTPException(403, "Observer access is required.")
        return identity

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse(status_code=404, content={"detail": "That record does not exist in this project."})

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ModelError)
    async def model_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/model", dependencies=[Depends(observer)])
    def model_status():
        return agents.model.describe()

    @app.get("/api/projects/{project_id}/studio", dependencies=[Depends(observer)])
    def studio(project_id: str):
        with store.connect() as conn:
            store.get(conn, "project", project_id)
            return agents.workspace(conn, project_id)

    @app.post("/api/projects/{project_id}/agent-jobs", status_code=202, dependencies=[Depends(observer)])
    def start_agents(project_id: str, payload: AgentRequest):
        return agents.start(project_id, payload.model_dump())

    @app.post("/api/session")
    def login(response: Response, identity=Depends(observer)):
        response.set_cookie("standout_observer", keys["observer"], httponly=True, samesite="strict", max_age=86400)
        return {"authenticated": True}

    @app.delete("/api/session")
    def logout(response: Response):
        response.delete_cookie("standout_observer")
        return {"authenticated": False}

    @app.get("/api/session")
    def session(identity=Depends(observer)):
        return {"authenticated": True}

    @app.get("/api/projects", dependencies=[Depends(observer)])
    def projects():
        with store.connect() as conn:
            return store.list(conn, "project")

    @app.post("/api/projects", status_code=201, dependencies=[Depends(observer)])
    def new_project(payload: ProjectInput):
        with store.connect(write=True) as conn:
            return service.create_project(conn, payload.model_dump(mode="json"))

    @app.get("/api/projects/{project_id}", dependencies=[Depends(observer)])
    def workspace(project_id: str):
        with store.connect() as conn:
            return service.workspace(conn, project_id)

    @app.post("/api/projects/{project_id}/evidence", status_code=201, dependencies=[Depends(observer)])
    def add_evidence(project_id: str, payload: EvidenceInput):
        with store.connect(write=True) as conn:
            project = store.get(conn, "project", project_id)
            item = store.add(conn, "evidence", project_id, {**payload.model_dump(), "synthetic": project["synthetic"]})
            store.event(conn, project_id, "evidence.added", {"evidence_id": item["id"]})
            return item

    @app.post("/api/projects/{project_id}/policies", status_code=201, dependencies=[Depends(observer)])
    def add_policy(project_id: str, payload: PolicyInput):
        with store.connect(write=True) as conn:
            return service.create_policy(conn, project_id, payload.model_dump())

    @app.post("/api/projects/{project_id}/packages", status_code=201, dependencies=[Depends(observer)])
    def generate(project_id: str, payload: DraftInput):
        with store.connect(write=True) as conn:
            return service.draft(conn, project_id, payload.policy_id)

    @app.post("/api/projects/{project_id}/packages/{package_id}/revisions", status_code=201, dependencies=[Depends(observer)])
    def revise(project_id: str, package_id: str, payload: RevisionInput):
        with store.connect(write=True) as conn:
            old = store.get(conn, "package", package_id, project_id)
            value = {k: v for k, v in old.items() if k not in {"id", "created_at", "content_hash"}}
            value.update(body=payload.body, parent_id=old["id"], human_edited=True)
            if old.get("generator") == "kimi-writer-v1":
                value.update(claims=[], voice_notes="", missing_information=[])
            value["content_hash"] = digest(value)
            package = store.add(conn, "package", project_id, value)
            store.event(conn, project_id, "package.revised", {"package_id": package["id"], "parent_id": old["id"], "intervention": "human-edit"})
            return package

    @app.get("/api/projects/{project_id}/packages/{package_id}/review", dependencies=[Depends(observer)])
    def review(project_id: str, package_id: str):
        with store.connect() as conn:
            return assess(store.get(conn, "package", package_id, project_id))

    @app.post("/api/projects/{project_id}/runs", status_code=201, dependencies=[Depends(observer)])
    def run(project_id: str, payload: RunInput):
        with store.connect(write=True) as conn:
            return service.run(conn, project_id, payload.model_dump())

    @app.get("/api/projects/{project_id}/runs/{run_id}", dependencies=[Depends(observer)])
    def run_detail(project_id: str, run_id: str):
        with store.connect() as conn:
            return service.run_detail(conn, project_id, run_id)

    @app.get("/api/projects/{project_id}/export", dependencies=[Depends(observer)])
    def export(project_id: str):
        with store.connect() as conn:
            workspace = service.workspace(conn, project_id)
            runs = [service.run_detail(conn, project_id, run["id"]) for run in workspace["runs"]]
            workspace["events"] = store.list(conn, "event", project_id)
            return {"schema_version": 2, "visibility": "observer-complete", "workspace": workspace, "runs": runs,
                    "agent_work": agents.workspace(conn, project_id), "model_calls": store.list(conn, "model_call", project_id),
                    "model_results": store.list(conn, "model_result", project_id)}

    @app.post("/api/projects/{project_id}/trials/{trial_id}/replay", dependencies=[Depends(observer)])
    def replay(project_id: str, trial_id: str):
        with store.connect() as conn:
            trial = store.get(conn, "trial", trial_id, project_id)
            package = store.get(conn, "package", trial["package_id"], project_id)
            if trial.get("assessment_id"):
                assessment = store.get(conn, "assessment", trial["assessment_id"], project_id)
                judgment = Judgment.model_validate({k: assessment[k] for k in Judgment.model_fields}).model_dump()
                result = decide(package, judgment, trial["evaluation"]["world"])
            else:
                result = select(package, trial["evaluation"]["world"])
            return {"matches": digest(result) == digest(trial["evaluation"]), "passed": result["passed"], "score": result["score"],
                    "mode": "allocation-from-saved-judgment" if trial.get("assessment_id") else "reference-recompute"}

    # These endpoints deliberately construct explicit, narrow response objects.
    # No serialization of a PrivateEvaluation is ever exposed to a learner token.
    @app.get("/api/learner/projects/{project_id}", dependencies=[Depends(role)])
    def learner_context(project_id: str):
        with store.connect() as conn:
            project = store.get(conn, "project", project_id)
            evidence = store.list(conn, "evidence", project_id)
            return {"context": public_context(project, evidence), "applicant_evidence": [item for item in evidence if item["kind"] != "Institution"],
                    "reservation_conditions": project["reservation_conditions"], "policies": store.list(conn, "policy", project_id)}

    @app.post("/api/learner/projects/{project_id}/runs", status_code=201)
    def learner_run(project_id: str, payload: RunInput, identity=Depends(role)):
        with store.connect(write=True) as conn:
            result = service.run(conn, project_id, payload.model_dump(), actor=identity)
            return {"run_id": result["id"], "trial_ids": result["trial_ids"]}

    @app.get("/api/learner/projects/{project_id}/trials/{trial_id}", dependencies=[Depends(role)])
    def feedback(project_id: str, trial_id: str):
        with store.connect() as conn:
            return store.get(conn, "trial", trial_id, project_id)["observation"]

    return app


app = create_app()
