#!/usr/bin/env python3
"""
memory_manager.py — エピソード記憶・忘却曲線エンジン  (Phase 3)

【概要】
 Ebbinghaus 忘却曲線 + SM-2 アルゴリズムを使い、
 VibeCordingBot の「エピソード記憶」を管理する。

 エピソード記憶 (Layer 2) は、ユーザーとの会話で得た
 重要な情報・記憶を「忘れにくさ」で管理し、
 時間が経つと自然に薄れていくシステム。

【数学的基盤】
 忘却曲線: R(t) = e^(-t/S)
   R: 記憶保持率 (0.0〜1.0)
   t: 最後のリコールからの経過日数
   S: 記憶強度 (初期値=1.0, リコールごとに += recall_boost)

 SM-2 アルゴリズム (間隔反復):
   EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))
   EF: 難易度係数 (初期値=2.5, 最小=1.3)
   q: 品質スコア 0〜5 (5=完璧に思い出せた)
   次回インターバル = 前回インターバル * EF'

 統合: recall_boost = EF / 2.5  (強い記憶ほど強度増加が大きい)

【研究根拠】
 - MemoryBank (AAAI 2024, arxiv:2305.10250):
     R = e^(-t/S), S += 1 on recall, t = 0 on recall
     → 本実装では S の増分を EF ベースに改良
 - SM-2 アルゴリズム (Wozniak 1987/2020):
     https://www.supermemo.com/en/blog/application-of-a-computer-to-improve-the-results
 - Mem0 (arxiv:2504.19413):
     エピソード記憶の選択的統合、LLM パフォーマンス 26% 向上

【ストレージ構造】
 data/episodic_memory/
   index.json            - 全エピソード記憶インデックス
   YYYY-MM/
     entries.json        - 月別エントリ詳細

 エントリ構造:
   id             str     SHA256(content)[:16]
   content        str     記憶内容
   source         str     "conversation" | "article" | "manual"
   user_id        str     会話ユーザーID (任意)
   created_at     str     ISO8601
   last_recalled  str     ISO8601
   recall_count   int     リコール回数
   strength       float   記憶強度 S (初期=1.0)
   ef             float   SM-2 難易度係数 (初期=2.5)
   interval_days  int     次回反復までの日数
   next_review    str     ISO8601 (次回要確認日)
   retention      float   現在の保持率 R (0.0〜1.0)
   tags           list    関連タグ
   layer          int     1=working, 2=episodic, 3=personality

【使い方】
 # 新しいエピソードを追加
 python scripts/memory_manager.py add --content "Claudeが新しいMCP機能を追加" --tags "Claude,MCP"

 # 記憶をリコール (保持率を更新)
 python scripts/memory_manager.py recall --id abc123 --quality 4

 # 忘却スコアを更新 (GitHub Actions で定期実行)
 python scripts/memory_manager.py decay

 # 統合候補を表示 (Layer 3 への昇格候補)
 python scripts/memory_manager.py consolidate --show

 # 全エピソードを一覧表示
 python scripts/memory_manager.py list

 # 関連記憶を検索 (BM25)
 python scripts/memory_manager.py search --query "Claude Code MCP"
"""

import argparse
import hashlib
import json
import logging
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from constants import JST

# ─── Paths ───
ROOT_DIR = Path(__file__).resolve().parent.parent
EPISODIC_DIR = ROOT_DIR / "data" / "episodic_memory"
INDEX_PATH = EPISODIC_DIR / "index.json"
PERSONALITY_PATH = ROOT_DIR / "data" / "character_knowledge" / "personality_layer.json"

# ─── Logging ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── SM-2 定数 ───
SM2_EF_INITIAL = 2.5      # 初期難易度係数
SM2_EF_MIN = 1.3           # 最小難易度係数
SM2_INTERVAL_INITIAL = 1   # 初回インターバル (日)
SM2_INTERVAL_SECOND = 6    # 2回目インターバル (日)

# ─── 忘却曲線定数 ───
MEMORY_STRENGTH_INITIAL = 1.0    # 初期記憶強度 S
RETENTION_THRESHOLD_FORGET = 0.3  # この保持率以下で「ほぼ忘れた」
RETENTION_THRESHOLD_ACTIVE = 0.7  # この保持率以上で「よく覚えている」

# ─── 統合閾値 (Layer 2 → Layer 3) ───
CONSOLIDATION_MIN_RECALLS = 5      # 最低リコール回数
CONSOLIDATION_MIN_RETENTION = 0.5  # 最低保持率


# ────────────────────────────────────────────────────────────────
# 数学的コア関数
# ────────────────────────────────────────────────────────────────

