"""Wrap the Chinese texts of .py files in _() (i18n): python -m tools.i18n_wrap <file> [...] [--dry] [--mark]

What it changes (the Python parser reads the file, so code structure is never guessed):
    "子腳本失敗"                  -> _("子腳本失敗")
    f"第 {n} 步"                  -> _("第 {n} 步", n=n)            (other expressions: {p1}, p1=expr)
    f"{x:.0f} 秒"                 -> _("{x} 秒", x=f"{x:.0f}")
What it leaves (data, not words to show, or texts that must be translated where they are used) and lists for a look:
docstrings, dict keys, x["..."], comparisons (== "工作中", in (...)), .startswith("...") / .endswith / .split / ...,
re patterns, module- and class-level values (tables: mark them N_() and translate where shown), default argument
values, texts already in _() / N_(), and lines marked "# i18n: keep" (a command or other data that
looks like words). A sentence whose values hold more Chinese is wrapped piece by piece and listed:
write it as whole sentences by hand.
--mark: also mark the module- / class-level texts N_("...") (then translate them where they are used: _(x) / i18n.tr)."""
import ast
import keyword
import io
import re
import sys
import tokenize

CJK = re.compile(r"[㐀-鿿]")
DATA_CALLS = {"startswith", "endswith", "split", "rsplit", "replace", "strip", "lstrip", "rstrip", "find", "rfind", "index",
              "count", "get", "setdefault", "pop", "removeprefix", "removesuffix", "partition", "rpartition", "encode"}
RE_FUNCS = {"compile", "match", "search", "sub", "subn", "findall", "finditer", "fullmatch", "split"}


def _has_cjk(node):
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str) and CJK.search(n.value) for n in ast.walk(node))


