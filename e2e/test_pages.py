"""From an empty project, as the tutorial goes: name it, add a camera, look at every page - in Chinese and in English."""
import re

from conftest import HAN

# the pages with a "what this page is for" card: (path, the card's id)
INTRO = [("/sources", "sources"), ("/collect", "collect"), ("/states", "states"), ("/review", "review"),
         ("/library", "library"), ("/scripts", "scripts"), ("/script", "script"), ("/schedules", "schedules"),
         ("/panel-design", "panel-design"), ("/packs", "packs")]
OTHERS = ["/", "/browse", "/labels", "/train", "/results", "/tests", "/storage", "/ai"]


def card(page, title):
    return page.locator("section", has=page.locator("h2", has_text=re.compile(f"^{re.escape(title)}$")))


def test_a_new_project_starts_at_the_first_stop(zh):
    page = zh.go("/")
    route = card(page, "入門路線")
    assert "完成 0 / 10" in route.inner_text()
    assert "下一站" in route.inner_text() and "替專案取名字" in route.inner_text()


def test_naming_the_project_ticks_the_first_stop(zh):
    page = zh.go("/")
    project = card(page, "專案")
    project.locator("input").nth(0).fill("Test farm")
    project.locator("input").nth(1).fill("One camera over a greenhouse")
    project.locator("input").nth(2).fill("camera")
    with page.expect_navigation():                       # saving reloads: the words are read when the pages open
        project.get_by_role("button", name="儲存").click()
    page.locator("main h1").first.wait_for()
    assert "完成 1 / 10" in card(page, "入門路線").inner_text()
    assert zh.api("GET", "/api/project")["name"] == "Test farm"


def test_adding_a_camera_by_its_address(zh, camera):
    page = zh.go("/sources")
    page.get_by_role("button", name="+ 加入來源").click()
    page.get_by_role("button", name=re.compile(r"^\+ HTTP")).click()
    page.get_by_placeholder("例如:魚池 A、大門口").fill("Greenhouse cam")
    page.get_by_placeholder("不填 = 用名稱").fill("GH-CAM")
    page.locator("input[placeholder^='rtsp://']").fill(camera)
    page.get_by_role("button", name="加入", exact=True).click()
    page.wait_for_load_state("networkidle")
    assert "Greenhouse cam" in zh.go("/sources").locator("main").inner_text()
    assert zh.api("GET", "/api/getting_started")["done"]["sources"] is True


def test_pages_show_the_camera_by_name_not_by_code(zh):
    for path in ("/collect", "/script"):                 # (Sources is where the code is shown)
        zh.go(path)
        assert "GH-CAM" not in zh.text(), path
    assert "Greenhouse cam" in zh.go("/collect").locator("main").inner_text()


def test_every_page_opens(zh):
    for path in OTHERS + [p for p, _ in INTRO]:
        zh.go(path)
        assert zh.page.locator("main h1").first.inner_text().strip(), path
    assert not zh.errors


def test_each_page_says_what_it_is_for_until_closed(zh):
    for path, _id in INTRO:
        page = zh.go(path)
        intro = page.locator("main").get_by_text("這頁是做什麼的", exact=True)
        assert intro.count() == 1, path
        assert page.locator("main").get_by_role("link", name="教學的這一章 ↗").get_attribute("href").startswith(
            "https://github.com/wrbyhaquc/inspector/blob/main/docs/tutorial.zh-TW.md#"), path
        page.locator("main").get_by_role("button", name="知道了").click()
        assert intro.count() == 0, path
        page.reload()
        page.locator("main h1").first.wait_for()
        assert page.locator("main").get_by_text("這頁是做什麼的", exact=True).count() == 0, path


def test_the_route_links_to_the_pages_and_the_chapters(zh):
    page = zh.go("/")
    route = card(page, "入門路線")
    assert "完成 2 / 10" in route.inner_text()
    hrefs = [a.get_attribute("href") for a in route.get_by_role("link", name="教學", exact=True).all()]
    assert len(hrefs) == 10 and all("tutorial.zh-TW.md#" in h for h in hrefs)
    route.get_by_role("link", name="去做 →").nth(1).click()           # the third stop: recording (the first has no page)
    page.locator("main h1").first.wait_for()
    assert page.url.endswith("/collect")


def test_english_pages_show_no_chinese(en):
    """every word the platform writes on these pages is translated (what the project calls things is English here)"""
    found = {}
    for path in OTHERS + [p for p, _ in INTRO]:
        en.go(path)
        bits = sorted({m for line in en.text().splitlines() if HAN.search(line) for m in [line.strip()]})
        if bits:
            found[path] = bits[:5]
    assert not found, found
    assert en.go("/").locator("main").get_by_text("What this page is for").count() == 0      # Home has the route instead
    assert "First steps" in en.text()
