"""Simplified Chinese from Traditional: python -m tools.i18n_zhcn

Writes web/src/i18n/locales/zh-CN.json and i18n/locales/zh-CN.json from the full lists to translate (zh-TW.json):
OpenCC turns Taiwan phrasing into mainland phrasing (pip install opencc-python-reimplemented; only this tool needs it),
then FIX corrects the words it gets wrong in this platform's sense. Run it again whenever the texts change."""
import json
import os
import re
from opencc import OpenCC

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cc = OpenCC("tw2sp")
# words OpenCC gets wrong in this platform's sense (applied to the converted text)
FIX = [("仿真器", "模拟器"), ("缺省", "默认"), ("调度", "定时任务"), ("接口", "界面"), ("监看", "监控"), ("品质", "质量"),
       ("「", "“"), ("」", "”"), ("录像档", "录像文件"), ("档案", "文件"),
       ("高端", "高级"), ("激活", "启用"), ("拷贝", "复制"), ("信道", "通道"), ("今天发送了", "今天传送了"), ("纪录", "记录")]


def conv(s):
    # keep {placeholders} and their {n|a|b} forms as they are
    parts = re.split(r"(\{[A-Za-z_][\w|]*\})", s)
    out = "".join(p if p.startswith("{") and p.endswith("}") else cc.convert(p) for p in parts)
    for a, b in FIX:
        out = out.replace(a, b)
    return out


def main():
    for base, dst in [("web/src/i18n/zh-TW.json", "web/src/i18n/locales/zh-CN.json"), ("i18n/zh-TW.json", "i18n/locales/zh-CN.json")]:
        keys = json.load(open(os.path.join(ROOT, base), encoding="utf-8"))
        cat = {k: conv(k) for k in keys}
        with open(os.path.join(ROOT, dst), "w", encoding="utf-8") as f:
            json.dump(cat, f, ensure_ascii=False, indent=1)
            f.write("\n")
        print(dst, len(cat))


if __name__ == "__main__":
    main()
