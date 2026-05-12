# Haiku 4.5 10-item sample — 2026-05-12 21:45 UTC

Side-by-side: current DB enrichment (qwen2.5:7b) vs fresh Haiku 4.5 call.
**No DB writes.** Eyeball the diff and tell me whether to proceed with the 988-item backfill.

What to check:
- `people` contains no underscored Reddit handles (e.g. `Responsible_Box_2422`)
- Non-game items (movies, hardware-only, pure industry) have empty `genres`
- Only the locked 12-genre / 6-platform / 13-event values appear
- tldr is neutral + accurate; sentiment_score is plausible

## 1. Minions & Monsters - Official Final Trailer (2026) Allison Janney, Christoph Waltz, Jeff Bridges

`IGN (YouTube)` · published 2026-05-07 16:09:06 · item id 21
<https://www.youtube.com/watch?v=Nfv5dsVEB0E>

### Current (qwen2.5:7b, in DB)

- **tldr:** The Minions are back with a new trailer featuring voice actors Allison Janney, Christoph Waltz, and Jeff Bridges.
- **games:** ['Minions & Monsters']
- **companies:** []
- **people:** ['Allison Janney', 'Christoph Waltz', 'Jeff Bridges']
- **category:** industry
- **sentiment:** 0.0 — Neutral sentiment as it's a promotional trailer.
- **genres:** ['Indie/Roguelike']
- **platforms:** []
- **event:** null

### New (Haiku 4.5)

- **tldr:** Animated comedy film featuring Minions teaming up with monsters for a movie production, starring voice actors Allison Janney, Christoph Waltz, and Jeff Bridges.
- **games:** []
- **companies:** ['Universal Pictures']
- **people:** ['Allison Janney', 'Christoph Waltz', 'Jeff Bridges']
- **category:** launch
- **sentiment:** 0.3 — Lighthearted trailer for an upcoming animated film.
- **genres:** []
- **platforms:** []
- **event:** null

---

## 2. Confusing times in the industry!

`r/GameDev` · published 2026-05-07 16:05:42 · item id 889
<https://www.reddit.com/r/gamedev/comments/1t6eyel/confusing_times_in_the_industry/>

### Current (qwen2.5:7b, in DB)

- **tldr:** A game developer expresses confusion about the reception of their indie games, questioning whether poor art affects perception and hindering validation of gameplay quality.
- **games:** []
- **companies:** []
- **people:** ['Responsible_Box_2422']
- **category:** community
- **sentiment:** -0.5 — Developer feels disappointed and uncertain about the reception of their indie games.
- **genres:** []
- **platforms:** []
- **event:** null

### New (Haiku 4.5)

- **tldr:** A solo indie developer with 8+ years of programming experience shares frustration about audience reception of their games, citing dismissal based on art quality rather than gameplay, and uncertainty about whether to continue without professional artists.
- **games:** []
- **companies:** []
- **people:** []
- **category:** community
- **sentiment:** -0.7 — Frustrated and discouraged by community dismissal of indie work.
- **genres:** []
- **platforms:** []
- **event:** null

---

## 3. It's not just Resident Evil Requiem pulling in the numbers for Capcom, Pragmata also just crossed another impressive sales milestone less than one month after its acclaimed release

`Eurogamer` · published 2026-05-07 16:14:42 · item id 131
<https://www.eurogamer.net/pragmata-2m-sales-milestone-hugh-diana>

### Current (qwen2.5:7b, in DB)

- **tldr:** Capcom's Pragmata has reached 2 million total sales within a month of its release.
- **games:** ['Pragmata', 'Resident Evil Requiem']
- **companies:** ['Capcom']
- **people:** []
- **category:** news
- **sentiment:** 0.5 — Positive sales milestone for Pragmata.
- **genres:** []
- **platforms:** []
- **event:** null

### New (Haiku 4.5)

- **tldr:** Pragmata has sold 2 million copies total, reaching another 1 million sales milestone less than a month after its release.
- **games:** ['Pragmata', 'Resident Evil Requiem']
- **companies:** ['Capcom']
- **people:** []
- **category:** news
- **sentiment:** 0.7 — Positive reception with strong commercial performance.
- **genres:** []
- **platforms:** []
- **event:** null

---

## 4. Aliens: Fireteam Elite 2 Revealed, And You Can Almost Hear The Motion Tracker Already

