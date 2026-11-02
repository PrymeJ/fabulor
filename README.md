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

## Features

### Playback

* **Every common audiobook layout.** Single M4B/M4A files with embedded chapters, `.cue` chapter
  files, and folders of MP3/M4A/FLAC parts played as one continuous book, each part a chapter.
* **Speed from 0.25x to 8x**, remembered per book.
* **Your place, kept.** Position is saved continuously and restored on reopen.
* **Smart rewind.** After a long pause, playback steps back a little so you don't lose the thread.
* **Undo for seeks.** Skipped too far, or clicked the wrong chapter? One key takes you back to where
  you were before the jump.
* **Sleep timer**, timed or to the end of the chapter, with an optional fade-out.
* **Listening sprints**: set a block of listening time and track it.
* **Audio tools for narration**: voice boost, a 5-band equalizer, mono/stereo, channel swap and
  left/right balance.

### Library

* **Five views**, from large covers to a compact list, with sorting by title, author, duration, year,
  progress, date added, recently played and finished.
* **Search with operators**: `#tag`, `@author`, `=1984`, `>1950`, `<1990`, year ranges, and title
  prefixes. Click an author, narrator or year to filter by it.
* **Tags with colors**, managed in their own panel.
* **Editable metadata.** Title, author, narrator and year can be edited and locked, so a rescan never
  overwrites your corrections.
* **Custom covers**: up to four per book, each with its own fit mode. Books without art get a
  generated cover with their title and author.
* **Library hygiene**: exclude books you don't want to see, and books whose folders disappear are
  detected on rescan. Listening history survives either way.

### Stats

* **Listening time** by day, week and month, with a 7-day chart.
* **Streaks** on a year-long calendar, and an hourly heatmap of when you listen.
* **Per-book history**: every session, how far you got, when you started and finished.

### Look and feel

* **62 hand-tuned themes**, with optional rotation, plus a theme generated from the current book's
  cover.
* **Frosted, transparent or opaque panels** over the cover art.
* **Keyboard-first.** Every panel can be driven from the keyboard. See
  [KEYBINDINGS.md](KEYBINDINGS.md).

---

## Tech Stack

* **UI:** PySide6 (Qt)
* **Playback:** mpv (via python-mpv)
* **Metadata:** Mutagen
* **Database:** SQLite
* **Language:** Python

---

## Running from source

Fabulor needs Python 3 and the mpv library (`libmpv`) installed on the system.

```bash
git clone https://github.com/PrymeJ/fabulor.git
cd fabulor
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

On first launch, add the folder that holds your audiobooks. Fabulor expects one folder per book,
named `Author - Title` by default (`Title - Author` is also supported).

---

## Project Status

In active development. Linux only for now, with a Windows release to follow.

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
