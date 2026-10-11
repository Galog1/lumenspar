"""HTTPS certificates in the frozen Linux build (see lumenspar/netcerts.py)."""

from __future__ import annotations

import ssl
import sys
from types import SimpleNamespace

from lumenspar import netcerts


def _frozen_linux(monkeypatch, cafile, capath):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(ssl, "get_default_verify_paths",
                        lambda: SimpleNamespace(cafile=cafile, capath=capath))


def test_the_system_bundle_is_used_when_openssls_own_location_is_missing(tmp_path, monkeypatch):
    _frozen_linux(monkeypatch, "/usr/lib/ssl/cert.pem", "/usr/lib/ssl/certs")   # Ubuntu's paths
    bundle = tmp_path / "ca-certificates.crt"
    bundle.write_text("pem")
    env = {}
    chosen = netcerts.use_system_bundle(env, bundles=(str(tmp_path / "absent.pem"), str(bundle)))
    assert chosen == str(bundle) and env["SSL_CERT_FILE"] == str(bundle)


def test_nothing_changes_when_openssls_own_location_works(tmp_path, monkeypatch):
    cafile = tmp_path / "cert.pem"
    cafile.write_text("pem")
    _frozen_linux(monkeypatch, str(cafile), None)
    env = {}
    assert netcerts.use_system_bundle(env, bundles=(str(cafile),)) is None and env == {}


def test_a_users_own_choice_is_respected(tmp_path, monkeypatch):
    _frozen_linux(monkeypatch, "/missing", "/missing")
    env = {"SSL_CERT_FILE": "/my/ca.pem"}
    assert netcerts.use_system_bundle(env, bundles=(str(tmp_path),)) is None
    assert env == {"SSL_CERT_FILE": "/my/ca.pem"}


def test_a_source_checkout_is_left_alone(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    env = {}
    assert netcerts.use_system_bundle(env) is None and env == {}
