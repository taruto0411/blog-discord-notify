import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import requests

RSS_URL = os.environ["RSS_URL"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

STATE_FILE = Path("state.json")


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"items": {}}
    return {"items": {}}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def fetch_rss(url):
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.text


def strip_tag(tag):
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def child_text(element, names):
    for child in element:
        tag_name = strip_tag(child.tag)
        if tag_name in names:
            return (child.text or "").strip()
    return ""


def collect_texts(element, names):
    texts = []
    for child in element:
        tag_name = strip_tag(child.tag)
        if tag_name in names:
            texts.append((child.text or "").strip())
    return texts


def parse_rss_items(rss_text):
    root = ET.fromstring(rss_text)

    channel = None
    for child in root:
        if strip_tag(child.tag) == "channel":
            channel = child
            break

    items = []
    for child in channel:
        if strip_tag(child.tag) != "item":
            continue

        title = child_text(child, {"title"}) or "無題"
        link = child_text(child, {"link"})
        guid = child_text(child, {"guid"})
        pub_date = child_text(child, {"pubDate", "published", "updated"})
        description = child_text(child, {"description", "summary"})
        content_list = collect_texts(child, {"encoded", "content"})
        content = "\n".join(t for t in content_list if t)

        item_id = guid or link
        if not item_id:
            continue

        fingerprint_source = "\n".join([
            title,
            link,
            pub_date,
            description,
            content,
        ])

        fingerprint = hashlib.sha256(
            fingerprint_source.encode("utf-8")
        ).hexdigest()

        items.append({
            "id": item_id,
            "title": title,
            "link": link,
            "pub_date": pub_date,
            "fingerprint": fingerprint,
        })

    return items


def send_discord(article, mode):

    text = "記事が更新されました"
    if mode == "new":
        text = "新しい記事が公開されました"

    payload = {
        "content": text,
        "embeds": [
            {
                "title": article["title"],
                "url": article["link"],
                "description": article["pub_date"],
            }
        ]
    }

    requests.post(DISCORD_WEBHOOK_URL, json=payload)


def main():

    state = load_state()
    old_items = state.get("items", {})

    rss = fetch_rss(RSS_URL)
    items = parse_rss_items(rss)

    new_state = {}

    notifications = []

    for item in items:

        new_state[item["id"]] = item

        old = old_items.get(item["id"])

        if old is None:
            notifications.append((item, "new"))

        elif old["fingerprint"] != item["fingerprint"]:
            notifications.append((item, "updated"))

    if not old_items:
        save_state({"items": new_state})
        print("初回保存のみ")
        return

    save_state({"items": new_state})

    for item, mode in notifications:
        send_discord(item, mode)


if __name__ == "__main__":
    main()