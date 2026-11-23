#!/usr/bin/env python3
"""Seeded random mutation testing for app/.

Each mutant is one small source change, applied to a throwaway copy of the
repo. The test suite should fail for it. A mutant that passes has "survived",
which means no test notices that behavior changing.

Exit codes: 0 score met, 1 score below --min-score, 2 the run itself is invalid
(for example the unmutated suite fails).
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import queue
import random
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COMPARE = {
    ast.Eq: ("==", "!="),
    ast.NotEq: ("!=", "=="),
    ast.Lt: ("<", "<="),
    ast.LtE: ("<=", "<"),
    ast.Gt: (">", ">="),
    ast.GtE: (">=", ">"),
    ast.Is: ("is", "is not"),
    ast.IsNot: ("is not", "is"),
    ast.In: ("in", "not in"),
    ast.NotIn: ("not in", "in"),
}
BINARY = {
    ast.Add: ("+", "-"),
    ast.Sub: ("-", "+"),
    ast.Mult: ("*", "/"),
    ast.Div: ("/", "*"),
}
BOOLEAN = {ast.And: ("and", "or"), ast.Or: ("or", "and")}


@dataclass(frozen=True)
class Mutant:
    file: str
    line: int
    operator: str
    start: int
    end: int
    original: str
    replacement: str


class Source:
    def __init__(self, text: str):
        self.text = text
        self.lines = text.split("\n")
        self.line_starts = [0]
        for line in self.lines:
            self.line_starts.append(self.line_starts[-1] + len(line) + 1)
        self.tokens = [
            (self.char(t.start), self.char(t.end), t.string)
            for t in tokenize.generate_tokens(io.StringIO(text).readline)
            if t.type in (tokenize.NAME, tokenize.OP) and t.string not in ("(", ")")
        ]

    def char(self, position: tuple[int, int]) -> int:
        line, column = position
        return self.line_starts[line - 1] + column

    def offset(self, line: int, utf8_column: int) -> int:
        prefix = self.lines[line - 1].encode("utf-8")[:utf8_column]
        return self.line_starts[line - 1] + len(prefix.decode("utf-8"))

    def start(self, node: ast.AST) -> int:
        return self.offset(node.lineno, node.col_offset)

    def end(self, node: ast.AST) -> int:
        return self.offset(node.end_lineno, node.end_col_offset)

    def operator_span(self, left: ast.AST, right: ast.AST, expected: str):
        low, high = self.end(left), self.start(right)
        found = [t for t in self.tokens if low <= t[0] and t[1] <= high]
        if not found or " ".join(t[2] for t in found) != expected:
            return None
        return found[0][0], found[-1][1]


def walk(node: ast.AST):
    """Yield runtime code only: no annotations and no f-string internals,
    whose positions differ between Python 3.10 and 3.12."""
    yield node
    for name, value in ast.iter_fields(node):
        if name in ("annotation", "returns"):
            continue
        children = value if isinstance(value, list) else [value]
        for child in children:
            if isinstance(child, ast.AST) and not isinstance(child, ast.JoinedStr):
                yield from walk(child)


def collect(rel_path: str, text: str) -> list[Mutant]:
    source = Source(text)
    tree = ast.parse(text)
    found: dict[tuple[int, int, str], Mutant] = {}

    def add(line: int, operator: str, start: int, end: int, replacement: str) -> None:
        original = text[start:end]
        if original == replacement:
            return
        mutated = text[:start] + replacement + text[end:]
        try:
            compile(mutated, rel_path, "exec", dont_inherit=True)
        except (SyntaxError, ValueError):
            return
        found[(start, end, replacement)] = Mutant(
            rel_path, line, operator, start, end, original, replacement
        )

    def swap(left, right, table_entry, operator: str) -> None:
        expected, replacement = table_entry
        span = source.operator_span(left, right, expected)
        if span:
            add(left.end_lineno, operator, span[0], span[1], replacement)

    for node in walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for index, op in enumerate(node.ops):
                swap(operands[index], operands[index + 1], COMPARE[type(op)], "compare")
        elif isinstance(node, ast.BoolOp):
            for left, right in zip(node.values, node.values[1:], strict=False):
                swap(left, right, BOOLEAN[type(node.op)], "boolean")
        elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            swap(node.left, node.right, BINARY[type(node.op)], "arithmetic")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            start = source.start(node)
            add(node.lineno, "remove-not", start, start + len("not"), "")
        elif isinstance(node, ast.If):
            start, end = source.start(node.test), source.end(node.test)
            add(node.lineno, "negate-if", start, end, f"not ({text[start:end]})")
        elif isinstance(node, ast.Return) and node.value is not None:
            if not (isinstance(node.value, ast.Constant) and node.value.value is None):
                add(
                    node.lineno,
                    "return-none",
                    source.start(node.value),
                    source.end(node.value),
                    "None",
                )
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                add(
                    node.lineno,
                    "flip-bool",
                    source.start(node),
                    source.end(node),
                    str(not node.value),
                )
            elif isinstance(node.value, int):
                add(
                    node.lineno,
                    "bump-int",
                    source.start(node),
                    source.end(node),
                    str(node.value + 1),
                )
    return sorted(found.values(), key=lambda m: (m.file, m.start, m.replacement))


def repo_files() -> list[str]:
    """Tracked and untracked non-ignored files, as they exist on disk now."""
    output = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return [p for p in output.split("\0") if p and (ROOT / p).is_file()]


def make_sandbox(parent: Path, name: str, files: list[str]) -> Path:
    sandbox = parent / name
    for rel_path in files:
        target = sandbox / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel_path, target)
    (sandbox / ".tmp").mkdir()
    return sandbox


def run_tests(sandbox: Path, timeout: float) -> tuple[str, int | None]:
    temp_dir = str(sandbox / ".tmp")
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "TMPDIR": temp_dir,
        "TEMP": temp_dir,
        "TMP": temp_dir,
    }
    env.pop("PYTHONPATH", None)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"],
            cwd=sandbox,
            env=env,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "timeout", None
    if result.returncode == 0:
        return "survived", 0
    if result.returncode in (1, 2):
        return "killed", result.returncode
    return "error", result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, help="replay a specific random sample")
    parser.add_argument("--samples", type=int, default=150, help="mutants to test")
    parser.add_argument("--min-score", type=float, default=80.0, help="required kill %%")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    parser.add_argument("--report", type=Path, default=Path("mutation-report.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    seed = args.seed if args.seed is not None else secrets.randbelow(2**32)
    files = repo_files()
    targets = sorted(p for p in files if p.startswith("app/") and p.endswith(".py"))
    texts = {p: (ROOT / p).read_text(encoding="utf-8") for p in targets}
    universe = [m for p in targets for m in collect(p, texts[p])]
    if not universe:
        print("No mutants generated.", file=sys.stderr)
        return 2
    chosen = random.Random(seed).sample(universe, min(args.samples, len(universe)))
    print(f"seed={seed} testing {len(chosen)} of {len(universe)} possible mutants", flush=True)

    with tempfile.TemporaryDirectory(prefix="mutation-") as parent_name:
        parent = Path(parent_name)
        baseline_box = make_sandbox(parent, "baseline", files)
        started = time.monotonic()
        status, code = run_tests(baseline_box, 300)
        baseline = time.monotonic() - started
        if status != "survived":
            print(f"Unmutated suite failed ({status}, exit {code}).", file=sys.stderr)
            return 2
        timeout = max(30.0, baseline * 10)

        boxes: queue.Queue[Path] = queue.Queue()
        for index in range(max(1, args.workers)):
            boxes.put(make_sandbox(parent, f"worker{index}", files))

        def evaluate(mutant: Mutant) -> dict:
            box = boxes.get()
            target = box / mutant.file
            original_bytes = target.read_bytes()
            text = texts[mutant.file]
            try:
                target.write_text(
                    text[: mutant.start] + mutant.replacement + text[mutant.end :],
                    encoding="utf-8",
                    newline="\n",
                )
                outcome, return_code = run_tests(box, timeout)
            finally:
                target.write_bytes(original_bytes)
                boxes.put(box)
            return {**asdict(mutant), "status": outcome, "return_code": return_code}

        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            results = list(pool.map(evaluate, chosen))

    counts = Counter(r["status"] for r in results)
    if counts["error"]:
        print(f"{counts['error']} mutants hit a pytest infrastructure error.", file=sys.stderr)
        return 2
    detected = counts["killed"] + counts["timeout"]
    score = 100.0 * detected / len(results)
    survivors = sorted(
        (r for r in results if r["status"] == "survived"),
        key=lambda r: (r["file"], r["line"]),
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "seed": seed,
                "universe": len(universe),
                "tested": len(results),
                "killed": counts["killed"],
                "timeout": counts["timeout"],
                "survived": counts["survived"],
                "score": round(score, 2),
                "min_score": args.min_score,
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    for r in survivors:
        print(
            f"SURVIVED {r['file']}:{r['line']} [{r['operator']}] "
            f"{r['original']!r} -> {r['replacement']!r}"
        )
    print(
        f"score={score:.1f}% killed={counts['killed']} timeout={counts['timeout']} "
        f"survived={counts['survived']} required={args.min_score:.1f}% seed={seed}"
    )
    if score < args.min_score:
        print("MUTATION GATE FAILED", file=sys.stderr)
        return 1
    print("Mutation gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
