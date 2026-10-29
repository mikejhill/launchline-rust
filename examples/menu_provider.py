"""Emit a small deterministic menu; commands run only when selected."""

import json

print(
    json.dumps(
        {
            "entries": [
                {
                    "id": "git",
                    "name": "Git status",
                    "command": "git",
                    "args": ["status"],
                    "description": "Inspect the current repository",
                },
                {
                    "id": "history",
                    "name": "Git history",
                    "command": "git",
                    "args": ["log", "--oneline", "-5"],
                    "description": "Recent commits",
                },
            ]
        }
    )
)
