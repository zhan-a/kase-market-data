#!/usr/bin/env python3
"""
Enforce the no-literals rule on plotting code. Gate step 6.

The rule needs its own check because the clean-clone gate cannot see this
class of defect: that gate compares numbers in the writeups against numbers in
script output, and a constant typed into plotting source is in neither set.
Two figures in the companion repository were built from stored constants and
neither was caught.

Fails on a numeric literal outside a styling context, an import or call that
performs analysis rather than drawing, and a data read from outside
data/derived/. Exit 1 on any finding.

Styling means a matplotlib keyword, an argument to an axis-configuration call,
the rcParams block, or a module-level UPPER_CASE constant. Integers of
magnitude 2 or less pass anywhere, being indices rather than measurements.

Ported from kase-price-discovery, with two changes: the target path, and the
input check also covers a reader call whose argument is an expression rather
than a string, so that a read from outside data/derived/ cannot hide behind a
Path built in the call.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "src" / "make_figures.py"]

# keywords that are appearance, not measurement
STYLE_KW = {
    "figsize", "dpi", "fontsize", "ms", "markersize", "lw", "linewidth",
    "markeredgewidth", "alpha", "zorder", "width", "height", "pad", "labelpad",
    "rotation", "ncol", "columnspacing", "handlelength", "borderpad",
    "width_ratios", "height_ratios", "wspace", "hspace", "left", "right", "top",
    "bottom", "x", "y", "xy", "xytext", "s", "capsize", "elinewidth",
    "gridspec_kw",
}

# axis and canvas configuration, not series
STYLE_FUNC = {
    "set_xlim", "set_ylim", "set_xbound", "set_ybound", "axhline", "axvline",
    "axhspan", "axvspan", "subplots", "subplots_adjust", "tight_layout",
    "set_xticks", "set_yticks", "margins", "set_position", "suptitle",
    "annotate", "text", "legend", "grid", "set_title", "set_xlabel",
    "set_ylabel", "update", "add_subplot", "figure", "set_size_inches",
}

# reads: a bare name resolves through the module constants, anything else must
# say DERIVED
READERS = {"read_csv", "read_table", "read_json", "read_excel", "read_pickle",
           "read_parquet", "open", "loadtxt", "genfromtxt"}

# analysis that must not happen here
FORBIDDEN_IMPORTS = {"statsmodels", "sklearn", "scipy", "glob", "yfinance"}
FORBIDDEN_CALLS = {
    "OLS", "lstsq", "polyfit", "read_parquet", "groupby", "merge_asof",
    "resample", "rolling", "cov", "corr", "quantile", "fit",
}

SMALL_INT = 2


class Checker(ast.NodeVisitor):
    def __init__(self, src, path):
        self.src, self.path = src.splitlines(), path
        self.findings = []
        self.allowed_nodes = set()
        self.upper_const_nodes = set()

    def note(self, node, kind, detail):
        line = self.src[node.lineno - 1].strip() if node.lineno <= len(self.src) else ""
        self.findings.append((node.lineno, kind, detail, line[:96]))

    # allowances
    def mark(self, node):
        for sub in ast.walk(node):
            self.allowed_nodes.add(id(sub))

    def visit_Module(self, node):
        # path constants point under data/derived/, so a read_csv on a bare
        # name is safe
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            seg = ast.unparse(stmt.value)
            if ".csv" in seg or "parquet" in seg:
                if "DERIVED" not in seg:
                    self.note(stmt, "input-outside-derived", seg[:60])
        # UPPER_CASE is where layout numbers live
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                if names and all(n.isupper() or "_" in n and n.upper() == n for n in names):
                    self.mark(stmt.value)
        self.generic_visit(node)

    def visit_Call(self, node):
        fname = node.func.attr if isinstance(node.func, ast.Attribute) else (
            node.func.id if isinstance(node.func, ast.Name) else "")
        if fname in FORBIDDEN_CALLS:
            self.note(node, "analysis-in-plotting", f"call to {fname}()")
        if fname in STYLE_FUNC:
            for a in node.args:
                self.mark(a)
        for kw in node.keywords:
            if kw.arg in STYLE_KW:
                self.mark(kw.value)
        if fname in READERS:
            for a in node.args:
                if isinstance(a, ast.Name):
                    continue  # bare names resolve through the constants
                seg = ast.unparse(a)
                if "DERIVED" not in seg and "data/derived" not in seg:
                    self.note(node, "input-outside-derived", seg[:60])
        self.generic_visit(node)

    def visit_Import(self, node):
        for a in node.names:
            if a.name.split(".")[0] in FORBIDDEN_IMPORTS:
                self.note(node, "analysis-in-plotting", f"imports {a.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module and node.module.split(".")[0] in FORBIDDEN_IMPORTS:
            self.note(node, "analysis-in-plotting", f"imports from {node.module}")
        if node.module == "_store":
            self.note(node, "analysis-in-plotting", "reads the bar store")
        self.generic_visit(node)

    # the literal check
    def visit_Constant(self, node):
        v = node.value
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return
        if id(node) in self.allowed_nodes:
            return
        if isinstance(v, int) and abs(v) <= SMALL_INT:
            return
        self.note(node, "unclassified-literal", repr(v))


def check(path):
    tree = ast.parse(path.read_text())
    c = Checker(path.read_text(), path)
    # two passes: a literal in a styling call is marked only once that call is
    # visited
    c.visit(tree)
    c.findings = []
    c.visit(tree)
    return sorted(set(c.findings))


def main():
    total = 0
    for path in TARGETS:
        if not path.exists():
            print(f"{path}: missing")
            total += 1
            continue
        findings = check(path)
        rel = path.relative_to(ROOT)
        if not findings:
            print(f"  ok    {rel}: no unclassified literals, no analysis")
            continue
        total += len(findings)
        print(f"  FAIL  {rel}: {len(findings)} finding(s)")
        for lineno, kind, detail, line in findings:
            print(f"          {rel}:{lineno}  {kind}: {detail}")
            print(f"            {line}")
    if total:
        print(f"\n{total} finding(s). A plotted number must come from data/derived/, "
              f"and a layout number must be a named constant.")
        return 1
    print("Plotting code plots only what an analysis script wrote.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
