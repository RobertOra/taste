# Taste Test

**https://robertora.github.io/taste-test/** — find out how good your taste in music is, from your Spotify or YouTube listening history.

It looks at the songs and artists you really got into, checks whether they went on to grow more than similar music people got into
at the same time, and ranks you against about 16,000 music enthusiasts on [ListenBrainz](https://listenbrainz.org), with an honest
range rather than a single number.

**Your files never leave your computer.** Everything runs in your browser; the site only downloads reference data.

## The study behind it

[Is good taste real?](https://robertora.github.io/taste-test/study.html) — 594,415 Last.fm listeners (2005–2013), half of them held
back until the method was frozen, and a replication on 95,770 ListenBrainz listeners through 2026. Short answer: yes, and the best
listeners' songs took off about 13 times as often as similar songs.

## What's in this repository

This repo holds only the published site. The code that builds it, and the full study, are in https://github.com/RobertOra/taste.

| Path | What it is |
|---|---|
| `index.html`, `app.js`, `style.css` | The scoring page |
| `engine.js` | Reads your history, finds what you got into, and scores it (all in the browser) |
| `data/` | The reference data from ListenBrainz, packed so the page can fetch just the pieces it needs |
| `study.html`, `study/` | The study write-up and its chart data |

Reference data: [ListenBrainz](https://listenbrainz.org) listens (public domain, CC0), and artist information from
[MusicBrainz](https://musicbrainz.org).
