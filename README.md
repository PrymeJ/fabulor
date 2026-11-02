# Fabulor

A desktop audiobook player that treats books as books.

---

## Philosophy

Audiobooks are not music.

A book isn't a playlist of tracks. It has chapters, a place you left off, and a history of how you listened to it. Fabulor is built around the book: one at a time, with everything about it a click or a key away.

And a player should be worth looking at. Each named theme is tuned by hand, the cover art takes center stage, and nothing moves without reason.

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
* **Search with operators.** Plain text searches titles, authors and narrators at once. To narrow
  it down:
  * `_dune`: titles starting with "dune"
  * `@le guin`: authors only
  * `#sci`: books with a tag starting with "sci"
  * `=1984`: published in 1984
  * `>1950`, `<1990`, or year ranges like `>1950<1990`: from, up to, or between years (a leading
    minus means BCE)

  Click an author, narrator or year in the library to filter by it.
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
* Every panel can be driven from the keyboard

---

## Non-Goals (v1)

* Streaming services
* Cloud sync
* Automatic chapter generation
* Over-engineered library management

---

## License

MIT
