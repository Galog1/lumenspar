"""Tests for the GOOD export document (lumenspar.good)."""

import json

import pytest

from lumenspar.good import Artifact, GoodExport, SubStat, Weapon, to_key


@pytest.mark.parametrize("name,expected", [
    ("Gladiator's Finale", "GladiatorsFinale"),
    ("Hunter's Path", "HuntersPath"),
    ("Light of Foliar Incision", "LightOfFoliarIncision"),
])
def test_to_key_strips_punctuation_and_camel_cases(name, expected):
    assert to_key(name) == expected


def test_to_dict_meta_present_and_empty_categories_omitted():
    doc = GoodExport().to_dict()
    assert doc == {"format": "GOOD", "version": 2, "source": "Lumenspar"}
    assert "artifacts" not in doc
    assert "weapons" not in doc
    assert "characters" not in doc
    assert "materials" not in doc


def test_to_dict_includes_populated_categories():
    export = GoodExport()
    export.artifacts.append(Artifact(
        setKey="Instructor", slotKey="flower", level=0, rarity=4,
        mainStatKey="hp", substats=[SubStat("def", 17.0)]))
    export.weapons.append(Weapon(key="PrototypeAmber", level=90, ascension=6,
                                 refinement=3))
    doc = export.to_dict()
    assert doc["artifacts"][0]["setKey"] == "Instructor"
    assert doc["artifacts"][0]["substats"][0] == {"key": "def", "value": 17.0}
    assert doc["weapons"][0]["refinement"] == 3
    assert "characters" not in doc
    assert "materials" not in doc


def test_to_dict_sorts_materials_and_omits_empty_category():
    export = GoodExport()
    export.materials = {"wheat": 5, "apple": 2, "Mora": 100}
    doc = export.to_dict()
    assert doc["materials"] == {"Mora": 100, "apple": 2, "wheat": 5}
    assert "artifacts" not in doc


def test_write_round_trips_via_json(tmp_path):
    export = GoodExport()
    export.materials = {"wheat": 3}
    out = export.write(tmp_path / "nested" / "out.json")
    assert json.loads(out.read_text()) == export.to_dict()
