"""GET /reports — claude.ai/design 'Gaming Chatter' weekly read-out.

Static placeholder data for now. The data shape mirrors data.jsx from the
design bundle so wiring real cluster output later is a straight swap.
Locked variants: grid + comfortable + light + orange (#D9682B).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.config import TEMPLATES_DIR

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------- Sparkline geometry ----------------------------------------------

def sparkline_path(data: list[float], width: int = 80, height: int = 24) -> dict:
    """Mirror of the primitives.jsx Sparkline math: returns {points, area}."""
    if not data:
        return {"points": "", "area": ""}
    lo = min(min(data), 0)
    hi = max(max(data), 1)
    rng = hi - lo or 1
    x_step = width / (len(data) - 1) if len(data) > 1 else width

    def y(v: float) -> float:
        return height - 2 - ((v - lo) / rng) * (height - 4)

    pts = " ".join(f"{i * x_step:.2f},{y(v):.2f}" for i, v in enumerate(data))
    area = f"0,{height} {pts} {width},{height}"
    return {"points": pts, "area": area}


def delta_tone(value: str) -> str:
    if value.startswith("+"):
        return "up"
    # Handle both ASCII '-' and Unicode minus '−'
    if value.startswith("-") or value.startswith("−"):
        return "down"
    return "neutral"


# ---------- Static placeholder data (mirrors data.jsx structure) -------------

SOURCES_META: dict[str, dict[str, str]] = {
    "IGN":               {"kind": "outlet"},
    "Kotaku":            {"kind": "outlet"},
    "Polygon":           {"kind": "outlet"},
    "PC Gamer":          {"kind": "outlet"},
    "Eurogamer":         {"kind": "outlet"},
    "RPS":               {"kind": "outlet"},
    "VGC":               {"kind": "outlet"},
    "Gamesindustry.biz": {"kind": "outlet"},
    "The Verge":         {"kind": "outlet"},
    "r/Games":           {"kind": "subreddit"},
    "r/pcgaming":        {"kind": "subreddit"},
    "r/truegaming":      {"kind": "subreddit"},
    "r/patientgamers":   {"kind": "subreddit"},
    "ResetEra":          {"kind": "forum"},
    "Hacker News":       {"kind": "forum"},
}

NAV_ITEMS = [
    {"id": "weekly",    "label": "Weekly read-out", "icon": "newspaper",    "is_active": True},
    {"id": "stories",   "label": "All stories",     "icon": "list",         "is_active": False},
    {"id": "watchlist", "label": "Watchlist",       "icon": "eye",          "is_active": False},
    {"id": "trends",    "label": "Trends",          "icon": "trending-up",  "is_active": False},
    {"id": "sources",   "label": "Sources",         "icon": "rss",          "is_active": False},
    {"id": "archive",   "label": "Archive",         "icon": "archive",      "is_active": False},
]

USER = {"name": "Jordan T.", "initials": "JT"}


WEEKS_RAW: dict[str, dict] = {
    "2026-W18": {
        "label": "Week of May 4, 2026",
        "range": "Apr 27 — May 3",
        "summary": {
            "headline": "Bethesda's Elder Scrolls VI slips to 2027, GTA VI sets new pre-order record, Valve quietly ships Steam Machine 2.",
            "stats": {"stories": 247, "sources": 14, "threads": 1893, "sentiment": -8},
        },
        "cards": {
            "week": {
                "stories": 247, "sources": 14, "threads": 1893,
                "top_genres": [["RPG", 38], ["Live service", 22], ["Indie", 18], ["Sim", 14], ["Shooter", 8]],
                "sentiment": -8,
            },
            "biggest": {
                "title": "Elder Scrolls VI delayed to Q1 2027",
                "dek": "Bethesda's Todd Howard confirmed the slip in a community letter Thursday — citing engine work on Creation 3 and a desire to avoid a holiday 2026 collision with GTA VI.",
                "sources": ["IGN", "Eurogamer", "VGC", "r/Games", "ResetEra"],
                "heat": 94, "confidence": 88, "relevance": 76,
                "sparkline": [12, 18, 22, 31, 48, 72, 94],
                "first_seen": "Thu 9:14 AM ET",
                "threads": 412,
            },
            "hottest": [
                {"title": "Hades II", "studio": "Supergiant", "heat": 91, "delta": "+12", "platform": "PC · Switch 2", "reason": "1.0 launch Tuesday; 96 Metacritic"},
                {"title": "Clair Obscur: Expedition 33", "studio": "Sandfall", "heat": 84, "delta": "+8", "platform": "All", "reason": "Crossed 3M units; word-of-mouth"},
                {"title": "GTA VI", "studio": "Rockstar", "heat": 82, "delta": "+22", "platform": "PS5 · XSX", "reason": "Pre-orders open; record breaks"},
                {"title": "Helldivers 2", "studio": "Arrowhead", "heat": 67, "delta": "-4", "platform": "PC · PS5", "reason": "Major Order arc resolves"},
                {"title": "Marathon", "studio": "Bungie", "heat": 41, "delta": "-18", "platform": "All", "reason": "Beta extended; mixed reception"},
            ],
            "risks": [
                {"title": "Embracer Group", "level": "high", "note": "Third spin-off in 18 months. 4,200 layoffs YTD across portfolio. Asmodee divestiture leaves debt exposure.", "trend": "worsening"},
                {"title": "Live-service saturation", "level": "med", "note": "Marathon, Concord redux, Fairgame$ all underperforming alphas. Pubs reassessing 2027 slate.", "trend": "stable"},
                {"title": "EU Digital Services Act", "level": "med", "note": "New loot-box guidance lands May 30. 12 publishers under preliminary review.", "trend": "worsening"},
                {"title": "Unity per-install fee", "level": "low", "note": "Reversal held; indie sentiment recovering but trust score still -34 vs 2023.", "trend": "improving"},
            ],
            "momentum_raw": {
                "steamCCU":    {"label": "Steam CCU",     "value": "32.1M",  "delta": "+4.2%", "spark": [28, 29, 28, 30, 31, 30, 32]},
                "twitchHrs":   {"label": "Twitch hrs",    "value": "189M",   "delta": "+1.8%", "spark": [180, 178, 182, 185, 184, 187, 189]},
                "gamePassNet": {"label": "Game Pass net", "value": "+312k",  "delta": "+0.6%", "spark": [180, 220, 240, 260, 280, 295, 312]},
                "psnNet":      {"label": "PSN net adds",  "value": "−128k",  "delta": "−0.3%", "spark": [40, 20, 0, -30, -60, -100, -128]},
            },
            "trends": {
                "wow": [
                    {"label": "RPG mentions", "value": "+38%", "tone": "up"},
                    {"label": "Live-service mentions", "value": "−12%", "tone": "down"},
                    {"label": "PC handheld coverage", "value": "+22%", "tone": "up"},
                    {"label": "VR coverage", "value": "−4%", "tone": "down"},
                ],
                "mom": [
                    {"label": "Studio layoff stories", "value": "+18%", "tone": "down-bad"},
                    {"label": "Indie hit features", "value": "+27%", "tone": "up"},
                    {"label": "Microtransaction debate", "value": "+9%", "tone": "neutral"},
                    {"label": "GPU/hardware", "value": "+44%", "tone": "up"},
                ],
            },
            "watch": [
                {"day": "Mon", "item": "Summer Game Fest dates leaked — expect official confirmation"},
                {"day": "Tue", "item": "Hades II 1.0 reviews embargo lifts 9 AM ET"},
                {"day": "Wed", "item": "EA Q4 earnings — eyes on Battlefield 2027 and EA Sports FC"},
                {"day": "Thu", "item": "Nintendo Indie World direct rumored"},
                {"day": "Fri", "item": "GDC Europe submissions close"},
            ],
            "community": {
                "positive": 41, "neutral": 32, "negative": 27,
                "top_threads": [
                    {"sub": "r/Games", "title": "TES VI delay megathread", "score": "8.2k", "sentiment": -22},
                    {"sub": "r/patientgamers", "title": "Finally finished Baldur's Gate 3", "score": "4.1k", "sentiment": 78},
                    {"sub": "ResetEra", "title": "Steam Machine 2 deep-dive", "score": "3.4k", "sentiment": 12},
                    {"sub": "r/pcgaming", "title": "DLSS 4 vs FSR 4 benchmarks", "score": "2.8k", "sentiment": 34},
                ],
            },
            "releases": [
                {"date": "May 6",  "title": "Hades II",                  "platform": "PC · Switch 2", "hype": 96},
                {"date": "May 9",  "title": "Capes",                     "platform": "All",           "hype": 62},
                {"date": "May 13", "title": "Senua's Saga: Hellblade II","platform": "XSX · PC",      "hype": 78},
                {"date": "May 21", "title": "The Alters",                "platform": "All",           "hype": 71},
                {"date": "May 23", "title": "Elden Ring: Nightreign",    "platform": "All",           "hype": 88},
            ],
            "studios": [
                {"studio": "Embracer Group",  "event": "Spin-off #3 announced — Coffee Stain Group",  "tone": "neutral",  "date": "Mon"},
                {"studio": "Bungie",          "event": "Marathon team restructured; 80 reassigned to Destiny", "tone": "negative", "date": "Tue"},
                {"studio": "Supergiant",      "event": "Hades II ships; team grows from 21 to 35",    "tone": "positive", "date": "Tue"},
                {"studio": "Sony Interactive","event": "Bend Studio cancels unannounced live-service","tone": "negative", "date": "Thu"},
                {"studio": "Annapurna",       "event": "Internal studio renamed; second project in motion", "tone": "positive", "date": "Fri"},
            ],
            "platforms": [
                {"name": "Steam",       "change": "Family Sharing 2.0 rollout begins",                 "impact": "high", "tone": "up"},
                {"name": "Game Pass",   "change": "Tier shake-up rumored — Standard merging with Core","impact": "med",  "tone": "neutral"},
                {"name": "PlayStation", "change": "PS+ Premium adds 4 day-one indies for May",         "impact": "med",  "tone": "up"},
                {"name": "Epic",        "change": "Mega Sale extended; 75% off threshold lowered",     "impact": "low",  "tone": "up"},
                {"name": "Nintendo",    "change": "Switch 2 firmware 2.1.0 — GameChat improvements",   "impact": "low",  "tone": "up"},
            ],
            "esports": {
                "top_stream": {"game": "League of Legends", "hrs": "44.2M", "delta": "+8%"},
                "big_event":  {"name": "MSI 2026 Group Stage", "peak": "2.1M concurrent"},
                "movers": [
                    {"game": "VALORANT",         "delta": "+14%", "note": "VCT Masters Tokyo runs all week"},
                    {"game": "Marvel Rivals",    "delta": "+6%",  "note": "Season 4 launch"},
                    {"game": "Counter-Strike 2", "delta": "−3%",  "note": "Between majors"},
                    {"game": "Fortnite",         "delta": "−7%",  "note": "Chapter mid-season lull"},
                ],
            },
            "drama": [
                {"title": "Marathon alpha leaks",     "severity": "med",  "recap": "Build leaked Tuesday; Bungie issued takedowns. Discourse split on whether art direction shipped or placeholder."},
                {"title": "Streamer vs publisher",    "severity": "low",  "recap": "Major creator alleges review-copy retaliation. Publisher denies; thread reaches 5k comments."},
                {"title": "AI voice acting",          "severity": "high", "recap": "SAG-AFTRA gaming strike enters month 9. Two AAA pubs reportedly using non-union AI voices in upcoming titles."},
            ],
        },
    },

    "2026-W17": {
        "label": "Week of Apr 27, 2026",
        "range": "Apr 20 — Apr 26",
        "summary": {
            "headline": "GDC fallout dominates: AI panels packed, Unity executives reshuffled, indie scene reports record submission counts.",
            "stats": {"stories": 218, "sources": 14, "threads": 1622, "sentiment": 12},
        },
        "cards": {
            "week": {"stories": 218, "sources": 14, "threads": 1622, "top_genres": [["Live service", 28], ["Indie", 26], ["RPG", 22], ["Shooter", 14], ["Strategy", 10]], "sentiment": 12},
            "biggest": {
                "title": "GDC 2026 — AI tooling dominates the floor",
                "dek": "Every AI session over capacity by Tuesday. Unity, Epic, and three middleware vendors announced agentic dev tools. Indie devs split between adoption and protest.",
                "sources": ["Gamesindustry.biz", "Polygon", "RPS", "Hacker News", "r/Games"],
                "heat": 86, "confidence": 91, "relevance": 82,
                "sparkline": [22, 34, 48, 61, 72, 80, 86],
                "first_seen": "Mon 11:30 AM ET", "threads": 287,
            },
            "hottest": [
                {"title": "Wuthering Waves", "studio": "Kuro", "heat": 88, "delta": "+18", "platform": "PC · Mobile · PS5", "reason": "50M players milestone"},
                {"title": "Balatro+", "studio": "LocalThunk", "heat": 72, "delta": "+4", "platform": "All", "reason": "Mobile launch sustains"},
                {"title": "Stellar Blade", "studio": "Shift Up", "heat": 64, "delta": "+2", "platform": "PS5 · PC", "reason": "PC port performance praised"},
                {"title": "Once Human", "studio": "Starry", "heat": 58, "delta": "−6", "platform": "PC", "reason": "Season 5 mixed reception"},
            ],
            "risks": [
                {"title": "Unity leadership churn", "level": "high", "note": "Third CTO in 30 months. Engine roadmap slipping; Godot mentions up 64% YoY in dev forums.", "trend": "worsening"},
                {"title": "SAG-AFTRA strike", "level": "high", "note": "Month 8. Two AAA delays attributed. Indie carve-out approved 12 studios so far.", "trend": "stable"},
                {"title": "Mobile UA costs", "level": "med", "note": "iOS CPI up 22% post-ATT changes. Mid-core publishers cutting marketing spend.", "trend": "worsening"},
            ],
            "momentum_raw": {
                "steamCCU":    {"label": "Steam CCU",     "value": "31.8M", "delta": "+2.1%", "spark": [27, 28, 29, 30, 30, 31, 32]},
                "twitchHrs":   {"label": "Twitch hrs",    "value": "186M",  "delta": "+0.4%", "spark": [183, 184, 185, 184, 186, 185, 186]},
                "gamePassNet": {"label": "Game Pass net", "value": "+288k", "delta": "+0.4%", "spark": [220, 230, 250, 260, 270, 280, 288]},
                "psnNet":      {"label": "PSN net adds",  "value": "+44k",  "delta": "+0.1%", "spark": [-20, -10, 0, 10, 20, 35, 44]},
            },
            "trends": {
                "wow": [
                    {"label": "AI tooling stories", "value": "+62%", "tone": "up"},
                    {"label": "Engine choice debates", "value": "+44%", "tone": "up"},
                    {"label": "VR coverage", "value": "+12%", "tone": "up"},
                    {"label": "Battle royale", "value": "−18%", "tone": "down"},
                ],
                "mom": [
                    {"label": "Layoff stories", "value": "+11%", "tone": "down-bad"},
                    {"label": "Indie features", "value": "+19%", "tone": "up"},
                    {"label": "Hardware leaks", "value": "+33%", "tone": "up"},
                    {"label": "Microtransactions", "value": "−6%", "tone": "neutral"},
                ],
            },
            "watch": [
                {"day": "Mon", "item": "Embracer earnings — restructuring update expected"},
                {"day": "Tue", "item": "Hades II 1.0 launch (note carryover into next week)"},
                {"day": "Wed", "item": "EA Q4 — Battlefield 2027 reveal window"},
                {"day": "Thu", "item": "Nintendo Indie World rumored"},
            ],
            "community": {
                "positive": 48, "neutral": 30, "negative": 22,
                "top_threads": [
                    {"sub": "r/Games", "title": "GDC takeaways megathread", "score": "6.4k", "sentiment": 28},
                    {"sub": "r/truegaming", "title": "Why I'm leaving live service", "score": "3.2k", "sentiment": -12},
                    {"sub": "ResetEra", "title": "Wuthering Waves 50M discussion", "score": "2.1k", "sentiment": 44},
                    {"sub": "r/pcgaming", "title": "Godot vs Unity 2026", "score": "1.8k", "sentiment": 18},
                ],
            },
            "releases": [
                {"date": "Apr 28", "title": "Tales of the Shire",  "platform": "All",      "hype": 64},
                {"date": "Apr 30", "title": "Indiana Jones DLC",   "platform": "XSX · PC", "hype": 71},
                {"date": "May 6",  "title": "Hades II",            "platform": "PC · Switch 2", "hype": 96},
            ],
            "studios": [
                {"studio": "Unity",                "event": "CTO replacement announced; engine-first messaging", "tone": "neutral",  "date": "Mon"},
                {"studio": "Activision-Blizzard",  "event": "FTC settlement finalized at $720M",                 "tone": "neutral",  "date": "Wed"},
                {"studio": "Kuro Games",           "event": "Wuthering Waves crosses 50M players",               "tone": "positive", "date": "Thu"},
            ],
            "platforms": [
                {"name": "Steam",       "change": "Concurrent record broken — 41.2M peak Saturday", "impact": "high", "tone": "up"},
                {"name": "Game Pass",   "change": "Day-one Hades II confirmed for next week",       "impact": "med",  "tone": "up"},
                {"name": "PlayStation", "change": "PS+ Premium May lineup announced",               "impact": "low",  "tone": "neutral"},
                {"name": "Epic",        "change": "Mega Sale 2026 dates set",                       "impact": "low",  "tone": "up"},
            ],
            "esports": {
                "top_stream": {"game": "League of Legends", "hrs": "40.9M", "delta": "+12%"},
                "big_event":  {"name": "MSI 2026 Play-Ins", "peak": "1.4M concurrent"},
                "movers": [
                    {"game": "Dota 2",          "delta": "+8%", "note": "ESL One Birmingham"},
                    {"game": "Apex Legends",    "delta": "−9%", "note": "Pre-season slump"},
                    {"game": "Mobile Legends",  "delta": "+4%", "note": "MPL Indonesia finals"},
                ],
            },
            "drama": [
                {"title": "AI voice debate",       "severity": "high", "recap": "Two indie devs publicly resign over studio's AI VO direction. Open letter draws 800+ signatures."},
                {"title": "Reviewer access flap",  "severity": "low",  "recap": "Outlet alleges blacklisting after critical preview. Publisher claims scheduling conflict."},
            ],
        },
    },

    "2026-W16": {
        "label": "Week of Apr 20, 2026",
        "range": "Apr 13 — Apr 19",
        "summary": {
            "headline": "Switch 2 holiday lineup leaks early, Steam Deck OLED 2 rumors solidify, indie smash 'Loop Hero 2' sells 1M in 8 days.",
            "stats": {"stories": 196, "sources": 14, "threads": 1408, "sentiment": -2},
        },
        "cards": {
            "week": {"stories": 196, "sources": 14, "threads": 1408, "top_genres": [["Indie", 32], ["RPG", 24], ["Strategy", 18], ["Live service", 14], ["Sim", 12]], "sentiment": -2},
            "biggest": {
                "title": "Microsoft cuts 1,800 from Xbox division",
                "dek": "Third round in 14 months. Affected teams include Halo Studios support, ZeniMax middleware, and platform marketing. Phil Spencer memo emphasizes 'sustainable growth'.",
                "sources": ["The Verge", "IGN", "Gamesindustry.biz", "ResetEra", "r/Games"],
                "heat": 89, "confidence": 94, "relevance": 84,
                "sparkline": [44, 56, 68, 78, 84, 87, 89],
                "first_seen": "Tue 7:02 AM ET", "threads": 524,
            },
            "hottest": [
                {"title": "Loop Hero 2", "studio": "Four Quarters", "heat": 86, "delta": "+44", "platform": "PC", "reason": "1M in 8 days; Steam #1"},
                {"title": "Tekken 8", "studio": "Bandai Namco", "heat": 71, "delta": "+8", "platform": "All", "reason": "Season 2 character drop"},
                {"title": "Path of Exile 2", "studio": "GGG", "heat": 68, "delta": "+6", "platform": "PC", "reason": "Endgame patch lands"},
                {"title": "Hi-Fi Rush 2", "studio": "Tango", "heat": 54, "delta": "+12", "platform": "All", "reason": "Reveal trailer"},
            ],
            "risks": [
                {"title": "Xbox division uncertainty", "level": "high", "note": "Third layoff round. First-party output forecast cut. Publisher confidence wavering.", "trend": "worsening"},
                {"title": "Steam dependency", "level": "med", "note": "Indie publishers report 88% revenue concentration on Steam. Epic, GOG, itch all flat YoY.", "trend": "stable"},
                {"title": "China approvals", "level": "low", "note": "April batch up 14% — recovering from 2024 trough. Cautious optimism for Western pubs.", "trend": "improving"},
            ],
            "momentum_raw": {
                "steamCCU":    {"label": "Steam CCU",     "value": "31.2M", "delta": "+1.8%", "spark": [29, 29, 30, 30, 30, 31, 31]},
                "twitchHrs":   {"label": "Twitch hrs",    "value": "184M",  "delta": "−0.6%", "spark": [186, 185, 184, 185, 184, 184, 184]},
                "gamePassNet": {"label": "Game Pass net", "value": "+241k", "delta": "−0.2%", "spark": [260, 252, 250, 248, 246, 244, 241]},
                "psnNet":      {"label": "PSN net adds",  "value": "−18k",  "delta": "−0.1%", "spark": [20, 12, 4, -2, -10, -15, -18]},
            },
            "trends": {
                "wow": [
                    {"label": "Indie features", "value": "+34%", "tone": "up"},
                    {"label": "Layoff stories", "value": "+18%", "tone": "down-bad"},
                    {"label": "Handheld coverage", "value": "+12%", "tone": "up"},
                    {"label": "Mobile gacha", "value": "−8%", "tone": "down"},
                ],
                "mom": [
                    {"label": "Hardware speculation", "value": "+28%", "tone": "up"},
                    {"label": "Live-service pivots", "value": "+12%", "tone": "neutral"},
                    {"label": "Studio closures", "value": "+22%", "tone": "down-bad"},
                    {"label": "Acquisition rumors", "value": "−14%", "tone": "neutral"},
                ],
            },
            "watch": [
                {"day": "Mon", "item": "GDC kicks off — keynote 9 AM PT"},
                {"day": "Tue", "item": "Unity earnings — engine roadmap update"},
                {"day": "Wed", "item": "Wuthering Waves anniversary stream"},
                {"day": "Thu", "item": "Embracer Q&A on restructuring"},
            ],
            "community": {
                "positive": 32, "neutral": 38, "negative": 30,
                "top_threads": [
                    {"sub": "r/Games", "title": "Xbox layoffs megathread", "score": "9.1k", "sentiment": -42},
                    {"sub": "r/pcgaming", "title": "Loop Hero 2 appreciation", "score": "3.8k", "sentiment": 68},
                    {"sub": "r/truegaming", "title": "Are we in a Switch era?", "score": "2.4k", "sentiment": 14},
                    {"sub": "ResetEra", "title": "GTA VI date skepticism", "score": "2.1k", "sentiment": -8},
                ],
            },
            "releases": [
                {"date": "Apr 22", "title": "SaGa Emerald Beyond", "platform": "All",     "hype": 58},
                {"date": "Apr 24", "title": "Stellar Blade PC",    "platform": "PC",      "hype": 71},
                {"date": "Apr 28", "title": "Tales of the Shire",  "platform": "All",     "hype": 64},
            ],
            "studios": [
                {"studio": "Microsoft / Xbox", "event": "1,800 layoffs across Halo, ZeniMax, marketing", "tone": "negative", "date": "Tue"},
                {"studio": "Four Quarters",    "event": "Loop Hero 2 hits 1M sales",                     "tone": "positive", "date": "Thu"},
                {"studio": "Take-Two",         "event": "Reaffirms GTA VI Oct 2026 in earnings call",    "tone": "neutral",  "date": "Wed"},
            ],
            "platforms": [
                {"name": "Steam",        "change": "Deck OLED 2 confirmed for Q3",            "impact": "high", "tone": "up"},
                {"name": "Nintendo",     "change": "Switch 2 holiday lineup leaks",            "impact": "high", "tone": "neutral"},
                {"name": "Game Pass",    "change": "April lineup announced",                   "impact": "low",  "tone": "neutral"},
                {"name": "PlayStation",  "change": "PS5 Pro firmware 26.01 — fluid mode tweaks","impact": "low", "tone": "up"},
            ],
            "esports": {
                "top_stream": {"game": "League of Legends", "hrs": "36.5M", "delta": "+4%"},
                "big_event":  {"name": "Six Invitational",  "peak": "0.9M concurrent"},
                "movers": [
                    {"game": "Rainbow Six Siege X", "delta": "+22%", "note": "Six Invitational week"},
                    {"game": "Counter-Strike 2",    "delta": "+6%",  "note": "BLAST Open Spring"},
                    {"game": "Street Fighter 6",    "delta": "+18%", "note": "Capcom Cup XI"},
                ],
            },
            "drama": [
                {"title": "GTA VI date doubts",     "severity": "med", "recap": "Industry analysts push back on Take-Two's October date. Take-Two CFO doubles down on call."},
                {"title": "Indie pricing wars",     "severity": "low", "recap": "Discussion over $19.99 indie pricing reignites; some devs raise, others hold."},
            ],
        },
    },
}

# Display order of momentum cells (data.jsx hard-codes this)
_MOMENTUM_KEYS = ["steamCCU", "twitchHrs", "gamePassNet", "psnNet"]


def _enrich_week(week: dict) -> dict:
    """Pre-compute sparkline geometry, delta tones, and momentum list shape."""
    cards = week["cards"]

    big = cards["biggest"]
    big["spark_path"] = sparkline_path(big["sparkline"], width=100, height=28)

    for g in cards["hottest"]:
        g["delta_tone"] = delta_tone(g["delta"])

    momentum_list = []
    for key in _MOMENTUM_KEYS:
        cell = dict(cards["momentum_raw"][key])
        tone = delta_tone(cell["delta"])
        cell["color"] = "var(--gc-success)" if tone == "up" else "var(--gc-danger)"
        cell["spark_path"] = sparkline_path(cell["spark"], width=56, height=20)
        momentum_list.append(cell)
    cards["momentum"] = momentum_list

    for m in cards["esports"]["movers"]:
        m["delta_tone"] = delta_tone(m["delta"])

    return week


@router.get("/reports")
def reports_view(request: Request, week: str = "2026-W18"):
    week_keys = list(WEEKS_RAW.keys())
    active_key = week if week in WEEKS_RAW else week_keys[0]

    weeks_index = [
        {"key": k, "label": WEEKS_RAW[k]["label"], "range": WEEKS_RAW[k]["range"], "is_active": k == active_key}
        for k in week_keys
    ]

    # Enrich a copy each request so repeated calls don't double-process.
    import copy
    week_data = _enrich_week(copy.deepcopy(WEEKS_RAW[active_key]))

    return templates.TemplateResponse(
        request,
        "reports.html",
        {
            "week": week_data,
            "weeks_index": weeks_index,
            "nav_items": NAV_ITEMS,
            "user": USER,
            "source_count": 14,
            "refreshed_at": "12 min ago",
            "sources_meta": SOURCES_META,
        },
    )
