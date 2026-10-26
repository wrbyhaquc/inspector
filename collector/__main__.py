import argparse

from .collector import Collector
from .config import Settings
from i18n import _


def main():
    ap = argparse.ArgumentParser(prog="python -m collector", description=_("資料收集器(截圖、觸控,加上專案外掛記錄的資料)"))
    ap.add_argument("--data", default=None, help=_("專案資料夾(預設:目前的專案)"))
    ap.add_argument("--interval", type=float, default=Settings.base_interval, help=_("每台的例行取樣間隔秒數"))
    ap.add_argument("--minutes", type=float, default=0, help=_("錄製幾分鐘後自動停止(0 = 直到 Ctrl+C)"))
    ap.add_argument("--only", action="append", default=[], help=_("只錄指定名稱的來源,可重複"))
    ap.add_argument("--no-touch", action="store_true", help=_("不記錄觸控"))
    ap.add_argument("--capture", default=Settings.capture,
                    help=_("截圖方式(由來源種類決定;例如 Android:window = 從 Windows 擷取視窗,預設;adb = 在裝置內截圖)"))
    ap.add_argument("--format", choices=("png", "jpg"), default=Settings.frame_format, help=_("畫面存成 png(原樣)或 jpg(小約 4 倍)"))
    ap.add_argument("--quality", type=int, default=Settings.jpeg_quality, help=_("jpg 的畫質 50~100"))
    a = ap.parse_args()
    s = Settings(data_root=a.data or __import__("project").data_root(), base_interval=a.interval, capture=a.capture,
                 duration=a.minutes * 60, only=a.only, record_touches=not a.no_touch, frame_format=a.format,
                 jpeg_quality=max(50, min(100, a.quality)))
    Collector(s).run()


if __name__ == "__main__":
    main()
