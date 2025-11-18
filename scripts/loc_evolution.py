from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt


@dataclass
class CommitLocRecord:
    commit_hash: str
    commit_number: int
    date: str
    total_loc: int
    added: int
    removed: int
    message: str


def run_command(args: Sequence[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    completed = subprocess.run(
        list(args),
        cwd=str(cwd) if cwd is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace") if isinstance(completed.stdout, bytes) else completed.stdout
    stderr = completed.stderr.decode("utf-8", errors="replace") if isinstance(completed.stderr, bytes) else completed.stderr
    return completed.returncode, stdout, stderr


def ensure_clean_working_tree(repo_dir: Path) -> None:
    code, out, err = run_command(["git", "status", "--porcelain"], cwd=repo_dir)
    if code != 0:
        raise RuntimeError(f"git status failed: {err.strip()}" or out.strip())
    if out.strip():
        raise RuntimeError("Working tree is not clean. Commit or stash changes before running this script.")


def get_release_ready_commits(repo_dir: Path) -> List[Tuple[str, str]]:
    code, out, err = run_command(
        ["git", "log", "--reverse", "--format=%H %cI", "release-ready"],
        cwd=repo_dir,
    )
    if code != 0:
        raise RuntimeError(f"git log failed for branch 'release-ready': {err.strip()}" or out.strip())
    commits: List[Tuple[str, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        commit_hash, date_str = parts
        commits.append((commit_hash, date_str))
    return commits


def should_exclude_file(filepath: Path) -> bool:
    exclude_paths = {
        "vendor",
        "lib",
        "extern",
        "node_modules",
        "__pycache__",
        ".recycle_bin",
        "venv",
        "env",
        ".git",
    }
    if any(part in exclude_paths for part in filepath.parts):
        return True

    name = filepath.name
    if name.startswith("test_") and filepath.suffix == ".py":
        return True
    if name.endswith("_test.py"):
        return True

    if name != "requirements.txt" and filepath.suffix in {".md", ".rst", ".txt"}:
        return True

    if filepath.suffix not in {".py", ".ts", ".js"} and name != "requirements.txt":
        return True

    if filepath.name == "requirements.txt":
        return False

    if is_mostly_imports(filepath):
        return True

    if looks_third_party(filepath):
        return True

    return False


def is_mostly_imports(filepath: Path, sample_lines: int = 200) -> bool:
    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    lines = text.splitlines()
    if not lines:
        return False
    lines = lines[:sample_lines]
    code_lines = 0
    import_like = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "//", "/*", "*")):
            continue
        code_lines += 1
        if filepath.suffix == ".py":
            if line.startswith("import ") or line.startswith("from "):
                import_like += 1
        else:
            if line.startswith("import ") or line.startswith("export ") or line.startswith("from "):
                import_like += 1
    if code_lines == 0:
        return False
    return import_like / code_lines > 0.5


def looks_third_party(filepath: Path) -> bool:
    lowered_parts = [p.lower() for p in filepath.parts]
    third_party_markers = {
        "third_party",
        "3rdparty",
        "3rd_party",
        "externals",
        "external",
        "dist",
        "build",
        "bundle",
        "min",
    }
    if any(marker in lowered_parts for marker in third_party_markers):
        return True

    name = filepath.name.lower()
    if any(name.startswith(prefix) for prefix in ("jquery", "react.", "react-", "lodash", "moment", "underscore")):
        return True
    if any(name.endswith(suffix) for suffix in (".min.js", ".bundle.js")):
        return True

    return False


def get_files_for_commit(repo_dir: Path) -> List[Path]:
    code, out, err = run_command(["git", "ls-files"], cwd=repo_dir)
    if code != 0:
        raise RuntimeError(f"git ls-files failed: {err.strip()}" or out.strip())
    files: List[Path] = []
    for line in out.splitlines():
        rel = line.strip()
        if not rel:
            continue
        path = repo_dir / rel
        if path.is_file() and not should_exclude_file(path):
            files.append(path)
    return files


def run_cloc_on_files(repo_dir: Path, files: Sequence[Path]) -> Optional[int]:
    if not files:
        return 0

    cloc_cmd = [
        "cloc",
        "--csv",
        "--quiet",
        "--sum-one",
        "--include-lang=Python,TypeScript,JavaScript",
    ]

    rel_paths = [str(f.relative_to(repo_dir)) for f in files]
    cloc_cmd.extend(rel_paths)

    code, out, err = run_command(cloc_cmd, cwd=repo_dir)
    if code != 0:
        sys.stderr.write(f"Warning: cloc failed: {err or out}\n")
        return None

    reader = csv.DictReader(out.splitlines())
    total_code = 0
    for row in reader:
        if row.get("language", "").lower() == "sum":
            try:
                total_code = int(row.get("code", "0"))
            except ValueError:
                total_code = 0
            break
    return total_code


def generate_records(
    repo_dir: Path,
    commits: Sequence[Tuple[str, str, str]],
    sample_every: int,
) -> List[CommitLocRecord]:
    records: List[CommitLocRecord] = []
    prev_total: Optional[int] = None
    for idx, (commit_hash, date_str, message) in enumerate(commits, start=1):
        if sample_every > 1 and (idx - 1) % sample_every != 0:
            continue

        code, _, err = run_command(["git", "checkout", "--quiet", commit_hash], cwd=repo_dir)
        if code != 0:
            sys.stderr.write(f"Warning: git checkout failed for {commit_hash}: {err}\n")
            continue

        files = get_files_for_commit(repo_dir)
        total_loc = run_cloc_on_files(repo_dir, files)
        if total_loc is None:
            continue

        if prev_total is None:
            added = total_loc
            removed = 0
        else:
            delta = total_loc - prev_total
            if delta >= 0:
                added = delta
                removed = 0
            else:
                added = 0
                removed = -delta

        prev_total = total_loc

        records.append(
            CommitLocRecord(
                commit_hash=commit_hash,
                commit_number=idx,
                date=date_str,
                total_loc=total_loc,
                added=added,
                removed=removed,
                message=message,
            )
        )

        print(
            f"Commit {idx}/{len(commits)}: {commit_hash[:7]} (+{added}, -{removed}, total: {total_loc} LOC)",
            flush=True,
        )

    return records


def write_csv(records: Sequence[CommitLocRecord], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["commit_hash", "commit_number", "date", "total_loc", "added", "removed", "message"])
        for r in records:
            writer.writerow(
                [
                    r.commit_hash,
                    r.commit_number,
                    r.date,
                    r.total_loc,
                    r.added,
                    r.removed,
                    r.message.replace("\n", " ").strip(),
                ]
            )


def write_summary(records: Sequence[CommitLocRecord], summary_path: Path) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        summary = "No records generated."
        summary_path.write_text(summary, encoding="utf-8")
        print(summary)
        return

    start_loc = records[0].total_loc
    end_loc = records[-1].total_loc
    peak_loc = max(r.total_loc for r in records)
    if start_loc == 0:
        compression_pct = 0.0
    else:
        compression_pct = (end_loc - start_loc) / start_loc * 100.0

    summary_lines = [
        f"Started at {start_loc} LOC",
        f"Ended at {end_loc} LOC",
        f"Peak LOC: {peak_loc}",
        f"Change: {compression_pct:.1f}%",
    ]
    summary = "\n".join(summary_lines)
    summary_path.write_text(summary, encoding="utf-8")
    print(f"Summary: Started at {start_loc} LOC, ended at {end_loc} LOC ({compression_pct:.1f}% change)")


def write_chart(records: Sequence[CommitLocRecord], png_path: Path) -> None:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        return

    x = [r.commit_number for r in records]
    additions = [r.added for r in records]
    deletions = [r.removed for r in records]

    width = 0.4
    x_add = [n - width / 2 for n in x]
    x_del = [n + width / 2 for n in x]

    plt.figure(figsize=(max(8, len(x) * 0.2), 6))
    plt.bar(x_add, additions, width=width, color="green", label="Additions")
    plt.bar(x_del, deletions, width=width, color="red", label="Deletions")
    plt.xlabel("Commit Number")
    plt.ylabel("Lines of Code Changed")
    plt.title("LOC Evolution on release-ready Branch (Per-Commit Delta)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(png_path)
    plt.close()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze LOC evolution on the release-ready branch using cloc and generate CSV/PNG/TXT reports."
        )
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="Path to the git repository (default: current directory)",
    )
    parser.add_argument(
        "--branch",
        type=str,
        default="release-ready",
        help="Branch to analyze (default: release-ready)",
    )
    parser.add_argument(
        "--sample-every",
        type=int,
        default=1,
        help="Analyze every Nth commit for speed (default: 1 = all commits)",
    )
    return parser.parse_args(argv)


def get_commits_with_messages(repo_dir: Path, branch: str) -> List[Tuple[str, str, str]]:
    format_str = "%H%x01%cI%x01%s"
    code, out, err = run_command(
        ["git", "log", "--reverse", f"--format={format_str}", branch],
        cwd=repo_dir,
    )
    if code != 0:
        raise RuntimeError(f"git log failed for branch '{branch}': {err.strip()}" or out.strip())
    commits: List[Tuple[str, str, str]] = []
    for line in out.splitlines():
        parts = line.split("\x01")
        if len(parts) != 3:
            continue
        commit_hash, date_str, message = parts
        commits.append((commit_hash, date_str, message))
    return commits


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    repo_dir = args.repo.resolve()

    try:
        ensure_clean_working_tree(repo_dir)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    code, out, err = run_command(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
    if code != 0:
        print(f"git rev-parse failed: {err.strip()}" or out.strip(), file=sys.stderr)
        return 1
    current_branch = out.strip()

    try:
        commits = get_commits_with_messages(repo_dir, args.branch)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not commits:
        print(f"No commits found on branch {args.branch}")
        return 0

    total_commits = len(commits)
    print(f"Analyzing {args.branch} branch ({total_commits} commits)")

    try:
        records = generate_records(repo_dir, commits, args.sample_every)
    finally:
        run_command(["git", "checkout", "--quiet", current_branch], cwd=repo_dir)

    reports_dir = repo_dir / "loc_reports"
    csv_path = reports_dir / "loc_history.csv"
    png_path = reports_dir / "loc_evolution.png"
    summary_path = reports_dir / "loc_summary.txt"

    write_csv(records, csv_path)
    print(f"Saved {csv_path.relative_to(repo_dir)}")

    write_chart(records, png_path)
    print(f"Saved {png_path.relative_to(repo_dir)}")

    write_summary(records, summary_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
