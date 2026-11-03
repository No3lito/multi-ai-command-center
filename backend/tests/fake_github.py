"""FAKE GitHub REST API for tests. Nothing here talks to GitHub.

An in-memory repository with commits, branches, pull requests and CI results, serving just the
endpoints a code job uses. Use it in-process (httpx.ASGITransport(app=make_app(state))) or as a
server: python -m tests.fake_github --port N.
"""

from __future__ import annotations

import argparse
import base64
import itertools
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

TOKEN = "test-github-token"
REPO = "owner/repo"


class FakeRepo:
    def __init__(self, files: dict[str, str] | None = None, ci: list[str] | None = None) -> None:
        self.ids = itertools.count(1)
        self.commits: dict[str, dict[str, Any]] = {}
        self.trees: dict[str, dict[str, str]] = {}
        self.branches: dict[str, str] = {}
        self.prs: dict[int, dict[str, Any]] = {}
        self.comments: list[tuple[int, str]] = []
        # CI conclusion for each new commit, in order (the last one repeats). "none": no CI.
        self.ci = ci or ["success"]
        self.ci_by_sha: dict[str, str] = {}
        root = self._commit(files or {}, [], "initial")
        self.branches["main"] = root

    def _commit(self, files: dict[str, str], parents: list[str], message: str) -> str:
        sha = f"c{next(self.ids):039d}"
        self.commits[sha] = {"files": dict(files), "parents": parents, "message": message}
        self.trees[f"t{sha[1:]}"] = dict(files)
        return sha

    def resolve(self, ref: str) -> str | None:
        return self.branches.get(ref) or (ref if ref in self.commits else None)

    def ci_for(self, sha: str) -> str:
        if sha not in self.ci_by_sha:
            index = min(len(self.ci_by_sha), len(self.ci) - 1)
            self.ci_by_sha[sha] = self.ci[index]
        return self.ci_by_sha[sha]


