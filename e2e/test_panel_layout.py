"""The operation panel's layout, arranged by dragging in its edit mode and shown that way on the panel."""
import json



def save(page):
    """publish the draft"""
    page.get_by_text("● 草稿已儲存,還沒發佈").wait_for()
    page.get_by_role("button", name="發佈", exact=True).click()
    page.get_by_role("dialog").get_by_role("button", name="發佈", exact=True).click()
    page.get_by_test_id("draft-state").filter(has_text="和發佈的一樣").wait_for()


def tile(page, block):
    return page.locator(f"[data-testid=edit-grid] [data-block={block}]")


def place(page, block):
    return json.loads(tile(page, block).get_attribute("data-place"))


def drag(page, start, end):
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(*end, steps=12)
    page.mouse.up()


def test_the_panel_is_edited_where_it_is_blocks_dragged_and_resized_on_its_grid(zh):
    page = zh.page
    page.goto(zh.base + "/panel-design")                                # the old design page: now the panel's edit mode
    page.wait_for_url(zh.base + "/panel/edit")
    page.get_by_text("編輯中").wait_for()
    for _ in range(2):
        page.get_by_role("button", name="+ 空白的設定區塊").click()
    save(page)
    blocks = zh.api("GET", "/api/panel/definition")["panel"]["blocks"]
    assert [(b["id"], b["place"]) for b in blocks] == [("b1", {"x": 0, "y": 0, "w": 6}), ("b2", {"x": 0, "y": 1, "w": 6})]

    grid = page.locator("[data-testid=edit-grid]").bounding_box()
    one, two = tile(page, "b1").bounding_box(), tile(page, "b2").bounding_box()
    drag(page, (two["x"] + 40, two["y"] + 40), (grid["x"] + grid["width"] * 0.5 + 40, one["y"] + 40))   # beside the first
    page.wait_for_function("JSON.parse(document.querySelector('[data-block=b2]').dataset.place).y === 0")
    assert place(page, "b2") == {"x": 6, "y": 0, "w": 6}
    page.wait_for_timeout(400)                                            # the grid settles before the next drag

    edge = tile(page, "b1").locator(".react-resizable-handle-e").bounding_box()       # the first: a third of the row
    drag(page, (edge["x"] + edge["width"] / 2, edge["y"] + edge["height"] / 2), (grid["x"] + grid["width"] / 3, edge["y"] + edge["height"] / 2))
    assert place(page, "b1") == {"x": 0, "y": 0, "w": 4}

    page.get_by_role("button", name="復原").click()                       # undo and redo
    assert place(page, "b1") == {"x": 0, "y": 0, "w": 6}
    page.get_by_role("button", name="重做").click()
    assert place(page, "b1") == {"x": 0, "y": 0, "w": 4}

    tile(page, "b1").click()                                              # picked: its words on the right
    props = page.get_by_role("complementary", name="屬性")
    props.locator("input").first.fill("上午")
    page.get_by_role("tab", name="大綱").click()                           # the outline: its new title
    assert "上午" in page.get_by_role("complementary", name="元件與大綱").inner_text()
    props.get_by_role("switch", name="手機上不顯示").click()                # on a phone: left off, and after the other
    page.get_by_role("button", name="手機", exact=True).click()
    phone = page.locator("[data-testid=phone-list] [data-block]")
    phone.first.get_by_role("button", name="往下").click()
    assert [x.get_attribute("data-block") for x in phone.all()] == ["b2", "b1"]
    page.get_by_role("button", name="寬螢幕", exact=True).click()
    save(page)
    blocks = {b["id"]: b for b in zh.api("GET", "/api/panel/definition")["panel"]["blocks"]}
    assert (blocks["b1"]["title"], blocks["b1"]["place"], blocks["b2"]["place"]) == ("上午", {"x": 0, "y": 0, "w": 4}, {"x": 6, "y": 0, "w": 6})
    assert (blocks["b1"]["phone"], blocks["b2"]["phone"]) == ({"order": 2, "hide": True}, {"order": 1})

    page.get_by_role("button", name="完成").click()                       # the panel itself: the same places
    page.wait_for_url(zh.base + "/panel")
    page.locator("#block-b1").wait_for()
    assert json.loads(page.locator("#block-b1").get_attribute("data-place")) == {"x": 0, "y": 0, "w": 4}
    left, right = page.locator("#block-b1").bounding_box(), page.locator("#block-b2").bounding_box()
    assert abs(left["y"] - right["y"]) < 2 and left["x"] < right["x"]


def test_panel_shell_bell_device_page_and_big_text(zh):
    page = zh.page
    page.goto(zh.base + "/panel")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="通知").first.click()                # the notices drawer
    page.get_by_text("沒有要處理的事").wait_for()
    page.keyboard.press("Escape")

    page.get_by_role("button", name="設定").click()                      # large text: the whole page scales
    page.get_by_role("switch", name="大字模式").click()
    assert page.evaluate("document.documentElement.style.fontSize") == "18px"
    page.get_by_role("switch", name="大字模式").click()
    assert page.evaluate("document.documentElement.style.fontSize") == ""
    page.keyboard.press("Escape")

    page.goto(zh.base + "/panel/device/nobody")                          # an emulator's own page; one not there
    page.get_by_text("找不到「nobody」").wait_for()
    page.get_by_role("button", name="回總覽").click()
    page.wait_for_url(zh.base + "/panel")


def test_the_panel_takes_the_designers_accent_and_large_text(zh):
    panel = zh.api("GET", "/api/panel/definition")["panel"]
    zh.api("POST", "/api/panel/definition", {"panel": {**panel, "theme": {"accent": "#7c3aed", "big_text": True}}})
    try:
        page = zh.page
        page.goto(zh.base + "/panel")
        page.evaluate("localStorage.removeItem('panel.big')")                          # no choice of this viewer's yet
        page.reload()
        page.wait_for_load_state("networkidle")
        page.locator("#panel-top").wait_for()
        assert page.evaluate("getComputedStyle(document.getElementById('panel-top')).getPropertyValue('--accent').trim()") == "124 58 237"
        assert page.evaluate("document.documentElement.style.fontSize") == "18px"        # large text unless turned off
        page.get_by_role("button", name="設定").click()
        page.get_by_role("switch", name="大字模式").click()                              # this viewer turns it off
        assert page.evaluate("document.documentElement.style.fontSize") == ""
        page.reload()
        page.wait_for_load_state("networkidle")
        page.locator("#panel-top").wait_for()
        assert page.evaluate("document.documentElement.style.fontSize") == ""            # and it stays off for them
    finally:
        zh.api("POST", "/api/panel/definition", {"panel": panel})
