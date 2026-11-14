"""JSON Schema of the script spec, version 1 (locked 2026-10-10): the format of scripts, sub-scripts, variables,
outputs and script tests as they are stored and as the JSON editor shows them.

Locked means: a field is never renamed, removed or given a new meaning in version 1. New kinds of steps, actions or
conditions, or new optional fields, raise the spec version (automation/spec.py FORMAT) and come with an upgrade.

    python -m automation.spec_schema [--write <folder>]     print / write the schemas as files

check(kind, doc) validates one document: the schema first (field names and types), then the platform's own checks
(states, buttons, variables, sub-scripts that must exist ...). Messages are for people: field path + what is wrong."""
import argparse
import json
import os

from . import spec
from i18n import N_, _, tr

ID = r"^[a-z][a-z0-9_]*$"
REF = {"oneOf": [
    {"type": "object", "properties": {"param": {"type": "string"}}, "required": ["param"], "additionalProperties": False},
    {"type": "object", "properties": {"setting": {"type": "string"}}, "required": ["setting"], "additionalProperties": False},
    {"type": "object", "properties": {"var": {"type": "string"}}, "required": ["var"], "additionalProperties": False},
    {"type": "object", "properties": {"state": {"type": "string"}}, "required": ["state"], "additionalProperties": False},
    {"type": "object", "properties": {"sum": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/num"}}}, "required": ["sum"], "additionalProperties": False},
]}
DEFS = {
    "ref": {"description": N_("執行時從參數 / 使用者設定 / 變數 / 狀態(畫面上讀到的數字)取值"), **REF},
    "num": {"description": N_("數字,或執行時從參數 / 設定 / 變數取值"), "oneOf": [{"type": "number"}, {"$ref": "#/$defs/ref"}]},
    "text": {"description": N_("文字(可用 {代號} 帶入變數或參數),或執行時取值"), "oneOf": [{"type": "string"}, {"$ref": "#/$defs/ref"}]},
    "point": {"description": N_("位置:按鈕庫的按鈕、座標、點位參數或使用者設定"), "oneOf": [
        {"type": "object", "properties": {"button": {"type": "string"}}, "required": ["button"], "additionalProperties": False},
        {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}}, "required": ["x", "y"], "additionalProperties": False},
        {"type": "object", "properties": {"param": {"type": "string"}}, "required": ["param"], "additionalProperties": False},
        {"type": "object", "properties": {"setting": {"type": "string"}}, "required": ["setting"], "additionalProperties": False},
        {"type": "object", "maxProperties": 0},
    ]},
    "cond": {"type": "object", "additionalProperties": False, "properties": {
        "kind": {"enum": ["state", "became", "count", "change", "time", "always", "var", "elapsed", "device", "visible", "compare"]},
        "left": {"$ref": "#/$defs/num"}, "right": {"$ref": "#/$defs/num"},
        "state": {"type": "string"}, "op": {"enum": ["is", "is_not", "lt", "lte", "gt", "gte"]},
        "value": {"description": N_("比較的值:選項、數字或參照")},
        "for": {"type": "number", "minimum": 0}, "min_conf": {"type": "number", "minimum": 0, "maximum": 1},
        "within": {"type": "number"}, "times": {"$ref": "#/$defs/num"}, "dir": {"enum": ["drop", "rise"]},
        "amount": {"$ref": "#/$defs/num"}, "from": {"type": "string"}, "to": {"type": "string"},
        "days": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 6}},
        "var": {"type": "string"}, "device": {"type": "string"}, "target": {"$ref": "#/$defs/point"}}},
    "when": {"description": N_("條件:外層「或者」,內層「而且」"), "type": "array",
             "items": {"type": "array", "items": {"$ref": "#/$defs/cond"}}},
    "args": {"type": "object", "description": N_("呼叫子腳本的參數:代號 → 值(位置、數字、文字、清單或參照)")},
    "action": {"type": "object", "required": ["type"], "additionalProperties": False, "properties": {
        "type": {"enum": ["tap", "long_press", "back", "call", "goto", "set_var", "wait", "none", "notify", "stop", "hold", "output"]},
        "text": {"type": "string"}, "target": {"$ref": "#/$defs/point"},
        "sub": {"type": "string"}, "args": {"$ref": "#/$defs/args"},
        "on_success": {"type": "string"}, "on_fail": {"type": "string"}, "situation": {"type": "string"},
        "var": {"type": "string"}, "mode": {"enum": ["set", "add", "now"]}, "value": {"$ref": "#/$defs/text_or_num"},
        "output": {"type": "string"}, "command": {"type": "string"}}},
    "text_or_num": {"oneOf": [{"type": "number"}, {"type": "string"}, {"$ref": "#/$defs/ref"}]},
    "rule": {"type": "object", "required": ["id", "when", "do"], "additionalProperties": False, "properties": {
        "id": {"type": "string", "pattern": ID}, "name": {"type": "string"}, "enabled": {"type": "boolean"},
        "urgent": {"type": "boolean"}, "when": {"$ref": "#/$defs/when"},
        "do": {"$ref": "#/$defs/steps", "description": N_("條件成立時依序做的步驟(和子腳本同一套步驟)")},
        "cooldown": {"type": "number", "minimum": 0}, "max_per_hour": {"type": ["integer", "null"], "minimum": 1},
        "max_per_day": {"type": ["integer", "null"], "minimum": 1}}},
    "situation": {"type": "object", "required": ["id", "name", "rules"], "additionalProperties": False, "properties": {
        "id": {"type": "string", "pattern": ID}, "name": {"type": "string"},
        "rules": {"type": "array", "items": {"$ref": "#/$defs/rule"}},
        "on_enter": {"oneOf": [{"$ref": "#/$defs/steps"}, {"type": "null"}], "description": N_("進入這個情境時做一次的步驟")},
        "max_seconds": {"type": ["number", "null"]}, "on_timeout": {"type": "string"}}},
    "step": {"type": "object", "required": ["type"], "additionalProperties": False, "properties": {
        "type": {"enum": ["tap", "long_press", "swipe", "back", "input_text", "launch_app", "pick", "walk_to", "capture_list", "wait",
                          "wait_until", "if", "retry", "repeat_until", "for_each", "call", "call_item", "set_var", "notify", "output",
                          "succeed", "fail", "ask", "goto", "stop", "stay", "hold"]},
        "situation": {"type": "string", "description": N_("切換情境:要切到的情境")},
        "after": {"type": "object", "additionalProperties": False, "description": N_("做完這個操作之後:等幾秒,或等到條件成立"),
                  "properties": {"seconds": {"$ref": "#/$defs/num"}, "until": {"$ref": "#/$defs/when"},
                                 "timeout": {"$ref": "#/$defs/num"}, "on_timeout": {"enum": ["fail", "continue"]}}},
        "fail_goto": {"type": "string", "description": N_("呼叫子腳本失敗時切到的情境(第 7 版留下的寫法)")},
        "options": {"description": N_("問使用者:選項(2~6 個),每個選了要做的步驟"), "type": "array", "minItems": 2, "maxItems": 6,
                    "items": {"type": "object", "required": ["label"], "additionalProperties": False,
                              "properties": {"label": {"type": "string", "minLength": 1, "maxLength": 20},
                                             "then": {"$ref": "#/$defs/steps"}}}},
        "default": {"description": N_("問使用者:沒人回答時選第幾個(0 = 失敗)"), "type": "integer", "minimum": 0, "maximum": 6},
        "label": {"type": "string"}, "target": {"$ref": "#/$defs/point"}, "from": {"$ref": "#/$defs/point"},
        "say": {"type": "string", "description": N_("給使用者看:正在做什麼(白話)")},
        "say_fail": {"type": "string", "description": N_("給使用者看:這一步失敗時說什麼(白話)")},
        "to": {"$ref": "#/$defs/point"}, "ms": {"$ref": "#/$defs/num"}, "seconds": {"$ref": "#/$defs/num"},
        "when": {"$ref": "#/$defs/when"}, "timeout": {"$ref": "#/$defs/num"}, "on_timeout": {"enum": ["fail", "continue"]},
        "then": {"$ref": "#/$defs/steps"}, "else": {"$ref": "#/$defs/steps"},
        "elif": {"type": "array", "items": {"type": "object", "required": ["when"], "additionalProperties": False,
                                            "properties": {"when": {"$ref": "#/$defs/when"}, "then": {"$ref": "#/$defs/steps"}}}},
        "steps": {"$ref": "#/$defs/steps"}, "times": {"$ref": "#/$defs/num"}, "delay": {"$ref": "#/$defs/num"},
        "max_times": {"$ref": "#/$defs/num"}, "max_seconds": {"$ref": "#/$defs/num"},
        "sub": {"type": "string"}, "args": {"$ref": "#/$defs/args"}, "on_fail": {"enum": ["fail", "continue", "stop"]},
        "catalog": {"type": "string", "description": N_("照目錄項目做:哪個目錄")},
        "item": {"description": N_("照目錄項目做:哪一項(項目代號,或執行時從使用者設定 / 參數取)"),
                 "oneOf": [{"type": "string"}, {"$ref": "#/$defs/ref"}]},
        "var": {"type": "string"}, "mode": {"enum": ["set", "add", "now"]}, "value": {"$ref": "#/$defs/text_or_num"},
        "list": {"type": "string"}, "as": {"type": "string", "pattern": ID}, "as_label": {"type": "string"},
        "on_item_fail": {"enum": ["fail", "continue"]}, "max_swipes": {"$ref": "#/$defs/num"}, "settle": {"$ref": "#/$defs/num"},
        "package": {"$ref": "#/$defs/text"}, "text": {"$ref": "#/$defs/text"},
        "output": {"type": "string"}, "command": {"type": "string"},
        "open": {"$ref": "#/$defs/point", "description": N_("走到地圖上的位置:點哪裡打開地圖")},
        "close": {"$ref": "#/$defs/point", "description": N_("走到地圖上的位置:點哪裡關掉地圖")},
        "anchor": {"$ref": "#/$defs/point", "description": N_("走到地圖上的位置:地圖上的基準圖示(找圖的按鈕)")},
        "anchors": {"type": "array", "items": {"type": "object", "required": ["button", "x", "y"], "additionalProperties": False,
                    "properties": {"button": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}}},
                    "description": N_("走到地圖上的位置:其他基準圖示和它們的位置(從第一個基準圖示算起);第一個不在畫面上時用")},
        "me": {"type": "object", "additionalProperties": False, "required": ["color", "box"],
               "description": N_("走到地圖上的位置:「自己」在地圖上的樣子(顏色)和地圖在畫面上的範圍"),
               "properties": {"color": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3},
                              "more": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3}},
                              "tol": {"type": "number"}, "min_px": {"type": "number"},
                              "box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}}},
        "points": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["x", "y"], "additionalProperties": False,
                   "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "label": {"type": "string"},
                                  "near": {"type": "number"},
                                  "links": {"type": "array", "items": {"type": "integer", "minimum": 1}},
                                  "end": {"type": "boolean"}, "check": {"type": "boolean"},
                                  "moves": {"type": "array", "items": {"type": "object", "required": ["to"], "additionalProperties": False,
                                            "properties": {"to": {"type": "integer", "minimum": 1},
                                                           "dir": {"type": "integer", "enum": [1, 2, 3, 4, 6, 7, 8, 9]},
                                                           "s": {"type": "number"}}}}}},
                   "description": N_("走到地圖上的位置:依序要走到的點(從基準圖示算起);點有「連到」時是路線網,最後一點是目的地")},
        "stick": {"type": "object", "required": ["x", "y", "r"], "additionalProperties": False,
                  "description": N_("走到地圖上的位置:方向控制(搖桿)的中心和推多遠"),
                  "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "r": {"type": "number"},
                                 "press": {"enum": ["drag", "edge"]}}},
        "near": {"$ref": "#/$defs/num"}, "push_ms": {"$ref": "#/$defs/num"}, "max_moves": {"$ref": "#/$defs/num"},
        "tries": {"$ref": "#/$defs/num", "description": N_("走到地圖上的位置(可走區域圖):卡住幾次(每次都換路繞過去)就放棄")},
        "area": {"type": "string", "description": N_("走到地圖上的位置:可走區域圖(填了就照它自己找路,走到最後一個點)")},
        "turn": {"$ref": "#/$defs/num", "description": N_("走到地圖上的位置:地圖方向和搖桿方向差幾度(填了就不用學)")},
        "speed": {"$ref": "#/$defs/num", "description": N_("走到地圖上的位置:推一秒在地圖上走幾個像素(填了就從這個開始)")},
        "until": {"$ref": "#/$defs/when", "description": N_("走到地圖上的位置:這個條件成立就算到了(可不填)")},
        "mini": {"type": "object", "additionalProperties": False, "required": ["box"],
                 "description": N_("走到地圖上的位置:跟著自己的小地圖(推完看它捲了多少,大地圖只偶爾打開)"),
                 "properties": {"box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                                "mask": {"type": "number"}, "check_every": {"type": "number"}, "min_resp": {"type": "number"}}}}},
    "steps": {"type": "array", "items": {"$ref": "#/$defs/step"}},
    "param": {"type": "object", "required": ["name", "type"], "additionalProperties": False, "properties": {
        "name": {"type": "string", "pattern": ID}, "label": {"type": "string"},
        "type": {"enum": ["point", "number", "text", "list"]}, "item": {"enum": ["point", "number", "text"]},
        "from_list": {"type": "string"}, "default": {}}},
}
META = {"format": {"const": spec.FORMAT, "description": N_("腳本規範版本")},
        "version": {"type": "integer"}, "created": {"type": "number"}, "note": {"type": "string"}}


def schema(kind):
    return tr(_schema(kind))


def _schema(kind):
    """The JSON Schema of one kind of document."""
    base = {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://inspector.local/spec/v{spec.FORMAT}/{kind}.schema.json", "$defs": DEFS}
    if kind == "script":
        return {**base, "title": _("主腳本 / 守門規則(腳本規範 v{FORMAT})", FORMAT=spec.FORMAT), "type": "object",
                "required": ["id", "name", "situations"], "additionalProperties": False, "properties": {
                    "id": {"type": "string", "pattern": ID}, "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string"}, "enabled": {"type": "boolean"},
                    "devices": {"type": "object", "description": _("部署:\"*\"(其他所有)、來源代號、或 \"#標籤\"(有這個標籤的來源)"),
                                "additionalProperties": {"enum": ["off", "shadow", "live"]}},
                    "initial": {"type": "string"}, "situations": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/situation"}},
                    "otherwise": {"$ref": "#/$defs/action"}, **META}}
    if kind == "sub":
        return {**base, "title": _("子腳本(腳本規範 v{FORMAT})", FORMAT=spec.FORMAT), "type": "object",
                "required": ["id", "name", "steps"], "additionalProperties": False, "properties": {
                    "id": {"type": "string", "pattern": ID}, "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string"}, "params": {"type": "array", "items": {"$ref": "#/$defs/param"}},
                    "say": {"type": "string", "description": _("給使用者看:這個子腳本在做什麼(白話)")},
                    "say_fail": {"type": "string", "description": _("給使用者看:失敗時說什麼(步驟沒有自己的說明時)")},
                    "steps": {"$ref": "#/$defs/steps"}, "cleanup": {"$ref": "#/$defs/steps"},
                    "timeout": {"type": "number", "minimum": 1}, **META}}
    if kind == "panel":
        control = {"type": "object", "required": ["id", "label", "type", "bind"], "additionalProperties": False, "properties": {
            "id": {"type": "string", "pattern": ID}, "label": {"type": "string", "minLength": 1}, "help": {"type": "string"},
            "type": {"enum": ["toggle", "time", "number", "multi", "single", "action"]}, "scope": {"enum": ["global", "device"]},
            "bind": {"type": "object", "required": ["kind"], "properties": {"kind": {"enum": [
                "setting", "schedule", "schedule_device", "schedule_arg", "entry_arg", "act_schedule", "act_sub", "act_situation", "act_stop"]}}},
            "min": {"type": ["number", "null"]}, "max": {"type": ["number", "null"]}, "unit": {"type": "string"},
            "scale": {"type": "number"}, "options": {"oneOf": [{"type": "string", "pattern": "^(list|catalog):"}, {"type": "array"}]},
            "chat": {"type": "string", "description": _("在聊天 Bot 裡的名稱(不填 = 用名稱)")},
            "chat_off": {"type": "boolean", "description": _("只放在頁面,聊天裡不能用")},
            "devices": {"type": "array", "items": {"type": "string"},
                        "description": _("每台各自的控制項只給這些來源(代號或 #標籤);不填 = 每一台")}}}
        block = {"type": "object", "required": ["id", "title"], "additionalProperties": False, "properties": {
            "id": {"type": "string"}, "title": {"type": "string"}, "help": {"type": "string"}, "toggle": {"type": "string"},
            "items": {"type": "array", "items": {"type": "string"}},
            "page": {"type": "string", "description": _("在哪個分頁(沒填 = 第一個)")},
            "width": {"enum": ["auto", "third", "narrow", "two_thirds", "wide"], "description": _("寬螢幕上:自動 / 1/3 列 / 半列 / 2/3 列 / 整列")},
            "widget": {"type": "object", "required": ["kind"], "properties": {"kind": {"enum": ["devices", "incidents", "deploy", "schedules", "log", "chat", "list", "values"]}}},
            "place": {"type": "object", "required": ["x", "y", "w"], "additionalProperties": False,
                      "description": _("寬螢幕 12 欄格線上的位置:第幾欄、第幾列、佔幾欄、幾列高(沒填 = 依內容)"), "properties": {
                          "x": {"type": "integer", "minimum": 0, "maximum": 11}, "y": {"type": "integer", "minimum": 0},
                          "w": {"type": "integer", "minimum": 1, "maximum": 12}, "h": {"type": "integer", "minimum": 1, "maximum": 100}}},
            "phone": {"type": "object", "additionalProperties": False, "description": _("手機(一欄)上:排第幾、要不要藏起來"), "properties": {
                "order": {"type": "integer"}, "hide": {"type": "boolean"}}}}}
        page = {"type": "object", "required": ["id", "title"], "additionalProperties": False, "properties": {
            "id": {"type": "string", "pattern": ID}, "title": {"type": "string", "minLength": 1}}}
        return {**base, "title": _("操作面板(腳本規範 v{FORMAT});同一份設計也決定聊天 Bot 能做什麼", FORMAT=spec.FORMAT), "type": "object",
                "required": ["blocks", "controls"], "additionalProperties": False, "properties": {
                    "title": {"type": "string"}, "devices": {"type": "array", "items": {"type": "string"}},
                    "pages": {"type": "array", "items": page, "description": _("分頁(沒有 = 一頁)")},
                    "sources": {"type": "object", "additionalProperties": False, "description": _("使用者可以掃描、選用的來源"), "properties": {
                        "kinds": {"type": "array", "items": {"type": "string"}, "description": _("種類,或「大類/*」")},
                        "q": {"type": "string", "description": _("名稱過濾(這些字都要有)")},
                        "help": {"type": "string", "description": _("掃描前要準備什麼")},
                        "new_mode": {"enum": ["shadow", "live"], "description": _("選用後主腳本先試跑或正式執行")}}},
                    "theme": {"type": "object", "additionalProperties": False, "description": _("面板的外觀"), "properties": {
                        "accent": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$", "description": _("強調色(要按的東西)")},
                        "big_text": {"type": "boolean", "description": _("預設用大字(看的人可以自己關掉)")}}},
                    "blocks": {"type": "array", "items": block}, "controls": {"type": "array", "items": control}, **META}}
    if kind == "catalogs":
        call = {"type": "object", "required": ["sub"], "additionalProperties": False, "properties": {
            "sub": {"type": "string", "description": _("要呼叫的子腳本")}, "args": {"$ref": "#/$defs/args"}}}
        item = {"type": "object", "required": ["id", "name", "calls"], "additionalProperties": False, "properties": {
            "id": {"type": "string", "pattern": ID}, "name": {"type": "string", "minLength": 1},
            "folder": {"type": "string", "description": _("放在哪個資料夾(a/b)")},
            "calls": {"type": "array", "minItems": 1, "items": call, "description": _("做法:依序呼叫這些子腳本")},
            "here": {"$ref": "#/$defs/when", "description": _("怎麼看出已經在那裡(先看:已經在就不用做;做完後等它成立)")},
            "here_wait": {"type": "number", "description": _("做完後等「已經在那裡」成立最多幾秒")},
            "note": {"type": "string"}}}
        cat = {"type": "object", "required": ["id", "name", "items"], "additionalProperties": False, "properties": {
            "id": {"type": "string", "pattern": ID}, "name": {"type": "string", "minLength": 1}, "description": {"type": "string"},
            "items": {"type": "array", "items": item}}}
        return {**base, "title": _("目錄(腳本規範 v{FORMAT})", FORMAT=spec.FORMAT), "type": "object",
                "properties": {"catalogs": {"type": "array", "items": cat}, "saved": {"type": "number"}, **META}}
    if kind == "variables":
        item = {"type": "object", "required": ["name", "scope", "reset"], "additionalProperties": False, "properties": {
            "name": {"type": "string", "pattern": ID}, "label": {"type": "string"}, "scope": {"enum": ["device", "global"]},
            "reset": {"enum": ["daily", "never"]}, "initial": {"type": "number"}}}
        return {**base, "title": _("變數"), "type": "object",
                "properties": {"vars": {"type": "array", "items": item}, "saved": {"type": "number"}, **META}}
    if kind == "outputs":
        item = {"type": "object", "required": ["id", "name", "type"], "properties": {
            "id": {"type": "string", "pattern": ID}, "name": {"type": "string"}, "type": {"type": "string"}}}
        return {**base, "title": _("輸出"), "type": "object",
                "properties": {"outputs": {"type": "array", "items": item}, "saved": {"type": "number"}, **META}}
    if kind == "tests":
        item = {"type": "object", "required": ["id", "name", "session", "device", "minutes", "expect"], "properties": {
            "id": {"type": "string"}, "name": {"type": "string"}, "session": {"type": "string"}, "device": {"type": "string"},
            "start": {"type": "number"}, "minutes": {"type": "number"}, "sub_result": {"enum": ["success", "fail"]},
            "sub_results": {"type": "object"},
            "expect": {"type": "array", "items": {"type": "object", "required": ["kind", "when"]}}}}
        return {**base, "title": _("腳本測試"), "type": "object",
                "properties": {"tests": {"type": "array", "items": item}, "saved": {"type": "number"}, **META}}
    raise KeyError(kind)


