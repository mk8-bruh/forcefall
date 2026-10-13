# Forcefall

## Requirements

- Python 3.8+ with Pillow (`pip install pillow`)
- Go (build Windows icons and version info)
- Docker (build for Linux from a different platform)

> Depending on your OS/shell you may need to run `./ff` in place of `ff`

## Commands

|                    command                    |                         function                          |
|:----------------------------------------------|:----------------------------------------------------------|
|`ff update [-p win64 \| linux \| macos \| all]`| download latest LÖVE2D nightly into .build/love           |
|`ff run <target> [--core PATH] [--assets PATH]`| run client/server/admin with the current nightly          |
|`ff fuse <VERSION> [target] [-p ...]          `| build executables (all targets, all platforms by default) |
|`ff clean [--all]                             `| delete build output (`--all` deletes downloads)           |

## Output

`ff fuse <VERSION>` outputs one file per target per platform to `.build/.out/<VERSION>/`:

```
forcefall_<VERSION>_win64.zip                   
forcefall_<VERSION>_linux.AppImage         
forcefall_<VERSION>_macos.zip                   

forcefall_<VERSION>_server_win64.zip
forcefall_<VERSION>_server_linux.AppImage
forcefall_<VERSION>_server_macos.zip

forcefall_<VERSION>_admin_win64.zip
forcefall_<VERSION>_admin_linux.AppImage
forcefall_<VERSION>_admin_macos.zip
```
