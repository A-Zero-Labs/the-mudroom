"""The three dashboards, rendered as HTML from the database on every request."""
import html
import json
from datetime import timedelta

from . import clock, db, lock

# The header: three rows. The house, then the two things you can do in it.
PLAY = [("doorstep", "Doorstep"), ("sorted", "Sorting dashboard"), ("planner", "Planning dashboard")]
YOURS = [("piping", "Inspect the piping"), ("whats-next", "What's next")]
# The log is not in the menu: the Sorting dashboard and the front door link to it where it matters.
GROUPS = ["Today", "Overdue", "This week", "Later", "No date"]   # the day first, then what slipped


def h(value):
    return html.escape("" if value is None else str(value), quote=True)


def paragraphs(text):
    """Plain text to HTML: blank lines make paragraphs, single newlines make breaks."""
    blocks = [b.strip("\n") for b in (text or "").split("\n\n") if b.strip()]
    return "".join(f"<p>{h(b).replace(chr(10), '<br>')}</p>" for b in blocks)


WATCH_RUN = """<script>
(function () {
  function ask() {
    fetch("/run-state", {cache: "no-store"}).then(function (r) { return r.json(); }).then(function (s) {
      if (!s.held) { location.reload(); } else { setTimeout(ask, 4000); }
    }).catch(function () { setTimeout(ask, 8000); });
  }
  setTimeout(ask, 4000);
})();
</script>"""


def layout(conn, title, current, body, refresh=None):
    from . import demo
    now = clock.as_datetime(db.get_state(conn, "clock"))

    def links(items):
        return "".join(f'<a href="/{slug}"{" class=\"current\"" if slug == current else ""}>{name}</a>'
                       for slug, name in items)
    play = "Play the demo" if demo.present() else "Your house"
    nav = (f'<div class="hrow"><span class="group">{play}</span><nav>{links(PLAY)}</nav></div>'
           f'<div class="hrow"><span class="group">Make it your own</span><nav>{links(YOURS)}</nav></div>')
    brand = " current" if current == "home" else ""
    refresh_tag = WATCH_RUN if refresh else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{refresh_tag}
<title>The Mudroom: {h(title)}</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="top">
  <div class="hrow brand-row"><a class="brand{brand}" href="/">The Mudroom</a><div class="clock">{h(clock.clock_label(now))}</div></div>
  {nav}
</header>
<main>
{body}
</main>
</body>
</html>
"""


def empty_section(heading, text):
    return f'<section class="empty-state">\n  <h2>{h(heading)}</h2>\n  <p>{h(text)}</p>\n</section>'


def empty_state(conn, title, current, heading, text):
    return layout(conn, title, current, empty_section(heading, text))


class Who:
    """A name with a hint of who they are to you, from the cast in people: Jordan (your
    manager), Sam (your partner), Alex (you). A sender the cast does not know, a newsletter
    or a recruiter, reads as the source wrote it."""

    def __init__(self, conn):
        self.you = db.get_state(conn, "you", "") or ""
        self.people = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM people")}
        self.by_name = {}
        for p in self.people.values():
            self.by_name.setdefault(p["name"].lower(), []).append(p["id"])
        self.ties = {(r["source"], r["sender"]): r["person_id"] for r in conn.execute(
            "SELECT source, sender, person_id FROM source_senders WHERE person_id IS NOT NULL")}

    def hint(self, pid):
        role = (self.people[pid].get("role") or "").split(",")[0].strip()
        role = role.replace(f"{self.you}'s", "your").replace(self.you, "you")
        return role[:1].lower() + role[1:] if role else ""

    def tag(self, name, source=None, pid=None):
        if not name:
            return ""
        if name == self.you:
            return f"{h(name)} <small>(you)</small>"
        if pid is None:
            pid = self.ties.get((source, name))
        if pid is None:
            ids = self.by_name.get(name.lower(), [])
            pid = ids[0] if len(ids) == 1 else None
        if pid in self.people:
            hint = self.hint(pid)
            shown = h(self.people[pid]["name"])
            return f"{shown} <small>({h(hint)})</small>" if hint else shown
        return h(name)

    def by_id(self, pid):
        if pid in self.people:
            return self.tag(self.people[pid]["name"], pid=pid)
        return h(pid or "")


# Doorstep: what came in, as a set of small inboxes. Mail is an inbox with one line per
# message that opens on click; messages are chat threads per person or channel; notes,
# invitations and meeting notes are small piles of their own. What has not been sorted yet
# reads as unread. Your replies sit beneath what they answered.

PILES = [("email", "Mail"), ("chat", "Messages"), ("capture", "Notes to self"),
         ("calendar", "Invitations"), ("transcript", "Meeting transcripts")]


def doorstep(conn, query=None):
    bar = demo_bar(conn)
    refresh = 5 if lock.held(conn) else None
    items = conn.execute("SELECT * FROM items WHERE status != 'sent' ORDER BY received_at DESC, id DESC").fetchall()
    if not items:
        body = (bar + '<section class="empty-state">\n  <h2>The door is clear.</h2>\n  <p>Nothing has '
                'arrived yet. When something comes in, every email, message, note and invite shows here '
                'as it arrived.</p>\n</section>')
        return layout(conn, "Doorstep", "doorstep", body, refresh)
    who = Who(conn)
    sent = {}
    for s in conn.execute("SELECT * FROM items WHERE status = 'sent' ORDER BY received_at, id"):
        sent.setdefault(s["thread"], []).append(s)
    last = conn.execute("SELECT at, detail FROM actions WHERE action = 'intake' ORDER BY id DESC LIMIT 1").fetchone()
    arrived = {i["id"] for i in items if last and i["staged_at"] == last["at"]}
    by_source = {}
    for i in items:
        by_source.setdefault(i["source"], []).append(i)
    piles = []
    for source, title in PILES:
        mine = by_source.get(source, [])
        if not mine:
            continue
        just_in = sum(1 for i in mine if i["id"] in arrived)
        badge = f'<span class="badge">{just_in} just in</span>' if just_in else ""
        if source == "chat":
            inner = chat_threads(mine, sent, who, arrived)
        else:
            inner = "".join(inbox_row(i, sent.get(i["thread"] or i["id"], []), who, arrived) for i in mine)
        piles.append(f'<section class="pile {h(source)}"><h2>{h(title)}<span>{len(mine)}</span>{badge}</h2>'
                     f'<div class="rows">{inner}</div></section>')
    wide = [p for p in piles if 'class="pile email"' in p or 'class="pile transcript"' in p]
    rest = [p for p in piles if p not in wide]
    return layout(conn, "Doorstep", "doorstep",
                  bar + f'<div class="piles"><div class="side">{"".join(wide)}</div><div class="side">{"".join(rest)}</div></div>'
                  + OPEN_ON_ARRIVAL, refresh)


OPEN_ON_ARRIVAL = """<script>
(function () {
  function open() {
    var el = location.hash && document.getElementById(location.hash.slice(1));
    while (el) { if (el.tagName === "DETAILS") el.open = true; el = el.parentElement; }
    if (location.hash) { var t = document.getElementById(location.hash.slice(1)); if (t) t.scrollIntoView({block: "center"}); }
  }
  window.addEventListener("hashchange", open); open();
})();
</script>"""


def when_short(item):
    at = clock.as_datetime(item["received_at"])
    return f"{clock.DAYS[at.weekday()][:3]} {at:%H:%M}"


def inbox_row(item, replies, who, arrived=()):
    """One line that opens on click: who, what, when. Open, the item in its source's own look,
    and your replies beneath it. A line that came in this round carries a dot."""
    heads = json.loads(item["raw"] or "{}")
    unread = item["status"] == "staged"
    new = item["id"] in arrived
    first = (item["subject"] or (item["body"] or "").strip().splitlines()[0] if (item["body"] or "").strip() else "") or ""
    if item["source"] == "calendar":
        first = f"{item['subject'] or ''} {heads.get('when', '')}".strip()
    snippet = ""
    if item["subject"] and item["body"]:
        snippet = " ".join((item["body"] or "").split())[:90]
    day = clock.as_datetime(item["received_at"]).date()
    opened = item_card(item, day, who) + "".join(sent_card(s, day, who) for s in replies)
    answered = f'<span class="answered">{len(replies)} from you</span>' if replies else ""
    return (f'<details class="row{" unread" if unread else ""}{" arrived" if new else ""}"><summary>'
            f'<b>{"<i class=\"dot-new\"></i>" if new else ""}{who.tag(item["sender"], item["source"])}</b>'
            f'<span class="what">{h(first)}{(" <small>" + h(snippet) + "</small>") if snippet else ""}</span>'
            f'{answered}<time>{h(when_short(item))}</time></summary>{opened}</details>')


def chat_threads(messages, sent, who, arrived=()):
    """Messages grouped by person or channel, each a thread of bubbles in time order, yours
    on the right."""
    threads = {}
    for m in messages:
        heads = json.loads(m["raw"] or "{}")
        channel = heads.get("channel", "") or "direct"
        key = m["sender"] if channel == "direct" else channel
        threads.setdefault(key, []).append(m)
    out = []
    for key, mine in threads.items():
        unread = sum(1 for m in mine if m["status"] == "staged")
        title = who.tag(key, "chat") if not key.startswith("#") else h(key)
        bubbles = []
        for m in sorted(mine, key=lambda r: (r["received_at"], r["id"])):
            kind = json.loads(m["raw"] or "{}").get("kind")
            voice = ' <small>(voice note)</small>' if kind == "voice note" else ""
            name = "" if not key.startswith("#") else f'<b>{who.tag(m["sender"], "chat")}</b> '
            mark = " arrived" if m["id"] in arrived else ""
            bubbles.append(f'<div class="msg in{" unread" if m["status"] == "staged" else ""}{mark}" id="{h(m["id"])}">'
                           f'{name}<span>{paragraphs(m["body"])}</span><time>{h(when_short(m))}{voice}</time>'
                           f'<a class="sorted" href="/sorted#{h(m["id"])}">how the door sorted it</a></div>')
            for s in sent.get(m["thread"] or m["id"], []):
                bubbles.append(f'<div class="msg out item sent chat" id="{h(s["id"])}"><span>{paragraphs(s["body"])}</span>'
                               f'<time>{h(when_short(s))}</time></div>')
        latest = max(mine, key=lambda r: r["received_at"])
        just_in = sum(1 for m in mine if m["id"] in arrived)
        badge = f'<span class="badge">{just_in} just in</span>' if just_in else ""
        dot = '<i class="dot-new"></i>' if just_in else ""
        out.append(f'<details class="row thread{" unread" if unread else ""}{" arrived" if just_in else ""}">'
                   f'<summary><b>{dot}{title}</b>'
                   f'<span class="what">{h(" ".join((latest["body"] or "").split())[:80])}</span>'
                   f'{badge}'
                   f'<time>{h(when_short(latest))}</time></summary><div class="bubbles">{"".join(bubbles)}</div></details>')
    return "".join(out)


def demo_bar(conn, brief=False):
    """Demo scaffolding: the story so far, and the one button for the next step. Leaves with
    the demo, together with engine/demo.py. Brief, on the front door, it keeps the time and
    the button and leaves the story to the Doorstep."""
    from . import agents, demo
    if not demo.present():
        return real_bar(conn)
    waiting = conn.execute("SELECT COUNT(*) FROM items WHERE status = 'staged'").fetchone()[0]
    again = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE status IN ('sent_back', 'answered')").fetchone()[0]
    any_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    upcoming = demo.upcoming(conn)
    last_batch = demo.last_batch(conn)
    held = lock.held(conn)
    last = agents.last_run(conn)
    now = clock.clock_label(clock.as_datetime(db.get_state(conn, "clock")))
    next_at = demo.slot(conn, upcoming) if upcoming else None
    story = h(demo.story(last_batch)) if last_batch and not brief else ""
    move = (f'<form method="post" action="/demo/next"><button>Move the clock to {h(next_at)}</button></form>'
            if upcoming else "")
    sort_now = '<form method="post" action="/demo/judge"><button>Sort what\'s at the door</button></form>'
    buttons = []
    if held:
        doing = (last or {}).get("message") or "working"
        line = f"{h(doing[:1].upper() + doing[1:])}. A minute or two; the page updates itself when it's done."
    elif last and last.get("ok") is False:
        line = h(last["message"])
        buttons.append(sort_now if waiting else move)
    elif waiting:
        line = f"It's {h(now)}. {waiting} things are at the door, waiting to be sorted."
        buttons.append(sort_now)
    elif not any_items:
        line = "The week starts on Monday morning." if brief else f"Welcome. {h(demo.intro(conn))}"
        buttons.append(move)
    elif again and upcoming:
        line = (f"It's {h(now)}. {story} You sent {again} thing{'s' if again > 1 else ''} back with a note; "
                f"the door looks at {'them' if again > 1 else 'it'} again when the clock moves.")
        buttons.append(move)
    elif again:
        line = (f"It's {h(now)}, the end of the week. You sent {again} thing{'s' if again > 1 else ''} back with "
                f"a note, and the door can look at {'them' if again > 1 else 'it'} once more.")
        buttons.append('<form method="post" action="/demo/judge"><button>Look again</button></form>')
    elif upcoming:
        line = f"It's {h(now)}. {story}" if story else f"It's {h(now)}. Next up: {h(demo.title(upcoming))}."
        buttons.append(move)
    else:
        line = (f"It's {h(now)}, and that's the end of the week. {story} The invented week has nothing more "
                f"to bring. Start it again to play it over, or make the house yours.")
    off = " disabled" if held else ""
    buttons.append(f'<form method="post" action="/demo/reset" onsubmit="return confirm(&#39;Start the week again? '
                   f'Everything played this week goes.&#39;)"><button class="quiet"{off}>Start the week again</button>'
                   f'</form>')
    return f'<section class="demo-bar"><p>{line}</p><div class="buttons">{"".join(buttons)}</div></section>\n'


def real_bar(conn):
    """The bar once the invented week has left: your sources bring things in, the judge
    button stays."""
    from . import agents
    waiting = conn.execute("SELECT COUNT(*) FROM items WHERE status = 'staged'").fetchone()[0]
    again = conn.execute(
        "SELECT COUNT(*) FROM proposals WHERE status IN ('sent_back', 'answered')").fetchone()[0]
    held = lock.held(conn)
    last = agents.last_run(conn)
    if held:
        line = "Sorting what is at the door, a minute or two. The page refreshes itself."
    elif last and last.get("ok") is False:
        line = h(last["message"])
    elif waiting or again:
        line = (f"{waiting} things are at the door, waiting to be sorted." if waiting
                else f"You sent {again} thing{'s' if again > 1 else ''} back with a note, waiting for another look.")
    else:
        line = ("Nothing at the door. Your source skills bring things in; python mudroom.py intake "
                "registers what they fetched.")
    buttons = ('<form method="post" action="/demo/judge"><button>Sort what\'s at the door</button></form>'
               if (waiting or again) and not held else "")
    return f'<section class="demo-bar"><p>{line}</p><div class="buttons">{buttons}</div></section>\n'


def item_card(item, batch_day, who):
    heads = json.loads(item["raw"] or "{}")
    received = clock.as_datetime(item["received_at"])
    when = f"{received:%H:%M}"
    if received.date() != batch_day:
        when = f"{clock.DAYS[received.weekday()][:3]} {when}"
    source = item["source"]
    sender = who.tag(item["sender"], source)
    subject = f"<h3>{h(item['subject'])}</h3>" if item["subject"] else ""
    if source == "email":
        kind = "Email"
        head = f"From <b>{sender}</b> to <b>{who.tag(heads.get('to') or who.you, source)}</b>"
        main = f'{subject}<div class="body">{paragraphs(item["body"])}</div>'
    elif source == "chat":
        channel = heads.get("channel", "")
        if heads.get("kind") == "voice note":
            kind = "Voice note, transcribed"
        elif channel in ("", "direct"):
            kind = "Direct message"
        else:
            kind = f"Chat in {h(channel)}"
        head = f"<b>{sender}</b>"
        main = f'<div class="bubble">{paragraphs(item["body"])}</div>'
    elif source == "capture":
        kind = "Note to self"
        head = f"<b>{sender}</b>"
        main = f'<div class="note">{paragraphs(item["body"])}</div>'
    elif source == "calendar":
        kind = "Calendar invite"
        head = f"From <b>{sender}</b>"
        detail = " ".join(h(heads[k]) for k in ("when", "where") if heads.get(k))
        main = f'{subject}<p class="when">{detail}</p><div class="body">{paragraphs(item["body"])}</div>'
    else:  # transcript
        kind = "Meeting notes"
        head = f"<b>{sender}</b>"
        lines = []
        for line in (item["body"] or "").splitlines():
            speaker, sep, said = line.partition(":")
            if sep and " " not in speaker.strip():
                lines.append(f"<p><b>{h(speaker.strip())}</b> {h(said.strip())}</p>")
            elif line.strip():
                lines.append(f"<p>{h(line)}</p>")
        main = f'{subject}<div class="script">{"".join(lines)}</div>'
    return f"""<article class="item {h(source)}" id="{h(item['id'])}">
  <div class="kind">{kind}</div>
  <header>{head}<time>{h(when)}</time></header>
  {main}
  <footer><a href="/sorted#{h(item['id'])}">How the door sorted it</a></footer>
