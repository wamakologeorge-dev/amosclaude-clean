from __future__ import annotations

import argparse
import json
from pathlib import Path

from amosclaud_model.config import model_root
from amosclaud_model.model import FolderLanguageModel
from amosclaud_model.workspace import import_folder, initialize


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="amosclaud-model", description="Train and run Amosclaud from local folders"
    )
    parser.add_argument(
        "--home", type=Path, help="Model workspace (defaults to AMOSCLAUD_MODEL_HOME)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the model workspace")
    ingest = commands.add_parser("import", help="Import a safe text/code dataset folder")
    ingest.add_argument("folder", type=Path)
    ingest.add_argument("--license", default="unverified", dest="license_name")
    commands.add_parser("train", help="Build a new atomic checkpoint")
    commands.add_parser("evaluate", help="Evaluate the current checkpoint against datasets/eval")
    commands.add_parser("checkpoints", help="List versioned checkpoints and metrics")
    promote = commands.add_parser("promote", help="Activate a verified checkpoint")
    promote.add_argument("checkpoint_id")
    commands.add_parser("rollback", help="Activate the previous verified checkpoint")
    chat = commands.add_parser("chat", help="Generate locally from the current checkpoint")
    chat.add_argument("prompt")
    chat.add_argument("--max-tokens", type=int, default=256)
    serve = commands.add_parser("serve", help="Start the OpenAI-compatible model server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8091)
    commands.add_parser("status", help="Inspect the model workspace")
    args = parser.parse_args(argv)
    root = (args.home or model_root()).expanduser().resolve()
    initialize(root)
    model = FolderLanguageModel(root)
    if args.command == "init":
        result = initialize(root)
    elif args.command == "import":
        result = import_folder(root, args.folder, args.license_name)
    elif args.command == "train":
        result = model.train()
    elif args.command == "evaluate":
        result = model.evaluate()
        if result is None:
            raise SystemExit("No evaluation documents found under datasets/eval")
    elif args.command == "checkpoints":
        result = model.checkpoints()
    elif args.command == "promote":
        result = model.promote(args.checkpoint_id)
    elif args.command == "rollback":
        result = model.rollback()
    elif args.command == "chat":
        print(model.generate(args.prompt, args.max_tokens))
        return 0
    elif args.command == "serve":
        import os
        import uvicorn

        os.environ["AMOSCLAUD_MODEL_HOME"] = str(root)
        uvicorn.run("amosclaud_model.server:app", host=args.host, port=args.port, reload=False)
        return 0
    else:
        result = {
            "root": str(root),
            "model": model.config.name,
            "trained": model.checkpoint_path.exists(),
            "checkpoint": str(model.checkpoint_path),
        }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
