"""Build dist/dont-be-a-viber-<version>.vsix — no Node, no vsce.

A .vsix is a zip: [Content_Types].xml + extension.vsixmanifest + extension/*.
The backend (server.py + nlv/) is bundled under extension/backend/ so the
published artifact is self-contained.

Usage: python tools/build_vsix.py
"""

from __future__ import annotations

import json
import os
import zipfile
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "extension")
BACKEND = os.path.join(ROOT, "backend")
DIST = os.path.join(ROOT, "dist")

with open(os.path.join(EXT, "package.json"), encoding="utf-8") as f:
    pkg = json.load(f)

VERSION = pkg["version"]
PUBLISHER = pkg["publisher"]
NAME = pkg["name"]

# marketplace tags must be plain words — no spaces or punctuation
TAGS = ",".join(
    t for t in ("".join(c for c in k if c.isalnum()) for k in pkg.get("keywords", [])) if t
)

MANIFEST = f"""<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{NAME}" Version="{VERSION}" Publisher="{PUBLISHER}"/>
    <DisplayName>{escape(pkg["displayName"])}</DisplayName>
    <Description xml:space="preserve">{escape(pkg["description"])}</Description>
    <Tags>{escape(TAGS)}</Tags>
    <Categories>{escape(",".join(pkg.get("categories", [])))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{pkg["engines"]["vscode"]}"/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value=""/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value=""/>
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace"/>
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value=""/>
      <Property Id="Microsoft.VisualStudio.Services.GitHubFlavoredMarkdown" Value="true"/>
      <Property Id="Microsoft.VisualStudio.Services.Content.Pricing" Value="Free"/>
      <Property Id="Microsoft.VisualStudio.Services.Links.Source" Value="https://github.com/PhialsBasement/DoNotBeAViber.git"/>
      <Property Id="Microsoft.VisualStudio.Services.Links.GitHub" Value="https://github.com/PhialsBasement/DoNotBeAViber.git"/>
      <Property Id="Microsoft.VisualStudio.Services.Links.Support" Value="https://github.com/PhialsBasement/DoNotBeAViber/issues"/>
    </Properties>
    <License>extension/LICENSE.txt</License>
    <Icon>extension/icon.png</Icon>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/README.md" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.Changelog" Path="extension/CHANGELOG.md" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Content.License" Path="extension/LICENSE.txt" Addressable="true"/>
    <Asset Type="Microsoft.VisualStudio.Services.Icons.Default" Path="extension/icon.png" Addressable="true"/>
  </Assets>
</PackageManifest>
"""

CONTENT_TYPES = """<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="js" ContentType="application/javascript"/>
  <Default Extension="md" ContentType="text/markdown"/>
  <Default Extension="txt" ContentType="text/plain"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="svg" ContentType="image/svg+xml"/>
  <Default Extension="py" ContentType="text/x-python"/>
  <Default Extension="vsixmanifest" ContentType="text/xml"/>
</Types>
"""

# what ships: extension files + the runtime backend (no tests, no fixtures)
EXTENSION_FILES = [
    "package.json",
    "extension.js",
    "CHANGELOG.md",
    "LICENSE.txt",
    "icon.png",
    "media/icon.svg",
]
# repo-root files mapped into the archive (README lives at root for GitHub)
ROOT_FILES = [
    ("README.md", "extension/README.md"),
]
BACKEND_FILES = [
    "server.py",
    "nlv/__init__.py",
    "nlv/session.py",
    "nlv/manager.py",
    "nlv/protocol.py",
    "nlv/prompt.py",
    "nlv/log.py",
]


def main() -> int:
    missing = [f for f in EXTENSION_FILES if not os.path.exists(os.path.join(EXT, f))]
    missing += [f for f in BACKEND_FILES if not os.path.exists(os.path.join(BACKEND, f))]
    missing += [f for f, _ in ROOT_FILES if not os.path.exists(os.path.join(ROOT, f))]
    if missing:
        print("missing files:", ", ".join(missing))
        return 1

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f"{NAME}-{VERSION}.vsix")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("extension.vsixmanifest", MANIFEST)
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        for f in EXTENSION_FILES:
            z.write(os.path.join(EXT, f), f"extension/{f}")
        for src, dst in ROOT_FILES:
            z.write(os.path.join(ROOT, src), dst)
        for f in BACKEND_FILES:
            z.write(os.path.join(BACKEND, f), f"extension/backend/{f}")

    size_kb = os.path.getsize(out) / 1024
    print(f"wrote {out} ({size_kb:.0f} KB)")
    with zipfile.ZipFile(out) as z:
        for name in z.namelist():
            print("  ", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