</article>
"""


def sent_card(item, batch_day, who):
    """Your reply or forward, beneath the item it answered, in the source's own look but
    going the other way."""
    heads = json.loads(item["raw"] or "{}")
    when = f"{clock.as_datetime(item['received_at']):%H:%M}"
    if clock.as_datetime(item["received_at"]).date() != batch_day:
        when = f"{clock.DAYS[clock.as_datetime(item['received_at']).weekday()][:3]} {when}"
    to = who.tag(heads.get("to", ""), item["source"])
    if heads.get("forwarded"):
        kind, head = "Passed on", f"To <b>{to}</b>"
    elif heads.get("fresh"):
        kind, head = "Your email", f"To <b>{to}</b>"
        subject = f"<h3>{h(item['subject'])}</h3>" if item["subject"] else ""
        main = f'{subject}<div class="body">{paragraphs(item["body"])}</div>'
        main = f'<div class="body">{paragraphs(item["body"]) or "<p class=\"empty\">No note.</p>"}</div>'
    elif item["source"] == "chat":
        kind, head = "Your reply", f"To <b>{to}</b>"
        main = f'<div class="bubble">{paragraphs(item["body"])}</div>'
    else:
        kind, head = "Your reply", f"To <b>{to}</b>"
        subject = f"<h3>{h(item['subject'])}</h3>" if item["subject"] else ""
        main = f'{subject}<div class="body">{paragraphs(item["body"])}</div>'
    return f"""<article class="item sent {h(item['source'])}" id="{h(item['id'])}">
  <div class="kind">{kind}</div>
  <header>{head}<time>{h(when)}</time></header>
  {main}
</article>
"""


# The Sorting dashboard: how each item was sorted, and what needs you. Four sections, one card per item,
# each with the reason, the work as the judgement proposed it, and the buttons: a yes, a no
# that needs no words, and a send-back that needs them.

CLASS_LABELS = {
    "memo-to-task": "Your own note", "file-newsletter": "Newsletter",
    "notice-to-task": "A notice with a date", "notice-to-diary": "A notice for the diary",
    "reply-needed": "Wants an answer", "answer-to-a-loop": "Answers something you were promised",
    "family-logistics": "Family logistics", "nothing-to-do": "Nothing to do",
    "promise-made": "A promise made", "meeting-actions": "What the meeting turned up",
    "worth-knowing": "Worth knowing",
}
SECTION_LEAD = {
    "ready": "The work is done. Each card says what a yes would do.",
    "yours": "No good answer without you. Each card is the question.",
    "headsup": "Nothing to do, and still worth knowing.",
    "filed": "Nothing was needed. The reason is kept with it.",
}
SECTION_EMPTY = {
    "ready": "Nothing waits on you.", "yours": "No questions this time.",
    "headsup": "Nothing to flag.", "filed": "Nothing filed.",
}
SOURCE_LABELS = {"email": "Email", "chat": "Message", "capture": "Note to self",
                 "calendar": "Invite", "transcript": "Meeting transcript"}


def checkin(conn, query=None):
    """Sorted: the four piles, with the cards on the left and what stays on the right."""
    from . import OUTCOMES
    running = running_line(conn)
    refresh = 5 if running else None
    waiting = conn.execute("SELECT COUNT(*) FROM items WHERE status = 'staged'").fetchone()[0]
    rows = conn.execute(
        "SELECT p.*, i.source, i.sender, i.subject, i.received_at, i.staged_at, r.action AS rule_words, "
        "s.disposition AS sender_disposition "
        "FROM proposals p JOIN items i ON i.id = p.item_id "
        "LEFT JOIN handling_rules r ON r.id = p.rule_id "
        "LEFT JOIN source_senders s ON s.source = i.source AND s.sender = i.sender "
        "WHERE p.status = 'pending' ORDER BY i.staged_at DESC, i.received_at, i.id").fetchall()
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM people")}
    calendars = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM calendars")}
    lookup = Lookup(conn, names, calendars)
    lookup.who = Who(conn)
    you = db.get_state(conn, "you", "")
    headsups = [r for r in rows if r["outcome"] == "headsup"]
    aside = ((headsup_list(headsups, lookup, you) if headsups else "")
             + promises_panel(conn, lookup.who) + questions_panel(conn, lookup.who) + note_box()
             + recent_panel(conn) + rules_line(conn))
    if not rows:
        empty = (empty_section(f"{waiting} items are at the door.",
                               "They have not been sorted yet. The Doorstep is where to sort them.")
                 if waiting else
                 empty_section("Nothing sorted yet.",
                               "When the first batch comes to the door, how each thing was sorted and what "
                               "needs you will show here."))
        return layout(conn, "Sorting dashboard", "sorted", running
                      + f'<div class="sorted-grid"><div class="main">{empty}</div><aside>{aside}</aside></div>', refresh)
    sections = []
    for outcome, title in OUTCOMES.items():
        mine = [r for r in rows if r["outcome"] == outcome]
        if mine and outcome == "filed":
            sections.append(filed_list(mine, lookup))
        elif outcome == "headsup":
            continue   # in the right-hand column
        elif mine and outcome == "ready":
            sections.append(f'<section class="outcome ready">\n<h2>{h(title)}<span>{len(mine)}</span></h2>\n'
                            f'{grouped_cards(mine, lookup, you)}\n</section>')
        elif mine:
            cards = "".join(proposal_card(r, lookup, you) for r in mine)
            sections.append(f'<section class="outcome {h(outcome)}">\n<h2>{h(title)}<span>{len(mine)}</span></h2>\n'
                            f'<div class="cards">{cards}</div>\n</section>')
        elif outcome in ("ready", "yours"):
            sections.append(f'<section class="outcome {h(outcome)}">\n<h2>{h(title)}</h2>\n'
                            f'<p class="empty">{h(SECTION_EMPTY[outcome])}</p>\n</section>')
    note = ""
    if waiting and not running:
        note = (f'<p class="door-note">{waiting} more things are at the door, not sorted yet. '
                f'<a href="/doorstep">The Doorstep</a> is where to sort them.</p>\n')
    main = note + "\n".join(sections) + next_run_panel(conn)
    return layout(conn, "Sorting dashboard", "sorted", running
                  + f'<div class="sorted-grid"><div class="main">{main}</div><aside>{aside}</aside></div>', refresh)


DOMAIN_TITLES = [("work", "Work"), ("family", "Home"), ("personal", "Personal")]


def card_domain(p, lookup, work):
    """Which part of life a card belongs to: the person who wrote it, else the work it
    proposes, else personal."""
    pid = lookup.who.ties.get((p["source"], p["sender"]))
    if pid is None:
        ids = lookup.who.by_name.get((p["sender"] or "").lower(), [])
        pid = ids[0] if len(ids) == 1 else None
    if pid in lookup.who.people:
        return lookup.who.people[pid].get("domain") or "personal"
    for w in work:
        d = w.get("domain") or w.get("calendar")
        if d in ("work", "family", "personal"):
            return d
        if w.get("target", "").startswith("task:") or w.get("target", "").startswith("event:"):
            kind, _, ident = w["target"].partition(":")
            row = lookup.conn.execute(
                f"SELECT {'domain' if kind == 'task' else 'calendar_id'} AS d FROM {'tasks' if kind == 'task' else 'events'} WHERE id = ?",
                (ident,)).fetchone()
            if row:
                return row["d"]
    return "personal"


def grouped_cards(mine, lookup, you):
    """The ready cards under Work, Home and Personal, each heading with its calendar's colour."""
    colours = {r["id"]: r["colour"] for r in lookup.conn.execute("SELECT id, colour FROM calendars")}
    groups = {k: [] for k, _ in DOMAIN_TITLES}
    for p in mine:
        groups.setdefault(card_domain(p, lookup, json.loads(p["work"] or "[]")), groups["personal"]).append(p)
    out = []
    for key, title in DOMAIN_TITLES:
        if not groups[key]:
            continue
        cards = "".join(proposal_card(r, lookup, you) for r in groups[key])
        out.append(f'<h3 class="life"><i class="dot" style="--cal:{h(colours.get(key, "#999"))}"></i>{h(title)}</h3>'
                   f'<div class="cards">{cards}</div>')
    return "".join(out)