KINDS = {"script": N_("主腳本 / 守門規則"), "sub": N_("子腳本"), "variables": N_("變數"), "outputs": N_("輸出"), "tests": N_("腳本測試"), "panel": N_("操作面板"), "catalogs": N_("目錄")}

_WORD = {"required": N_("缺少欄位"), "additionalProperties": N_("不認得的欄位"), "enum": N_("值不正確"),
         "type": N_("型別不對"), "const": N_("值不對"), "pattern": N_("格式不對(只能用小寫英文、數字、底線,且以英文開頭)"),
         "minItems": N_("至少要有一個"), "minLength": N_("不能空白"), "minimum": N_("太小"), "maximum": N_("太大"), "oneOf": N_("寫法不對")}


def _path(p):
    out = ""
    for k in p:
        out += f"[{k}]" if isinstance(k, int) else (f".{k}" if out else str(k))
    return out or _("(整份)")


def schema_errors(kind, doc, limit=20):
    """[{"path", "message"}] of the schema check (field names and types)."""
    import jsonschema
    v = jsonschema.Draft202012Validator(schema(kind))
    out = []
    for e in sorted(v.iter_errors(doc), key=lambda e: (len(e.path), list(map(str, e.path)))):
        word = _(_WORD.get(e.validator, e.validator))
        detail = ""
        if e.validator == "required":
            detail = e.message.split("'")[1] if "'" in e.message else ""
        elif e.validator == "additionalProperties":
            detail = _("、").join(sorted(set(e.instance) - set((e.schema.get("properties") or {}).keys())))
        elif e.validator == "enum":
            detail = _("只能是 {p1}", p1=_("、").join(map(str, e.validator_value)))
        elif e.validator == "type":
            detail = _("要是 {validator_value}", validator_value=e.validator_value)
        out.append({"path": _path(e.absolute_path), "message": f"{word}" + (f":{detail}" if detail else "")})
        if len(out) >= limit:
            break
    return out


