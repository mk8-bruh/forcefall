import argparse
import io
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / ".build"
LOVE = BUILD / "love"
STAGE = BUILD / "stage"
DIST = BUILD / ".out"
CACHE = BUILD / "cache"

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.+-]+)?$")
DEV_RE = re.compile(r"^dev\.\d+$")
BUNDLE_PREFIX = "com.forcefall"
ICON = ROOT / "assets" / "icon.png"
WINRES = "github.com/tc-hib/go-winres@v0.3.3"

# --- targets: name -> {name: executable, title: display name, headless: lovec + no window/icon, sources: [[src dir, dest prefix in .love]]} ---
TARGETS = {
    "client": {"name": "forcefall", "title": "Forcefall", "headless": False,
               "sources": [["client", ""], ["shared", "shared"], ["core", "core"], ["assets", "assets"]]},
    "server": {"name": "forcefall-server", "title": "Forcefall Server", "headless": True,
               "sources": [["server", ""], ["shared", "shared"], ["core", "core"]]},
    "admin":  {"name": "forcefall-admin", "title": "Forcefall Admin", "headless": False,
               "sources": [["admin",  ""], ["shared", "shared"], ["core", "core"], ["assets", "assets"]]},
}
EXCLUDE_DIRS = {"_drafts", ".git", "__pycache__"}
EXCLUDE_EXT = {".pxo", ".aseprite", ".ase", ".kra", ".psd"}

NIGHTLY_REPO = "love2d/love"
NIGHTLY_WORKFLOW = "main.yml"
NIGHTLY_BRANCH = "main"
ARTIFACTS = {
    "win64": "love-windows-x64",
    "linux": "love-linux-X64.AppImage",
    "macos": "love-macos",
}
PLATFORMS = list(ARTIFACTS)
APPIMAGETOOL = "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"


def host_platform():
    return {"win32": "win64", "darwin": "macos"}.get(sys.platform, "linux")


def log(*a):
    print("[build]", *a, flush=True)


def fetch(url, headers=None):
    headers = {"User-Agent": "forcefall-build", **(headers or {})}
    if shutil.which("curl"):
        cmd = ["curl", "-fsSL", "--retry", "3", url]
        for k, v in headers.items():
            cmd[1:1] = ["-H", f"{k}: {v}"]
        return subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def run(cmd, **kw):
    log("$", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def latest_run():
    url = (f"https://api.github.com/repos/{NIGHTLY_REPO}/actions/workflows/{NIGHTLY_WORKFLOW}/runs"
           f"?branch={NIGHTLY_BRANCH}&status=success&per_page=1")
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    r = json.loads(fetch(url, headers))["workflow_runs"][0]
    return {"id": r["id"], "sha": r["head_sha"], "date": r["updated_at"]}


def installed(plat):
    f = LOVE / plat / "version.json"
    return json.loads(f.read_text()) if f.exists() else None


def install(plat, info):
    log(f"downloading {ARTIFACTS[plat]} (run {info['id']}, {info['sha'][:8]}, {info['date']})")
    outer = zipfile.ZipFile(io.BytesIO(fetch(f"https://nightly.link/{NIGHTLY_REPO}/actions/runs/{info['id']}/{ARTIFACTS[plat]}.zip")))
    tmp = LOVE / f"{plat}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    if plat == "win64":
        inner = next(n for n in outer.namelist() if n.endswith("-win64.zip"))
        with zipfile.ZipFile(io.BytesIO(outer.read(inner))) as z:
            for m in z.infolist():
                rel = m.filename.split("/", 1)[1] if "/" in m.filename else ""
                if rel and not m.is_dir():
                    (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
                    (tmp / rel).write_bytes(z.read(m))
    elif plat == "linux":
        name = next(n for n in outer.namelist() if n.endswith(".AppImage"))
        (tmp / "love.AppImage").write_bytes(outer.read(name))
        (tmp / "love.AppImage").chmod(0o755)
        if host_platform() == "linux":
            run([tmp / "love.AppImage", "--appimage-extract"], cwd=tmp, stdout=subprocess.DEVNULL)
    elif plat == "macos":
        (tmp / "love-macos.zip").write_bytes(outer.read("love-macos.zip"))
        if host_platform() == "macos":
            run(["ditto", "-x", "-k", tmp / "love-macos.zip", tmp])

    (tmp / "version.json").write_text(json.dumps(info, indent=2))
    shutil.rmtree(LOVE / plat, ignore_errors=True)
    tmp.rename(LOVE / plat)


def cmd_update(args):
    plats = PLATFORMS if args.platform == ["all"] else args.platform
    try:
        info = latest_run()
    except Exception as e:
        sys.exit(f"could not query latest love nightly: {e}")
    for plat in plats:
        cur = installed(plat)
        if cur and cur["id"] == info["id"] and not args.force:
            log(f"{plat}: up to date ({info['sha'][:8]}, {info['date']})")
        else:
            install(plat, info)


def ensure(plat):
    if not installed(plat):
        install(plat, latest_run())


def stage(target):
    if target not in TARGETS:
        sys.exit(f"unknown target '{target}', expected one of: {', '.join(TARGETS)}")
    out = STAGE / target
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    for src, dest in TARGETS[target]["sources"]:
        src = ROOT / src
        if not src.is_dir():
            sys.exit(f"missing source dir {src}")
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for f in filenames:
                p = Path(dirpath) / f
                if p.suffix.lower() in EXCLUDE_EXT:
                    continue
                to = out / dest / p.relative_to(src)
                to.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, to)
    if not TARGETS[target]["headless"]:
        shutil.copy2(ICON, out / "icon.png")
    if not (out / "main.lua").exists():
        sys.exit(f"{target}: no main.lua at the root of the staged game")
    return out


def pack(target):
    src = stage(target)
    out = BUILD / f"{target}.love"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src).as_posix())
    return out


