"""The operation panel's draft: changes are kept as a draft until published, what is wrong keeps it from being
published, every publish is a version that can come back, the draft can be previewed."""


def state(page, text):
    page.get_by_test_id("draft-state").filter(has_text=text).wait_for()


def test_changes_wait_in_a_draft_until_they_are_published(zh):
    zh.api("POST", "/api/panel/definition", {"panel": {"title": "第一版", "devices": [], "blocks": [], "controls": []}})
    page = zh.page
    page.goto(zh.base + "/panel/edit")
    page.get_by_text("編輯中").wait_for()
    page.get_by_label("面板名稱").fill("草稿裡的名字")
    state(page, "● 草稿已儲存,還沒發佈")
    assert zh.api("GET", "/api/panel")["title"] != "草稿裡的名字"           # the users still see the published one
    page.reload()                                                       # the draft is kept
    page.get_by_text("編輯中").wait_for()
    assert page.get_by_label("面板名稱").input_value() == "草稿裡的名字"

    page.get_by_role("button", name="+ 數值").click()                      # no variable picked: an error
    page.get_by_role("tab", name="問題 1").click()
    page.get_by_test_id("problems").get_by_text("錯誤", exact=True).wait_for()
    assert page.get_by_role("button", name="發佈", exact=True).is_disabled()
    page.get_by_role("button", name="復原").click()
    page.get_by_role("tab", name="問題", exact=True).wait_for()
    page.get_by_role("tab", name="聊天").click()                          # what chat can do: a tab of its own
    page.get_by_role("complementary", name="屬性").get_by_text("聊天裡可以做的事").wait_for()

    page.get_by_role("button", name="預覽").click()                       # the draft as its users will see it
    frame = page.frame_locator("iframe[title=預覽]")
    frame.get_by_text("草稿預覽").wait_for()
    assert frame.get_by_role("button", name="草稿裡的名字").count() == 1
    page.get_by_role("dialog", name="預覽").get_by_role("button", name="手機").click()
    assert page.locator("iframe[title=預覽]").evaluate("e => e.style.width") == "390px"
    page.get_by_role("button", name="關閉").click()

    page.get_by_role("button", name="發佈", exact=True).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("textbox").fill("改名字")
    dialog.get_by_role("button", name="發佈", exact=True).click()
    state(page, "和發佈的一樣")
    assert zh.api("GET", "/api/panel")["title"] == "草稿裡的名字"
    notes = [v["note"] for v in zh.api("GET", "/api/panel/versions")["items"]]
    assert notes == ["改名字", "直接存檔(沒有經過草稿)"]                 # published at once (an AI): kept too

    page.get_by_role("button", name="版本紀錄").click()                   # an older version back, as a draft
    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("versions").get_by_role("button", name="載入成草稿").last.click()
    state(page, "● 草稿已儲存,還沒發佈")
    assert page.get_by_label("面板名稱").input_value() == "第一版"
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="放棄草稿").click()                   # and dropped: the published one again
    state(page, "和發佈的一樣")
    assert page.get_by_label("面板名稱").input_value() == "草稿裡的名字"
    assert zh.api("GET", "/api/panel/draft")["draft"] is None
