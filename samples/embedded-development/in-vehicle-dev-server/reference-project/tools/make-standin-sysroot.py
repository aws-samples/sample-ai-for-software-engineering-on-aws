#!/usr/bin/env python3
# SPDX-License-Identifier: MIT-0
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
"""Build a stand-in CC-1 sysroot from Ubuntu 24.04 arm64 packages.

The real sysroot comes from the Buildroot build of the bench's target image. Until that exists, this script
unpacks the arm64 packages that provide glibc, the Linux UAPI headers, libsystemd and the C++ runtime into a
directory, without installing anything into the host system:

    python3 tools/make-standin-sysroot.py /opt/cc1-sysroot

It downloads the package index of ports.ubuntu.com over HTTPS, picks the newest version of each package from
noble-updates, noble-security or noble, downloads the .deb files, checks their SHA-256 against the index, unpacks each
with `dpkg -x` and writes `standin-manifest.txt` (package, version, SHA-256) into the sysroot. Run it in the build
container (tools/Dockerfile), which has dpkg, Python and the CA certificates.
"""

import hashlib
import lzma
import os
import pathlib
import subprocess
import sys
import tempfile
import urllib.request

MIRROR = "https://ports.ubuntu.com/ubuntu-ports"
SUITES = ("noble-updates", "noble-security", "noble")
COMPONENTS = ("main", "universe")
PACKAGES = (
    "libc6", "libc6-dev", "libcrypt1", "libcrypt-dev", "linux-libc-dev",
    "libsystemd0", "libsystemd-dev", "libcap2", "libgcrypt20", "libgpg-error0", "liblz4-1", "liblzma5", "libzstd1",
    "libgcc-s1", "libstdc++6", "libgcc-12-dev", "libstdc++-12-dev",
)


def fetch(url):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return resp.read()
        except OSError as exc:
            print(f"retry {attempt + 1}: {url}: {exc}", file=sys.stderr)
    raise SystemExit(f"cannot download {url}")


def index():
    best = {}
    for suite in SUITES:
        for comp in COMPONENTS:
            text = lzma.decompress(fetch(f"{MIRROR}/dists/{suite}/{comp}/binary-arm64/Packages.xz")).decode()
            for stanza in text.split("\n\n"):
                fields = dict(line.split(": ", 1) for line in stanza.splitlines() if ": " in line and line[0] != " ")
                name = fields.get("Package")
                if name not in PACKAGES:
                    continue
                old = best.get(name)
                if old is None or subprocess.run(["dpkg", "--compare-versions", fields["Version"], "gt",
                                                  old["Version"]], check=False).returncode == 0:
                    best[name] = fields
    missing = [p for p in PACKAGES if p not in best]
    if missing:
        raise SystemExit(f"not found in the index: {missing}")
    return best


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    root = pathlib.Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=True)
    manifest = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, fields in sorted(index().items()):
            data = fetch(f"{MIRROR}/{fields['Filename']}")
            digest = hashlib.sha256(data).hexdigest()
            if digest != fields["SHA256"]:
                raise SystemExit(f"{name}: SHA-256 mismatch")
            deb = pathlib.Path(tmp) / f"{name}.deb"
            deb.write_bytes(data)
            subprocess.run(["dpkg", "-x", str(deb), str(root)], check=True)
            manifest.append(f"{name} {fields['Version']} {digest}")
    # Merged /usr layout, as on the target.
    for d in ("lib", "lib64"):
        link = root / d
        if not link.exists() and not link.is_symlink():
            os.symlink(f"usr/{d}" if (root / "usr" / d).exists() else "usr/lib", link)
    (root / "standin-manifest.txt").write_text("\n".join(manifest) + "\n")
    print(f"stand-in sysroot ready in {root} ({len(manifest)} packages)")


if __name__ == "__main__":
    main()
