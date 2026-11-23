from pagifyx.core.brand import LogoHint, choose_logo


def test_choose_logo_prefers_a_logo_hint() -> None:
    candidates = [LogoHint("0", "nav-icon"), LogoHint("1", "site-logo.svg")]
    assert choose_logo(candidates) == LogoHint("1", "site-logo.svg")


def test_choose_logo_falls_back_to_the_first_candidate() -> None:
    candidates = [LogoHint("0", "brand mark")]
    assert choose_logo(candidates) == candidates[0]
    assert choose_logo([]) is None
