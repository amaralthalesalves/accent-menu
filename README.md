# special-chars-menu

Having a 65% keyboard kinda sucks if you are a brazilian, because accent marks are very hard to use in them and the default solution from kde-keyboard has many flaws. So I created this solution: a tiny accent picker with a global hotkey. Press `Ctrl+Alt+E` and a small popup. It also works in Windows, which I didn't find a good solution to.
opens next to the text caret with the accented forms of **e**:

```
 1   2   3   4
 é   ê   è   ë
```

- `1`-`9` inserts the character. `Shift+digit` inserts the uppercase form (the
  popup shows uppercase while Shift is held).
- `←`/`→` + `Enter`, or a mouse click, also work. `Esc` closes the popup.

Default letters: `a e i o u c n`. It is a single file, `accent_menu.py`, that
only needs Python 3 and Tkinter (standard library).

## Configuration

Edit the dicts at the top of `accent_menu.py`:

- `ACCENTS`: letter -> accented characters shown in the popup.
- `MODIFIERS`: hotkey modifiers, default `("ctrl", "alt")`.
- `COLORS`: popup palette.

Run `--install` again after changing them.

## Linux

Tested on Fedora 44, KDE Plasma 6.8 (Wayland).

### Requirements

- Python 3 with Tkinter (Fedora: `sudo dnf install python3-tkinter`).
- `wl-clipboard` (Wayland) or `xclip` (X11).
- `python3-gobject` (preinstalled on Fedora KDE). Used to talk to KWin over D-Bus.
- Write access to `/dev/uinput`. If it is missing, `--install` prints this fix:

  ```sh
  echo 'KERNEL=="uinput", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/70-uinput-accent-menu.rules
  sudo udevadm control --reload && sudo udevadm trigger /dev/uinput
  ```

### Install

```sh
python3 accent_menu.py --install
```

On KDE this:

- registers the global shortcuts with KDE's `kglobalaccel` (they appear in
  System Settings → Shortcuts and persist across reboots);
- creates hidden launchers in `~/.local/share/applications/accent-menu-<letter>.desktop`;
- adds a KWin window rule `accent-menu` to `~/.config/kwinrulesrc` (no title bar,
  hidden from the taskbar and Alt+Tab, no focus-stealing prevention);
- makes `accent_menu.py --input-method` KWin's input method (see
  [Positioning](#positioning)). This **replaces the current one**, usually
  `plasma-keyboard` (KDE's on-screen keyboard and its press-and-hold accent popup);
  the previous value is saved in `kwinrc` and restored by `--uninstall`. You can also
  switch back in System Settings → Keyboard → Virtual Keyboard.

Nothing needs to be added to autostart: KDE's shortcut daemon launches
`accent_menu.py <letter>` on demand each time, and KWin itself starts (and
restarts) the small `--input-method` background process at every login.

The launchers point to the script's absolute path, so don't move or delete it
after installing. If you move it, run `--install` again.

### Uninstall

```sh
python3 accent_menu.py --uninstall
```

This removes the shortcuts, launchers and KWin rule, and restores the previous
input method.

### Other desktops (GNOME, Sway, ...)

`--install` prints one command per letter. Bind each as a custom shortcut, e.g.
`python3 /path/to/accent_menu.py e`.

GNOME: Settings → Keyboard → Keyboard Shortcuts → Custom Shortcuts → `+`, set
the command to `python3 /path/to/accent_menu.py e` and the shortcut to
`Ctrl+Alt+E`. Repeat for each letter.

### How text is inserted

The character is put in the clipboard and the PRIMARY selection, a virtual
keyboard (uinput) presses `Shift+Insert`, and the previous clipboard is
restored. This bypasses IBus, compose and plasma-keyboard (the source of
duplicated text). The virtual keyboard and the clipboard backup are prepared
while the popup is open, so the character appears about 40 ms after pressing
the digit.

### Positioning

Wayland only tells the active **input method** where the text caret of another app
is. So `--input-method` is a minimal input method: it creates an invisible 1x1
"overlay panel", KWin keeps that panel at the caret of the focused text field, and
the popup reads the panel position from KWin (~50 ms, while Tk starts).

- Verified on KDE Plasma 6.8 in Chrome and Orca (Electron). It works in any app
  that supports Wayland text input (GTK, Qt/KDE, Firefox, recent Chromium and
  Electron), with no per-app setup. These are the same apps where KDE's own
  accent popup is positioned correctly.
- Where the app doesn't report a caret (XWayland apps, some terminals), the popup
  opens above the mouse pointer.
- The input method only reports positions; it never types or grabs the keyboard.
  Text is still inserted via the clipboard path above.
- Only one input method can be active, so this conflicts with fcitx5/IBus set as
  KWin's input method. `--install` warns when it replaces something other than
  `plasma-keyboard`.
- KDE only. On other desktops the window manager places the popup.

## Windows

Not yet tested on real hardware.

### Requirements

Python 3 from python.org (includes Tkinter and the `pythonw` / `.pyw` association).

### Run

```bat
pythonw accent_menu.py
```

Runs in the background with no console window and registers the hotkeys with
`RegisterHotKey`. If a hotkey is already taken by another app, that letter is
skipped. Run it once with `python accent_menu.py` (with a console) to see
which ones failed.

### Start at login

```bat
python accent_menu.py --install
```

Writes `accent-menu.pyw` into the Startup folder (`shell:startup`, i.e.
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`). Don't move the
script after installing.

To uninstall, delete that file and end the `pythonw.exe` process in Task Manager.

### Details

- Text is typed directly with `SendInput(KEYEVENTF_UNICODE)`; the clipboard is
  not used.
- The popup opens above the text caret, found via `GetGUIThreadInfo` (classic
  Win32 apps), then MSAA `OBJID_CARET` (Chrome, Edge, Firefox, Electron), falling
  back to the mouse pointer. DPI-aware.

## Known conflicts

Global hotkeys take the key combination away from every app. With `Ctrl+Alt`:

- JetBrains IDEs lose `Ctrl+Alt+O` (optimize imports), `Ctrl+Alt+C` (extract
  constant), etc.
- On Windows `Ctrl+Alt` is the same as `AltGr`, so on layouts like Brazilian
  ABNT2, `Ctrl+Alt+E` stops typing `°`.

To avoid a conflict, change `MODIFIERS` (e.g. `("meta", "alt")`) or remove the
letter from `ACCENTS`, then run `--install` again.