`GameSpot` · published 2026-05-07 16:05:00 · item id 36
<https://www.gamespot.com/articles/aliens-fireteam-elite-2-revealed-and-you-can-almost-hear-the-motion-tracker-already/1100-6539841/?ftag=CAD-01-10abi2f>

### Current (qwen2.5:7b, in DB)

- **tldr:** Aliens: Fireteam Elite 2 is a sequel to the 2021 game, set for release in Summer 2026 on PC, PS5, and Xbox Series X|S with cross-play support.
- **games:** ['Aliens: Fireteam Elite', 'Aliens: Fireteam Elite 2']
- **companies:** ['Cold Iron Studios', 'Daybreak Game Company']
- **people:** []
- **category:** launch
- **sentiment:** 0.0 — Neutral announcement of a sequel.
- **genres:** ['Shooter']
- **platforms:** ['PC', 'PlayStation', 'Xbox']
- **event:** null

### New (Haiku 4.5)

- **tldr:** Aliens: Fireteam Elite 2 has been officially revealed with a Summer 2026 release window for PC, PS5, and Xbox Series X|S, expanding the fireteam from three to four players and adding new Xenomorph types and a Horde mode.
- **games:** ['Aliens: Fireteam Elite', 'Aliens: Fireteam Elite 2']
- **companies:** ['Cold Iron Studios', 'Daybreak Game Company']
- **people:** []
- **category:** news
- **sentiment:** 0.6 — Positive reception with expanded gameplay features and improvements.
- **genres:** ['Shooter', 'Action']
- **platforms:** ['PC', 'PlayStation', 'Xbox']
- **event:** null

---

## 5. The Story Behind One Of The Grossest Video Game Scenes Of 2026

`Kotaku` · published 2026-05-07 16:00:59 · item id 111
<https://kotaku.com/mixtape-minigame-makeout-scene-stacey-colin-tongues-2000693029>

### Current (qwen2.5:7b, in DB)

- **tldr:** Mixtape's depiction of a teenage first kiss is so realistic it might be too gross for some players.
- **games:** ['Mixtape']
- **companies:** []
- **people:** []
- **category:** review
- **sentiment:** -0.2 — The review suggests the game's realism might be off-putting to some.
- **genres:** ['Indie/Roguelike']
- **platforms:** []
- **event:** null

### New (Haiku 4.5)

- **tldr:** Mixtape features an intentionally awkward teenage first-kiss scene that successfully captures the discomfort of the moment, though perhaps more effectively than intended.
- **games:** ['Mixtape']
- **companies:** []
- **people:** []
- **category:** review
- **sentiment:** 0.3 — Positive execution of an intentionally uncomfortable scene.
- **genres:** []
- **platforms:** []
- **event:** null

---

## 6. Assassin’s Creed Black Flag Resynced Is Getting Overhauled With Tons Of Modern Accessibility Features

`Kotaku` · published 2026-05-07 16:00:50 · item id 112
<https://kotaku.com/assassins-creed-black-flag-resynced-colorblind-skippable-qtes-bigger-subtitles-accessibility-features-2000693687>

### Current (qwen2.5:7b, in DB)

- **tldr:** Ubisoft is overhauling Assassin’s Creed Black Flag Resynced with numerous accessibility features and improvements set to launch on July 9.
- **games:** ['Assassin’s Creed Black Flag Resynced']
- **companies:** ['Ubisoft']
- **people:** []
- **category:** patch
- **sentiment:** 0.8 — Positive update on accessibility features for an older game.
- **genres:** []
- **platforms:** ['PC', 'PlayStation', 'Xbox']
- **event:** null

### New (Haiku 4.5)

- **tldr:** Ubisoft is adding extensive accessibility features to Assassin's Creed Black Flag Resynced ahead of its July 9 launch, including colorblind options, screen narration, gameplay captions, customizable difficulty settings, and skippable QTEs.
- **games:** ["Assassin's Creed Black Flag Resynced"]
- **companies:** ['Ubisoft']
- **people:** []
- **category:** patch
- **sentiment:** 0.8 — Positive reception of comprehensive accessibility improvements.
- **genres:** ['Action', 'Adventure']
- **platforms:** []
- **event:** null

---

## 7. Mortal Kombat 2 Movie Producer Lashes Out At Negative Reviews That ‘Don’t Have Any Love For The Genre’

`Kotaku` · published 2026-05-07 15:00:38 · item id 114
<https://kotaku.com/mortal-kombat-2-movie-reviews-rant-producer-todd-garner-2000693958>