class Wrapper:
    def __init__(self, src, path):
        self.src, self.path = src, path
        self.tree = ast.parse(src)
        self.lines = src.splitlines(keepends=True)
        self.starts = [0]
        for ln in self.lines:
            self.starts.append(self.starts[-1] + len(ln))
        self.parent = {}
        for p in ast.walk(self.tree):
            for c in ast.iter_child_nodes(p):
                self.parent[c] = p
        self.report = []
        self.count = 0
        self.marked = 0
        self.mark = False

    def off(self, line, col):
        # ast columns are utf-8 byte offsets
        text = self.lines[line - 1]
        return self.starts[line - 1] + len(text.encode("utf-8")[:col].decode("utf-8"))

    def span(self, node):
        return self.off(node.lineno, node.col_offset), self.off(node.end_lineno, node.end_col_offset)

    def seg(self, node):
        a, b = self.span(node)
        return self.src[a:b]

    def note(self, node, why):
        self.report.append(f"{self.path}:{node.lineno} {why}")

    # ---------- what is data ----------
    def data_reason(self, node):
        """Why this text node is left as it is (None: it is a text to show)."""
        if "# i18n: keep" in self.lines[node.lineno - 1]:
            return "marked keep"
        p = self.parent.get(node)
        child = node
        while isinstance(p, (ast.Tuple, ast.List, ast.Set)):        # an element of a literal collection
            child, p = p, self.parent.get(p)
        if isinstance(p, ast.Expr):
            return "docstring / bare text"
        if isinstance(p, ast.Dict) and child in p.keys:
            return "dict key"
        if isinstance(p, ast.Subscript) and child is p.slice:
            return 'x["..."]'
        if isinstance(p, ast.Compare):
            return "comparison"
        if isinstance(p, ast.Call):
            f = p.func
            if child is f:
                return None
            if isinstance(f, ast.Name) and f.id in ("_", "N_"):
                return "already wrapped"
            if isinstance(f, ast.Attribute) and f.attr in ("get", "pop", "setdefault") and p.args and child is not p.args[0]:
                pass                                         # d.get("key", "不限"): the default is a text to show
            elif isinstance(f, ast.Attribute) and f.attr in DATA_CALLS:
                return f".{f.attr}(...)"
            if isinstance(f, ast.Attribute) and f.attr in RE_FUNCS and isinstance(f.value, ast.Name) and f.value.id == "re":
                return "re pattern"
        if isinstance(p, ast.Attribute):                     # "、".join(...) and other methods on a text
            return f'"...".{p.attr}()'
        if isinstance(p, ast.arguments):
            return "default argument"
        if isinstance(p, ast.FormattedValue) and child is p.format_spec:
            return "format spec"
        # module- / class-level values are read once: the table must be N_() and translated where shown
        q = node
        while q in self.parent:
            q = self.parent[q]
            if isinstance(q, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return None
            if isinstance(q, ast.arguments):
                return "default argument"
            if isinstance(q, (ast.ClassDef, ast.Module)):
                return "module/class level (mark N_() and translate where shown)"
        return None

    # ---------- rendering ----------
    def render(self, node, inner=False):
        """The source of node with every text inside it wrapped (a JoinedStr / str Constant itself included)."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and CJK.search(node.value):
            why = self.data_reason(node) if not inner else self.data_reason_inner(node)
            if why and why.startswith("module/class") and self.mark:
                self.marked += 1
                return "N_(" + _dq(node.value) + ")"
            if why:
                if why != "already wrapped" and not why.startswith("docstring"):
                    self.note(node, f"留下({why}): {node.value[:40]!r}")
                return self.seg(node)
            self.count += 1
            return "_(" + _dq(node.value) + ")"
        if isinstance(node, ast.JoinedStr) and _has_cjk(node):
            why = self.data_reason(node)
            if why:
                if why != "already wrapped":
                    self.note(node, f"留下({why}): {self.seg(node)[:50]}")
                return self.seg(node)
            return self.wrap_fstring(node)
        return self.render_children(node)

    def data_reason_inner(self, node):
        return self.data_reason(node)

    def render_children(self, node):
        """node's source with the texts inside it wrapped (node itself is not a text)."""
        a, b = self.span(node)
        edits = []
        for c in self.targets(node):
            ca, cb = self.span(c)
            edits.append((ca, cb, self.render(c)))
        out, pos = [], a
        for ca, cb, txt in sorted(edits):
            out.append(self.src[pos:ca])
            out.append(txt)
            pos = cb
        out.append(self.src[pos:b])
        return "".join(out)

    def targets(self, node):
        """The outermost text nodes (with Chinese) inside node."""
        found = []

        def walk(n):
            for c in ast.iter_child_nodes(n):
                if isinstance(c, ast.JoinedStr) and _has_cjk(c) or isinstance(c, ast.Constant) and isinstance(c.value, str) and CJK.search(c.value):
                    if hasattr(c, "lineno"):
                        found.append(c)
                    continue
                walk(c)
        walk(node)
        return found

    def wrap_fstring(self, node):
        msg, params, used = [], [], set()
        split = False
        for i, v in enumerate(node.values):
            if isinstance(v, ast.Constant):
                msg.append(v.value)
                continue
            expr = v.value
            name = _param_name(expr, used, len(params) + 1)
            src = self.render_children_or_self(expr)
            if _has_cjk(expr):
                split = True
            if v.conversion == ord("r"):
                src = f"repr({src})"
            elif v.conversion in (ord("s"), ord("a")):
                src = f"str({src})"
            if v.format_spec is not None:
                spec = self.seg(v.format_spec) if hasattr(v.format_spec, "lineno") else "".join(
                    x.value for x in v.format_spec.values if isinstance(x, ast.Constant))
                if all(isinstance(x, ast.Constant) for x in v.format_spec.values):
                    spec = "".join(x.value for x in v.format_spec.values)
                    src = f"format({src}, {spec!r})"
                else:
                    self.note(node, "格式裡有值,請手動處理")
                    return self.seg(node)
            msg.append("{" + name + "}")
            params.append(f"{name}={src}")
        if split:
            self.note(node, "句子被含中文的值拆開,請手動寫成一整句")
        self.count += 1
        text = "".join(msg)
        return "_(" + _dq(text) + (", " + ", ".join(params) if params else "") + ")"

    def render_children_or_self(self, expr):
        if isinstance(expr, ast.Constant) or isinstance(expr, ast.JoinedStr):
            return self.render(expr)
        return self.render_children(expr)

    def run(self):
        out = self.render_children(self.tree) if self.tree.body else self.src
        a = self.span(self.tree.body[0])[0] if self.tree.body else 0
        b = self.span(self.tree.body[-1])[1] if self.tree.body else 0
        return self.src[:a] + out[0:] + self.src[b:] if False else out


def _dq(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def _param_name(expr, used, i):
    n = None
    if isinstance(expr, ast.Name):
        n = expr.id
    elif isinstance(expr, ast.Attribute):
        n = expr.attr
    elif isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant) and isinstance(expr.slice.value, str):
        n = expr.slice.value
    elif isinstance(expr, ast.Call):
        f = expr.func
        if isinstance(f, ast.Attribute) and f.attr == "get" and expr.args and isinstance(expr.args[0], ast.Constant) \
                and isinstance(expr.args[0].value, str):
            n = expr.args[0].value
        elif isinstance(f, ast.Name) and f.id in ("len",):
            n = None
    if not n or not re.fullmatch(r"[A-Za-z_]\w*", n) or n in ("_", "msg") or keyword.iskeyword(n):
        n = f"p{i}"
    k, j = n, 2
    while k in used:
        k = f"{n}{j}"
        j += 1
    used.add(k)
    return k


def _module_span_render(w):
    """The whole file with its texts wrapped."""
    edits = []
    for c in w.targets(w.tree):
        a, b = w.span(c)
        edits.append((a, b, w.render(c)))
    if w.count or w.marked:
        # a throwaway "_" (for _ in ..., x, _ = ...) would make _ a local of the whole function: rename it
        for n in ast.walk(w.tree):
            if isinstance(n, ast.Name) and n.id == "_" and isinstance(n.ctx, ast.Store) or isinstance(n, ast.arg) and n.arg == "_":
                a = w.off(n.lineno, n.col_offset)
                edits.append((a, a + 1, "_x"))
            elif isinstance(n, ast.Name) and n.id == "_" and isinstance(n.ctx, ast.Load) \
                    and not (isinstance(w.parent.get(n), ast.Call) and w.parent[n].func is n):
                w.note(n, "「_」被當成變數讀取,請手動改名")
    out, pos = [], 0
    for a, b, txt in sorted(edits):
        out.append(w.src[pos:a])
        out.append(txt)
        pos = b
    out.append(w.src[pos:])
    return "".join(out)


def _ensure_import(src, names=("_",)):
    m = re.search(r"^from i18n import (.*)$", src, re.M)
    if m:
        have = [x.strip() for x in m.group(1).split(",")]
        want = sorted(set(have) | set(names), key=lambda x: (x != "N_", x))
        return src[:m.start(1)] + ", ".join(want) + src[m.end(1):]
    line = "from i18n import " + ", ".join(sorted(names, key=lambda x: (x != "N_", x))) + "\n"
    tree = ast.parse(src)
    last = None
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            last = n
        elif last is not None or not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant)):
            if last is not None:
                break
    lines = src.splitlines(keepends=True)
    if last is None:
        idx = 0
        if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
            idx = tree.body[0].end_lineno
        lines.insert(idx, line)
    else:
        lines.insert(last.end_lineno, line)
    return "".join(lines)


def main(argv):
    dry = "--dry" in argv
    total = 0
    for path in [a for a in argv if not a.startswith("--")]:
        src = open(path, encoding="utf-8").read()
        w = Wrapper(src, path)
        w.mark = "--mark" in argv
        out = _module_span_render(w)
        if (w.count or w.marked) and not dry:
            out = _ensure_import(out, (["_"] if w.count else []) + (["N_"] if w.marked else []))
            ast.parse(out)                                   # never write a file that no longer parses
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(out)
        total += w.count
        print(f"{path}: 包進 _() {w.count} 處" + (f",標記 N_() {w.marked} 處" if w.marked else "") + f",留下/要手動 {len(w.report)} 處")
        for r in w.report:
            print("   " + r)
    print(f"合計 {total} 處")


if __name__ == "__main__":
    main(sys.argv[1:])