def headsup_list(mine, lookup, you):
    """Heads-up as a list: one line each, Got it on the line, Got them all for the lot. The line
    opens to the rule that shaped it, the send-back box and From now on."""
    lines = []
    for p in mine:
        subject = f": {h(p['subject'])}" if p["subject"] else ""
        pid = h(p["id"])
        hidden = f'<input type="hidden" name="id" value="{pid}">'
        lines.append(
            f'<li id="{h(p["item_id"])}"><details><summary><span><a href="/doorstep#{h(p["item_id"])}">'
            f'<b>{lookup.who.tag(p["sender"], p["source"])}</b>{subject}</a> <small>{h(p["reason"])}</small></span>'
            f'</summary>{shaped_by(p)}<div class="acts">'
            f'<form method="post" action="/card/send-back" class="words-form">{hidden}'
            f'<input name="words" required placeholder="Wants more than knowing? Say what" aria-label="what to change">'
            f'<button class="quiet">Send back</button></form>{from_now_on_menu(p, hidden, you)}</div></details>'
            f'<form method="post" action="/card/done">{hidden}<button class="quiet">Got it</button></form></li>')
    group = ('<form method="post" action="/card/done-all" class="group"><button>Got them all</button></form>'
             if len(mine) > 1 else "")
    return (f'<section class="outcome headsup"><h2>Heads-up<span>{len(mine)}</span></h2>{group}'
            f'<ul class="filed-lines headsup-lines">{"".join(lines)}</ul></section>')


def status_line(conn):
    """One quiet line: what you just did. The round's summary was here too and went, 2026-10-01,
    since it added little; since_last_time stays for the tests and anyone who wants it back."""
    last = last_thing(conn)
    return f'<div class="status">{last}</div>\n' if last else ""


def recent_panel(conn):
    """Your last few presses, folded away: there for a glance, not in the way."""
    you = (db.get_state(conn, "you", "") or "").lower()
    rows = conn.execute("SELECT at, detail FROM actions WHERE actor = ? AND detail IS NOT NULL "
                        "ORDER BY id DESC LIMIT 8", (you,)).fetchall()
    if not rows:
        return ""
    lines = "".join(f'<li><time>{h(when_label(r["at"]))}</time><span>{h(r["detail"])}</span></li>' for r in rows)
    return (f'<details class="outcome recent"><summary><h2>What you did<span>{len(rows)}</span></h2></summary>'
            f'<ul class="recent-lines">{lines}</ul></details>')


def rules_line(conn):
    n = conn.execute("SELECT COUNT(*) FROM handling_rules WHERE status = 'active'").fetchone()[0]
    skips = conn.execute("SELECT COUNT(*) FROM source_senders WHERE disposition = 'skip'").fetchone()[0]
    total = n + skips
    what = f"{total} house rule{'s' if total != 1 else ''}" if total else "No house rules yet"
    return (f'<div class="rules-line"><p>{h(what)}.</p>'
            f'<a href="/log" class="to-log">Open the log</a></div>')


def filed_list(mine, lookup):
    """Filed away as a folded list: one line per item, a File it on each, and one press for
    the lot. Nothing to read unless you open it."""
    lines = []
    for p in mine:
        subject = f": {h(p['subject'])}" if p["subject"] else ""
        lines.append(
            f'<li id="{h(p["item_id"])}"><span><a href="/doorstep#{h(p["item_id"])}">'
            f'<b>{lookup.who.tag(p["sender"], p["source"])}</b>{subject}</a> <small>{h(p["reason"])}</small></span>'
            f'<form method="post" action="/card/approve"><input type="hidden" name="id" value="{h(p["id"])}">'
            f'<button class="quiet">File it</button></form></li>')
    return (f'<details class="outcome filed"><summary><h2>Filed away<span>{len(mine)}</span></h2></summary>\n'
            f'<form method="post" action="/card/file-all" class="group"><button>File all {len(mine)} away</button></form>'
            f'<ul class="filed-lines">{"".join(lines)}</ul></details>')


def running_line(conn):
    """The line that says a run is in flight, so a page that is about to change says so, or
    that the last run failed, so the page does not go quiet with the door unjudged."""
    from . import agents
    waiting = conn.execute("SELECT COUNT(*) FROM items WHERE status = 'staged'").fetchone()[0]
    if not lock.held(conn):
        last = agents.last_run(conn)
        if last and last.get("ok") is False and waiting:
            return (f'<p class="running failed">{h(last["message"])} {waiting} things at the door, not sorted. '
                    f'Try again from <a href="/doorstep">the Doorstep</a>.</p>\n')
        return ""
    what = f"{waiting} items at the door" if waiting else "what you sent back or answered"
    doing = (agents.last_run(conn) or {}).get("message") or f"sorting {what}"
    return (f'<p class="running"><span class="pulse"></span>{h(doing[:1].upper() + doing[1:])}. '
            f'A minute or two; the page updates itself when it\'s done.</p>\n')


# The log: every press and every effect, and the house rules above them.

ACTORS = {"engine": "the door", "rule": "a house rule"}
ACTIONS = {
    "approve": "said yes", "accept": "accepted", "decline": "declined", "send-back": "sent back",
    "done": "done", "ignore": "ignored", "answer": "answered", "choose": "picked", "tick": "ticked",
    "untick": "unticked", "note": "left a note", "rule": "made a rule", "unrule": "removed a rule",
    "promise-resolved": "resolved a promise",
    "task": "added a task", "event": "added to the diary", "send": "sent", "forward": "passed on",
    "update": "changed", "commitment": "noted a promise", "person": "noted about a person",
    "file": "filed", "intake": "brought in", "process": "sorted", "reset": "started the week again",
}
KINDS_OF_ROW = {
    "presses": ("What you pressed", None),
    "effects": ("What the door did for you", ("task", "event", "send", "forward", "update", "commitment",
                                              "person", "file", "rule")),
    "runs": ("Runs", ("intake", "process", "reset")),
}


def log(conn, query=None):
    """The audit trail as a page: the house rules, then every row of the actions log, newest
    first, in plain words, filtered by what kind of row it is."""
    show = (query or {}).get("show", ["all"])[0]
    you = (db.get_state(conn, "you", "") or "").lower()
    rows = conn.execute("SELECT * FROM actions ORDER BY id DESC").fetchall()
    if show == "presses":
        rows = [r for r in rows if r["actor"] == you]
    elif show in KINDS_OF_ROW and KINDS_OF_ROW[show][1]:
        rows = [r for r in rows if r["action"] in KINDS_OF_ROW[show][1]]
    links = "".join(
        f'<a href="/log?show={k}"{" class=\"current\"" if show == k else ""}>{h(t)}</a>'
        for k, t in [("all", "Everything")] + [(k, v[0]) for k, v in KINDS_OF_ROW.items()])
    lines = "".join(log_line(r, you) for r in rows) or '<li class="empty">Nothing yet.</li>'
    body = (f'{rules_panel(conn)}\n<section class="outcome log"><h2>The log<span>{len(rows)}</span></h2>'
            f'<nav class="filters">{links}</nav><ul class="log-lines">{lines}</ul></section>')
    return layout(conn, "Log", "log", body)


def log_line(r, you):
    who = "you" if r["actor"] == you else ACTORS.get(r["actor"], r["actor"])
    what = ACTIONS.get(r["action"], r["action"])
    at = clock.as_datetime(r["at"])
    when = f"{clock.DAYS[at.weekday()][:3]} {at:%H:%M}"
    detail = r["detail"] or ""
    if detail.startswith("{"):
        try:
            d = json.loads(detail)
            detail = d.get("title") or d.get("what") or d.get("label") or d.get("body") or d.get("subject") or ""
            if not detail and "changes" in d:
                detail = ", ".join(f"{k} to {v}" for k, v in d["changes"].items() if k not in ("closed_by", "closed_on", "done_at"))
            if not detail and r["action"] == "process":
                names = {"ready": "ready for you", "yours": "for your input", "headsup": "heads-up", "filed": "filed away"}
                detail = ", ".join(f"{v} {names.get(k, k)}" for k, v in d.items() if v)
            if not detail and r["action"] == "intake":
                detail = f"{d.get('staged', 0)} items"
        except ValueError:
            pass
    target = f' <small>{h(r["target"])}</small>' if r["target"] and r["actor"] != you else ""
    undo = "" if r["reversible"] else ' <small class="fixed">cannot be undone</small>'
    return (f'<li><time>{h(when)}</time><span><b>{h(who)}</b> {h(what)}{target}'
            f'{(": " + h(detail)) if detail else ""}{undo}</span></li>')


def rules_panel(conn):
    """Every house rule in plain words, how often it fired, and a way to remove it. Senders
    never read again are rules too, so they show here with a way back."""
    active = conn.execute("SELECT * FROM handling_rules WHERE status = 'active' ORDER BY taught_on, id").fetchall()
    skipped = conn.execute("SELECT * FROM source_senders WHERE disposition = 'skip' ORDER BY taught_on, sender").fetchall()
    lines = []
    for r in active:
        fired = {0: "never fired yet", 1: "fired once"}.get(r["fired"], f"fired {r['fired']} times")
        last = f", last {when_label(r['last_applied'])}" if r["last_applied"] else ""
        lines.append(f'<li><span>{h(r["action"])} <small>{h(fired)}{h(last)}, taught {when_label(r["taught_on"])}</small></span>'
                     f'<form method="post" action="/rule/retire"><input type="hidden" name="id" value="{h(r["id"])}">'
                     f'<button class="quiet">Remove</button></form></li>')
    for s in skipped:
        lines.append(f'<li><span>Never read {h(s["sender"])} again <small>{h(s["source"])}, not fetched at all'
                     f'{", taught " + when_label(s["taught_on"]) if s["taught_on"] else ""}</small></span>'
                     f'<form method="post" action="/rule/read-again"><input type="hidden" name="source" value="{h(s["source"])}">'
                     f'<input type="hidden" name="sender" value="{h(s["sender"])}"><button class="quiet">Read again</button></form></li>')
    body = (f'<ul class="rules">{"".join(lines)}</ul>' if lines else
            '<p class="empty">None yet. From now on, on any card, makes one.</p>')
    return (f'\n<section class="outcome house-rules"><h2>House rules{"<span>" + str(len(lines)) + "</span>" if lines else ""}</h2>'
            f'<p class="lead">What you told the door to do from now on.</p>{body}</section>')


