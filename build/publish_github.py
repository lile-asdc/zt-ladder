"""把站点发布到 GitHub Pages（无 git 依赖，全走 REST API）。

用法：
    python build/publish_github.py --token ghp_xxx --repo zt-ladder

会做四件事：
1. 确认账号 / 创建仓库（public）
2. 用 Git Data API 一次性提交 build/ + public/ + .github/
3. 打开 Pages（GitHub Actions 构建）
4. 触发一次「每日更新」工作流
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com"
SKIP_DIRS = {"__pycache__", ".git", "logs", "work", ".edgeone", ".localappdata", ".npm-cache"}
INCLUDE_FILES = ["README.md", "requirements.txt", ".gitignore"]
INCLUDE_DIRS = ["build", "public", ".github"]


class GitHubError(RuntimeError):
    pass


class GH:
    def __init__(self, token: str):
        self.token = token

    def call(self, method: str, path: str, payload=None):
        url = path if path.startswith("http") else API + path
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "zt-ladder-publisher",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise GitHubError(f"{method} {path} -> {exc.code}: {detail}") from exc

    def try_call(self, method: str, path: str, payload=None):
        try:
            return self.call(method, path, payload)
        except GitHubError as exc:
            # 空仓库的 ref 查询会返回 409，未开启 Pages 返回 404，都当作「还没有」
            if "-> 404" in str(exc) or "-> 409" in str(exc):
                return None
            raise


def collect_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name in INCLUDE_FILES:
        path = ROOT / name
        if path.is_file():
            files[name] = path.read_bytes()
    for folder in INCLUDE_DIRS:
        base = ROOT / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            if path.suffix in {".pyc"}:
                continue
            files[rel.as_posix()] = path.read_bytes()
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--repo", default="zt-ladder")
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args()

    gh = GH(args.token)
    user = gh.call("GET", "/user")
    owner = user["login"]
    print(f"账号：{owner}")

    repo_path = f"/repos/{owner}/{args.repo}"
    repo = gh.try_call("GET", repo_path)
    if repo is None:
        print(f"创建仓库 {owner}/{args.repo} ...")
        repo = gh.call(
            "POST",
            "/user/repos",
            {
                "name": args.repo,
                "private": args.private,
                "description": "连板天梯 · 每日涨停复盘（自动更新）",
                "has_issues": False,
                "has_wiki": False,
            },
        )
    print(f"仓库：{repo['html_url']}")

    files = collect_files()
    print(f"待提交 {len(files)} 个文件 ...")

    branch = repo.get("default_branch") or "main"
    ref_path = f"{repo_path}/git/ref/heads/{branch}"
    parent_sha = None
    base_tree = None
    ref = gh.try_call("GET", ref_path)
    if ref is None:
        # 空仓库：Git Data API 不能直接建 blob，先用 Contents API 造第一个提交
        gh.call(
            "PUT",
            f"{repo_path}/contents/README.md",
            {
                "message": "chore: 初始化仓库",
                "content": base64.b64encode("# zt-ladder\n".encode()).decode(),
            },
        )
        ref = gh.call("GET", ref_path)
    parent_sha = ref["object"]["sha"]
    commit = gh.call("GET", f"{repo_path}/git/commits/{parent_sha}")
    base_tree = commit["tree"]["sha"]

    tree = []
    for i, (path, content) in enumerate(sorted(files.items()), 1):
        blob = gh.call(
            "POST",
            f"{repo_path}/git/blobs",
            {"content": base64.b64encode(content).decode(), "encoding": "base64"},
        )
        tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if i % 20 == 0:
            print(f"  已上传 {i}/{len(files)}")

    tree_payload = {"tree": tree}
    if base_tree:
        tree_payload["base_tree"] = base_tree
    new_tree = gh.call("POST", f"{repo_path}/git/trees", tree_payload)

    message = f"连板天梯：初始化站点与每日更新（{time.strftime('%Y-%m-%d')}）"
    commit_payload = {"message": message, "tree": new_tree["sha"], "parents": [parent_sha] if parent_sha else []}
    new_commit = gh.call("POST", f"{repo_path}/git/commits", commit_payload)

    if ref:
        gh.call("PATCH", f"{repo_path}/git/refs/heads/{branch}", {"sha": new_commit["sha"], "force": True})
    else:
        gh.call("POST", f"{repo_path}/git/refs", {"ref": f"refs/heads/{branch}", "sha": new_commit["sha"]})
    print(f"提交完成：{new_commit['sha'][:8]}")

    pages = gh.try_call("GET", f"{repo_path}/pages")
    if pages is None:
        print("打开 GitHub Pages（Actions 构建）...")
        try:
            gh.call("POST", f"{repo_path}/pages", {"build_type": "workflow"})
        except GitHubError as exc:
            print(f"  Pages 开启返回：{exc}")
    else:
        print(f"Pages 已存在：{pages.get('html_url')}")

    # 触发一次，立刻出第一版
    try:
        gh.call(
            "POST",
            f"{repo_path}/actions/workflows/daily.yml/dispatches",
            {"ref": branch},
        )
        print("已触发工作流：连板天梯 · 每日更新")
    except GitHubError as exc:
        print(f"触发工作流失败（可稍后在 Actions 页面手动 Run）：{exc}")

    url = f"https://{owner}.github.io/{args.repo}/"
    print(f"\n站点地址（首次构建约 1-2 分钟）：{url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