def make_app(repo: FakeRepo) -> Starlette:
    def auth(request: Request) -> Response | None:
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            return JSONResponse({"message": "Bad credentials"}, status_code=401)
        return None

    def guarded(fn: Any) -> Any:
        async def handler(request: Request) -> Response:
            return auth(request) or await fn(request)

        return handler

    async def repo_info(request: Request) -> Response:
        return JSONResponse({"default_branch": "main", "full_name": REPO})

    async def get_ref(request: Request) -> Response:
        sha = repo.branches.get(request.path_params["branch"])
        if sha is None:
            return JSONResponse({"message": "Not Found"}, status_code=404)
        return JSONResponse({"object": {"sha": sha}})

    async def tree(request: Request) -> Response:
        sha = request.path_params["sha"]
        files = repo.commits[sha]["files"] if sha in repo.commits else repo.trees.get(sha)
        if files is None:
            return JSONResponse({"message": "Not Found"}, status_code=404)
        return JSONResponse(
            {"tree": [{"path": p, "type": "blob", "size": len(c.encode())} for p, c in sorted(files.items())]}
        )

    async def get_commit(request: Request) -> Response:
        sha = request.path_params["sha"]
        return JSONResponse({"sha": sha, "tree": {"sha": f"t{sha[1:]}"}})

    async def post_tree(request: Request) -> Response:
        body = await request.json()
        files = dict(repo.trees[body["base_tree"]])
        for e in body["tree"]:
            if e.get("sha", "x") is None:
                files.pop(e["path"], None)
            else:
                files[e["path"]] = e["content"]
        tid = f"t{next(repo.ids):039d}"
        repo.trees[tid] = files
        return JSONResponse({"sha": tid}, status_code=201)

    async def post_commit(request: Request) -> Response:
        body = await request.json()
        sha = repo._commit(repo.trees[body["tree"]], body["parents"], body["message"])
        return JSONResponse({"sha": sha}, status_code=201)

    async def post_ref(request: Request) -> Response:
        body = await request.json()
        name = body["ref"].removeprefix("refs/heads/")
        if name in repo.branches:
            return JSONResponse({"message": "Reference already exists"}, status_code=422)
        repo.branches[name] = body["sha"]
        return JSONResponse({"ref": body["ref"]}, status_code=201)

    async def patch_ref(request: Request) -> Response:
        body = await request.json()
        name = request.path_params["branch"]
        old = repo.branches.get(name)
        if old is None:
            return JSONResponse({"message": "Not Found"}, status_code=404)
        if not body.get("force") and old not in repo.commits[body["sha"]]["parents"]:
            return JSONResponse({"message": "Update is not a fast forward"}, status_code=422)
        repo.branches[name] = body["sha"]
        return JSONResponse({"ref": name})

    async def contents(request: Request) -> Response:
        sha = repo.resolve(request.query_params.get("ref", "main"))
        files = repo.commits[sha]["files"] if sha else {}
        path = request.path_params["path"]
        if path not in files:
            return JSONResponse({"message": "Not Found"}, status_code=404)
        return JSONResponse(
            {"encoding": "base64", "content": base64.b64encode(files[path].encode()).decode()}
        )

    def view(pr: dict[str, Any]) -> dict[str, Any]:
        """GitHub's shape: head and base are objects; head.sha is the branch's current commit."""
        return {
            **pr,
            "head": {"ref": pr["head"], "sha": repo.branches.get(pr["head"])},
            "base": {"ref": pr["base"]},
        }

    async def pulls(request: Request) -> Response:
        if request.method == "GET":
            head = request.query_params.get("head", "").split(":", 1)[-1]
            return JSONResponse(
                [view(p) for p in repo.prs.values() if p["head"] == head and p["state"] == "open"]
            )
        body = await request.json()
        if any(p["head"] == body["head"] and p["state"] == "open" for p in repo.prs.values()):
            return JSONResponse(
                {"message": "Validation Failed: A pull request already exists"}, status_code=422
            )
        number = len(repo.prs) + 1
        repo.prs[number] = {
            "number": number,
            "html_url": f"https://github.com/{REPO}/pull/{number}",
            "head": body["head"],
            "base": body["base"],
            "title": body["title"],
            "body": body["body"],
            "state": "open",
            "merged": False,
        }
        return JSONResponse(view(repo.prs[number]), status_code=201)

    async def pull(request: Request) -> Response:
        pr = repo.prs.get(int(request.path_params["n"]))
        if pr is None:
            return JSONResponse({"message": "Not Found"}, status_code=404)
        if request.method == "PATCH":
            pr.update(await request.json())
        return JSONResponse(view(pr))

    async def merge(request: Request) -> Response:
        pr = repo.prs[int(request.path_params["n"])]
        if pr["state"] != "open":
            return JSONResponse({"message": "Pull Request is not mergeable"}, status_code=405)
        head = repo.branches[pr["head"]]
        body = await request.json()
        if body.get("sha") and body["sha"] != head:
            return JSONResponse(
                {"message": "Head branch was modified. Review and try the merge again."}, status_code=409
            )
        sha = repo._commit(repo.commits[head]["files"], [repo.branches["main"]], body["commit_title"])
        repo.branches["main"] = sha
        pr.update(state="closed", merged=True)
        return JSONResponse({"sha": sha, "merged": True})

    async def runs(request: Request) -> Response:
        sha = request.query_params.get("head_sha", "")
        result = repo.ci_for(sha)
        if result == "none":
            return JSONResponse({"workflow_runs": []})
        return JSONResponse(
            {"workflow_runs": [{"id": int(sha[1:]), "status": "completed", "conclusion": result}]}
        )

    async def jobs(request: Request) -> Response:
        return JSONResponse(
            {
                "jobs": [
                    {
                        "id": 7,
                        "name": "backend",
                        "conclusion": "failure",
                        "steps": [{"name": "Pytest", "conclusion": "failure"}],
                    },
                    {"id": 8, "name": "web", "conclusion": "success", "steps": []},
                ]
            }
        )

    async def logs(request: Request) -> Response:
        return PlainTextResponse(
            "2026-11-03T10:00:00.0000000Z FAILED tests/test_calc.py::test_add - assert -1 == 3"
        )

    async def comment(request: Request) -> Response:
        repo.comments.append((int(request.path_params["n"]), (await request.json())["body"]))
        return JSONResponse({}, status_code=201)

    async def state(request: Request) -> Response:
        return JSONResponse(
            {
                "branches": repo.branches,
                "prs": repo.prs,
                "main_files": repo.commits[repo.branches["main"]]["files"],
            }
        )

    async def configure(request: Request) -> Response:
        body = await request.json()
        repo.ci = body.get("ci", repo.ci)
        return JSONResponse({})

    r = f"/repos/{REPO}"
    return Starlette(
        routes=[
            Route("/_state", state),
            Route("/_config", configure, methods=["POST"]),
            Route(r, guarded(repo_info)),
            Route(r + "/git/ref/heads/{branch:path}", guarded(get_ref)),
            Route(r + "/git/trees/{sha}", guarded(tree)),
            Route(r + "/git/trees", guarded(post_tree), methods=["POST"]),
            Route(r + "/git/commits/{sha}", guarded(get_commit)),
            Route(r + "/git/commits", guarded(post_commit), methods=["POST"]),
            Route(r + "/git/refs", guarded(post_ref), methods=["POST"]),
            Route(r + "/git/refs/heads/{branch:path}", guarded(patch_ref), methods=["PATCH"]),
            Route(r + "/contents/{path:path}", guarded(contents)),
            Route(r + "/pulls", guarded(pulls), methods=["GET", "POST"]),
            Route(r + "/pulls/{n:int}", guarded(pull), methods=["GET", "PATCH"]),
            Route(r + "/pulls/{n:int}/merge", guarded(merge), methods=["PUT"]),
            Route(r + "/actions/runs", guarded(runs)),
            Route(r + "/actions/runs/{id:int}/jobs", guarded(jobs)),
            Route(r + "/actions/jobs/{id:int}/logs", guarded(logs)),
            Route(r + "/issues/{n:int}/comments", guarded(comment), methods=["POST"]),
        ]
    )


SAMPLE_FILES = {
    "app/calc.py": "def add(a, b):\n    return a - b\n",
    "tests/test_calc.py": "from app.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    "README.md": "# Sample\n",
    ".env": "SECRET=do-not-touch\n",
}


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(make_app(FakeRepo(SAMPLE_FILES)), host="127.0.0.1", port=args.port, log_level="warning")