def note_box():
    """A new thought. It goes to the door as a note to self and the next run judges it, so
    what you meant to do about something survives filing it away."""
    return ('\n<section class="note-box"><h2>A note for the door</h2>'
            '<p class="lead">A new thought. It lands on the Doorstep and is sorted on the next run.</p>'
            '<form method="post" action="/note" class="words-form">'
            '<input name="text" required placeholder="Book the dentist, or: from now on, file the Daily Digest" '
            'aria-label="a note for the door"><button>Leave it at the door</button></form></section>')


def since_last_time(conn):
    """What the last run did, in a few sentences composed from the log: what came in, how it
    was sorted, who from the cast answered, which rules fired. Nothing here is written by a
    model; every number is a row the engine wrote."""
    intake_row = conn.execute(
        "SELECT at, detail FROM actions WHERE action = 'intake' ORDER BY id DESC LIMIT 1").fetchone()
    if intake_row is None:
        return ""
    at = intake_row["at"]
    came = json.loads(intake_row["detail"] or "{}")
    label = came.get("label") or "The last batch"
    parts = [f"{h(label)} brought {came.get('staged', 0)} items in"
             + (f", and {came['skipped']} more were not read, as you asked" if came.get("skipped") else "") + "."]
    sorted_ = {"ready": 0, "yours": 0, "headsup": 0, "filed": 0}
    judged = 0
    for r in conn.execute("SELECT detail FROM actions WHERE action = 'process' AND at = ?", (at,)):
        counts = json.loads(r["detail"] or "{}")
        for k in sorted_:
            sorted_[k] += counts.get(k, 0)
        judged += sum(counts.get(k, 0) for k in sorted_)
    if judged:
        bits = [f"{sorted_['ready']} ready for you", f"{sorted_['yours']} for your input",
                f"{sorted_['headsup']} heads-up", f"{sorted_['filed']} filed away"]
        parts.append(", ".join(b for b in bits if not b.startswith("0 ")) + ".")
    else:
        parts.append("Not sorted yet.")
    cast = [r["sender"] for r in conn.execute(
        "SELECT DISTINCT sender FROM items WHERE staged_at = ? AND raw LIKE '%\"cast\": true%' ORDER BY sender", (at,))]
    if cast:
        parts.append((" and ".join(cast) if len(cast) < 3 else ", ".join(cast[:-1]) + " and " + cast[-1])
                     + (" answered you." if len(cast) > 1 else " answered you."))
    fired = conn.execute(
        "SELECT COUNT(*) FROM decision_log WHERE actor = 'process' AND at = ? AND reason LIKE 'house rule %'", (at,)).fetchone()[0]
    if fired:
        parts.append(f"A house rule shaped {fired} of them." if fired > 1 else "A house rule shaped one of them.")
    return f'<p class="since"><b>Since last time.</b> {" ".join(parts)}</p>\n'


def last_thing(conn):
    """The last press, in the sentence the engine logged for it, so a page that has just
    changed says what changed."""
    you = (db.get_state(conn, "you", "") or "").lower()
    row = conn.execute("SELECT detail FROM actions WHERE actor = ? ORDER BY id DESC LIMIT 1", (you,)).fetchone()
    return f'<p class="last-thing">{h(row["detail"])}</p>\n' if row and row["detail"] else ""


def promises_panel(conn, who):
    """Every promise still open, yours and theirs, with when it is due. The door matches what
    arrives against these and closes them on a card."""
    rows = conn.execute(
        "SELECT * FROM commitments WHERE status = 'open' ORDER BY due IS NULL, due, id").fetchall()
    if not rows:
        return ""
    lines = []
    for c in rows:
        name = who.by_id(c["person_id"]) if c["person_id"] else "someone"
        due = f"<small>by {h(when_label(c['due']))}</small>" if c["due"] else "<small>no date given</small>"
        head = f"You promised {name}" if c["owner"] == "me" else f"{name} promised you"
        hidden = f'<input type="hidden" name="id" value="{h(c["id"])}">'
        acts = (f'<span class="acts"><form method="post" action="/promise/close">{hidden}'
                f'<input type="hidden" name="how" value="resolved"><button class="quiet">Resolved</button></form></span>')
        lines.append(f'<li class="promise"><span>{head}: {h(c["what"])}</span>{due}{acts}</li>')
    return (f'\n<section class="outcome promises"><h2>Promises<span>{len(rows)}</span></h2>'
            f'<ul class="lines">{"".join(lines)}</ul></section>')


def questions_panel(conn, who):
    """Every question still open. One with a card points at it; one without, such as a question
    the week began with, takes its answer here."""
    rows = conn.execute("SELECT * FROM questions WHERE status = 'open' ORDER BY asked_on, id").fetchall()
    if not rows:
        return ""
    lines = []
    for q in rows:
        if q["item_id"]:
            lines.append(f'<li><span>{h(q["question"])}</span><small><a href="#{h(q["item_id"])}">its card</a></small></li>')
        else:
            lines.append(
                f'<li class="ask"><span>{h(q["question"])}</span>'
                f'<form method="post" action="/question/answer" class="words-form">'
                f'<input type="hidden" name="id" value="{h(q["id"])}">'
                f'<input name="answer" required placeholder="Your answer" aria-label="your answer">'
                f'<button>Answer</button></form></li>')
    return (f'\n<section class="outcome questions"><h2>Questions waiting<span>{len(rows)}</span></h2>'
            f'<ul class="lines">{"".join(lines)}</ul></section>')


def next_run_panel(conn):
    """What waits for the next run: cards sent back with words, and questions answered, so
    nothing you said can vanish before it is folded in."""
    rows = conn.execute(
        "SELECT p.*, i.source, i.sender, i.subject, q.question, q.answer "
        "FROM proposals p JOIN items i ON i.id = p.item_id LEFT JOIN questions q ON q.id = p.question_id "
        "WHERE p.status IN ('sent_back', 'answered') ORDER BY p.decided_at, p.id").fetchall()
    if not rows:
        return ""
    who = Who(conn)
    cards = []
    for p in rows:
        source = SOURCE_LABELS.get(p["source"], p["source"])
        subject = f": {h(p['subject'])}" if p["subject"] else ""
        if p["status"] == "answered":
            was, words = p["question"], p["answer"]
        else:
            was, words = p["reason"], p["sent_back"]
        cards.append(
            f'<article class="card {h(p["status"]).replace("_", "-")}" id="{h(p["item_id"])}">\n'
            f'  <a class="origin" href="/doorstep#{h(p["item_id"])}">{h(source)} from <b>{who.tag(p["sender"], p["source"])}</b>{subject}</a>\n'
            f'  <p class="reason was">{h(was)}</p>\n'
            f'  <blockquote class="words">{paragraphs(words)}</blockquote>\n</article>\n')
    return (f'\n<section class="outcome next-run">\n<h2>For the next run<span>{len(rows)}</span></h2>\n'
            f'<p class="lead">Sorted again on the next run.</p>\n'
            f'<div class="cards">{"".join(cards)}</div>\n</section>')


class Lookup:
    """Names for the ids the work refers to, so a card can say 'the swimming entry' rather
    than event:swimming."""

    def __init__(self, conn, names, calendars):
        self.conn, self.names, self.calendars = conn, names, calendars

    def person(self, pid):
        return self.names.get(pid, pid)

    def target(self, ref):
        kind, _, tid = (ref or "").partition(":")
        table = {"task": "tasks", "event": "events", "commitment": "commitments", "question": "questions"}.get(kind)
        if not table:
            return kind, ref
        col = {"commitments": "what", "questions": "question"}.get(table, "title")
        row = self.conn.execute(f"SELECT {col} AS t FROM {table} WHERE id = ?", (tid,)).fetchone()
        return kind, (row["t"] if row else tid)


def proposal_card(p, lookup, you=""):
    work = json.loads(p["work"] or "[]")
    source = SOURCE_LABELS.get(p["source"], p["source"])
    subject = f": {h(p['subject'])}" if p["subject"] else ""
    origin = (f'<a class="origin" href="/doorstep#{h(p["item_id"])}">{h(source)} from '
              f'<b>{lookup.who.tag(p["sender"], p["source"])}</b>{subject}</a>')
    lines = [work_line(w, lookup) for w in work]
    if lines and p["outcome"] == "yours" and work[0]["kind"] == "choose":
        lines = [f"<li>{h(work[0].get('summary'))}</li>"]   # the picks are the tick boxes below
    if lines:
        heading = ("The question" if p["outcome"] == "yours" else
                   "What accepting does" if p["source"] == "calendar" else "What a yes does")
        did = f'<div class="work"><h4>{heading}</h4><ul>{"".join(lines)}</ul></div>'
    else:
        did = ""
    return f"""<article class="card {h(p['outcome'])}" id="{h(p['item_id'])}">
  {origin}
  <p class="reason">{h(p['reason'])}</p>
  {shaped_by(p)}
  {did}
  {buttons(p, work, you)}
</article>
"""


def shaped_by(p):
    """The line that names the rule that shaped the card, or the sender never read again."""
    if p["rule_words"]:
        return f'<p class="shaped">House rule: {h(p["rule_words"])}.</p>'
    if p["sender_disposition"] == "skip":
        return f'<p class="shaped">From now on, mail from {h(p["sender"])} is not read at all.</p>'
    return ""


def buttons(p, work, you=""):
    """What a person can do with the card. Ready takes a yes, a no, or words to judge it again
    by. Filed takes the yes that files the original. A heads-up is taken as read. A yours card
    takes the answer, or the picks, and two closes: done, you handled it, and ignore. A
    heads-up can be sent back too, for when it wants more than knowing."""
    pid = h(p["id"])
    hidden = f'<input type="hidden" name="id" value="{pid}">'
    menu = from_now_on_menu(p, hidden, you)
    if p["outcome"] == "yours":
        closes = (f'<form method="post" action="/card/done">{hidden}<button class="quiet">Done, I handled it</button></form>'
                  f'<form method="post" action="/card/ignore">{hidden}<button class="quiet">Ignore</button></form>')
        if work and work[0]["kind"] == "choose":
            boxes = "".join(
                f'<label><input type="checkbox" name="pick" value="{n}"> {h(c["what"])} '
                f'<small>{"yours to do" if c["owner"] == "me" else "promised to you"}</small></label>'
                for n, c in enumerate(work[0]["candidates"]))
            return (f'<footer class="acts"><form method="post" action="/card/choose" class="picks">{hidden}'
                    f'<div class="boxes">{boxes}</div><button>Take these</button></form>{closes}{menu}</footer>')
        return (f'<footer class="acts"><form method="post" action="/card/answer" class="words-form">{hidden}'
                f'<input name="answer" required placeholder="Your answer" aria-label="your answer">'
                f'<button>Answer</button></form>{closes}{menu}</footer>')
    if p["outcome"] == "ready":
        invite = p["source"] == "calendar"
        return (f'<footer class="acts">'
                f'<form method="post" action="/card/approve">{hidden}<button>{"Accept" if invite else "Approve"}</button></form>'
                f'<form method="post" action="/card/decline">{hidden}<button class="quiet">Decline</button></form>'
                f'<form method="post" action="/card/send-back" class="words-form">{hidden}'
                f'<input name="words" required placeholder="Not as it is? Say what to change" '
                f'aria-label="what to change"><button class="quiet">Send back</button></form>'
                f'{menu}</footer>')
    if p["outcome"] == "filed":
        return (f'<footer class="acts"><form method="post" action="/card/approve">{hidden}'
                f'<button class="quiet">File it away</button></form>{menu}</footer>')
    if p["outcome"] == "headsup":
        return (f'<footer class="acts"><form method="post" action="/card/done">{hidden}'
                f'<button class="quiet">Got it</button></form>'
                f'<form method="post" action="/card/send-back" class="words-form">{hidden}'
                f'<input name="words" required placeholder="Wants more than knowing? Say what" '
                f'aria-label="what to change"><button class="quiet">Send back</button></form>{menu}</footer>')
    return ""


