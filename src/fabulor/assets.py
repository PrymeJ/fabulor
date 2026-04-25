import os
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
ICON_PATH = os.path.join(ASSETS_DIR, "fabulor.ico")

def get_asset_path(relative: str) -> str:
    """Resolve a theme asset path relative to the assets directory."""
    return os.path.join(ASSETS_DIR, relative)