def love_exe(plat, console):
    d = LOVE / plat
    if plat == "win64":
        return d / ("lovec.exe" if console else "love.exe")
    if plat == "linux":
        return d / "squashfs-root" / "AppRun"
    return d / "love.app" / "Contents" / "MacOS" / "love"


def cmd_run(args):
    plat = host_platform()
    ensure(plat)
    game = stage(args.target)
    cmd = [str(love_exe(plat, not args.no_console)), str(game), *args.args]
    log("$", " ".join(cmd))
    try:
        sys.exit(subprocess.run(cmd, cwd=ROOT).returncode)
    except KeyboardInterrupt:
        sys.exit(130)


# --- icons / exe resources ---

def icon_image():
    try:
        from PIL import Image
    except ImportError:
        sys.exit("icon conversion needs Pillow: pip install pillow")
    return Image.open(ICON).convert("RGBA")


def winres_tool():
    exe = "go-winres.exe" if os.name == "nt" else "go-winres"
    tool = shutil.which("go-winres") or CACHE / exe
    if not Path(tool).exists():
        if not shutil.which("go"):
            sys.exit("windows exe patching needs go-winres (or go to install it)")
        CACHE.mkdir(parents=True, exist_ok=True)
        run(["go", "install", WINRES], env={**os.environ, "GOBIN": str(CACHE)})
    return tool


def numeric(version):
    m = VERSION_RE.match(version)
    return ".".join(m.groups()) if m else "0.0.0"