def from_now_on_menu(p, hidden, you=""):
    """The choices that make sense for this item's sender. Your own notes have none. A sender
    already never read again has none either, since the card says so."""
    if not p["sender"] or p["sender"] == you or p["source"] == "capture" or p["sender_disposition"] == "skip":
        return ""
    from .decide import CHOICES
    buttons = "".join(
        f'<form method="post" action="/rule/from-now-on">{hidden}<input type="hidden" name="choice" value="{h(key)}">'
        f'<button class="quiet">{h(words.format(sender=p["sender"]))}</button></form>'
        for key, (_, words) in CHOICES.items())
    return f'<details class="from-now-on"><summary>From now on</summary><div class="choices">{buttons}</div></details>'


def when_label(text):
    """'Wednesday 14:30' for a datetime, 'Wednesday' for a date, as the card reads it."""
    if not text:
        return ""
    if "T" in text:
        dt = clock.as_datetime(text)
        return f"{clock.day_name(dt)} {dt:%H:%M}"
    return clock.day_name(clock.as_date(text))


def work_line(w, lookup):
    kind = w.get("kind")
    if kind == "task":
        due = f", due {when_label(w['due'])}" if w.get("due") else ""
        high = ", high priority" if w.get("priority") == 1 else ""
        notes = f'<small>{h(w["notes"])}</small>' if w.get("notes") else ""
        return f"<li>Add a task in {h(w.get('domain'))}: <b>{h(w['title'])}</b>{h(due)}{high}{notes}</li>"
    if kind == "event":
        start = when_label(w.get("start"))
        end = w.get("end")
        till = f" to {clock.as_datetime(end):%H:%M}" if end and "T" in end else ""
        if not end and w.get("minutes"):
            till = f", {w['minutes']} minutes"
        notes = f'<small>{h(w["notes"])}</small>' if w.get("notes") else ""
        return (f"<li>Put in the {h(lookup.calendars.get(w.get('calendar'), w.get('calendar')))} "
                f"diary: <b>{h(w['title'])}</b>, {h(start)}{h(till)}{notes}</li>")
    if kind == "reply":
        by = f" by {when_label(w['by'])}" if w.get("by") else ""
        return f'<li>Send this reply{h(by)}:<blockquote>{paragraphs(w.get("body"))}</blockquote></li>'
    if kind == "rule":
        where = {"skip": f"never read at all, from {h(w.get('source'))} intake on",
                 "filed": "read, and filed without asking", "headsup": "read, and shown as a heads-up only",
                 "ready": "read, and always made into work", "yours": "read, and always brought to you",
                 "auto": "read, sorted, and if it is ready, done on its own, without a yes"
                 }.get(w.get("outcome"), h(w.get("outcome")))
        return (f"<li>From now on, <b>{h(w.get('action'))}</b><small>A rule on the {h(w.get('scope'))} "
                f"<b>{h(w.get('pattern'))}</b>: {where}.</small></li>")
    if kind == "email":
        return (f'<li>Send an email to <b>{lookup.who.by_id(w.get("to"))}</b>, <b>{h(w.get("subject"))}</b>:'
                f'<blockquote>{paragraphs(w.get("body"))}</blockquote></li>')
    if kind == "forward":
        note = f'<small>{h(w["note"])}</small>' if w.get("note") else ""
        return f"<li>Pass it on to <b>{lookup.who.by_id(w.get('to'))}</b>{note}</li>"
    if kind == "update":
        tkind, title = lookup.target(w.get("target"))
        changes = w.get("changes") or {}
        if tkind == "commitment" and changes.get("status") == "closed":
            return f"<li>Promise kept, so it comes off the list: <b>{h(title)}</b></li>"
        if tkind == "question" and changes.get("status") == "closed":
            return f"<li>Close the question, settled by this: <b>{h(title)}</b></li>"
        parts = []
        for field, value in changes.items():
            shown = when_label(value) if field in ("due", "start", "end") and value else value
            parts.append(f"{h(field)} to {h(shown)}")
        return f"<li>Change the {h(tkind)} <b>{h(title)}</b>: {'; '.join(parts)}</li>"
    if kind == "commitment":
        who = lookup.who.by_id(w.get("person"))
        due = f", by {when_label(w['due'])}" if w.get("due") else ""
        if w.get("owner") == "me":
            return f"<li>Remember you promised <b>{who}</b>: {h(w['what'])}{h(due)}</li>"
        return f"<li>Remember <b>{who}</b> promised you: {h(w['what'])}{h(due)}</li>"
    if kind == "person":
        facts = ", ".join(f"{k} {v}" for k, v in w.items() if k not in ("kind", "id", "name") and v)
        named = h(w["name"]) if w.get("name") else lookup.who.by_id(w.get("id"))
        return f"<li>Note about <b>{named}</b>: {h(facts)}</li>"
    if kind == "question":
        return f'<li class="question">{h(w.get("question"))}</li>'
    if kind == "choose":
        opts = "".join(
            f"<li>{h(c.get('what'))} <small>{'yours to do' if c.get('owner') == 'me' else 'promised by ' + lookup.who.by_id(c.get('person'))}"
            f"{', by ' + when_label(c['due']) if c.get('due') else ''}</small></li>"
            for c in w.get("candidates") or [])
        return f'<li>{h(w.get("summary"))}<ul class="candidates">{opts}</ul></li>'
    return f"<li>{h(json.dumps(w))}</li>"


# Planner: the to-do list next to the week across the three calendars.

def planner(conn, query=None):
    now = clock.as_datetime(db.get_state(conn, "clock"))
    today = now.date()
    start = clock.as_date(db.get_state(conn, "week_start"))
    calendars = {c["id"]: c for c in conn.execute("SELECT * FROM calendars")}
    tasks = conn.execute(
        "SELECT * FROM tasks WHERE status = 'open' OR done_at >= ? "
        "ORDER BY status = 'done', due IS NULL, due, priority, title", (start.isoformat(),)
    ).fetchall()   # ticked this week stays on the list, ticked, so it can be unticked
    events = conn.execute("SELECT * FROM events ORDER BY start").fetchall()
    # where a task or an entry came from: the item that made it, so the line can say so
    who = Who(conn)
    origins = {}
    for r in conn.execute("SELECT id, sender, source FROM items"):
        origins[r["id"]] = f'<a class="origin" href="/doorstep#{h(r["id"])}">from {who.tag(r["sender"], r["source"])}</a>'
    body = f"""<section class="planner">
  <div class="todo">
    <h2>To do</h2>
    {todo_list(tasks, calendars, today, start, origins)}
  </div>
  <div class="week">
    <h2>This week</h2>
    {legend(calendars)}
    {week_grid(events, calendars, start, today, origins)}
  </div>
</section>"""
    return layout(conn, "Planning dashboard", "planner", body)


def todo_list(tasks, calendars, today, start, origins=None):
    if not tasks:
        return '<p class="empty">Nothing to do. Enjoy it.</p>'
    week_end = start + timedelta(days=6)
    groups = {name: [] for name in GROUPS}
    for t in tasks:
        if not t["due"]:
            groups["No date"].append(t)
            continue
        due = clock.as_date(t["due"])
        if due < today:
            groups["Overdue"].append(t)
        elif due == today:
            groups["Today"].append(t)
        elif due <= week_end:
            groups["This week"].append(t)
        else:
            groups["Later"].append(t)
    parts = []
    for name in GROUPS:
        if groups[name]:
            lines = "".join(task_line(t, calendars, today, origins or {}) for t in groups[name])
            parts.append(f'<h3>{name}</h3>\n<ul class="tasks">{lines}</ul>')
    return "\n".join(parts)


def task_line(t, calendars, today, origins=None):
    colour = calendars[t["domain"]]["colour"] if t["domain"] in calendars else "#999"
    due = due_label(clock.as_date(t["due"]), today) if t["due"] else ""
    flag = ' <em class="high">high</em>' if t["priority"] == 1 else ""
    done = t["status"] == "done"
    box = (f'<form method="post" action="/task/{"untick" if done else "tick"}">'
           f'<input type="hidden" name="id" value="{h(t["id"])}">'
           f'<input type="checkbox"{" checked" if done else ""} aria-label="done" '
           f'onchange="this.form.submit()"></form>')
    origin = (origins or {}).get(t["source"], "")
    return (
        f'<li class="task{" done" if done else ""}">{box}'
        f'<span class="title">{h(t["title"])}{flag}</span>'
        f'<span class="meta"><i class="dot" style="--cal:{h(colour)}"></i>{h(due)}{origin}</span></li>'
    )


def due_label(due, today):
    gap = (due - today).days
    if gap < 0:
        return f"was due {clock.short_date(due)}"
    if gap == 0:
        return "today"
    if gap < 7:
        return clock.day_name(due)
    return clock.short_date(due)


def legend(calendars):
    chips = []
    for c in calendars.values():
        note = f" <small>{h(c['note'])}</small>" if c["note"] else ""
        chips.append(f'<span class="chip" style="--cal:{h(c["colour"])}"><i class="dot"></i>{h(c["name"])}{note}</span>')
    return f'<div class="legend">{"".join(chips)}</div>'


def week_grid(events, calendars, start, today, origins=None):
    columns = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        todays = [e for e in events if clock.as_date(e["start"]) == day]
        rows = "".join(event_line(e, calendars, origins or {}) for e in todays) or '<li class="free">free</li>'
        marker = " today" if day == today else ""
        columns.append(
            f'<div class="day{marker}"><h3>{clock.DAYS[offset][:3]} <span>{day.day}</span></h3>'
            f"<ul>{rows}</ul></div>"
        )
    return f'<div class="days">{"".join(columns)}</div>'


def event_line(e, calendars, origins=None):
    colour = calendars[e["calendar_id"]]["colour"]
    start = clock.as_datetime(e["start"])
    notes = f"<small>{h(e['notes'])}</small>" if e["notes"] else ""
    origin = (origins or {}).get(e["source"], "")
    return (
        f'<li class="event" style="--cal:{h(colour)}"><time>{start:%H:%M}</time>'
        f"<span>{h(e['title'])}{notes}{origin}</span></li>"
    )


# The front door: a room you step into. The metaphor is drawn, not explained: a door, a coat
# rack with four hooks for the four piles, boots on the mat. The copy welcomes you in.

HOOKS = [
    ("ready", "Ready for you", "Done for you. One click and it goes."),
    ("yours", "Needs your input", "A decision only you can make, so it asks you."),
    ("headsup", "Heads-up", "Nothing to do, but you'd want to know."),
    ("filed", "Filed away", "Nothing to do and nothing to know. Out of your way."),
]
PROMISES = [
    ("Nothing leaves without your yes.", "Every reply, every diary entry, every time."),
    ("It only proposes.", "A small engine you can read in an afternoon does the writing."),
    ("You can see everything it did.", "The log is a page, not a file: every press and every effect, in order."),
]


def welcome(conn, query=None):
    """The page at /: the room, the four hooks, and two doors: play the invented week, or
    hang your own coats here."""
    hooks = "".join(
        f'<li class="hook {k}"><span class="peg"></span><b>{h(t)}</b><small>{h(d)}</small></li>'
        for k, t, d in HOOKS)
    body = f"""<section class="welcome">
  <div class="porch">
    <div class="words">
      <h1>Boots off. Coats on the hook.<br>Your day stays clean.</h1>
      <p>A mudroom is the little room at the door where the mess stops, so the house stays
      tidy. The Mudroom does that for everything that comes at you: mail, messages, notes,
      invitations. Each one waits at the door until it has been looked at and hung on one of
      four hooks. Nothing gets into the house without your yes.</p>
    </div>
    {mudroom_drawing()}
  </div>
  <ul class="hooks">{hooks}</ul>
  <div class="doors">
    {demo_door(conn)}
    <div class="door">
      <h2>Set up your own</h2>
      <p>Ready to use it for real? Connect your own mail, chat and calendar and let it sort your
      mornings. It only ever sends, books or files when you say yes, and it learns your rules as
      you go: "file these without asking", "just show me those". After a while, you can let it do
      more on its own.</p>
      <p>Nothing to install beyond what you already have: it runs on your own computer, with the
      Claude you already use, and it never keeps a password.</p>
      <a class="go-button" href="/whats-next">See what that looks like</a>
      <p class="hint">Want to know how the pieces fit first? <a href="/piping">Inspect the piping</a>.</p>
    </div>
  </div>
</section>"""
    return layout(conn, "Welcome", "home", body, 5 if lock.held(conn) else None)


