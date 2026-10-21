# packs

The package the active pack's plugin is imported as (`packs.<name>`). The plugin itself stays in the pack,
`<data>/packs/<id>/plugin/`, and is mounted here when Inspector starts (`project/plugins.py`); install packs with
`python -m project.pack install` or on the Packs page. Older versions kept plugin folders here (`packs/<name>/`),
which still works for a single project folder. Apart from `__init__.py` and this file, nothing here is under version
control.

使用中方案包的外掛以 `packs.<名稱>` 匯入。外掛本身留在方案包裡(`<data>/packs/<代號>/plugin/`),Inspector 啟動時掛到這裡
(`project/plugins.py`);方案包用 `python -m project.pack install` 或「方案包」頁安裝。舊版把外掛資料夾放在這裡
(`packs/<名稱>/`),單一專案資料夾時仍可使用。這個資料夾除了 `__init__.py` 與本說明以外不進版控。
