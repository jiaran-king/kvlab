import argparse
import copy
import json
from pathlib import Path

from .engine import simulate
from .inputs import compile_scenario
from .result import compare_observed, export


def main():
    parser = argparse.ArgumentParser(description="Offline KV mechanism simulator")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "sweep"):
        p = sub.add_parser(command)
        p.add_argument("--config", type=Path)
        p.add_argument("--output", type=Path, default=Path("output/kvsim"))
        if command == "sweep":
            p.add_argument("--kv-gib", nargs="+", type=float, required=True)
    p = sub.add_parser("explain")
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--request-id", required=True)
    p = sub.add_parser("compare")
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--observed", type=Path, required=True)
    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--duration", type=int, default=7200, help="Maximum service lifetime in seconds")
    args = parser.parse_args()
    if args.command == "serve":
        from .web import serve
        serve(args.port, args.duration)
        return
    if args.command == "explain":
        result = json.loads(args.result.read_text())
        print(json.dumps(next(r for r in result["requests"] if r["request_id"] == args.request_id), ensure_ascii=False, indent=2))
        return
    if args.command == "compare":
        print(json.dumps(compare_observed(json.loads(args.result.read_text()), json.loads(args.observed.read_text())), indent=2))
        return
    settings = json.loads(args.config.read_text()) if args.config else {}
    scenario = compile_scenario(settings)
    if args.command == "run":
        result = simulate(scenario)
        export(result, args.output)
        print(json.dumps({"status": result["status"], **result["summary"], "failure": result["failure"]}, ensure_ascii=False))
    else:
        rows = []
        if len(args.kv_gib) > 12:
            parser.error("At most 12 capacity points")
        for value in args.kv_gib:
            point = copy.deepcopy(scenario)
            point["config"].pop("kv_bytes", None)
            point["config"]["kv_gib"] = value
            result = simulate(point)
            export(result, args.output / f"{value:g}GiB")
            rows.append({"kv_gib": value, "status": result["status"], **result["summary"]})
        (args.output / "sweep.json").write_text(json.dumps(rows, indent=2))
        print(json.dumps(rows, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except NotImplementedError as exc:
        print(json.dumps({"status": "unsupported", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2)
