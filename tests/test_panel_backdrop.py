"""Three-state panel backdrop: transparent | frosty | opaque (pure, headless).

Widened 2026-07-28 from a blur on/off boolean. The design point that keeps it small:
`get_blur_enabled()` is REDEFINED as `mode == "frosty"`, so none of the eleven blur
call sites in panels.py/app.py had to change — they still ask "should the blur run".

  transparent -> no blur; the theme's own panel_opacity_hover alpha
  frosty      -> blur;    the theme's own panel_opacity_hover alpha
  opaque      -> no blur; alpha forced to 1.0, overriding the theme

'opaque' deliberately does not blur: a fully opaque panel hides what is behind it,
so blurring would be invisible work — the same reasoning _panel_hides_everything
already uses for the Timeline tab.
"""
import pytest

from fabulor.themes import _resolve_theme, set_panel_alpha_override


class _FakeSettings:
    """Stands in for QSettings: a plain dict with the same value()/setValue() shape."""

    def __init__(self, initial=None):
        self._d = dict(initial or {})

    def value(self, key, default=None):
        return self._d.get(key, default)

    def setValue(self, key, val):
        self._d[key] = val


def _make_config(initial=None):
    from fabulor.config import Config
    cfg = Config.__new__(Config)
    cfg.settings = _FakeSettings(initial)
    return cfg


@pytest.fixture(autouse=True)
def _reset_override():
    # The override is module-level state; never let one test leak into the next.
    yield
    set_panel_alpha_override(None)


# --- mode round-trip -------------------------------------------------------

@pytest.mark.parametrize("mode", ["transparent", "frosty", "opaque"])
def test_mode_round_trips(mode):
    cfg = _make_config()
    cfg.set_panel_backdrop(mode)
    assert cfg.get_panel_backdrop() == mode


def test_unknown_mode_falls_back_to_transparent():
    cfg = _make_config()
    cfg.set_panel_backdrop("nonsense")
    assert cfg.get_panel_backdrop() == "transparent"


# --- only frosty blurs -----------------------------------------------------

@pytest.mark.parametrize("mode,expected", [
    ("transparent", False),
    ("frosty", True),
    ("opaque", False),      # opaque hides what is behind it — blurring is invisible work
])
def test_get_blur_enabled_is_frosty_only(mode, expected):
    cfg = _make_config()
    cfg.set_panel_backdrop(mode)
    assert cfg.get_blur_enabled() is expected


# --- alpha override --------------------------------------------------------

@pytest.mark.parametrize("mode,expected", [
    ("transparent", None),
    ("frosty", None),
    ("opaque", 1.0),
])
def test_alpha_override_only_for_opaque(mode, expected):
    cfg = _make_config()
    cfg.set_panel_backdrop(mode)
    assert cfg.get_panel_alpha_override() == expected


def test_override_reaches_every_theme_via_resolve():
    # The whole reason the override lives in _resolve_theme: it is the single funnel
    # every stylesheet function passes through, so one write covers all eight
    # `rgba(bg_main, panel_opacity_hover)` sites without threading a parameter.
    before = _resolve_theme("Blindsight")["panel_opacity_hover"]
    assert before < 1.0                      # themes ship 0.88-0.95
    set_panel_alpha_override(1.0)
    assert _resolve_theme("Blindsight")["panel_opacity_hover"] == 1.0
    assert _resolve_theme("Plum Island")["panel_opacity_hover"] == 1.0
    set_panel_alpha_override(None)
    assert _resolve_theme("Blindsight")["panel_opacity_hover"] == before


# --- migration from the old boolean ---------------------------------------

def test_migrates_legacy_blur_true_to_frosty():
    # An existing install that had blur ON must keep looking the same, not reset.
    cfg = _make_config({"blur_enabled": "true"})
    assert cfg.get_panel_backdrop() == "frosty"
    assert cfg.get_blur_enabled() is True


def test_migrates_legacy_blur_false_to_transparent():
    cfg = _make_config({"blur_enabled": "false"})
    assert cfg.get_panel_backdrop() == "transparent"


def test_fresh_install_defaults_to_transparent():
    assert _make_config().get_panel_backdrop() == "transparent"


def test_new_key_wins_over_the_legacy_one():
    # Once the new key is set it is authoritative, whatever the stale boolean says.
    cfg = _make_config({"blur_enabled": "true"})
    cfg.set_panel_backdrop("opaque")
    assert cfg.get_panel_backdrop() == "opaque"


def test_legacy_key_is_kept_in_step():
    # So a downgrade, or any reader still on the old accessor, sees something sane
    # rather than a stale value.
    cfg = _make_config()
    cfg.set_panel_backdrop("frosty")
    assert cfg.settings.value("blur_enabled") == "true"
    cfg.set_panel_backdrop("opaque")
    assert cfg.settings.value("blur_enabled") == "false"


def test_legacy_setter_still_works():
    # blur_mode_changed(bool) is still wired; On -> frosty, Off -> transparent.
    cfg = _make_config()
    cfg.set_blur_enabled(True)
    assert cfg.get_panel_backdrop() == "frosty"
    cfg.set_blur_enabled(False)
    assert cfg.get_panel_backdrop() == "transparent"