def compute_retention(entry: dict, now: datetime | None = None) -> float:
    """
    Ebbinghaus 忘却曲線で現在の記憶保持率を計算。

    R(t) = e^(-t/S)
      t: last_recalled からの経過日数
      S: 記憶強度

    Args:
        entry: エピソード記憶エントリ
        now: 現在時刻 (None の場合は実時刻)

    Returns:
        保持率 0.0〜1.0
    """
    if now is None:
        now = datetime.now(JST)

    last_recalled_str = entry.get("last_recalled") or entry.get("created_at", "")
    try:
        last = datetime.fromisoformat(last_recalled_str.replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=JST)
    except (ValueError, AttributeError):
        return 1.0  # パース失敗時は保持率 100% (新しい記憶として扱う)

    t = max((now - last).total_seconds() / 86400, 0)  # 日数
    S = entry.get("strength", MEMORY_STRENGTH_INITIAL)
    S = max(S, 0.1)  # ゼロ除算防止

    R = math.exp(-t / S)
    return round(max(0.0, min(1.0, R)), 4)


def recall_entry(entry: dict, quality: int = 4, now: datetime | None = None) -> dict:
    """
    エントリをリコールし、記憶強度・SM-2パラメータを更新する。

    SM-2 アルゴリズム:
      EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))
      EF' = max(EF', 1.3)
      インターバル:
        n=1: I=1
        n=2: I=6
        n>2: I = I_prev * EF'

    Args:
        entry: エピソード記憶エントリ
        quality: リコール品質 0〜5
                 5: 完璧 / 4: 正確だが少し迷った / 3: 正確だが難しかった
                 2: 間違えたが思い出せた / 1: 間違えた / 0: 全く覚えていない
        now: 現在時刻

    Returns:
        更新されたエントリ (in-place ではなくコピー)
    """
    if now is None:
        now = datetime.now(JST)

    entry = entry.copy()
    quality = max(0, min(5, quality))

    # SM-2: EF 更新
    ef = entry.get("ef", SM2_EF_INITIAL)
    ef_new = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef_new = max(ef_new, SM2_EF_MIN)

    # SM-2: インターバル更新
    recall_count = entry.get("recall_count", 0) + 1
    prev_interval = entry.get("interval_days", SM2_INTERVAL_INITIAL)
    if recall_count == 1:
        interval = SM2_INTERVAL_INITIAL
    elif recall_count == 2:
        interval = SM2_INTERVAL_SECOND
    else:
        interval = max(1, round(prev_interval * ef_new))

    # 記憶強度 S 更新 (MemoryBank + SM-2 hybrid)
    # EF が高いほど強度増加が大きい (良い記憶ほど強化)
    recall_boost = ef_new / SM2_EF_INITIAL  # 0.52〜~2.0
    strength = entry.get("strength", MEMORY_STRENGTH_INITIAL) + recall_boost
    strength = round(strength, 4)

    # quality が低い場合は部分的にリセット
    if quality < 3:
        strength = max(
            MEMORY_STRENGTH_INITIAL,
            strength - recall_boost * 0.5
        )

    next_review = (now + timedelta(days=interval)).isoformat()

    entry.update({
        "recall_count": recall_count,
        "last_recalled": now.isoformat(),
        "ef": round(ef_new, 4),
        "interval_days": interval,
        "next_review": next_review,
        "strength": strength,
        "retention": 1.0,  # リコール直後は保持率 100%
        "last_quality": quality,
    })

    return entry


def should_review(entry: dict, now: datetime | None = None) -> bool:
    """
    このエントリを今日レビューすべきか判定する。

    条件:
      1. next_review が今日以前
      または
      2. retention < RETENTION_THRESHOLD_ACTIVE (保持率が下がってきた)
    """
    if now is None:
        now = datetime.now(JST)

    # 保持率が低下している
    retention = compute_retention(entry, now)
    if retention < RETENTION_THRESHOLD_ACTIVE:
        return True

    # next_review 日程を過ぎている
    next_review_str = entry.get("next_review", "")
    if not next_review_str:
        return True
    try:
        next_review = datetime.fromisoformat(
            next_review_str.replace("Z", "+00:00")
        )
        if next_review.tzinfo is None:
            next_review = next_review.replace(tzinfo=JST)
        return now >= next_review
    except ValueError:
        return True


