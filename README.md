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

## License

MIT
