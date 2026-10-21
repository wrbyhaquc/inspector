"""Plugins (one folder each); see project/plugins.py. The active pack's plugin may live outside this folder: it is
mounted here as packs.<name> so every process (worker processes too) imports it by the same name."""
try:
    from project import manifest as _manifest, pack_dir as _pack_dir
    from project.plugins import mount as _mount, pack_info as _pack_info
    if _pack_info().get("plugin") and not any(lv == "error" for lv, _t in _manifest.check(_pack_info(), _pack_dir())):
        _mount(_pack_info()["plugin"])
except Exception:  # a broken pack must not take the platform down; registry() reports it
    pass