def demo_door(conn):
    """The first panel: the demo while it is here, and the house as yours once it has left.
    The button goes to the Doorstep, where the welcome and the story are; nothing is brought
    in from here."""
    from . import demo
    if demo.present():
        any_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        now = clock.clock_label(clock.as_datetime(db.get_state(conn, "clock")))
        go = (f'<a class="go-button" href="/doorstep">It&#x27;s {h(now)}. Carry on at the Doorstep</a>' if any_items
              else '<a class="go-button" href="/doorstep">Start the week</a>')
        return f"""<div class="door">
      <h2>Play the demo</h2>
      <p>Meet Alex. Runs a cookie bakery for Jordan, the owner, who wants to know when the new
      shop opens. Has a partner who's working late, a nine-year-old with a swimming badge, and a
      mum who's not well. Alex's week is about to land on you: four days of mail, messages and
      notes, and you decide what happens to every one of them. Say yes, say no, send it back
      with a note, or teach the Mudroom a rule and watch it fire tomorrow.</p>
      <p>Be nice to Jordan. Or don't. The people write back, and they remember.</p>
      {go}
    </div>"""
    you = db.get_state(conn, "you", "") or "you"
    return f"""<div class="door">
      <h2>{h(you)}'s Mudroom</h2>
      <p>The demo week has been removed. What arrives now comes from your own mail, chat and
      calendar, and the Sorting dashboard is where you say yes.</p>
      <a class="go-button" href="/sorted">Open the Sorting dashboard</a>
    </div>"""


def whats_next(conn, query=None):
    """What's next: the pitch. Big, short, and backed by the numbers from the week you just
    played, pulled from the database rather than made up."""
    from . import demo
    here = demo.present()
    you = db.get_state(conn, "you", "") or "you"
    n = {
        "in": conn.execute("SELECT COUNT(*) FROM items WHERE status != 'sent'").fetchone()[0],
        "sent": conn.execute("SELECT COUNT(*) FROM actions WHERE action IN ('send', 'forward')").fetchone()[0],
        "promises": conn.execute("SELECT COUNT(*) FROM commitments WHERE status = 'closed'").fetchone()[0],
        "filed": conn.execute("SELECT COUNT(*) FROM items WHERE status = 'filed'").fetchone()[0],
        "rules": conn.execute("SELECT COUNT(*) FROM handling_rules WHERE status = 'active'").fetchone()[0]
                 + conn.execute("SELECT COUNT(*) FROM source_senders WHERE disposition = 'skip'").fetchone()[0],
        "yes": conn.execute("SELECT COUNT(*) FROM actions WHERE action IN ('approve', 'accept')").fetchone()[0],
    }
    played = n["in"] > 0
    score = "".join(
        f'<div class="score"><b>{v}</b><span>{h(label)}</span></div>' for v, label in [
            (n["in"], "things came in"), (n["yes"], "times you said yes"), (n["sent"], "replies went out"),
            (n["promises"], "promises kept"), (n["filed"], "filed without you"), (n["rules"], "rules you taught it")]
        if v) if played else ""   # a zero is not a score
    tiles = sum(1 for v in n.values() if v)
    scoreboard = (f'<div class="scoreboard"><p class="caption">Your week so far, straight from the log</p>'
                  f'<div class="scores">{score}</div></div>' if played and tiles >= 3 else "")
    state = ("" if here else
             f'<p class="state">The demo week is gone. This is {h(you)}\'s Mudroom now. Connect the first inbox and '
             f'the numbers above start being yours.</p>')
    body = f"""<section class="pitch">
  <h1>Never go through your inbox<br>by hand again.</h1>
  <p class="lead">You just watched the Mudroom do a week. Mail, messages, notes, invitations: read once, sorted
  into four piles, replies written, promises remembered, rules learned. You said yes a few times and drank your
  coffee. Now picture it doing <em>your</em> week.</p>
  {scoreboard}
  {state}
  <div class="two-ways">
    <div class="way before">
      <h2>Monday, the old way</h2>
      <ul>
        <li>Forty emails. You read all forty.</li>
        <li>Three of them wanted a reply. You wrote three.</li>
        <li>One had a promise in it. You forgot it by Thursday.</li>
        <li>Twenty were newsletters. You deleted them again.</li>
        <li>Your mum asked about Thursday. You answered on Wednesday.</li>
      </ul>
    </div>
    <div class="way after">
      <h2>Monday, with the Mudroom</h2>
      <ul>
        <li>Forty emails. You read a list of six.</li>
        <li>Three replies were waiting, in your voice. You pressed yes three times.</li>
        <li>The promise is on your list, and it closes itself when the answer comes.</li>
        <li>The newsletters were filed before you woke up. You told it to, once.</li>
        <li>Your mum got her answer at 08:31.</li>
      </ul>
    </div>
  </div>
  <h2 class="big">Then make it yours. Properly yours.</h2>
  <div class="yours-grid">
    <div><b>It's your code.</b><p>Small enough to read in an afternoon. Want the week as a list? Want a fifth
    pile? Want the cards to swear at you? Change it.</p></div>
    <div><b>It learns your rules.</b><p>Every card has a From now on. Every rule sticks. After a month it handles
    your mail the way you would, before you have looked.</p></div>
    <div><b>It never acts alone.</b><p>Nothing is sent, booked or filed without your yes. It keeps no passwords.
    It writes down everything it did, on a page you can read.</p></div>
  </div>
  <h2 class="big">And when you trust it, let go a little.</h2>
  <div class="letgo">
    <p>Today it asks before everything. That is the right place to start. But every yes you give is a
    data point, and after a few weeks the log shows the same thing over and over: you said yes to every
    newsletter it filed, every "see you Thursday" it drafted, every invitation it accepted.</p>
    <p>So you let it off the leash, one rope at a time. <b>File those on your own.</b> <b>Answer
    invitations from people I know.</b> <b>Send the two-line replies without asking.</b> <b>Book the
    meeting if my diary is free.</b> Each one is a switch you flip, each one is logged, each one you can
    flip back in a second. The Mudroom never takes an inch you did not give it.</p>
    <p class="punch">The end state is a morning where your mail has been read, answered, filed and booked,
    and the only thing waiting for you is the handful of decisions only you can make.</p>
  </div>
  <h2 class="big">What the demo couldn't show you</h2>
  <ul class="honest">
    <li>The people were actors. An AI played them from a one-page script. Yours will surprise you more.</li>
    <li>Nothing was actually sent. With your mail, yes means sent. That is why it is your yes.</li>
    <li>Your real inbox is duller than this week was. More filing, fewer dates. The rules are what fix that.</li>
    <li>It starts out knowing nobody. It learns who people are from what you tell it, one answer at a time.</li>
  </ul>
  <div class="go">
    <p>Open Claude Code in this folder and type</p>
    <p class="cmd">/make-it-mine</p>
    <p>It asks your name, clears the demo, connects your first inbox and runs the first pass. One step at a
    time, and it waits for you after each one.</p>
  </div>
  <p class="more">The small print, with the limits and what it cannot protect you from: <code>docs/make-it-yours.md</code>
  in this folder. Curious how the pieces fit? <a href="/piping">Inspect the piping</a>.</p>
</section>"""
    return layout(conn, "What's next", "whats-next", body)


def mudroom_drawing():
    """A door, a coat rack with four hooks, a mat and a pair of boots. Simple shapes in the
    page's own colours, so it reads in light and dark alike."""
    return """<svg class="room" viewBox="0 0 320 240" role="img" aria-label="A mudroom: a door, four coats on hooks, boots on the mat">
  <rect class="wall" x="0" y="0" width="320" height="240"/>
  <rect class="floor" x="0" y="190" width="320" height="50"/>
  <rect class="doorframe" x="24" y="40" width="88" height="150" rx="4"/>
  <rect class="doorleaf" x="30" y="46" width="76" height="144" rx="3"/>
  <rect class="pane" x="44" y="58" width="48" height="40" rx="3"/>
  <circle class="knob" cx="96" cy="124" r="4"/>
  <rect class="rail" x="140" y="62" width="160" height="8" rx="4"/>
  <g class="coats">
    <g class="coat ready" transform="translate(152 70)"><circle class="peg" cx="8" cy="0" r="3"/><path d="M8 4 l-14 10 v44 h28 v-44 z"/></g>
    <g class="coat yours" transform="translate(192 70)"><circle class="peg" cx="8" cy="0" r="3"/><path d="M8 4 l-12 10 v38 h24 v-38 z"/></g>
    <g class="coat headsup" transform="translate(232 70)"><circle class="peg" cx="8" cy="0" r="3"/><path d="M8 4 l-13 9 v30 h26 v-30 z"/></g>
    <g class="coat filed" transform="translate(272 70)"><circle class="peg" cx="8" cy="0" r="3"/><path d="M8 4 l-10 8 v26 h20 v-26 z"/></g>
  </g>
  <rect class="mat" x="130" y="170" width="150" height="22" rx="6"/>
  <g class="boots" transform="translate(180 148)">
    <path d="M2 0 h12 a2 2 0 0 1 2 2 v22 h10 a4 4 0 0 1 4 4 v6 a2 2 0 0 1 -2 2 h-26 a2 2 0 0 1 -2 -2 v-32 a2 2 0 0 1 2 -2 z"/>
    <path d="M32 0 h12 a2 2 0 0 1 2 2 v22 h10 a4 4 0 0 1 4 4 v6 a2 2 0 0 1 -2 2 h-26 a2 2 0 0 1 -2 -2 v-32 a2 2 0 0 1 2 -2 z"/>
  </g>
</svg>"""


# How it works: the process, end to end.


# The landing page: the machinery, and what every part of it does.

SOURCES = [
    ("src-email", "Email",
     "The mudroom can read the inboxes of as many email accounts as you have, Gmail for example. "
     "Every message it finds becomes a new entry in <code>items</code>, carrying the sender, the "
     "subject, the body, and the original message as it arrived. It can send email too, though "
     "never without your approval."),
    ("src-chat", "Chat",
     "The mudroom can read both one-to-one and group chats, Signal for example. A chat message "
     "becomes an entry in <code>items</code> exactly like an email does, carrying who sent it, "
     "when, and what they said. It can send chat messages too, where the tool allows it and "
     "you permit the mudroom to do so."),
    ("src-calendar", "Calendar",
     "The mudroom can read your calendars across as many accounts as you keep, Google Calendar for "
     "example. Each entry lands in <code>items</code> like anything else, carrying who set it, "
     "when it runs, and who is coming. It builds one view of all of them, so it can spot a "
     "clash you would otherwise only catch by opening two apps. It can add meetings too, though "
     "never without your approval."),
    ("src-tasks", "Tasks",
     "The mudroom can read and write the tasks you keep in an app like Todoist. Anything you throw "
     "into its inbox is a new item, exactly like an email, and lands in <code>items</code> with "
     "you as the sender. Over time you can teach the mudroom how you like that app kept, and it "
     "will do that work ready for your approval."),
    ("src-transcripts", "Transcripts",
     "The mudroom can read written transcripts of meetings and calls, from Microsoft Teams for "
     "example, or from a recorder like Plaud. Each transcript becomes one entry in "
     "<code>items</code>, carrying the title, when it happened, and the whole text. Transcripts "
     "are the richest source there is. One transcript can turn up people the mudroom has never "
     "met, a meeting that needs a slot, and half a dozen things somebody said they would do, "
     "including a promise you made out loud and would otherwise forget. The Evaluation Agent "
     "gathers those last ones onto one card and asks which of them are yours."),
    ("src-other", "Other",
     "The sources above are examples. The mudroom can support many other kinds of data too:"
     "<ul>"
     "<li>A work tracker like Jira or Azure DevOps.</li>"
     "<li>A shared drive where documents land.</li>"
     "<li>A support queue.</li>"
     "<li>A forms inbox.</li>"
     "</ul>"
     "Anything you can read with code can become a source, without major changes to the "
     "mudroom's architecture."),
]

