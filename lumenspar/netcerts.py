"""Make HTTPS work in the Linux AppImage on any distribution.

The AppImage carries the build machine's OpenSSL (Ubuntu), which looks for
trusted certificates in /usr/lib/ssl. Other distributions keep them elsewhere
(Fedora in /etc/pki, Arch and Fedora Atomic in /etc/ssl/certs), so on those
every HTTPS request failed verification -- the wish counter, the Enka.Network
import and the Gemini reader alike. When OpenSSL's built-in location is
missing, this points it at the system's own certificate bundle, so the app
trusts exactly what the system trusts.

Only the frozen Linux build needs it; a source checkout uses the system's
Python and OpenSSL, and Windows uses its own certificate store.
"""

from __future__ import annotations

import os
import ssl
import sys
from pathlib import Path

# Where distributions keep the PEM bundle of trusted CAs.
SYSTEM_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",                  # Debian, Ubuntu, Arch, Gentoo
    "/etc/pki/tls/certs/ca-bundle.crt",                    # Fedora, RHEL
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",   # Fedora (the source of the above)
    "/etc/ssl/ca-bundle.pem",                              # openSUSE
    "/etc/ssl/cert.pem",                                   # Alpine, Void
)


def use_system_bundle(environ=os.environ, bundles=SYSTEM_BUNDLES) -> str | None:
    """Set SSL_CERT_FILE when OpenSSL's own location has nothing in it.

    Returns the bundle chosen, or None when nothing needed changing.
    """
    if not getattr(sys, "frozen", False) or sys.platform != "linux":
        return None
    if environ.get("SSL_CERT_FILE") or environ.get("SSL_CERT_DIR"):
        return None                                    # the user chose already
    paths = ssl.get_default_verify_paths()
    if (paths.cafile and Path(paths.cafile).is_file()) or \
            (paths.capath and Path(paths.capath).is_dir()):
        return None                                    # OpenSSL's own location works
    for bundle in bundles:
        if Path(bundle).is_file():
            environ["SSL_CERT_FILE"] = bundle
            return bundle
    return None
