from lumenspar import reactions as R


def test_team_elements():
    assert R.team_elements(["Pyro", "", "hydro"]) == {"pyro", "hydro"}


def test_amp_options():
    t = {"pyro", "hydro", "cryo", "electro", "dendro"}
    assert R.amp_options("pyro", t) == ["vaporize", "melt"]
    assert R.amp_options("hydro", t) == ["vaporize"]
    assert R.amp_options("cryo", t) == ["melt"]
    assert R.amp_options("electro", t) == ["aggravate"]
    assert R.amp_options("dendro", t) == ["spread"]
    assert R.amp_options("geo", t) == []
    assert R.amp_options("pyro", {"pyro"}) == []
    assert R.amp_options("electro", {"electro", "pyro"}) == []
    assert R.amp_options("dendro", {"dendro"}) == []


def test_reaction_row_allowed():
    ok = R.reaction_row_allowed
    assert ok("overloaded", "pyro", {"pyro", "electro"})
    assert not ok("overloaded", "hydro", {"pyro", "electro", "hydro"})
    assert not ok("overloaded", "pyro", {"pyro"})
    assert ok("superconduct", "cryo", {"cryo", "electro"})
    assert ok("lunarcharged", "hydro", {"hydro", "electro"})
    assert not ok("electrocharged", "pyro", {"hydro", "electro", "pyro"})
    assert ok("shattered", "geo", {"cryo", "hydro", "geo"})
    assert not ok("shattered", "cryo", {"cryo"})
    assert ok("swirl_pyro", "anemo", {"anemo", "pyro"})
    assert not ok("swirl_pyro", "anemo", {"anemo", "hydro"})
    assert not ok("swirl_pyro", "pyro", {"anemo", "pyro"})
    assert ok("burning", "dendro", {"pyro", "dendro"})
    assert ok("bloom", "hydro", {"hydro", "dendro"})
    assert ok("lunarbloom", "dendro", {"hydro", "dendro"})
    assert not ok("bloom", "pyro", {"pyro", "hydro", "dendro"})
    assert ok("hyperbloom", "electro", {"electro", "hydro", "dendro"})
    assert not ok("hyperbloom", "electro", {"electro", "dendro"})
    assert ok("burgeon", "pyro", {"pyro", "hydro", "dendro"})
    assert ok("crystallize", "geo", {"geo", "cryo"})
    assert not ok("lunarcrystallize", "geo", {"geo", "dendro"})
    assert not ok("crystallize", "pyro", {"pyro", "cryo"})
    assert ok("enemyFrozen", "pyro", set())


def test_reaction_label():
    assert R.reaction_label("electrocharged") == "Electro-Charged"
    assert R.reaction_label("crystallize") == "Crystallize (shield)"
    assert R.reaction_label("swirl_cryo") == "Swirl (Cryo)"
    assert R.reaction_label("enemyFrozen") is None
    assert R.reaction_label("swirl_bogus") is None
