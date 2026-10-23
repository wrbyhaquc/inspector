"""On GitHub Actions, each failed test is also an error annotation (shown on the run's page, no sign-in needed)."""
import os


def pytest_runtest_logreport(report):
    if not os.environ.get("GITHUB_ACTIONS") or not report.failed:
        return
    path, line = report.location[0], (report.location[1] or 0) + 1
    text = str(report.longreprtext or "")[-1500:]
    text = text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    title = f"{report.nodeid} ({report.when})".replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
    print(f"\n::error file={path.replace(os.sep, '/')},line={line},title={title}::{text}", flush=True)
