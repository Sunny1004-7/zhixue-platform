#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate the complete SPDX inventory for Python and npm dependencies.

The script reads the backend Python lockfile, resolves its PyPI JSON metadata,
and reads every package from the npm lockfile.  It records package
versions, declared licences and dependency relationships, but deliberately
does not calculate or compare file hashes.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


ROOT = Path(__file__).resolve().parents[1]
PYTHON_REQUIREMENTS = [ROOT / "backend" / "requirements.lock.txt"]
PYTHON_LOCKS = [ROOT / "backend" / "requirements-complete.lock.txt"]
NPM_LOCK = ROOT / "frontend" / "package-lock.json"
OUTPUT = ROOT / "sbom.spdx.json"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"


def _json_url(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=45) as response:
        return json.load(response)


def _declared_license(info: dict[str, Any]) -> str:
    expression = str(info.get("license_expression") or info.get("license") or "").strip()
    lowered = expression.lower()
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if "mit license" in lowered and "permission is hereby granted" in lowered:
        return "MIT"
    if expression and expression.upper() not in {"UNKNOWN", "NONE"} and len(expression) < 80:
        return expression
    classifiers = info.get("classifiers") or []
    known = {
        "MIT License": "MIT",
        "Apache Software License": "Apache-2.0",
        "BSD License": "BSD-3-Clause",
        "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
        "GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
        "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
        "ISC License (ISCL)": "ISC",
    }
    for classifier in classifiers:
        if classifier.startswith("License ::"):
            tail = classifier.rsplit("::", 1)[-1].strip()
            if tail in known:
                return known[tail]
    return "NOASSERTION"


def _read_direct_requirements() -> dict[str, Requirement]:
    direct: dict[str, Requirement] = {}
    for path in PYTHON_REQUIREMENTS:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            direct[canonicalize_name(requirement.name)] = requirement
    return direct


def _candidate_version(name: str, constraints: list[Requirement]) -> str:
    releases = _json_url(f"https://pypi.org/pypi/{quote(name)}/json")["releases"]
    candidates: list[Version] = []
    for raw_version, files in releases.items():
        if not files:
            continue
        try:
            version = Version(raw_version)
        except InvalidVersion:
            continue
        if version.is_prerelease:
            continue
        if all(not requirement.specifier or version in requirement.specifier for requirement in constraints):
            candidates.append(version)
    if not candidates:
        joined = ", ".join(str(item.specifier) for item in constraints)
        raise RuntimeError(f"Cannot resolve {name} for constraints: {joined}")
    return str(max(candidates))


def _resolve_python() -> tuple[dict[str, dict[str, Any]], dict[str, set[str]], set[str]]:
    direct = _read_direct_requirements()
    selected: dict[str, str] = {}
    for path in PYTHON_LOCKS:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            pinned = next((item[2:] for item in str(requirement.specifier).split(",") if item.startswith("==")), None)
            if not pinned:
                raise RuntimeError(f"Python lock entry is not pinned: {line}")
            selected[canonicalize_name(requirement.name)] = pinned
    metadata: dict[str, dict[str, Any]] = {}
    relationships: dict[str, set[str]] = defaultdict(set)
    environment = default_environment()

    for name, version in sorted(selected.items()):
        payload = _json_url(f"https://pypi.org/pypi/{quote(name)}/{quote(version)}/json")
        info = payload["info"]
        metadata[name] = {
            "name": info.get("name") or name,
            "version": version,
            "license": _declared_license(info),
            "url": info.get("package_url") or f"https://pypi.org/project/{name}/{version}/",
        }
        known_licenses = {
            "colbert-ai": "MIT",
            "fsspec": "BSD-3-Clause",
            "mypy-extensions": "MIT",
        }
        if name in known_licenses:
            metadata[name]["license"] = known_licenses[name]
        for raw_dependency in info.get("requires_dist") or []:
            dependency = Requirement(raw_dependency)
            dependency_name = canonicalize_name(dependency.name)
            if dependency_name not in selected:
                continue
            if dependency.marker and not dependency.marker.evaluate({**environment, "extra": ""}):
                # Include an optional-extra edge only when that package is part
                # of the resolved lock, which means the selected environment
                # requested it through another declaration.
                marker_text = str(dependency.marker)
                if "extra" not in marker_text:
                    continue
            relationships[name].add(dependency_name)
    return metadata, relationships, set(direct)


def _npm_name(path: str, entry: dict[str, Any]) -> str:
    if entry.get("name"):
        return str(entry["name"])
    marker = "node_modules/"
    return path.rsplit(marker, 1)[-1]


