"""Starting the operation panel from the design: a first version from a template, the design's own things dragged or
clicked onto the panel."""
import json


def tile(page, block):
    return page.locator(f"[data-testid=edit-grid] [data-block={block}]")


def test_a_panel_starts_from_a_template_and_the_designs_own_settings(zh):
    zh.api("POST", "/api/settings", {"settings": [{"id": "wait", "label": "等待秒數", "type": "number", "scope": "shared", "default": 30}]})
    zh.api("POST", "/api/variables", {"vars": [{"name": "trips", "label": "今天次數", "scope": "device", "reset": "daily", "initial": 0}]})
    page = zh.page
    page.goto(zh.base + "/panel/edit")
    first = page.get_by_role("region", name="產生第一版")                     # an empty panel: first versions offered
    first.get_by_role("button").filter(has_text="只看").click()
    tile(page, "b1").wait_for()
    assert page.locator("[data-testid=edit-grid] [data-block]").count() == 4  # devices, incidents, values, log
    page.get_by_role("button", name="復原").click()                          # a template is one step: taken back
    first.wait_for()

    things = page.get_by_role("complementary", name="元件與大綱")
    assert "30" in things.locator("[data-thing='setting:wait']").inner_text()   # each thing as it is now
    grid = page.locator("[data-testid=edit-grid]").bounding_box()
    things.locator("[data-thing='setting:wait']").drag_to(page.locator("[data-testid=edit-grid]"),
                                                          target_position={"x": grid["width"] * 0.75, "y": 40})
    tile(page, "b1").wait_for()
    assert json.loads(tile(page, "b1").get_attribute("data-place"))["x"] == 6     # where it was dropped
    things.locator("[data-thing='variable:trips']").click()                  # a click: its own block, at the bottom
    tile(page, "w1").wait_for()
    assert things.locator("[data-thing='setting:wait']").get_by_text("已放上").count() == 1
    page.get_by_text("● 草稿已儲存,還沒發佈").wait_for()
    page.get_by_role("button", name="發佈", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="發佈", exact=True).click()
    page.get_by_test_id("draft-state").filter(has_text="和發佈的一樣").wait_for()

    panel = zh.api("GET", "/api/panel/definition")["panel"]
    blocks = {b["id"]: b for b in panel["blocks"]}
    assert [c["bind"] for c in panel["controls"] if c["id"] in blocks["b1"]["items"]] == [{"kind": "setting", "setting": "wait"}]
    assert blocks["w1"]["widget"] == {"kind": "values", "vars": ["trips"]}
    page.get_by_role("button", name="完成").click()
    page.wait_for_url(zh.base + "/panel")
    page.locator("#block-w1").get_by_role("columnheader", name="今天次數").wait_for()             # the variable's column on the panel