STAGES = [
    ("intake", "Intake Engine", ("fetches what is new", "from all your sources"),
     ["source_state", "source_senders"], ["source_state", "items", "decision_log"],
     "Intake runs on a schedule, or on demand when you start it manually. It checks each source "
     "for anything new, using the timestamps kept in <code>source_state</code>. This way only new "
     "material gets fetched, instead of your whole inbox every time. Anything new gets registered "
     "in <code>items</code>, so each email gets its own entry. Every entry is then checked against "
     "<code>source_senders</code>, which is where your preferences live, for example to ignore a "
     "particular marketing newsletter. If something is skipped, the reason is registered in "
     "<code>decision_log</code>, so every decision stays traceable. Only once every item is "
     "registered does a new timestamp go into <code>source_state</code>. This way nothing gets "
     "lost if the intake fails halfway."),
    ("learn", "Learning Agent", ("learns from what you said", "since the last run"),
     ["questions", "proposals", "decision_log", "people", "interactions", "handling_rules",
      "source_senders"], [],
     "This is where the mudroom gets better at understanding you, your preferences and your "
     "life. It picks up the <code>questions</code> you answered since last time and applies "
     "them. For example, you might have answered a question about who a particular person is "
     "to you. This agent will update their entry in <code>people</code> based on your answer. "
     "Or you might have told the mudroom that you are not interested in a particular "
     "newsletter. That sender is marked skip in <code>source_senders</code>, so intake never "
     "reads it again. It also picks up anything you sent back with a comment. The "
     "<code>proposals</code> entry then "
     "gets judged again, knowing what you said. This step "
     "writes nothing to the database itself. What it "
     "works out goes into the same file the Evaluation Agent finishes, and the Processing "
     "Engine writes the lot."),
    ("judge", "Evaluation Agent", ("decides what needs doing,", "and preps the work"),
     ["items", "people", "interactions", "commitments", "questions", "handling_rules"], [],
     "This is the step that does the thinking. An LLM reads what just arrived in "
     "<code>items</code>. It pulls the background on whoever is involved from <code>people</code> "
     "and <code>interactions</code>, so it knows an email from your mother is not spam. Unless you "
     "tell it otherwise, in which case the Learning Agent takes you at your word on the next run. "
     "It checks <code>commitments</code> and <code>questions</code>, where your open promises and "
     "open questions live. Say a colleague finally confirms they have unblocked you. The agent "
     "spots that answer. It closes the promise, and preps the task you can now start. For each "
     "new item it settles three things: what kind of work this is, what should happen to it, and "
     "why. What should happen has four possible answers:"
     "<ul>"
     "<li><b>Ready for you</b>: the work is done and waiting on your yes, a drafted reply or a "
     "suggested meeting.</li>"
     "<li><b>Needs your input</b>: it has no good answer and the decision is yours. Tell it what "
     "you want done with that kind of thing and it saves your preference in "
     "<code>handling_rules</code>.</li>"
     "<li><b>Heads-up</b>: there is nothing for you to do, and you should still know. A decision "
     "taken in a thread you were copied on.</li>"
     "<li><b>Filed away</b>: nothing was needed. A newsletter you never open, or a thank-you that "
     "closes a thread.</li>"
     "</ul>"
     "All of it lands in one file, <code>handover.json</code>: what it read, what it decided, "
     "why, and what it learned about you along the way. The Processing Engine picks it up from "
     "there and does the writing."),
    ("apply", "Processing Engine", ("writes down what was decided,", "and acts on what you approve"),
     ["items", "handling_rules", "proposals"],
     ["proposals", "tasks", "events", "commitments", "questions", "people", "interactions",
      "decision_log", "actions", "items", "source_senders", "handling_rules"],
     'This engine has two jobs. The first is turning <code>handover.json</code> into records. It checks the file against what actually arrived, so nothing can be invented. It applies any of your rules that match. Then it writes the lot in one go:'
     '<ul>'
     '<li><code>proposals</code>: what was decided about each item, and the work that came with it.</li>'
     '<li><code>tasks</code>, <code>events</code>, <code>commitments</code> and <code>questions</code>: the work itself, each in its own table.</li>'
     '<li><code>decision_log</code>: why, in plain words, including the things it skipped.</li>'
     '<li><code>actions</code>: anything it actually did.</li>'
     '</ul>'
     'If one part is wrong, none of it is written. The second job is doing what you approve. A button on a page sends the engine one instruction, and the engine is what sends the email, books the meeting, makes the task, or files the original away. Nothing with an effect happens until you press something. Only this engine and the Intake Engine write to the database. Neither agent does. Waiting for you on every effect is the setting this repo ships with. Once you trust it, you can let the engine act on its own for some kinds of work, and <code>docs/make-it-yours.md</code> sets out what that takes.'),
]

TABLES = [
    ("source_state", "when a source was last reviewed",
     "A bookmark for when each source was last fetched. That way the next run reads only what "
     "is new, instead of your whole inbox again.",
     ["source        email",
      "account       you@example.com",
      "cursor        2026-09-14 07:52",
      "last_seen_id  email-18f2c9a01"]),
    ("source_senders", "which senders to ignore or prioritise",
     "What the mudroom knows about each sender, checked at intake once everything new is registered. "
     "<code>skip</code> means the item is marked and never read, so the Evaluation Agent never sees it. "
     "<code>watch</code> means always read, and never treat their "
     "mail as bulk. <code>person</code> ties the address to someone in <code>people</code>, so "
     "the Evaluation Agent "
     "knows who wrote. A sender with no row yet is read and judged as normal, and the "
     "mudroom may ask you who they are. Every row records what taught it.",
     ["sender        digest@example.com",
      "source        email",
      "disposition   skip",
      "taught_by     proposal-9",
      "note          newsletter, never actioned"]),
    ("items", "what came in, and from where",
     "Everything that came in, flattened to one shape whatever the source. An email, a chat "
     "message and a meeting transcript all look the same here, which is what lets every later step "
     "stop caring where a thing came from. Each entry's id is built from the source name and the "
     "id the provider gave it, so the same email turning up in two fetches updates one entry "
     "instead of making two.",
     ["id            email-18f2c9a01",
      "source        email",
      "sender        Jordan",
      "subject       Update and a date",
      "received_at   2026-09-14 07:52",
      "body          Can I get the project update..."]),
    ("decision_log", "why each thing was handled that way",
     "Why each thing was handled the way it was, in plain words. Written for everything, including "
     "the ones skipped without being read. Nothing reads it back yet, and that is deliberate. "
     "The mudroom is collecting it now so that a later version has years of your decisions to "
     "learn from.",
     ["at            2026-09-14 07:53",
      "actor         intake",
      "item          email-18f2c9c07",
      "decision      skipped",
      "reason        sender marked skip",
      "              in source_senders"]),
    ("proposals", "what it decided to do with each item",
     "What the mudroom decided about one item: the kind of work it is, what should happen to it, the "
     "reason, and what it proposes doing. A proposal sits <code>pending</code> until you approve or decline it. "
     "There is no case where it goes ahead on its own.",
     ["item          email-18f2c9a01",
      "class         reply-needed",
      "outcome       ready",
      "reason        Jordan asked for a written reply",
      "status        pending"]),
    ("actions", "what was actually done",
     "One row for every effect, by an engine or by you, with a flag saying whether it can be "
     "undone. This is the audit trail.",
     ["at            2026-09-14 08:40",
      "actor         you",
      "action        approve",
      "target        proposal-14",
      "reversible    yes"]),
    ("tasks", "what needs doing",
     "Things to do. Created when a proposal carrying a task is approved, or seeded when you set the "
     "mudroom up. The planner page is a view onto this table.",
     ["title         Send the update to Jordan",
      "domain        work",
      "priority      1",
      "due           2026-09-15",
      "status        open"]),
    ("events", "what is in your diary",
     "Things in your diary. Read so the mudroom knows what your week already holds, and written "
     "when an approved proposal puts something new in it.",
     ["title         School pick-up",
      "calendar      family",
      "start         2026-09-16 14:30",
      "end           2026-09-16 15:00"]),
    ("commitments", "what was promised, in both directions",
     "Promises, in both directions. owner <code>me</code> means you promised someone. owner "
     "<code>them</code> means "
     "someone promised you. The mudroom keeps each one open until an answer turns up, "
     "sometimes days later and on an unrelated thread. The Evaluation Agent spots that "
     "answer and proposes closing it.",
     ["owner         me",
      "person        jordan",
      "what          Confirm the go-live date",
      "due           2026-09-16 09:00",
      "status        open"]),
    ("questions", "what it needs you to answer",
     "Things the mudroom needs you to answer before it can act well. Only one open question per "
     "subject ever stands, so a rephrasing collapses onto the existing one instead of asking you "
     "the same thing twice in different words. Once you answer, the Learning Agent folds it in "
     "and marks the question <code>consumed</code>, so the same answer is never applied twice.",
     ["subject       person:taylor",
      "question      Taylor Reid has emailed you",
      "              twice this week. Who are they?",
      "asked_on      2026-09-14",
      "status        open"]),
    ("people", "who the people around you are",
     "Who the people around you are. Built as they appear, instead of entered up front. A profile "
     "stays a stub until the mudroom knows enough to be sure it is not confusing two people "
     "with the same first name. A fact you stated in an answer is written as you gave it. A "
     "fact the mudroom worked out on its own becomes a proposal you approve, so nothing "
     "reaches this table without you.",
     ["id            jordan",
      "name          Jordan",
      "pronouns      she/her",
      "role          your manager",
      "trait         short emails, wants a date"]),
    ("interactions", "when you last spoke to someone",
     "Every time you and someone exchanged something, and through which item. direction "
     "<code>in</code> means they contacted you, <code>out</code> means you contacted them. Together they tell you that you "
     "have not spoken to someone in three months, which no single message ever says.",
     ["person        jordan",
      "item          email-18f2c9a01",
      "direction     in",
      "at            2026-09-14 07:52"]),
    ("handling_rules", "what you told it to do from now on",
     "What you told it to do from now on. A rule matches on a sender, a domain or a subject, and "
     "sets what happens to anything matching it. Rules run after the item has been read. "
     "<code>source_senders</code> decides whether an item is read at all. "
     "<code>handling_rules</code> decides what happens to it once it has been. Rules are retired instead of deleted, so you "
     "can see what you once asked for and when it last fired. Every rule records what taught it, "
     "so a rule you do not remember writing can be traced back to the decision that made it.",
     ["scope         sender",
      "pattern       admin@school.example",
      "action        make a task",
      "status        active",
      "taught_by     proposal-14",
      "last_applied  2026-09-14"]),
]

SECTIONS = [
    ("Intake", ["source_state", "items"]),
    ("Decisions made", ["proposals", "actions", "decision_log"]),
    ("Actions", ["tasks", "events", "commitments", "questions"]),
    ("Who you deal with", ["people", "interactions"]),
    ("What you taught it", ["source_senders", "handling_rules"]),
]