def is_consolidation_candidate(entry: dict, now: datetime | None = None) -> bool:
    """
    Layer 3 (Personality Layer) への統合候補か判定する。

    条件:
      - recall_count >= CONSOLIDATION_MIN_RECALLS (5回以上思い出した)
      - retention >= CONSOLIDATION_MIN_RETENTION (まだよく覚えている)
      - layer == 2 (まだ Layer 3 に昇格していない)
    """
    if entry.get("layer", 2) >= 3:
        return False  # 既に統合済み

    if entry.get("recall_count", 0) < CONSOLIDATION_MIN_RECALLS:
        return False

    retention = compute_retention(entry, now)
    return retention >= CONSOLIDATION_MIN_RETENTION


# ────────────────────────────────────────────────────────────────
# BM25 検索 (外部依存なし)
# ────────────────────────────────────────────────────────────────

def tokenize_memory(text: str) -> list[str]:
    """シンプルな日本語/英語トークナイザ (Worker 側の tokenize() と対応)"""
    import re
    # 英数字単語
    tokens = re.findall(r'[a-zA-Z0-9]+', text.lower())
    # 日本語 2-gram (バイグラム)
    jp_text = re.sub(r'[a-zA-Z0-9\s\.,!?、。！？「」\[\]（）\(\)\-_/\\]', '', text)
    for i in range(len(jp_text) - 1):
        tokens.append(jp_text[i:i+2])
    # 単漢字
    tokens.extend(list(jp_text))
    return [t for t in tokens if len(t) >= 1]


def bm25_search_memory(
    query: str,
    entries: list[dict],
    top_k: int = 5,
    k1: float = 1.5,
    b: float = 0.75
) -> list[tuple[dict, float]]:
    """
    BM25 でエピソード記憶を検索する。

    Args:
        query: 検索クエリ
        entries: 検索対象エントリ一覧
        top_k: 上位K件
        k1, b: BM25 パラメータ

    Returns:
        [(entry, score), ...] スコア降順
    """
    if not entries:
        return []

    query_terms = tokenize_memory(query)
    if not query_terms:
        return []

    # 各エントリのトークン化 (content + tags)
    docs = []
    for entry in entries:
        text = entry.get("content", "") + " " + " ".join(entry.get("tags", []))
        docs.append(tokenize_memory(text))

    avg_dl = sum(len(d) for d in docs) / len(docs) if docs else 1.0

    results = []
    for i, (entry, doc_terms) in enumerate(zip(entries, docs)):
        if not doc_terms:
            continue

        score = 0.0
        dl = len(doc_terms)
        term_freq = {}
        for t in doc_terms:
            term_freq[t] = term_freq.get(t, 0) + 1

        for qt in query_terms:
            tf = term_freq.get(qt, 0)
            if tf == 0:
                continue
            n_docs_with_term = sum(1 for d in docs if qt in d)
            idf = math.log(
                (len(docs) - n_docs_with_term + 0.5) / (n_docs_with_term + 0.5) + 1
            )
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
            score += idf * tf_norm

        # 記憶強度・保持率でスコアをブースト
        retention = compute_retention(entry)
        strength_boost = 1.0 + entry.get("strength", 1.0) * 0.1
        final_score = score * retention * strength_boost

        if final_score > 0:
            results.append((entry, round(final_score, 4)))

    results.sort(key=lambda x: -x[1])
    return results[:top_k]


# ────────────────────────────────────────────────────────────────
# ストレージ操作
# ────────────────────────────────────────────────────────────────

def load_index() -> list[dict]:
    """エピソード記憶インデックスを読み込む"""
    if INDEX_PATH.exists():
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_index(entries: list[dict]):
    """エピソード記憶インデックスを保存"""
    EPISODIC_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    logger.info(f"index.json 保存: {len(entries)} エントリ")


def make_entry_id(content: str) -> str:
    """コンテンツから一意ID生成"""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def add_entry(
    content: str,
    source: str = "conversation",
    user_id: str = "",
    tags: list[str] | None = None,
    layer: int = 2
) -> dict:
    """
    新しいエピソード記憶を追加する。

    Args:
        content: 記憶内容
        source: 記憶ソース ("conversation" | "article" | "manual")
        user_id: ユーザーID
        tags: タグリスト
        layer: メモリーレイヤー (2=episodic, 3=personality)

    Returns:
        新しく作成されたエントリ
    """
    now = datetime.now(JST)
    entry_id = make_entry_id(content)

    entries = load_index()

    # 重複チェック
    existing = next((e for e in entries if e["id"] == entry_id), None)
    if existing:
        logger.info(f"既存エントリ (スキップ): {entry_id}")
        return existing

    next_review = (now + timedelta(days=SM2_INTERVAL_INITIAL)).isoformat()

    entry = {
        "id": entry_id,
        "content": content,
        "source": source,
        "user_id": user_id,
        "created_at": now.isoformat(),
        "last_recalled": now.isoformat(),
        "recall_count": 0,
        "strength": MEMORY_STRENGTH_INITIAL,
        "ef": SM2_EF_INITIAL,
        "interval_days": SM2_INTERVAL_INITIAL,
        "next_review": next_review,
        "retention": 1.0,
        "tags": tags or [],
        "layer": layer,
        "last_quality": None,
    }

    entries.append(entry)
    save_index(entries)
    logger.info(f"エントリ追加: {entry_id} | {content[:50]}")
    return entry


