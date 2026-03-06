#!/usr/bin/env python3
"""
GitHub Actions 失敗時に Discord へランダム Vibeちゃんメッセージを送信する。

パーツ分解ランダム組み合わせ方式:
  opening × subject × state × reaction × emoji × check × tail
  = 15 × 8 × 10 × 8 × 15 × 8 × 10 = 約11億通り

外部ライブラリ不要（stdlib の urllib.request を使用）ため、
pip install 不要でどのワークフローからも呼び出せる。
"""

import json
import os
import random
import urllib.request
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

# ─── メッセージパーツ定義 ───

# 冒頭の一言（15通り）
OPENINGS = [
    "えっ！？", "あわわっ！", "ぎゃーっ！", "うわわ！", "（やばい！）",
    "ちょっと待って！", "む、むむ…", "あっ！", "えーっ！", "ひゃー！",
    "ぽかん…", "ご、ごめん！", "うわあ、", "（えっ、これどうしよ！）", "はわわっ！",
]

# 何が失敗したか（8通り）
SUBJECTS = [
    "ワークフローが", "自動化が", "GitHub Actionsが", "処理が",
    "バックグラウンドの作業が", "裏側の処理が", "定時実行が", "パイプラインが",
]

# どう失敗したか（10通り）
STATES = [
    "止まっちゃった！", "失敗しちゃった！", "うまくいかなかった…",
    "クラッシュしちゃったみたい", "エラーで止まっちゃったの", "バグっちゃったっぽい",
    "固まっちゃった！", "途中で倒れちゃった！", "白旗あげちゃった", "詰まっちゃったの",
]

# 心の声・リアクション（8通り）
REACTIONS = [
    "", " （うう…どうしよ）", " （ぐすん）",
    " （あわわ）", " （震え）", " （汗）",
    " （ひたすら反省中）", " （ど、どうしたらいいの！）",
]

# 絵文字（15通り）
EMOJIS = [
    "😱", "😭", "💦", "💥", "😰", "🐛",
    "🌀", "😲", "🫨", "🤯", "😵‍💫", "🥺",
    "😤", "⚡", "🆘",
]

# 確認・対処依頼（8通り）
CHECKS = [
    "ログを確認してみてね！", "実行IDから詳細を見てね！", "確認してもらえる？",
    "調べてみてくれると助かる！", "チェックお願いね！", "ちょっと見てもらえる？",
    "詳細リンクを見てね！", "ログをのぞいてみて！",
]

# 末尾の一言（10通り）
TAILS = [
    " ごめんね…", " 直すから待ってて！", " 見てもらえると嬉しいな",
    " なんとかするから！", "", " がんばる！",
    " よろしくお願いします…", " ファイト！", " 🙏", " (ノД｀)",
]


def build_message() -> str:
    """パーツをランダム選択して失敗メッセージを生成する（約11億通り）"""
    return (
        random.choice(OPENINGS)
        + random.choice(SUBJECTS)
        + random.choice(STATES)
        + random.choice(REACTIONS)
        + random.choice(EMOJIS)
        + " "
        + random.choice(CHECKS)
        + random.choice(TAILS)
    )


def send_notification(webhook_url: str, content: str) -> None:
    """Discord Webhook にメッセージを送信する"""
    payload = json.dumps({
        "username": "Vibeちゃん",
        "content": content,
    }).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        status = resp.status
    if status not in (200, 204):
        print(f"Discord notification failed: HTTP {status}")
    else:
        print("Discord failure notification sent")


def main() -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set, skipping notification")
        return

    repo       = os.environ.get("GITHUB_REPOSITORY", "")
    run_id     = os.environ.get("GITHUB_RUN_ID", "")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    workflow   = os.environ.get("GITHUB_WORKFLOW", "")
    now        = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    run_url = f"{server_url}/{repo}/actions/runs/{run_id}"
    msg = build_message()

    content = (
        f"{msg}\n"
        f"ワークフロー: `{workflow}`\n"
        f"実行ID: [{run_id}]({run_url})\n"
        f"時刻: {now}"
    )

    send_notification(webhook_url, content)


if __name__ == "__main__":
    main()
