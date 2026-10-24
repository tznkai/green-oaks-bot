# Card image attribution

## Source and author

The card images in this directory are the work of Byron Knoll, from the vector-playing-cards
project, and were taken from https://code.google.com/archive/p/vector-playing-cards/ (Google Code
Archive).

Byron Knoll's public-domain statement, as given on that project:

> "These images are released into the public domain - attribution is appreciated but not required."

They were copied from CapersBot (https://github.com/tznkai/CapersBot, `cardimages/`), which used the
same source.

## Exception: `ace_of_spades.png`

The centre of `ace_of_spades.png` has been replaced. The original ornate centre spade is attributed
to another artist and carries no public-domain statement, so it is not covered by Byron Knoll's
statement above. It has been removed.

The replacement centre is a plain spade pip taken from `2_of_spades.png` (also Byron Knoll's work),
scaled with LANCZOS to the size of the centre pip on `ace_of_hearts.png` and `ace_of_clubs.png`, and
centred where their pips are. The card frame and corner indices are the original Byron Knoll artwork.

The change is made by `tools/make_plain_ace_of_spades.py`, which is deterministic and rebuilds the
file from the other card images in this directory.

## Selection used by Green Oaks Bot

40 cards: A, 2–7, J, Q, K in four suits.

- Aces: `ace_of_<suit>.png` (the plain `ace_of_spades.png`, not `ace_of_spades2.png`)
- 2–7: `<n>_of_<suit>.png`
- Jacks: `jack_of_<suit>.png` (plain art)
- Queens and Kings: `queen_of_<suit>2.png`, `king_of_<suit>2.png` (alternate art)

This matches the files CapersBot actually loads. Every image is 500×726 RGBA.
