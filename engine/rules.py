"""House rules: what you told the door to do from now on, applied after every judgement.

A rule in handling_rules matches an item on a sender, a domain or a subject and sets what
happens to it. Processing asks for the matching rule once per item, after the judgement and
before anything is written. A rule that files or flags is enforced here: the outcome is
overridden, the work dropped, and the decision log says which rule fired. A rule that asks for
work, ready or yours, is the judgement's to honour, since only the judgement can draft the
work; processing refuses a file that does not honour it, naming the rule.

source_senders is the other half: it decides whether a sender is read at all, and intake
applies it. This module only ever reads that table.
"""
import json

ENFORCED = ("filed", "headsup")


def match(conn, item_id):
    """The active rule that matches an item, or None. The oldest matching rule wins, so a
    rule you taught first is not silently outranked by one you taught later."""
    item = conn.execute("SELECT sender, subject, raw FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        return None
    heads = json.loads(item["raw"] or "{}")
    sender = (item["sender"] or "").lower()
    address = str(heads.get("from") or heads.get("address") or item["sender"] or "").lower()
    domain = address.rsplit("@", 1)[1] if "@" in address else ""
    subject = (item["subject"] or "").lower()
    for rule in conn.execute("SELECT * FROM handling_rules WHERE status = 'active' ORDER BY taught_on, id"):
        pattern = rule["pattern"].lower().strip()
        if not pattern:
            continue
        if rule["scope"] == "sender" and pattern == sender:
            return rule
        if rule["scope"] == "domain" and domain and (domain == pattern or domain.endswith("." + pattern)):
            return rule
        if rule["scope"] == "subject" and pattern in subject:
            return rule
    return None


def fired(conn, rule, item_id, now):
    """Record that a rule shaped an item: the count, the time, and a decision log row."""
    conn.execute("UPDATE handling_rules SET fired = fired + 1, last_applied = ? WHERE id = ?", (now, rule["id"]))
    conn.execute(
        "INSERT INTO decision_log (at, actor, item_id, decision, reason) VALUES (?, 'process', ?, ?, ?)",
        (now, item_id, rule["outcome"], f"house rule {rule['id']} fired: {rule['action']}"))


def words(rule):
    """The rule in one line, as the panel and the card show it."""
    return rule["action"]