HANDOVER = ('handover', 'handover.json', 'Both agents write into this one file, and it is the only thing either of them produces. Neither can touch the database, so whatever they worked out has to be named here for the Processing Engine to act on.'
            '<ul>'
            '<li><b>consumed</b>: the questions the Learning Agent used this run. The engine marks them used, so the same answer never gets applied twice.</li>'
            '<li><b>people</b> and <b>senders</b>: what your answers taught it, about a person or about a sender worth skipping.</li>'
            '<li><b>seen</b>: every item the Evaluation Agent looked at. The engine checks this against what intake registered, so nothing goes missing unnoticed.</li>'
            '<li><b>items</b>: one entry each, carrying what kind of work it is, what should happen to it, why, and the work itself. The work is a list, because one item can produce several things.</li>'
            '</ul>'
            'Nothing here sends or writes anything. The file is only text. It can say "send this to Jordan", and nothing happens. If the agent gets something badly wrong, the worst that reaches you is a bad draft on a card, waiting for you to say no. Once the Processing Engine has checked the file and written what it accepts, the file is gone.', ['{', '  "consumed": ["q-taylor-identity"],', '  "people": [{"id": "taylor",', '              "name": "Taylor Reid"}],', '  "seen": ["email-18f2c9a01", "email-18f2c9b44"],', '  "items": [{', '    "id": "email-18f2c9a01",', '    "class": "reply-needed",', '    "outcome": "ready",', '    "reason": "Jordan asked for a written reply",', '    "work": [{"kind": "reply", "to": "jordan",', '              "body": "Sending it before two."}]', '  }],', '  "senders": [{"sender": "digest@example.com",', '               "disposition": "skip"}]', '}'])

EFFECTS = [
    ("out-email", "Send an email",
     "After you approve a draft email the Evaluation Agent prepared for you, the engine sends it "
     "on your behalf."),
    ("out-meeting", "Add a meeting",
     "After you approve a meeting the Evaluation Agent prepared, the engine puts it in your "
     "diary. The same card can move or lengthen a meeting you already have."),
    ("out-task", "Create a task",
     "After you approve a task the Evaluation Agent prepared, the engine writes it to your task "
     "app. The same card can move a task you already have to where it belongs."),
    ("out-forward", "Forward to someone",
     "After you approve a forward the Evaluation Agent prepared, the engine passes the message on "
     "to someone who was never in the thread."),
    ("out-reply", "Reply in a chat",
     "After you approve a draft reply the Evaluation Agent prepared, the engine posts it in the "
     "thread it came from."),
    ("out-file", "File the original away",
     "After you approve, the engine moves the original out of your inbox and gives it a label. "
     "Easy to undo: the label comes off and the message comes back."),
]

# Pills carry what the subtitle cannot. The engine's subtitle already names both its jobs,
# so it has none.
TRIGGERS = {"intake": ("run on a schedule", "run on demand"),
            "judge": ("Ready for you", "Needs your input", "Heads-up", "Filed away")}


def box(key, x, y, w, ht, title, sub, reads, writes, pills=()):
    """One hoverable box. The data attributes are what the script lights up."""
    mid = x + w // 2
    if not sub:
        body = f'<text class="s-title s-small" x="{mid}" y="{y + 18}">{h(title)}</text>'
    else:
        lines = sub if isinstance(sub, tuple) else (sub,)
        body = f'<text class="s-title" x="{mid}" y="{y + 34}">{h(title)}</text>'
        for n, line in enumerate(lines):
            body += f'<text class="s-sub" x="{mid}" y="{y + 54 + n * 16}">{h(line)}</text>'
        for n, pill in enumerate(pills):
            px, pw, py = x + 16, w - 32, y + 82 + n * 25
            body += (f'<rect class="s-pill" x="{px}" y="{py}" width="{pw}" height="24" rx="12"/>'
                     f'<text class="s-pill-text" x="{px + pw // 2}" y="{py + 16}">{h(pill)}</text>')
    return (f'<g class="stage" data-stage="{key}" data-reads="{",".join(reads)}" '
            f'data-writes="{",".join(writes)}" tabindex="0">'
            f'<rect x="{x}" y="{y}" width="{w}" height="{ht}" rx="8"/>{body}</g>')


DASHBOARDS = [
    ("dash-checkin", "Sorting dashboard",
     ["items", "proposals", "decision_log", "people", "interactions", "commitments", "questions"],
     [],
     "Everything that was sorted, in four groups: Ready for you, Needs your input, Heads-up and "
     "Filed away. Each card shows what came in, what the Evaluation Agent decided, and why. "
     "Approve or decline, and the engine does the rest."),
    ("dash-planner", "Planning dashboard",
     ["tasks", "events"], [],
     "Your to-do list and your week, drawn from <code>tasks</code> and <code>events</code>. Tick "
     "something off and the engine records it. Everything here is something you already "
     "approved, so there is nothing left to decide."),
    ("dash-other", "Other",
     [], [],
     "You can build your own pages. Each one is a function that queries the database and returns "
     "HTML, plus one line in the routing table. No framework, no build step. Some ideas:"
     "<ul>"
     "<li><b>Before a one-to-one</b>: what you owe that person, what they owe you, and when you "
     "last spoke.</li>"
     "<li><b>Who is waiting on you</b>: everything you promised and have not done yet.</li>"
     "<li><b>What has gone quiet</b>: people you have not spoken to in months, and things you are "
     "still waiting on.</li>"
     "<li><b>Sunday evening</b>: your week as it stands, and the things you promised that "
     "still need a slot.</li>"
     "</ul>"),
]


# The two agents sit on top. The line runs along the bottom, rises into them, and comes back down.
FLOW = {"learn": (288, 66, 190), "judge": (552, 66, 190),
        "intake": (288, 386, 170), "apply": (552, 386, 170)}


def diagram():
    """The flow only. What it touches is the list beside it."""
    parts = ['<rect class="d-group" x="40" y="332" width="192" height="224" rx="11"/>'
             '<text class="d-group-label" x="136" y="356">Sources</text>']
    for i, (key, name, _) in enumerate(SOURCES):
        parts.append(box(key, 54, 368 + i * 30, 164, 25, name, "", [], []))

    # the two agents share a box, because they are one pass and one model
    parts.append('<rect class="d-group d-llm" x="272" y="20" width="528" height="258" rx="12"/>'
                 '<text class="d-group-label d-llm-label" x="536" y="44">Run by an LLM</text>')

    for key, title, sub, reads, writes, _ in STAGES:
        x, y, ht = FLOW[key]
        parts.append(box(key, x, y, 232, ht, title, sub, reads, writes,
                         pills=TRIGGERS.get(key, ())))

    parts.append('<rect class="d-group" x="824" y="424" width="192" height="132" rx="11"/>'
                 '<text class="d-group-label" x="920" y="448">Human in the loop</text>')
    for i, (key, name, reads, writes, _) in enumerate(DASHBOARDS):
        parts.append(box(key, 838, 460 + i * 30, 164, 26, name, "", reads, writes))

    for d in ('M236 471 H284',          # sources into intake
              'M404 382 V 260',         # up into the agents
              'M524 161 H548',          # one agent to the next
              'M668 260 V 382',         # back down into the engine
              'M788 450 H820',          # the engine hands work across
              'M820 476 H788',          # and you hand a decision back
              'M788 396 H820'):         # and once you approve, the engine sends
        parts.insert(0, f'<path class="d-arrow" marker-end="url(#tip)" d="{d}"/>')

    parts.append('<rect class="d-group" x="824" y="184" width="192" height="222" rx="11"/>'
                 '<text class="d-group-label" x="920" y="208">What goes out</text>')
    for i, (key, name, _) in enumerate(EFFECTS):
        parts.append(box(key, 838, 220 + i * 30, 164, 26, name, "", [], []))

    # the handover file rides the line coming back down
    fx, fy = 651, 310
    parts.append(
        f'<g class="stage filemark" data-stage="handover" data-reads="" data-writes="" tabindex="0">'
        f'<rect x="{fx}" y="{fy}" width="34" height="44" rx="4"/>'
        f'<path class="f-fold" d="M{fx + 22} {fy} V {fy + 10} H {fx + 34}"/>'
        + "".join(f'<line class="f-rule" x1="{fx + 8}" y1="{fy + 20 + n * 7}" '
                  f'x2="{fx + 26}" y2="{fy + 20 + n * 7}"/>' for n in range(3))
        + f'<text class="f-label" x="{fx + 48}" y="{fy + 28}">handover.json</text></g>')

    return f"""<svg class="arch" viewBox="0 0 1060 580" role="img"
     aria-label="Two agents run by one LLM sit across the top, a learning agent and an evaluation agent. Below them the flow runs from six kinds of source into an intake engine, rises into those two agents, then comes back down through the handover file into the processing engine and the two pages where a person decides. Beside it sits what it sends once you approve: an email, a meeting, a task, a forward, a chat reply, and the original filed out of your inbox. Point at any box to see which tables it reads and writes.">
<defs><marker id="tip" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
  orient="auto-start-reverse"><path class="d-tip" d="M0 0 L10 5 L0 10 z"/></marker></defs>
{"".join(parts)}
</svg>"""


def db_column():
    """The file, as an ordinary list. Every entry is a target like a box in the flow."""
    meta = {t[0]: t for t in TABLES}
    out = []
    for label, keys in SECTIONS:
        rows = "".join(
            f'<li class="tbl" data-table="{k}" data-stage="tbl-{k}" tabindex="0">'
            f'<b>{k}</b><span>{h(meta[k][1])}</span></li>' for k in keys)
        out.append(f'<section><h3>{h(label)}</h3><ul>{rows}</ul></section>')
    return f"""<aside class="dbcol">
  <header>
    <code>mudroom.db</code>
    <p>A local SQLite database file that holds everything. One file on your own machine,
    yours to back up, copy or delete.</p>
    <p class="key"><i class="key-r"></i> read <i class="key-w"></i> write</p>
  </header>
  {"".join(out)}
</aside>"""


def body(text):
    """A panel body. A description may carry a list, which cannot sit inside a paragraph."""
    if "<ul>" not in text:
        return "<p>%s</p>" % text
    head, rest = text.split("<ul>", 1)
    items, tail = rest.split("</ul>", 1)
    close = "<p>%s</p>" % tail if tail.strip() else ""
    return "<p>%s</p><ul>%s</ul>%s" % (head, items, close)


def landing(conn, query=None):
    panels = ['<div class="step" data-for="%s"><b>%s</b>%s</div>' % (k, h(t), body(d))
              for k, t, d in list(SOURCES) + list(EFFECTS) + [(HANDOVER[0], HANDOVER[1], HANDOVER[2])]
              + [(k, t, d) for k, t, _, _, d in DASHBOARDS]]
    panels += ['<div class="step" data-for="%s"><b>%s</b>%s</div>'
               % (k, h(t if isinstance(t, str) else t), body(d))
               for k, t, _, _, _, d in STAGES]
    key, name, what, example = HANDOVER
    panels = [p for p in panels if 'data-for="%s"' % key not in p]
    panels.append('<div class="step two-up" data-for="%s"><b>%s</b>'
                  '<div class="cols"><div>%s</div><pre>%s</pre></div></div>'
                  % (key, name, body(what), "\n".join(h(line) for line in example)))
    for tkey, _, twhat, texample in TABLES:
        rows = "\n".join(h(line) for line in texample)
        panels.append('<div class="step two-up" data-for="tbl-%s"><b>%s</b>'
                      '<div class="cols"><div>%s</div><pre>%s</pre></div></div>'
                      % (tkey, tkey, body(twhat), rows))
    return layout(conn, "Inspect the piping", "piping", f"""<section class="hero">
  <div class="flowcol">
    {diagram()}
    <div class="detail">
      <span class="pin-hint">pinned. click it again, or press escape, to release</span>
      <p class="step hint" data-for="">Point at any box. Blue outline means that step reads the
      table, amber fill means it writes to it. Click a box to pin it, so you can scroll and read.</p>
      {"".join(panels)}
    </div>
  </div>
  {db_column()}
</section>
<script src="/static/arch.js"></script>""")