# ────────────────────────────────────────────────────────────────
# バッチ処理
# ────────────────────────────────────────────────────────────────

def run_decay_update():
    """
    全エントリの保持率を更新する。
    GitHub Actions で定期実行 (例: 毎日深夜)。

    - retention を再計算
    - 保持率が閾値を下回ったエントリをログ出力
    - should_review() のエントリを別途ログ
    """
    entries = load_index()
    if not entries:
        logger.info("エントリなし")
        return

    now = datetime.now(JST)
    updated_count = 0
    forgot_count = 0
    review_count = 0

    for entry in entries:
        old_retention = entry.get("retention", 1.0)
        new_retention = compute_retention(entry, now)
        entry["retention"] = new_retention

        if new_retention != old_retention:
            updated_count += 1

        if new_retention < RETENTION_THRESHOLD_FORGET:
            forgot_count += 1
            logger.debug(
                f"  ⚠️ ほぼ忘れた: {entry['id']} | "
                f"retention={new_retention:.3f} | {entry['content'][:40]}"
            )

        if should_review(entry, now):
            review_count += 1

    save_index(entries)
    logger.info(
        f"decay 更新: 更新={updated_count}, "
        f"低保持率={forgot_count}, "
        f"要レビュー={review_count} / {len(entries)} 総エントリ"
    )


def get_consolidation_candidates(entries: list[dict] | None = None) -> list[dict]:
    """
    Layer 3 昇格候補のエントリを返す。

    条件:
      - recall_count >= CONSOLIDATION_MIN_RECALLS
      - retention >= CONSOLIDATION_MIN_RETENTION
      - layer == 2
    """
    if entries is None:
        entries = load_index()
    return [e for e in entries if is_consolidation_candidate(e)]


def run_consolidation(dry_run: bool = False):
    """
    統合処理: Layer 2 エピソード記憶 → Layer 3 パーソナリティ層

    統合候補エントリを personality_layer.json に移動し、
    元エントリの layer を 3 に更新する。
    """
    entries = load_index()
    candidates = get_consolidation_candidates(entries)

    if not candidates:
        logger.info("統合候補なし")
        return

    logger.info(f"統合候補: {len(candidates)} 件")
    for c in candidates:
        logger.info(f"  - [{c['id']}] {c['content'][:60]} (recall={c['recall_count']}, R={c.get('retention', 0):.3f})")

    if dry_run:
        logger.info("[DRY RUN] 統合を実行しません")
        return

    # personality_layer.json を読み込み
    PERSONALITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if PERSONALITY_PATH.exists():
        with open(PERSONALITY_PATH, "r", encoding="utf-8") as f:
            personality = json.load(f)
    else:
        personality = {
            "version": "1.0",
            "description": "VibeちゃんBotの体に刻まれた知識・人格要素",
            "entries": []
        }

    existing_ids = {e["id"] for e in personality.get("entries", [])}
    newly_consolidated = 0

    for entry in entries:
        if not is_consolidation_candidate(entry):
            continue
        if entry["id"] in existing_ids:
            entry["layer"] = 3  # 既存統合済みとしてマーク
            continue

        # パーソナリティ層エントリに変換
        personality_entry = {
            "id": entry["id"],
            "content": entry["content"],
            "source": entry.get("source", "unknown"),
            "tags": entry.get("tags", []),
            "recall_count": entry.get("recall_count", 0),
            "consolidated_at": datetime.now(JST).isoformat(),
            "original_created_at": entry.get("created_at", ""),
        }
        personality["entries"].append(personality_entry)
        entry["layer"] = 3
        newly_consolidated += 1

    # 保存
    with open(PERSONALITY_PATH, "w", encoding="utf-8") as f:
        json.dump(personality, f, ensure_ascii=False, indent=2)

    save_index(entries)
    logger.info(f"統合完了: {newly_consolidated} 件を Layer 3 に昇格")
    logger.info(f"personality_layer.json: {len(personality['entries'])} 総エントリ")


# ────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────

def cmd_add(args):
    """エントリ追加コマンド"""
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    entry = add_entry(
        content=args.content,
        source=args.source,
        user_id=args.user_id or "",
        tags=tags,
    )
    print(json.dumps(entry, ensure_ascii=False, indent=2))


