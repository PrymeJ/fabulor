# Fabulor

A modern audiobook player designed for focused listening.

Most desktop players treat audiobooks like music. Fabulor does not.

---

## Philosophy

Audiobooks are not music.
The screen is not the primary interface.

Fabulor is built for people who listen while doing something else.
The UI stays out of the way. Controls remain accessible at all times.

---

## Key Features (Planned)

* Fast library loading with SQLite caching
* Proper audiobook handling (M4B chapters, MP3 folders)
* High-speed playback (up to 4x+) with pitch correction via mpv
* Per-book playback state (position, speed)
* Global hotkeys for control without focus
* Minimal, vertical UI with optional mini-player mode
* Editable metadata (title, cover art)

---

## Tech Stack

* **UI:** PySide6 (Qt)
* **Playback:** mpv (via python-mpv)
* **Metadata:** Mutagen
* **Database:** SQLite
* **Language:** Python

---

## Project Status

Early development.

Current focus:

* mpv playback integration
* basic file loading
* speed control

UI and library system will follow.

---

## Goals

* Instant startup after initial scan
* Reliable high-speed playback
* Clean, distraction-free interface
* Full control without relying on the mouse

---

## Non-Goals (v1)

* Streaming services
* Cloud sync
* Automatic chapter generation
* Over-engineered library management

---

## System Dependencies
This project requires `libmpv` to be installed on your system:

- **openSUSE Leap**: `sudo zypper install libmpv1 python3-python-mpv`
- **openSUSE Tumbleweed**: `sudo zypper install libmpv2 python3-python-mpv`
- **Ubuntu/Debian**: `sudo apt install libmpv1 python3-mpv`
- **Fedora/RHEL**: `sudo dnf install mpv-libs python3-mpv`
- **Arch**: `sudo pacman -S mpv python-mpv`

## License

MIT
