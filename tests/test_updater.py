"""The updater: which release counts, what it will download, how it installs."""

import hashlib
import io
import re
import sys
import urllib.error
from pathlib import Path

import pytest

from lumenspar import _version, updater
from lumenspar.updater import Asset, Release, UpdateError

BASE = "https://github.com/Galog1/lumenspar/releases/download"


def _asset(name, size=0, digest=None, url=None):
    a = {"name": name, "size": size, "browser_download_url": url or f"{BASE}/v9/{name}"}
    if digest:
        a["digest"] = digest
    return a


def _rel(tag, assets=(), draft=False, pre=True, body=""):
    return {"tag_name": tag, "draft": draft, "prerelease": pre, "body": body,
            "html_url": f"https://github.com/Galog1/lumenspar/releases/tag/{tag}",
            "assets": list(assets)}


# -- versions ---------------------------------------------------------------------

def test_version_matches_pyproject():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "(.+)"', text, re.M).group(1)
    assert _version.__version__ == declared


def test_parse_version():
    assert updater.parse_version("0.3.3") == (0, 3, 3)
    assert updater.parse_version("v1.10.0") == (1, 10, 0)
    for bad in ("", "latest", "0.3.3-dev", "v1.2.x", None):
        assert updater.parse_version(bad) is None


def test_is_newer():
    assert updater.is_newer("0.3.4", "0.3.3")
    assert updater.is_newer("0.10.0", "0.9.9")          # numeric, not text, order
    assert updater.is_newer("1.0", "0.9.9")
    assert not updater.is_newer("0.3.3", "0.3.3")
    assert not updater.is_newer("0.3.3.0", "0.3.3")
    assert not updater.is_newer("0.3.2", "0.3.3")
    assert not updater.is_newer("nightly", "0.3.3")      # unparseable never counts


# -- releases ---------------------------------------------------------------------

def test_parse_releases_keeps_prereleases_skips_drafts_and_junk():
    payload = [_rel("v0.3.3"), _rel("v0.3.5", draft=True), _rel("v0.3.4"),
               _rel("nightly"), "junk", None, _rel("v0.2.0", pre=False)]
    assert [r.version for r in updater.parse_releases(payload)] == ["0.3.4", "0.3.3", "0.2.0"]
    assert updater.parse_releases({"message": "rate limited"}) == []


def test_latest_release_uses_the_release_list():
    seen = []

    def fetch(url):
        seen.append(url)
        return [_rel("v0.3.3"), _rel("v0.4.0")]

    assert updater.latest_release(fetch).version == "0.4.0"
    assert seen == [updater.API] and "releases?" in updater.API    # not /releases/latest
    assert updater.latest_release(lambda url: []) is None


def test_assets_must_come_from_this_repositorys_releases():
    good = _asset("Lumenspar-Setup-0.4.0.exe", 5, "sha256:ABCD")
    evil = _asset("Lumenspar-Setup-0.4.0.exe", url="https://evil.example/x.exe")
    other = _asset("a.exe", url="https://github.com/someone/else/releases/download/v1/a.exe")
    rel = updater.parse_releases([_rel("v0.4.0", [good, evil, other])])[0]
    assert [a.url for a in rel.assets] == [good["browser_download_url"]]
    assert rel.assets[0].sha256 == "abcd" and rel.assets[0].size == 5


def test_release_page_is_never_an_outside_link():
    r = _rel("v0.4.0")
    r["html_url"] = "https://evil.example/"
    assert updater.parse_releases([r])[0].page == updater.RELEASE_PAGE


def test_asset_for_each_kind_of_install():
    rel = updater.parse_releases([_rel("v0.4.0", [
        _asset("Lumenspar-0.4.0-x86_64.AppImage"), _asset("Lumenspar-Setup-0.4.0.exe"),
        _asset("source.zip")])])[0]
    assert updater.asset_for(rel, "windows").name == "Lumenspar-Setup-0.4.0.exe"
    assert updater.asset_for(rel, "appimage").name == "Lumenspar-0.4.0-x86_64.AppImage"
    assert updater.asset_for(rel, "source") is None
    assert updater.asset_for(Release("1", "v1"), "windows") is None


def test_fetch_json_errors_become_update_errors(monkeypatch):
    def boom(code):
        def f(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return f
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom(403))
    with pytest.raises(UpdateError, match="rate-limit"):
        updater.fetch_json("https://api.github.com/x")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom(500))
    with pytest.raises(UpdateError, match="500"):
        updater.fetch_json("https://api.github.com/x")

    def offline(req, timeout=0):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(updater.urllib.request, "urlopen", offline)
    with pytest.raises(UpdateError, match="reach GitHub"):
        updater.fetch_json("https://api.github.com/x")


# -- download ---------------------------------------------------------------------

class _Resp:
    def __init__(self, data, length=None):
        self._b = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}

    def read(self, n):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(data, length=None):
    return lambda req, timeout=0: _Resp(data, length)


