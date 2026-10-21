"""Interface languages (多語系): what there is to translate and what each language still lacks.

    python -m tools.i18n extract     every text in t('...') (web) / _("...") (Python) -> the full lists to translate:
                                     web/src/i18n/zh-TW.json and i18n/zh-TW.json ({text: text}, sorted)
    python -m tools.i18n check       per language: how many texts it lacks, and texts it has that are no longer used
    python -m tools.i18n todo [-v]   Chinese written straight into the code (not in t() / _() yet), per file

A text must be written out in the call (t('第 {n} 步', { n }), not t(`第 ${n} 步`) or t(variable)): the tool
reports the ones it cannot read. Python tables mark their texts with N_("...") and translate them where they are
shown with _(table[key]) - those calls are fine."""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CJK = re.compile(r"[㐀-鿿]")
SIDES = {
    "web": {"glob": (".ts", ".tsx"), "prefix": "web/src/", "call": re.compile(r"(?<![\w.$])t\(\s*(['\"])((?:\\.|(?!\1).)*)\1"),
            "bad": re.compile(r"(?<![\w.$])t\(\s*(`|[A-Za-z_$])"), "base": "web/src/i18n/zh-TW.json", "locales": "web/src/i18n/locales"},
    "server": {"glob": (".py",), "prefix": "", "call": re.compile(r"(?<![\w.])N?_\(\s*(['\"])((?:\\.|(?!\1).)*)\1"),
               "bad": re.compile(r"(?<![\w.])N?_\(\s*f['\"]"), "base": "i18n/zh-TW.json", "locales": "i18n/locales"},
}
SKIP_DIRS = ("web/node_modules/", "web/dist/", "tools/", "docs/", "web/src/i18n/", "i18n/")   # the t() / _() modules themselves


def _files(side):
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8").stdout.split()
    cfg = SIDES[side]
    return [f for f in out if f.endswith(cfg["glob"]) and f.startswith(cfg["prefix"]) and not f.startswith(SKIP_DIRS)
            and not (side == "server" and f.startswith("web/"))]


def _unescape(s, quote):
    return s.replace("\\" + quote, quote).replace("\\\\", "\\").replace("\\n", "\n")


def texts(side):
    """{text: [file:line, ...]} of every t() / _() call, and the calls that cannot be read."""
    cfg, found, bad = SIDES[side], {}, []
    for f in _files(side):
        src = open(os.path.join(ROOT, f), encoding="utf-8").read()
        for m in cfg["call"].finditer(src):
            line = src.count("\n", 0, m.start()) + 1
            found.setdefault(_unescape(m.group(2), m.group(1)), []).append(f"{f}:{line}")
        for m in cfg["bad"].finditer(src):
            line = src.count("\n", 0, m.start()) + 1
            bad.append(f"{f}:{line}")
    return found, bad


def extract():
    for side, cfg in SIDES.items():
        found, bad = texts(side)
        path = os.path.join(ROOT, cfg["base"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({k: k for k in sorted(found)}, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        print(f"{side}: {len(found)} 段文字 -> {cfg['base']}")
        for b in bad:
            print(f"   讀不到(要直接寫出文字): {b}")


def check():
    for side, cfg in SIDES.items():
        found, _ = texts(side)
        d = os.path.join(ROOT, cfg["locales"])
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not f.endswith(".json"):
                continue
            cat = json.load(open(os.path.join(d, f), encoding="utf-8"))
            missing = [k for k in found if not cat.get(k)]
            unused = [k for k in cat if k not in found]
            print(f"{side} {f[:-5]}: 共 {len(found)} 段,缺 {len(missing)} 段,多出(已不用){len(unused)} 段")


def todo(verbose=False):
    """Chinese still written straight into the code: string literals / JSX text with Chinese outside t() / _()."""
    lit = re.compile(r"""(['"`])((?:\\.|(?!\1).)*?)\1""")
    total = 0
    for side, cfg in SIDES.items():
        rows = []
        for f in _files(side):
            src = open(os.path.join(ROOT, f), encoding="utf-8").read()
            src = re.sub(r"(?m)^\s*(#|//).*$", "", src)                  # whole-line comments
            src = re.sub(r'"""[\s\S]*?"""', "", src) if side == "server" else re.sub(r"/\*[\s\S]*?\*/", "", src)
            wrapped = {m.start(2) for m in cfg["call"].finditer(src)}
            n = 0
            for m in lit.finditer(src):
                if CJK.search(m.group(2)) and m.start(2) not in wrapped:
                    n += 1
            if f.endswith(".tsx"):
                n += sum(1 for m in re.finditer(r">([^<>{}]*)<", src) if CJK.search(m.group(1)))
            if n:
                rows.append((n, f))
        rows.sort(reverse=True)
        sub = sum(n for n, _ in rows)
        total += sub
        print(f"{side}: 還有約 {sub} 處中文沒有包進 {'t()' if side == 'web' else '_()'}({len(rows)} 個檔案)")
        for n, f in rows if verbose else rows[:12]:
            print(f"   {n:5}  {f}")
    print(f"合計約 {total} 處")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    {"extract": extract, "check": check, "todo": lambda: todo("-v" in sys.argv)}[cmd]()
