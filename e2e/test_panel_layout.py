"""The operation panel's layout, arranged by dragging in its design page and shown that way on the panel."""


def save(page):
    page.get_by_role("button", name="儲存", exact=True).click()
    page.get_by_text("● 有未儲存的修改").wait_for(state="hidden")


def tiles(page):
    return page.locator("[data-testid=layout] [data-block]")


def test_blocks_are_arranged_by_dragging_them_and_their_edges(zh):
    page = zh.go("/panel-design")
    for _ in range(2):
        page.get_by_role("button", name="+ 新增設定區塊").click()
    save(page)
    assert [b["id"] for b in zh.api("GET", "/api/panel/definition")["panel"]["blocks"]] == ["b1", "b2"]
    assert tiles(page).count() == 2

    tiles(page).nth(1).drag_to(tiles(page).nth(0))                      # the second block before the first
    assert [t.get_attribute("data-block") for t in tiles(page).all()] == ["b2", "b1"]

    grid = page.locator("[data-testid=layout]").bounding_box()

    def pull(block, to_x):                                              # drag a block's right edge to x
        box = page.locator(f"[data-edge={block}]").bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(to_x, box["y"] + box["height"] / 2, steps=8)
        page.mouse.up()

    pull("b2", grid["x"] + grid["width"] - 2)                           # the first block: the whole row
    assert "寬度:整列" in tiles(page).nth(0).inner_text()
    pull("b1", grid["x"] + grid["width"] / 3)                           # the second, now on the next row: a third
    assert "寬度:1/3 列" in tiles(page).nth(1).inner_text()

    save(page)
    blocks = zh.api("GET", "/api/panel/definition")["panel"]["blocks"]
    assert [(b["id"], b.get("width")) for b in blocks] == [("b2", "wide"), ("b1", "third")]

    zh.page.goto(zh.base + "/panel")                                    # the panel itself: the same order and widths
    zh.page.wait_for_load_state("networkidle")
    zh.page.locator("#block-b1").wait_for()
    assert "xl:col-span-6" in zh.page.locator("#block-b2").get_attribute("class")
    assert "xl:col-span-2" in zh.page.locator("#block-b1").get_attribute("class")
    assert zh.page.locator("#block-b2").bounding_box()["y"] < zh.page.locator("#block-b1").bounding_box()["y"]