### Current (qwen2.5:7b, in DB)

- **tldr:** Mortal Kombat 2 movie producer responds to negative reviews, saying they lack love for the genre.
- **games:** ['Mortal Kombat 2']
- **companies:** []
- **people:** ['Producer']
- **category:** opinion
- **sentiment:** -0.1 — Slightly negative due to producer's defensive tone.
- **genres:** ['Action']
- **platforms:** []
- **event:** null

### New (Haiku 4.5)

- **tldr:** The producer of Mortal Kombat 2 movie criticized negative reviews, suggesting critics lack appreciation for the fighting game genre.
- **games:** ['Mortal Kombat']
- **companies:** []
- **people:** []
- **category:** opinion
- **sentiment:** -0.3 — Producer defensive; mixed reception acknowledged but deflected.
- **genres:** []
- **platforms:** []
- **event:** null

---

## 8. A datamine suggests Resident Evil Requiem nearly had a merchant character like Resi 4

`Eurogamer` · published 2026-05-07 11:27:38 · item id 142
<https://www.eurogamer.net/resident-evil-requiem-merchant-datamine>

### Current (qwen2.5:7b, in DB)

- **tldr:** A datamine suggests that Resident Evil Requiem almost included a merchant character similar to the one from Resident Evil 4.
- **games:** ['Resident Evil Requiem', 'Resident Evil 4']
- **companies:** []
- **people:** []
- **category:** leak
- **sentiment:** 0.0 — Neutral, as it's just a leak with no clear positive or negative implications.
- **genres:** ['Action', 'RPG']
- **platforms:** []
- **event:** null

### New (Haiku 4.5)

- **tldr:** A datamine of Resident Evil Requiem reveals cut content suggesting a merchant character similar to Resident Evil 4's iconic Merchant was planned but not included in the final game.
- **games:** ['Resident Evil Requiem', 'Resident Evil 4']
- **companies:** []
- **people:** []
- **category:** leak
- **sentiment:** 0.0 — Neutral reporting on discovered cut game content.
- **genres:** ['Survival-horror']
- **platforms:** []
- **event:** null

---

## 9. Watch Polygon's new Minecraft documentary about the kids rebuilding New York

`Polygon` · published 2026-05-07 16:08:23 · item id 51
<https://www.polygon.com/battle-of-the-boroughs-full-documentary-minecraft/>

### Current (qwen2.5:7b, in DB)

- **tldr:** Polygon releases a new Minecraft documentary focusing on children rebuilding New York City in the game.
- **games:** ['Minecraft']
- **companies:** ['Polygon']
- **people:** []
- **category:** community
- **sentiment:** 0.5 — Positive sentiment as it highlights children's creativity and hopefulness.
- **genres:** []
- **platforms:** []
- **event:** null

### New (Haiku 4.5)

- **tldr:** Polygon released a documentary about young players rebuilding New York City in Minecraft through a competitive project called Battle of the Boroughs.
- **games:** ['Minecraft']
- **companies:** ['Polygon']
- **people:** []
- **category:** community
- **sentiment:** 0.3 — Optimistic about youth creativity and community engagement through gaming.
- **genres:** ['Simulation']
- **platforms:** ['Multi-platform']
- **event:** null

---

## 10. Yacht Club Games "make-or-break" moment Mina the Hollower gets a May release date

`Rock Paper Shotgun` · published 2026-05-07 16:04:30 · item id 441
<https://www.rockpapershotgun.com/yacht-club-games-make-or-break-moment-mina-the-hollower-gets-a-may-release-date>

### Current (qwen2.5:7b, in DB)

- **tldr:** Yacht Club Games announces that their new game Mina the Hollower will be released in May.
- **games:** ['Mina the Hollower']
- **companies:** ['Yacht Club Games']
- **people:** []
- **category:** news
- **sentiment:** 0.0 — Neutral announcement of a release date.
- **genres:** ['Action', 'Adventure']
- **platforms:** []
- **event:** null

### New (Haiku 4.5)

- **tldr:** Yacht Club Games announced a May release date for Mina the Hollower, their first new IP in over a decade following years of Shovel Knight content.
- **games:** ['Mina the Hollower', 'Shovel Knight']
- **companies:** ['Yacht Club Games']
- **people:** []
- **category:** launch
- **sentiment:** 0.3 — Positive milestone for studio after extended development period.
- **genres:** ['Action', 'Adventure']
- **platforms:** ['PC']
- **event:** null

---