def must_match(kind, doc):
    """Raise ValueError when a document about to be saved does not match the spec (the same check as export and
    the JSON editor): a value the run accepts but the spec does not (e.g. true / false compared) is caught here."""
    errs = schema_errors(kind, doc, 3)
    if errs:
        raise ValueError(_("不符合腳本規範:{p1}", p1=_("、").join(f"{e['path']} {e['message']}" for e in errs)))


def check(kind, doc, data_root):
    """-> [{"path", "message"}]; empty = the document can be saved."""
    errs = schema_errors(kind, doc)
    if errs:
        return errs
    try:
        if kind == "script":
            import automation
            import schema as schema_mod
            from . import subs
            automation.validate(automation.normalize(doc), schema_mod.load(data_root), subs.load_all(data_root),
                                {v["name"] for v in automation.variables(data_root)})
        elif kind == "sub":
            import automation
            import schema as schema_mod
            from . import subs
            lib = subs.load_all(data_root)
            subs.validate(doc, {k: v for k, v in lib.items() if k != doc.get("id")}, schema_mod.load(data_root),
                          {v["name"] for v in automation.variables(data_root)})
        elif kind == "panel":
            from server.panel_chat import check as check_chat
            from server.panel import normalize
            check_chat(normalize(json.loads(json.dumps(doc))))
    except ValueError as e:
        return [{"path": _("(內容)"), "message": str(e)}]
    return []


def main():
    ap = argparse.ArgumentParser(prog="python -m automation.spec_schema", description=_("印出 / 寫出腳本規範的 JSON Schema"))
    ap.add_argument("--write", help=_("寫到這個資料夾(每種一個 .schema.json)"))
    a = ap.parse_args()
    for k in KINDS:
        text = json.dumps(schema(k), ensure_ascii=False, indent=1)
        if a.write:
            os.makedirs(a.write, exist_ok=True)
            with open(os.path.join(a.write, f"{k}.schema.json"), "w", encoding="utf-8") as f:
                f.write(text + "\n")
        else:
            print(text)


if __name__ == "__main__":
    main()