def test_download_verifies_and_renames(tmp_path):
    data = b"x" * 700_000
    asset = Asset("Lumenspar-Setup-1.exe", f"{BASE}/v1/Lumenspar-Setup-1.exe", len(data),
                  hashlib.sha256(data).hexdigest())
    seen = []
    out = updater.download(asset, tmp_path, progress=lambda d, t: seen.append((d, t)),
                           opener=_opener(data))
    assert out.read_bytes() == data and out.name == asset.name
    assert not list(tmp_path.glob("*.part"))
    assert seen[-1] == (len(data), len(data))


def test_download_rejects_a_wrong_checksum_and_deletes_it(tmp_path):
    data = b"hello"
    asset = Asset("a.exe", f"{BASE}/v1/a.exe", len(data), hashlib.sha256(b"other").hexdigest())
    with pytest.raises(UpdateError, match="checksum"):
        updater.download(asset, tmp_path, opener=_opener(data))
    assert list(tmp_path.iterdir()) == []


def test_download_rejects_a_short_file(tmp_path):
    asset = Asset("a.exe", f"{BASE}/v1/a.exe", 100)
    with pytest.raises(UpdateError, match="incomplete"):
        updater.download(asset, tmp_path, opener=_opener(b"short"))
    assert list(tmp_path.iterdir()) == []


def test_download_without_a_digest_still_checks_size(tmp_path):
    data = b"abc"
    asset = Asset("a.exe", f"{BASE}/v1/a.exe", 3)
    assert updater.download(asset, tmp_path, opener=_opener(data)).read_bytes() == data


def test_download_refuses_untrusted_urls_and_odd_names(tmp_path):
    with pytest.raises(UpdateError, match="hosted"):
        updater.download(Asset("a.exe", "https://evil.example/a.exe"), tmp_path,
                         opener=_opener(b""))
    for name in ("..\\evil.exe", "../evil.exe", "sub/a.exe", ""):
        with pytest.raises(UpdateError):
            updater.download(Asset(name, f"{BASE}/v1/x"), tmp_path, opener=_opener(b""))


def test_download_can_be_cancelled(tmp_path):
    asset = Asset("a.exe", f"{BASE}/v1/a.exe", 5)
    with pytest.raises(UpdateError, match="cancel"):
        updater.download(asset, tmp_path, should_stop=lambda: True, opener=_opener(b"12345"))
    assert list(tmp_path.iterdir()) == []


def test_download_stops_a_runaway(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "MAX_BYTES", 10)
    asset = Asset("a.exe", f"{BASE}/v1/a.exe")
    with pytest.raises(UpdateError, match="larger"):
        updater.download(asset, tmp_path, opener=_opener(b"x" * 100, length=100))
    assert list(tmp_path.iterdir()) == []


# -- installing -------------------------------------------------------------------

def test_windows_command_runs_the_installer_then_the_app():
    cmd = updater.windows_install_command(Path(r"C:\t\Lumenspar-Setup-1.exe"),
                                          Path(r"C:\Users\x\AppData\Local\Programs\Lumenspar\Lumenspar.exe"))
    assert cmd.index("/wait") < cmd.index("Setup-1.exe") < cmd.index("&&") < cmd.rindex("Lumenspar.exe")
    for flag in ("/VERYSILENT", "/NORESTART", "/CLOSEAPPLICATIONS"):
        assert flag in cmd
    with pytest.raises(UpdateError):
        updater.windows_install_command(Path('C:\\a"b\\s.exe'), Path("C:\\l.exe"))


def test_apply_appimage_replaces_the_running_file(tmp_path):
    current = tmp_path / "Lumenspar.AppImage"
    current.write_bytes(b"old")
    new = tmp_path / "dl" / "Lumenspar-1-x86_64.AppImage"
    new.parent.mkdir()
    new.write_bytes(b"new")
    assert updater.apply_appimage(new, current) == current
    assert current.read_bytes() == b"new"
    assert not (tmp_path / "Lumenspar.AppImage.new").exists()
    if sys.platform != "win32":
        assert current.stat().st_mode & 0o111


def test_apply_appimage_failure_leaves_the_old_one(tmp_path):
    current = tmp_path / "Lumenspar.AppImage"
    current.write_bytes(b"old")
    with pytest.raises(UpdateError):
        updater.apply_appimage(tmp_path / "missing", current)
    assert current.read_bytes() == b"old" and not list(tmp_path.glob("*.new"))
    with pytest.raises(UpdateError, match="Could not find"):
        updater.apply_appimage(current, tmp_path / "nowhere.AppImage")


def test_how_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert updater.how_installed() == "source"
    img = tmp_path / "x.AppImage"
    img.write_bytes(b"")
    monkeypatch.setenv("APPIMAGE", str(img))
    assert updater.how_installed() == "appimage"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert updater.how_installed() == "source"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert updater.how_installed() == "windows"
