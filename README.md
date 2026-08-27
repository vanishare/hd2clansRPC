# WARNING! THIS PROJECT WAS MADE WITH CODEX, IF YOU DON'T TRUST IT OR JUST GENERAL HATER JOE, MOVE ALONG!

<img width="402" height="164" alt="2026-08-27 17_06_35-" src="https://github.com/user-attachments/assets/93187243-9309-4c32-bc29-50afdb25d570" />
<img width="220" height="144" alt="2026-08-27 13_09_11-" src="https://github.com/user-attachments/assets/5f97981b-4e97-4bf4-89fa-4b151d9fa975" />

# HD2 Clan Discord RPC

Custom Discord Rich Presence for Helldivers 2 clans on [HD2 Clans](https://hd2clans.com).

The app waits for `helldivers2.exe`, reads the configured clan page, shows the clan's active operation when one is available, and falls back to fleet/hangar activity when there is no current operation.

## Features

- Detects Helldivers 2 and only checks HD2 Clans while the game is running.
- Reads clan operations from the HD2 Clans clan API.
- Shows operation progress when available.
- Falls back to hangar/fleet status when there are no active clan operations.
- Supports Discord Rich Presence buttons for the clan page and current status.
- Reloads `hd2_rpc_config.json` while running when the file changes.
- Adds a tray icon with config, log, reload, reconnect, and exit actions.
- Writes a rotating log so the log file does not grow forever.
- Registers itself in the current user's Windows startup when `autostart` is enabled.
- Keeps only one running instance; a second launch exits immediately.

## Discord setup

Discord Rich Presence needs a Discord application.

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create a new application.
3. Use your clan name as the application name if you want that name to appear in Discord.
4. Copy the application's `Application ID`.
5. Put that value into `client_id` in `hd2_rpc_config.json`.
6. Open the application's Rich Presence assets page.
7. Upload your clan logo and any small icon you want to use.
8. Put the uploaded asset names into `large_image` and `small_image`.

Important: Discord RPC image fields are asset keys from your Discord application, not normal image URLs. A direct logo URL from HD2 Clans will not work there.

Also note that Discord usually does not show Rich Presence buttons to the account that owns the activity. Other users should see them on your profile.

## User setup

For a release build:

1. Download `hd2_custom_clan_rpc.exe`.
2. Copy `hd2_rpc_config.example.json` next to the exe.
3. Rename the copied file to `hd2_rpc_config.json`.
4. Edit `client_id`, `clan_url`, `hangar_url`, `clan_name`, `large_image`, and `small_image`.
5. Run the exe.

When `autostart` is `true`, the app adds itself to the current user's Windows startup. To stop it, use the tray menu's `Exit` action first; launching the exe again while one copy is already running will not create a second active instance.

Example clan config:

```json
{
  "client_id": "YOUR_DISCORD_APPLICATION_CLIENT_ID",
  "clan_url": "https://hd2clans.com/clan/66",
  "hangar_url": "https://hd2clans.com/clan/66/hangar",
  "clan_name": "HellDads",
  "large_image": "clan_logo",
  "small_image": "helldivers2"
}
```

`operation_relation` controls which clan operations are eligible:

- `all`: operations issued by the clan or participated in by the clan.
- `issued`: only operations issued by the clan.
- `participated`: only operations the clan participated in.

`show_concluded_operations` should normally stay `false`; when there are no active operations, the app should fall back to fleet status instead of showing old completed operations.

## Build from source

Install Python 3.12 or newer, then run:

```powershell
pip install -r requirements.txt
compile.bat
```

The built exe will be written to `dist/hd2_custom_clan_rpc.exe`.

Manual build command:

```powershell
python -m PyInstaller --onefile --windowed --noconsole --noupx --icon=hd2_icon.ico --name "hd2_custom_clan_rpc" --hidden-import=psutil --hidden-import=pystray --hidden-import=PIL --hidden-import=PIL.Image --hidden-import=PIL.ImageDraw hd2_rpc.py
```

## Files for GitHub

Recommended source files:

- `hd2_rpc.py`
- `hd2_rpc_config.example.json`
- `requirements.txt`
- `compile.bat`
- `hd2_custom_clan_rpc.spec`
- `hd2_icon.ico`
- `README.md`
- `.gitignore`

Do not commit local runtime files such as `dist/`, `build/`, `__pycache__/`, `*.log`, or your real `hd2_rpc_config.json`.
