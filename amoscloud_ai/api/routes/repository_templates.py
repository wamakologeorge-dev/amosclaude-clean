"""Repository initialization templates for licenses and .gitignore files."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from amoscloud_ai.api.routes.repositories import (
    _access,
    _checkout,
    _commit,
    _current_user,
    _db,
    _open,
    _repo_lock,
    _repo_path,
    _require_write,
)

router = APIRouter(prefix="/repositories", tags=["repository-templates"])

LicenseKey = Literal[
    "none",
    "mit",
    "apache-2.0",
    "gpl-3.0",
    "agpl-3.0",
    "lgpl-3.0",
    "mpl-2.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "isc",
    "unlicense",
    "epl-2.0",
    "bsl-1.0",
    "cc0-1.0",
]


class RepositoryTemplateRequest(BaseModel):
    license: LicenseKey = "none"
    initialize_gitignore: bool = False
    branch: str = "main"


LICENSE_NAMES = {
    "mit": "MIT License",
    "apache-2.0": "Apache License 2.0",
    "gpl-3.0": "GNU General Public License v3.0",
    "agpl-3.0": "GNU Affero General Public License v3.0",
    "lgpl-3.0": "GNU Lesser General Public License v3.0",
    "mpl-2.0": "Mozilla Public License 2.0",
    "bsd-2-clause": "BSD 2-Clause License",
    "bsd-3-clause": "BSD 3-Clause License",
    "isc": "ISC License",
    "unlicense": "The Unlicense",
    "epl-2.0": "Eclipse Public License 2.0",
    "bsl-1.0": "Boost Software License 1.0",
    "cc0-1.0": "Creative Commons Zero v1.0 Universal",
}

LICENSE_URLS = {
    "apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0",
    "gpl-3.0": "https://www.gnu.org/licenses/gpl-3.0.txt",
    "agpl-3.0": "https://www.gnu.org/licenses/agpl-3.0.txt",
    "lgpl-3.0": "https://www.gnu.org/licenses/lgpl-3.0.txt",
    "mpl-2.0": "https://www.mozilla.org/MPL/2.0/",
    "epl-2.0": "https://www.eclipse.org/legal/epl-2.0/",
    "bsl-1.0": "https://www.boost.org/LICENSE_1_0.txt",
    "cc0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt",
}


def _license_text(key: LicenseKey, owner: str) -> str | None:
    if key == "none":
        return None

    year = datetime.now(timezone.utc).year
    copyright_line = f"Copyright (c) {year} {owner}"

    if key == "mit":
        return f"""MIT License

{copyright_line}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

    if key == "bsd-2-clause":
        return f"""BSD 2-Clause License

{copyright_line}

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES.
"""

    if key == "bsd-3-clause":
        return f"""BSD 3-Clause License

{copyright_line}

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES.
"""

    if key == "isc":
        return f"""ISC License

{copyright_line}

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
"""

    if key == "unlicense":
        return """This is free and unencumbered software released into the public domain.

Anyone is free to copy, modify, publish, use, compile, sell, or distribute this
software, either in source code form or as a compiled binary, for any purpose,
commercial or non-commercial, and by any means.

In jurisdictions that recognize copyright laws, the author or authors of this
software dedicate any and all copyright interest in the software to the public
domain. The software is provided "as is", without warranty of any kind.

For more information, please refer to https://unlicense.org/
"""

    name = LICENSE_NAMES[key]
    url = LICENSE_URLS[key]
    return f"""{name}

SPDX-License-Identifier: {key.upper()}

{copyright_line}

This project is licensed under the {name}.
The complete, authoritative license terms are available at:
{url}

A copy of those terms should be retained with redistributed versions of this
project. This notice does not replace any conditions in the authoritative
license text.
"""


GITIGNORE = """# Amosclaud standard ignore file
.env
.env.*
!.env.example
.venv/
venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
node_modules/
dist/
build/
coverage/
.coverage
.DS_Store
Thumbs.db
*.log
.idea/
.vscode/
"""


@router.get("/license-options")
def list_license_options() -> list[dict[str, str]]:
    options = [{"key": "none", "name": "No license", "spdx": ""}]
    options.extend(
        {"key": key, "name": name, "spdx": key.upper()}
        for key, name in LICENSE_NAMES.items()
    )
    return options


@router.post("/{repository_id}/initialize-template")
def initialize_repository_template(
    repository_id: int,
    body: RepositoryTemplateRequest,
    user=Depends(_current_user),
) -> dict:
    with _repo_lock(repository_id), _db() as db:
        row = _access(db, repository_id, user["id"])
        _require_write(row)
        repo = _open(repository_id)
        _checkout(repo, body.branch)
        root = _repo_path(repository_id)
        changed: list[str] = []

        license_text = _license_text(body.license, user["name"] or user["email"])
        if license_text:
            (root / "LICENSE").write_text(license_text, encoding="utf-8")
            changed.append("LICENSE")

        if body.initialize_gitignore:
            (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
            changed.append(".gitignore")

        if not changed:
            return {"files": [], "commit": None}

        try:
            commit = _commit(repo, f"Add {LICENSE_NAMES.get(body.license, 'repository')} template files", user)
        except HTTPException as exc:
            if exc.status_code == 409:
                return {"files": changed, "commit": None}
            raise

        db.execute(
            "UPDATE repositories SET updated_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), repository_id),
        )
        db.commit()
        return {"files": changed, "commit": commit, "license": body.license}