def cmd_recall(args):
    """リコールコマンド"""
    entries = load_index()
    target = next((e for e in entries if e["id"] == args.id), None)
    if not target:
        logger.error(f"エントリが見つかりません: {args.id}")
        sys.exit(1)

    quality = int(args.quality)
    updated = recall_entry(target, quality)

    # インデックス更新
    for i, e in enumerate(entries):
        if e["id"] == args.id:
            entries[i] = updated
            break

    save_index(entries)
    print(f"リコール完了: {updated['id']}")
    print(f"  strength: {target.get('strength', 1.0):.3f} → {updated['strength']:.3f}")
    print(f"  EF: {target.get('ef', 2.5):.3f} → {updated['ef']:.3f}")
    print(f"  interval: {updated['interval_days']} 日")
    print(f"  next_review: {updated['next_review']}")


def cmd_decay(args):
    """忘却曲線更新コマンド"""
    run_decay_update()


def cmd_consolidate(args):
    """統合コマンド"""
    if args.show:
        entries = load_index()
        candidates = get_consolidation_candidates(entries)
        if not candidates:
            print("統合候補なし")
            return
        print(f"統合候補: {len(candidates)} 件")
        for c in candidates:
            print(f"  [{c['id']}] recall={c['recall_count']}, "
                  f"R={compute_retention(c):.3f}, {c['content'][:60]}")
    else:
        run_consolidation(dry_run=args.dry_run)


def cmd_list(args):
    """一覧表示コマンド"""
    entries = load_index()
    if not entries:
        print("エントリなし")
        return

    now = datetime.now(JST)
    # retention を最新値で更新して表示
    entries_with_retention = [
        {**e, "retention": compute_retention(e, now)}
        for e in entries
    ]
    # retention 降順
    entries_with_retention.sort(key=lambda e: -e.get("retention", 0))

    print(f"{'ID':<16} {'retention':>9} {'recall':>6} {'strength':>8} {'layer':>5}  content")
    print("-" * 80)
    for e in entries_with_retention:
        print(
            f"{e['id']:<16} "
            f"{e.get('retention', 0):>9.3f} "
            f"{e.get('recall_count', 0):>6} "
            f"{e.get('strength', 1.0):>8.3f} "
            f"{e.get('layer', 2):>5}  "
            f"{e.get('content', '')[:45]}"
        )


def cmd_search(args):
    """検索コマンド"""
    entries = load_index()
    results = bm25_search_memory(args.query, entries, top_k=int(args.top_k))

    if not results:
        print(f"'{args.query}' に一致するエントリなし")
        return

    print(f"検索結果: '{args.query}' ({len(results)} 件)")
    for entry, score in results:
        print(f"  [{entry['id']}] score={score:.4f} | {entry.get('content', '')[:60]}")


def main():
    parser = argparse.ArgumentParser(
        description="VibeCordingBot エピソード記憶マネージャ",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = subparsers.add_parser("add", help="エントリ追加")
    p_add.add_argument("--content", required=True, help="記憶内容")
    p_add.add_argument("--source", default="manual",
                       choices=["conversation", "article", "manual"],
                       help="記憶ソース")
    p_add.add_argument("--user-id", default="", help="ユーザーID")
    p_add.add_argument("--tags", default="", help="タグ (カンマ区切り)")
    p_add.set_defaults(func=cmd_add)

    # recall
    p_recall = subparsers.add_parser("recall", help="リコール実行")
    p_recall.add_argument("--id", required=True, help="エントリID")
    p_recall.add_argument("--quality", default=4,
                          help="品質スコア 0〜5 (default: 4)")
    p_recall.set_defaults(func=cmd_recall)

    # decay
    p_decay = subparsers.add_parser("decay", help="忘却曲線更新 (全エントリ)")
    p_decay.set_defaults(func=cmd_decay)

    # consolidate
    p_cons = subparsers.add_parser("consolidate", help="Layer 3 統合")
    p_cons.add_argument("--show", action="store_true", help="候補を表示のみ")
    p_cons.add_argument("--dry-run", action="store_true", help="実行しない")
    p_cons.set_defaults(func=cmd_consolidate)

    # list
    p_list = subparsers.add_parser("list", help="全エントリ一覧")
    p_list.set_defaults(func=cmd_list)

    # search
    p_search = subparsers.add_parser("search", help="BM25 検索")
    p_search.add_argument("--query", required=True, help="検索クエリ")
    p_search.add_argument("--top-k", default=5, help="取得件数 (default: 5)")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