def patch_win_exe(exe, target, version):
    t = TARGETS[target]
    work = BUILD / "winres" / target
    shutil.rmtree(work, ignore_errors=True)
    tool = winres_tool()
    run([tool, "extract", "--xml-manifest", "--dir", work, exe], stderr=subprocess.DEVNULL)
    icon_image().save(work / "icon.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    res = json.loads((work / "winres.json").read_text())
    res["RT_GROUP_ICON"] = {"#1": {"0409": "icon.ico"}}
    v = numeric(version) + ".0"
    res["RT_VERSION"] = {"#1": {"0000": {
        "fixed": {"file_version": v, "product_version": v},
        "info": {"0409": {
            "FileDescription": t["title"],
            "FileVersion": version,
            "InternalName": t["name"],
            "OriginalFilename": f"{t['name']}.exe",
            "ProductName": t["title"],
            "ProductVersion": version,
        }},
    }}}
    (work / "winres.json").write_text(json.dumps(res, indent=2))
    run([tool, "patch", "--in", work / "winres.json", "--delete", "--no-backup", exe])
    shutil.rmtree(work, ignore_errors=True)


# --- fuse ---

def artifact(target, version, plat):
    suffix = "" if target == "client" else f"_{target}"
    return DIST / version / f"forcefall{suffix}_{version}_{plat}"


def fuse_win64(target, love, version, out):
    name = TARGETS[target]["name"]
    src = LOVE / "win64"
    work = BUILD / "win64" / out.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    skip = {"love.exe", "lovec.exe", "love.ico", "game.ico", "changes.txt", "readme.txt", "version.json"}
    for p in src.iterdir():
        if p.is_file() and p.name not in skip:
            shutil.copy2(p, work / p.name)
    exe = work / f"{name}.exe"
    shutil.copy2(src / ("lovec.exe" if TARGETS[target]["headless"] else "love.exe"), exe)
    patch_win_exe(exe, target, version)
    for attempt in range(5):
        try:
            with open(exe, "ab") as f:
                f.write(love.read_bytes())
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(1)
    shutil.make_archive(str(out), "zip", work.parent, work.name)
    shutil.rmtree(work, ignore_errors=True)
    return out.with_name(out.name + ".zip")


def zip_add(zout, path, data, mode=0o100644):
    info = zipfile.ZipInfo(path)
    info.external_attr = mode << 16
    info.create_system = 3
    info.compress_type = zipfile.ZIP_DEFLATED
    zout.writestr(info, data)


def fuse_macos(target, love, version, out):
    t = TARGETS[target]
    name, app = t["name"], f"{t['title']}.app"
    icns = io.BytesIO()
    icon_image().save(icns, format="ICNS")
    with zipfile.ZipFile(LOVE / "macos" / "love-macos.zip") as zin, \
            zipfile.ZipFile(out.with_name(out.name + ".zip"), "w", zipfile.ZIP_DEFLATED) as zout:
        for m in zin.infolist():
            if not m.filename.startswith("love.app/"):
                continue
            data = zin.read(m)
            path = m.filename[len("love.app"):]
            if path == "/Contents/MacOS/love":
                path = f"/Contents/MacOS/{name}"
            elif path == "/Contents/Resources/OS X AppIcon.icns":
                continue
            elif path == "/Contents/Info.plist":
                pl = plistlib.loads(data)
                pl.update({
                    "CFBundleIdentifier": f"{BUNDLE_PREFIX}.{target}",
                    "CFBundleName": t["title"],
                    "CFBundleDisplayName": t["title"],
                    "CFBundleExecutable": name,
                    "CFBundleIconFile": name,
                    "CFBundleShortVersionString": numeric(version),
                    "CFBundleVersion": numeric(version),
                })
                for k in ("CFBundleIconName", "CFBundleDocumentTypes", "UTExportedTypeDeclarations"):
                    pl.pop(k, None)
                data = plistlib.dumps(pl)
            info = zipfile.ZipInfo(app + path, m.date_time)
            info.external_attr = m.external_attr
            info.create_system = m.create_system
            info.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(info, data)
        zip_add(zout, f"{app}/Contents/Resources/{name}.icns", icns.getvalue())
        zip_add(zout, f"{app}/Contents/Resources/{name}.love", love.read_bytes())
    return out.with_name(out.name + ".zip")


def fuse_linux(target, love, version, out):
    t = TARGETS[target]
    name = t["name"]
    work = BUILD / "appdir" / target
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    shutil.copy2(LOVE / "linux" / "love.AppImage", work / "love.AppImage")
    (work / "love.AppImage").chmod(0o755)
    run([work / "love.AppImage", "--appimage-extract"], cwd=work, stdout=subprocess.DEVNULL)
    appdir = work / "squashfs-root"
    shutil.copy2(love, appdir / f"{name}.love")
    apprun = appdir / "AppRun"
    text = apprun.read_text()
    marker = '#FUSE_PATH="$APPDIR/my_game.love"'
    if marker not in text:
        sys.exit("AppRun layout changed upstream, FUSE_PATH marker not found")
    text = text.replace(marker, f'FUSE_PATH="$APPDIR/{name}.love"')
    apprun.write_text(text.replace('"$APPDIR/bin/love"', f'"$APPDIR/bin/{name}"'))
    (appdir / "bin" / "love").rename(appdir / "bin" / name)

    for f in ("love.desktop", "love.svg", ".DirIcon"):
        (appdir / f).unlink(missing_ok=True)
    shutil.copy2(ICON, appdir / f"{name}.png")
    os.symlink(f"{name}.png", appdir / ".DirIcon")
    (appdir / f"{name}.desktop").write_text(
        "[Desktop Entry]\n"
        f"Name={t['title']}\n"
        f"Exec={name}\n"
        f"Icon={name}\n"
        "Type=Application\n"
        "Categories=Game;\n"
        f"X-AppImage-Version={version}\n"
        f"Terminal={'true' if t['headless'] else 'false'}\n")

    tool = CACHE / "appimagetool"
    if not tool.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        log("downloading appimagetool")
        tool.write_bytes(fetch(APPIMAGETOOL))
        tool.chmod(0o755)
    env = {**os.environ, "ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1"}
    run([tool, "--no-appstream", appdir, out.with_name(out.name + ".AppImage")], env=env, stdout=subprocess.DEVNULL)
    shutil.rmtree(work, ignore_errors=True)
    return out.with_name(out.name + ".AppImage")


def fuse_linux_docker(target, version):
    if not shutil.which("docker"):
        log("linux: skipped (needs a linux host or docker)")
        return False
    rel = Path(__file__).resolve().relative_to(ROOT).as_posix()
    script = ("apt-get -qq update >/dev/null && apt-get -qq install -y file >/dev/null"
              f" && python {rel} fuse {version} {target} --platform linux")
    run(["docker", "run", "--rm", "-v", f"{ROOT}:/w", "-w", "/w", "python:3.12-slim", "sh", "-c", script])
    return True


FUSERS = {"win64": fuse_win64, "linux": fuse_linux, "macos": fuse_macos}


def cmd_fuse(args):
    if not (VERSION_RE.match(args.version) or DEV_RE.match(args.version)):
        sys.exit(f"invalid version '{args.version}', expected X.Y.Z[-suffix] or dev.N")
    if args.target == "all":
        targets = [t for t, c in TARGETS.items() if (ROOT / c["sources"][0][0] / "main.lua").exists()]
        log("targets:", ", ".join(targets) or "none")
    else:
        targets = [args.target]
    plats = PLATFORMS if args.platform == ["all"] else args.platform
    for target in targets:
        love = pack(target)
        for plat in plats:
            if plat == "linux" and host_platform() != "linux":
                fuse_linux_docker(target, args.version)
                continue
            ensure(plat)
            (DIST / args.version).mkdir(parents=True, exist_ok=True)
            out = FUSERS[plat](target, love, args.version, artifact(target, args.version, plat))
            log(f"{target}/{plat}: {out.relative_to(ROOT).as_posix()}")


def cmd_pack(args):
    log(pack(args.target).relative_to(ROOT))


def cmd_clean(args):
    for d in (STAGE, DIST, BUILD / "appdir", BUILD / "winres", BUILD / "win64") + ((LOVE, CACHE) if args.all else ()):
        shutil.rmtree(d, ignore_errors=True)
    for f in BUILD.glob("*.love"):
        f.unlink()


def main():
    p = argparse.ArgumentParser(prog="ff")
    sub = p.add_subparsers(dest="cmd", required=True)
    plat_arg = dict(nargs="+", choices=PLATFORMS + ["all"])

    s = sub.add_parser("update", help="fetch latest love nightly into .build/love")
    s.add_argument("-p", "--platform", default=[host_platform()], **plat_arg)
    s.add_argument("-f", "--force", action="store_true")
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("run", help="stage a target and run it with the nightly")
    s.add_argument("target")
    s.add_argument("--no-console", action="store_true", help="windows: love.exe instead of lovec.exe")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("pack", help="build .build/<target>.love")
    s.add_argument("target")
    s.set_defaults(func=cmd_pack)

    s = sub.add_parser("fuse", help="fuse executables into .build/.out/<version>/<target>_<platform>")
    s.add_argument("version", help="X.Y.Z[-suffix] or dev.N")
    s.add_argument("target", nargs="?", default="all")
    s.add_argument("-p", "--platform", default=["all"], **plat_arg)
    s.set_defaults(func=cmd_fuse)

    s = sub.add_parser("clean", help="remove build output (--all also drops love + cache)")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_clean)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