def _resolve_npm() -> tuple[dict[str, dict[str, Any]], dict[str, set[str]], set[str]]:
    lock = json.loads(NPM_LOCK.read_text(encoding="utf-8"))
    entries = {path: entry for path, entry in lock.get("packages", {}).items() if path and entry.get("version")}
    metadata: dict[str, dict[str, Any]] = {}
    relationships: dict[str, set[str]] = defaultdict(set)
    path_to_key: dict[str, str] = {}
    name_to_paths: dict[str, list[str]] = defaultdict(list)
    for path, entry in entries.items():
        name = _npm_name(path, entry)
        key = f"npm:{path}"
        path_to_key[path] = key
        name_to_paths[name].append(path)
        metadata[key] = {
            "name": name,
            "version": str(entry["version"]),
            "license": str(entry.get("license") or "NOASSERTION"),
            "url": f"https://www.npmjs.com/package/{name}/v/{entry['version']}",
        }

    def locate(parent_path: str, dependency_name: str) -> str | None:
        base = parent_path
        while True:
            candidate = f"{base}/node_modules/{dependency_name}" if base else f"node_modules/{dependency_name}"
            if candidate in entries:
                return candidate
            if "/node_modules/" not in base:
                break
            base = base.rsplit("/node_modules/", 1)[0]
        candidates = name_to_paths.get(dependency_name, [])
        return candidates[0] if len(candidates) == 1 else None

    for path, entry in entries.items():
        parent_key = path_to_key[path]
        for dependency_name in (entry.get("dependencies") or {}):
            located = locate(path, dependency_name)
            if located:
                relationships[parent_key].add(path_to_key[located])

    root_entry = lock.get("packages", {}).get("", {})
    root_names = set((root_entry.get("dependencies") or {})) | set((root_entry.get("devDependencies") or {}))
    direct = {path_to_key[f"node_modules/{name}"] for name in root_names if f"node_modules/{name}" in path_to_key}
    return metadata, relationships, direct


def _spdx_id(ecosystem: str, key: str, version: str) -> str:
    token = re.sub(r"[^A-Za-z0-9.-]+", "-", f"{ecosystem}-{key}-{version}").strip("-")
    return f"SPDXRef-{token}"


def main() -> None:
    python_meta, python_edges, python_direct = _resolve_python()
    npm_meta, npm_edges, npm_direct = _resolve_npm()
    packages = [{
        "name": "zhixing-submission",
        "SPDXID": "SPDXRef-Zhixing",
        "versionInfo": "0.1.0",
        "downloadLocation": "NOASSERTION",
        "licenseConcluded": "LicenseRef-Zhixing-Competition-Evaluation",
        "licenseDeclared": "LicenseRef-Zhixing-Competition-Evaluation",
    }]
    relationships = [{
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": "SPDXRef-Zhixing",
    }]
    ids: dict[tuple[str, str], str] = {}
    for ecosystem, metadata in (("pypi", python_meta), ("npm", npm_meta)):
        for key, item in sorted(metadata.items(), key=lambda pair: (pair[1]["name"].lower(), pair[1]["version"])):
            spdx_id = _spdx_id(ecosystem, key, item["version"])
            ids[(ecosystem, key)] = spdx_id
            packages.append({
                "name": item["name"],
                "SPDXID": spdx_id,
                "versionInfo": item["version"],
                "downloadLocation": item["url"],
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": item["license"],
                "externalRefs": [{
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:{ecosystem}/{quote(item['name'], safe='@/') }@{item['version']}",
                }],
            })
    for ecosystem, edges in (("pypi", python_edges), ("npm", npm_edges)):
        for parent, children in edges.items():
            for child in sorted(children):
                if (ecosystem, parent) in ids and (ecosystem, child) in ids:
                    relationships.append({
                        "spdxElementId": ids[(ecosystem, parent)],
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": ids[(ecosystem, child)],
                    })
    for ecosystem, direct in (("pypi", python_direct), ("npm", npm_direct)):
        for key in sorted(direct):
            if (ecosystem, key) in ids:
                relationships.append({
                    "spdxElementId": "SPDXRef-Zhixing",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": ids[(ecosystem, key)],
                })

    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "zhixing-submission-complete-sbom",
        "documentNamespace": f"https://zhixing.local/sbom/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "creationInfo": {
            "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "creators": ["Organization: Project team", "Tool: tools/generate_sbom.py"],
            "comment": "Complete direct and transitive dependency inventory generated from Python declarations and package-lock.json; no file hashes are calculated.",
        },
        "packages": packages,
        "relationships": relationships,
    }
    OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    rows = []
    direct_keys = {("pypi", key) for key in python_direct} | {("npm", key) for key in npm_direct}
    for ecosystem, metadata in (("pypi", python_meta), ("npm", npm_meta)):
        for key, item in metadata.items():
            level = "直接依赖" if (ecosystem, key) in direct_keys else "传递依赖"
            rows.append((ecosystem, item["name"], item["version"], item["license"], level))
    rows.sort(key=lambda item: (item[0], item[1].lower(), item[2]))
    notice_lines = [
        "# 第三方开源软件及许可证说明",
        "",
        "知学智教的项目源码由项目贡献者完成。工程使用的第三方软件及其传递依赖列于下表，组件著作权归各自权利人，使用时遵守相应许可证。版本和依赖关系以`sbom.spdx.json`为准；该清单由`tools/generate_sbom.py`根据Python依赖声明与前端锁文件生成。",
        "",
        "| 生态 | 组件 | 版本 | 声明许可证 | 依赖层级 |",
        "| --- | --- | --- | --- | --- |",
    ]
    notice_lines.extend(f"| {eco} | {name} | {version} | {license_name} | {level} |" for eco, name, version, license_name, level in rows)
    notice_lines.extend([
        "",
        "模型权重不随提交包再分发。使用者应依据所选模型的许可证和服务条款配置模型文件或授权接口。",
        "",
    ])
    NOTICES.write_text("\n".join(notice_lines), encoding="utf-8")
    print(f"Generated {OUTPUT.name}: {len(packages) - 1} third-party packages")


if __name__ == "__main__":
    main()
