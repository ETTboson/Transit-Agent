"""Run a local evaluator exposing score(root, output) against saved agent runs."""
import argparse
import importlib.util
from pathlib import Path
import sys


def run(scorer, root, output="scores"):
    scorer = Path(scorer).resolve(strict=True)
    root = Path(root).resolve(strict=True)
    if not scorer.is_file() or not root.is_dir():
        raise ValueError("Provide an evaluator file and a run directory")
    destination = (root / output).resolve()
    if not destination.is_relative_to(root) or destination == root:
        raise ValueError("Output must be a subdirectory of the run directory")
    if destination.exists():
        raise FileExistsError(destination)
    spec = importlib.util.spec_from_file_location("local_evaluator", scorer)
    module = importlib.util.module_from_spec(spec)
    # Existing evaluators import companion scoring modules from their directory.
    previous_path = sys.path.copy()
    sys.path.insert(0, str(scorer.parent))
    try:
        spec.loader.exec_module(module)
        return module.score(root, output)
    finally:
        sys.path[:] = previous_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scorer", required=True, type=Path, help="Local scoring program")
    parser.add_argument("--root", required=True, type=Path, help="Directory of saved runs")
    parser.add_argument("--output", default="scores", help="New output directory within the runs")
    args = parser.parse_args()
    run(args.scorer, args.root, args.output)


if __name__ == "__main__":
    main()
