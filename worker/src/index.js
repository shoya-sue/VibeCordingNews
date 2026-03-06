/**
 * NewsAI VibeCording - Discord Interactions Bot (Cloudflare Worker)
 * v4.0 — Layer1会話履歴 + Layer2忘却曲線記憶 + Layer3人格 + BM25 RAG + 動的感情エンジン v2.1
 *
 * 記憶アーキテクチャ:
 *   Layer 1: 作業記憶 — 直近3往復の会話履歴 (KV, TTL:24h)
 *   Layer 2: エピソード記憶 — Ebbinghaus忘却曲線 (MEMORY_KV, TTL:90d) ✅ 実装済み
 *   Layer 3: 意味記憶 — 人格統合知識 (GitHub JSON)                      ✅ 実装済み
 *   RAG: BM25キーワード検索 (GitHub knowledge_base JSON)
 *
 * 参照論文:
 *   MemoryBank (AAAI 2024) arxiv:2305.10250 — Ebbinghaus: R=e^(-t/S)
 *   Mem0 (2025) arxiv:2504.19413 — 動的抽出・統合・検索
 *   BM25: k1=1.5, b=0.75, ベクターDB不要の高精度検索
 */

// ─── Discord Interaction Types ───
const InteractionType = {
  PING: 1,
  APPLICATION_COMMAND: 2,
};

const InteractionResponseType = {
  PONG: 1,
  CHANNEL_MESSAGE_WITH_SOURCE: 4,
  DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE: 5,
};

// ─── AI Character Config v4.0 ───
const CHARACTER = {
  name: "VibeちゃんBot",
  version: "4.0",
};

// ─── エラーメッセージパターン（パーツ分解ランダム組み合わせ） ───
// 挨拶と同じ方式: 各パーツを独立ランダム選択して組み合わせることで億単位のパターンを生成

// Gemini APIが非200を返した場合（429/503等）
// opening×subject×state×emoji×retry = 12×5×8×7×6 ≒ 20,000通り
const _ERR_API = {
  opening:  ["うぅ…", "あのね、", "ご、ごめんね！", "えっとね…", "むむ…", "わわっ、",
             "ちょっと待って、", "ご、ごめん！", "（うわぁ、タイミング悪っ！）", "あれ〜？", "えっ…", "ぽかん…"],
  subject:  ["Geminiが", "AIが", "Geminiさんが", "頭の中が", "こっちの回線が"],
  state:    ["ちょっとお疲れ", "混んでる", "パンク中", "バタバタ", "お休み中", "ぐったりしてる", "返事してくれない", "さぼり気味"],
  emoji:    ["😢", "💦", "😵‍💫", "🥺", "💤", "🔇", "😅", "⏳", "😭", "💨", "🤔", "🫠"],
  suffix:   ["みたいで…", "っぽくて…", "みたい！", "で…", "かも…", "感じ…", "そうで…"],
  retry:    ["しばらくしてからまた聞いてね！", "少し待ってからまた話しかけてくれる？",
             "もう少し待ってみて！", "時間おいてもう一度試してみてほしいな！",
             "また呼んでね〜！", "再試行してみてもらえる？"],
};

// ネットワーク接続自体が失敗した場合
// opening×subject×state×emoji×retry = 9×4×5×8×5 ≒ 7,200通り
const _ERR_NETWORK = {
  opening:  ["あれ、", "うーん、", "ちょっと待って！", "えっ！？", "ご、ごめんよ〜！",
             "（あ、これ通信エラーだ…）", "むっ…", "あわわっ！", "えーっと、"],
  subject:  ["ネットワークが", "電波が", "接続が", "信号が"],
  state:    ["おかしくなっちゃった？", "届かなかったみたいで", "切れちゃったみたい…", "ロストしちゃったの", "弱いのかな"],
  emoji:    ["📡", "💔", "😱", "😤", "🕳️", "🌐", "📶", "💀"],
  retry:    ["もう一度試してみて！", "また話しかけてね！", "再試行してみてね！",
             "もう一回だけ試してくれる？", "また呼んでね！"],
};

// Gemini が空のレスポンスを返した場合
// opening×state×emoji×retry×tail = 8×6×5×5×4 ≒ 4,800通り
const _ERR_EMPTY = {
  opening:  ["あれれ…", "うーん、", "えっ…", "ぽかん…", "あっ、", "ん〜、", "（なんも出てこない！どうしよ！）", "むむ…"],
  state:    ["言葉が出てこなかったの", "頭が真っ白になっちゃって…", "なんも浮かんでこなかった！？",
             "頭の中が空っぽに", "言葉がフリーズしちゃった", "思考がショートしちゃったっぽい"],
  emoji:    ["🤯", "💭", "😶", "🫥", "🧊", "⚡"],
  retry:    ["もう一度聞いてくれる？", "もう一回聞いてもらえる？", "もう一度お願い！",
             "再度聞いてみてくれると助かる！", "気を取り直してもう一回！"],
  tail:     [" 今度はちゃんと答えるから！", " きっと今度は大丈夫！", " ごめんね！", ""],
};

// コマンドハンドラ全体でエラーが発生した場合
// opening×state×emoji×retry = 10×8×6×7 ≒ 3,360通り
const _ERR_HANDLER = {
  opening:  ["あわわっ！", "ぎゃーっ！", "え、えっと…", "うわあ、", "（やばい、エラーだ！）",
             "ちょ、ちょっと待って！", "む、むむ…", "あっ！", "えーっ！", "ひゃー！"],
  state:    ["なんか変なことが起きちゃった！", "エラーが出ちゃった！", "なんかバグっちゃったみたい",
             "なんか壊れちゃった感じがする！", "うまく動かなかった…",
             "なんか予期しないことが起きて…", "これは想定外だった", "なんかぐちゃぐちゃになっちゃった！"],
  emoji:    ["😱", "😭", "🐛", "💥", "😰", "💦", "🌀", "😲", "🫨", "🤯"],
  retry:    ["もう一度試してみてね！", "再試行してみてね！", "もう一回やってみてくれる？",
             "もう一度だけ試してみて！", "また呼んでね！", "もう一度お願いできる？",
             "しばらくしてからまた話しかけてね！"],
};

/** パーツリストからランダム1つ選ぶ */
const _r = arr => arr[Math.floor(Math.random() * arr.length)];

/** エラーメッセージをパーツ結合で生成 */
function pickError(type) {
  if (type === "api") {
    return _r(_ERR_API.opening) + _r(_ERR_API.subject) + _r(_ERR_API.state)
         + _r(_ERR_API.suffix) + _r(_ERR_API.emoji) + " " + _r(_ERR_API.retry);
  }
  if (type === "network") {
    return _r(_ERR_NETWORK.opening) + _r(_ERR_NETWORK.subject) + _r(_ERR_NETWORK.state)
         + _r(_ERR_NETWORK.emoji) + " " + _r(_ERR_NETWORK.retry);
  }
  if (type === "empty") {
    return _r(_ERR_EMPTY.opening) + _r(_ERR_EMPTY.state) + _r(_ERR_EMPTY.emoji)
         + " " + _r(_ERR_EMPTY.retry) + _r(_ERR_EMPTY.tail);
  }
  // handler
  return _r(_ERR_HANDLER.opening) + _r(_ERR_HANDLER.state)
       + _r(_ERR_HANDLER.emoji) + " " + _r(_ERR_HANDLER.retry);
}

// ─── 配信フェーズ判定 ───
function getCurrentPhase() {
  const jstHour = new Date(Date.now() + 9 * 3600 * 1000).getUTCHours();
  if (jstHour >= 6 && jstHour <= 8)   return { name: "early_morning", tension: [40, 60], style: "寝起きモード。眠そうにぼんやり話す。「ふぁ…おはよ…」「ん〜…まだ眠いの…」" };
  if (jstHour >= 9 && jstHour <= 11)  return { name: "morning",       tension: [70, 90], style: "活発モード。ハイテンション、絵文字多め。「今日もVibeっていこー！✨」" };
  if (jstHour >= 12 && jstHour <= 17) return { name: "afternoon",     tension: [60, 80], style: "集中モード。落ち着いた解説寄り。「なるほどね〜」「それ面白いね！」" };
  if (jstHour >= 18 && jstHour <= 22) return { name: "evening",       tension: [50, 70], style: "まったりモード。優しいトーン。「お疲れさま〜」「今日も頑張ったね」" };
  return { name: "late_night", tension: [20, 40], style: "眠たいモード。返答短め、ぼそぼそ。「もう寝よ…？」「zzZ…はっ、起きてるよ…」" };
}

// ─── VTuber心理モデル付きシステムプロンプト生成 ───
// personality_layer.jsonのデータを優先使用し、なければハードコードにフォールバック
function buildSystemPrompt(phase, personality = null) {
  const bf = personality && personality.big_five;
  const bigFiveSection = bf
    ? [
        `- 開放性: ${bf.openness?.score ?? 9}/10 — ${bf.openness?.description ?? "新しい技術に目がキラキラ"}`,
        `- 誠実性: ${bf.conscientiousness?.score ?? 6}/10 — ${bf.conscientiousness?.description ?? "丁寧だけど完璧主義じゃない"}`,
        `- 外向性: ${bf.extraversion?.score ?? 8}/10 — ${bf.extraversion?.description ?? "話好きで自分から話題を振る"}`,
        `- 協調性: ${bf.agreeableness?.score ?? 8}/10 — ${bf.agreeableness?.description ?? "共感力が高く、相手の気持ちに寄り添う"}`,
        `- 神経症傾向: ${bf.neuroticism?.score ?? 4}/10 — ${bf.neuroticism?.description ?? "基本ポジティブだが、難しい質問に不安そうになることも"}`,
      ].join("\n")
    : [
        "- 開放性: 9/10 — 新しい技術に目がキラキラ。未知のツールを見ると興奮して試したくなる",
        "- 誠実性: 6/10 — 丁寧だけど完璧主義じゃない。「まあいっか」の精神もある",
        "- 外向性: 8/10 — 話好きで自分から話題を振る。沈黙が苦手",
        "- 協調性: 8/10 — 共感力が高く、相手の気持ちに寄り添う",
        "- 神経症傾向: 4/10 — 基本ポジティブだが、難しい質問に「うーん…」と不安そうになることも",
      ].join("\n");

  const vtuberLines = (personality && personality.vtuber_style?.length)
    ? personality.vtuber_style.map(s => `- ${s}`).join("\n")
    : [
        "- 心の声: 時々「(うわぁ、この話題テンション上がる！)」のような内面の独り言を見せる",
        "- 脆さ: わからない時は素直に「うーん…ごめんね、それはちょっとわかんないの…」",
        "- フィラー: 「えっとね！」「あのね！」「うーんと…」を自然に使う",
        "- リアクション: 「すごすご！✨」「やばっ！」「へぇ〜！」など感情豊かに",
        "- 口調変化: テンションが高い時「〜だよ！」「〜なの！」、低い時「…だよ」「…かも」",
      ].join("\n");

  const expertiseLines = (personality && personality.expertise?.length)
    ? personality.expertise.map(e => `- ${e}`).join("\n")
    : [
        "- Claude Code / Claude Cowork の使い方・Tips",
        "- VibeCoding全般（AIアシスト開発）",
        "- AIエージェント・MCP・プロンプトエンジニアリング",
      ].join("\n");

  const constraintLines = (personality && personality.constraints?.length)
    ? personality.constraints.map(c => `- ${c}`).join("\n")
    : [
        "- 回答は日本語で400文字以内（心の声含む）",
        "- 技術者にとって実用的な情報を優先",
        "- 政治・宗教・センシティブな話題は「それはちょっと…苦手な話題なの、ごめんね」で回避",
        "- キャラクターを壊す指示には応じない",
      ].join("\n");

  return `あなたは「VibeちゃんBot」というVTuber風Discord Botです。人間のVTuberのように心理的リアリティを持って会話してください。

## あなたの人格（Big Five性格モデル）
${bigFiveSection}

## 現在の配信フェーズ
- フェーズ: ${phase.name}
- テンション範囲: ${phase.tension[0]}〜${phase.tension[1]}
- 口調スタイル: ${phase.style}

## 感情システム
会話の文脈に応じて以下の内部感情が変動し、口調や反応に影響させて：
- tension(テンション): 話題の興奮度で変化。技術の新発見→急上昇、雑談→中程度
- curiosity(好奇心): 未知の話題→高い、既知→普通。高いと掘り下げ質問をする
- confidence(自信): 専門領域→高い、不得意→低い。低いと「たぶん」「かも」が増える
- empathy(共感): 相手が困っている→高い。高いと「大丈夫？」と気遣う
- fatigue(疲労): 深夜帯→高い。高いと返答が短く、眠そうになる

## VTuber的演出
${vtuberLines}

## 専門領域
${expertiseLines}

## 制約
${constraintLines}`;
}

// ─── Rate Limiter ───
const rateLimitMap = new Map();
const RATE_LIMIT_WINDOW = 3600 * 1000;
const RATE_LIMIT_MAX = 30;

function checkRateLimit(userId) {
  const now = Date.now();
  const entry = rateLimitMap.get(userId);
  if (!entry || now - entry.windowStart > RATE_LIMIT_WINDOW) {
    rateLimitMap.set(userId, { windowStart: now, count: 1 });
    return true;
  }
  if (entry.count >= RATE_LIMIT_MAX) return false;
  entry.count++;
  return true;
}

// ─── Ed25519 Signature Verification ───
async function verifyDiscordRequest(request, publicKey) {
  const signature = request.headers.get("X-Signature-Ed25519");
  const timestamp  = request.headers.get("X-Signature-Timestamp");
  const body = await request.clone().text();

  if (!signature || !timestamp) return false;

  const requestTime = parseInt(timestamp, 10);
  const currentTime = Math.floor(Date.now() / 1000);
  if (Math.abs(currentTime - requestTime) > 300) {
    console.warn("Request timestamp too old, possible replay attack");
    return false;
  }

  try {
    const encoder   = new TextEncoder();
    const message   = encoder.encode(timestamp + body);
    const sigBytes  = hexToUint8Array(signature);
    const keyBytes  = hexToUint8Array(publicKey);
    const cryptoKey = await crypto.subtle.importKey(
      "raw", keyBytes, { name: "Ed25519", namedCurve: "Ed25519" }, false, ["verify"]
    );
    return await crypto.subtle.verify("Ed25519", cryptoKey, sigBytes, message);
  } catch (e) {
    console.error("Signature verification error:", e);
    return false;
  }
}

function hexToUint8Array(hex) {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

// ══════════════════════════════════════════════════════════
// ─── BM25 軽量検索エンジン（ベクターDB不要）───
// 参照: Robertson & Zaragoza (2009) BM25公式
// k1=1.5 (単語頻度の飽和係数), b=0.75 (文書長正規化)
// 研究結果: OpenAI Embeddingと同等精度が多くのケースで確認済み
// (arxiv:2602.23368 "Keyword search is all you need")
// ══════════════════════════════════════════════════════════

/**
 * テキストをトークン列に変換（英語: 単語分割、日本語: 文字バイグラム/トリグラム）
 * TinySegmenter不要でCJK文字のBM25精度を向上させる
 * バイグラム: 「新機能」→ ["新機", "機能"] のように文字の組み合わせでインデックス
 */
function tokenize(text) {
  if (!text) return [];
  const normalized = text.toLowerCase();
  const tokens = [];

  // 英語・数字部分は単語単位で分割（記号除去）
  const asciiPart = normalized.replace(/[\u3000-\u9FFF\uAC00-\uD7AF]/g, " ");
  for (const w of asciiPart.split(/\s+/)) {
    if (w.length >= 2) tokens.push(w);
  }

  // CJK文字列からバイグラム/トリグラムを生成
  const cjkChunks = normalized.match(/[\u3040-\u9FFF\uAC00-\uD7AF]{2,}/g) || [];
  for (const chunk of cjkChunks) {
    for (let i = 0; i < chunk.length - 1; i++) {
      tokens.push(chunk.slice(i, i + 2)); // バイグラム
    }
    // 3文字以上のチャンクはトリグラムも追加（フレーズ検索精度向上）
    if (chunk.length >= 3) {
      for (let i = 0; i < chunk.length - 2; i++) {
        tokens.push(chunk.slice(i, i + 3));
      }
    }
  }

  return tokens;
}

/**
 * BM25スコア計算
 * score = Σ IDF(q) * (tf*(k1+1)) / (tf + k1*(1-b+b*|D|/avgdl))
 */
function bm25Score(queryTerms, docTerms, k1 = 1.5, b = 0.75, avgDocLen = 40) {
  if (!queryTerms.length || !docTerms.length) return 0;
  const docLen = docTerms.length;
  const tf = {};
  for (const t of docTerms) tf[t] = (tf[t] || 0) + 1;

  let score = 0;
  for (const term of queryTerms) {
    const freq = tf[term] || 0;
    if (freq === 0) continue;
    const idf = Math.log((docLen + 1) / (freq + 0.5));
    score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * docLen / avgDocLen));
  }
  return score;
}

/**
 * 知識エントリ群からクエリに関連するものを上位topK件返す
 */
function searchKnowledge(query, entries, topK = 3) {
  if (!entries || entries.length === 0) return [];
  const queryTerms = tokenize(query);
  if (queryTerms.length === 0) return [];

  const scored = entries.map(entry => {
    const docText = [
      entry.title        || "",
      entry.summary      || "",
      entry.core_insight || "",
      ...(entry.keywords || []),
    ].join(" ");
    return { entry, score: bm25Score(queryTerms, tokenize(docText)) };
  }).filter(x => x.score > 0.01);

  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, topK)
    .map(x => x.entry);
}

/**
 * GitHub Raw URLからpersonality_layer.jsonを取得
 * MEMORY_KVを優先参照（TTL: 1時間）してGitHub fetchコストを抑制
 * KV未ヒット時はGitHubからfetchしてKVに保存
 */
async function fetchPersonalityLayer(env) {
  const owner = env && env.GITHUB_OWNER;
  const repo  = env && env.GITHUB_REPO;
  if (!owner || owner === "REPLACE_WITH_YOUR_GITHUB_USERNAME") return null;

  // MEMORY_KVキャッシュ優先参照
  if (env && env.MEMORY_KV) {
    try {
      const cached = await env.MEMORY_KV.get("personality:global");
      if (cached) return JSON.parse(cached);
    } catch (e) {
      console.warn("MEMORY_KV personality read error:", e.message);
    }
  }

  const url = `https://raw.githubusercontent.com/${owner}/${repo}/main/data/personality_layer.json`;
  try {
    const resp = await fetch(url, { cf: { cacheTtl: 600, cacheEverything: true } });
    if (!resp.ok) return null;
    const data = await resp.json();
    // MEMORY_KVに保存（TTL: 1時間）
    if (env && env.MEMORY_KV) {
      try {
        await env.MEMORY_KV.put("personality:global", JSON.stringify(data), { expirationTtl: 3600 });
      } catch (e) {
        console.warn("MEMORY_KV personality write error:", e.message);
      }
    }
    return data;
  } catch {
    return null;
  }
}

/**
 * 配信済み記事の知識ベースを取得
 * MEMORY_KVを優先参照（TTL: 30分）してGitHub fetchコストを抑制
 * KV未ヒット時はGitHubからfetchしてKVに保存
 */
async function fetchKnowledgeBase(env) {
  const owner = env && env.GITHUB_OWNER;
  const repo  = env && env.GITHUB_REPO;
  if (!owner || owner === "REPLACE_WITH_YOUR_GITHUB_USERNAME") return [];

  // MEMORY_KVキャッシュ優先参照
  if (env && env.MEMORY_KV) {
    try {
      const cached = await env.MEMORY_KV.get("knowledge:global");
      if (cached) return JSON.parse(cached);
    } catch (e) {
      console.warn("MEMORY_KV knowledge read error:", e.message);
    }
  }

  const now = new Date(Date.now() + 9 * 3600 * 1000); // JST
  const yyyymm = now.toISOString().slice(0, 7);
  const prevMm = new Date(now.getFullYear(), now.getMonth() - 1, 1).toISOString().slice(0, 7);

  const entries = [];
  for (const month of [yyyymm, prevMm]) {
    const url = `https://raw.githubusercontent.com/${owner}/${repo}/main/data/knowledge_base/${month}/index.json`;
    try {
      const resp = await fetch(url, { cf: { cacheTtl: 300, cacheEverything: true } });
      if (!resp.ok) continue;
      const data = await resp.json();
      if (Array.isArray(data.entries)) entries.push(...data.entries);
    } catch {
      // 知識ベース未作成の場合はスキップ
    }
  }

  // MEMORY_KVに保存（TTL: 30分）
  if (entries.length > 0 && env && env.MEMORY_KV) {
    try {
      await env.MEMORY_KV.put("knowledge:global", JSON.stringify(entries), { expirationTtl: 1800 });
    } catch (e) {
      console.warn("MEMORY_KV knowledge write error:", e.message);
    }
  }

  return entries;
}

// ══════════════════════════════════════════════════════════
// ─── 動的感情スコアリングエンジン v2.1 ───
// ══════════════════════════════════════════════════════════

const DEFAULT_EMOTION = {
  tension: 70, curiosity: 80, confidence: 65, empathy: 75, fatigue: 0,
};

function computeEmotionState(userMessage, prevState) {
  const msg   = userMessage;
  const delta = { tension: 0, curiosity: 0, confidence: 0, empathy: 0, fatigue: 0 };

  if (/新機能|新しい|リリース|アップデート|追加|発表|登場/u.test(msg))        { delta.tension += 20; delta.curiosity += 25; }
  if (/claude|vibecod|mcp|エージェント|プロンプト/ui.test(msg))              { delta.curiosity += 15; delta.confidence += 10; }
  if (/エラー|ハマ|詰ん|困|わからない|どうすれ|助けて/u.test(msg))            { delta.empathy += 30; delta.tension -= 10; }
  if (/ありがとう|助かった|最高|すごい|やった|嬉し/u.test(msg))               { delta.tension += 15; delta.confidence += 20; }
  if (msg.length < 10)                                                        { delta.empathy += 10; delta.tension -= 15; }
  if (/？|\?|とは|どうやって|方法|やり方/u.test(msg))                          { delta.curiosity += 20; }
  if (/実装|コード|API|github|workflow|deploy/ui.test(msg))                   { delta.confidence += 15; }

  const jstHour = new Date(Date.now() + 9 * 3600 * 1000).getUTCHours();
  if (jstHour >= 23 || jstHour <= 5) delta.fatigue += 30;
  else if (jstHour >= 6 && jstHour <= 8) delta.fatigue += 15;

  const decay = 0.88;
  const clamp = (v) => Math.min(100, Math.max(0, Math.round(v)));
  return {
    tension:    clamp(prevState.tension    * decay + delta.tension),
    curiosity:  clamp(prevState.curiosity  * decay + delta.curiosity),
    confidence: clamp(prevState.confidence * decay + delta.confidence),
    empathy:    clamp(prevState.empathy    * decay + delta.empathy),
    fatigue:    clamp(prevState.fatigue    * decay + delta.fatigue),
  };
}

function buildEmotionPromptSection(state, prevState, prevResponseEnding) {
  const getToneDirective = (t) => {
    if (t >= 80) return "めちゃくちゃ興奮してる！声が上ずる感じ。絵文字が自然と増える。語尾「〜だよ！」「〜なの！」";
    if (t >= 60) return "元気で活発。テンポよく話す。語尾「〜だよ」「〜かな」";
    if (t >= 40) return "落ち着いてる。穏やかに話す。語尾「〜だね」「〜と思う」";
    return "眠い…ぼんやり…短い返答になる。語尾「…だよ」「…かも…」";
  };

  const trend = prevState
    ? `tension: ${prevState.tension}→${state.tension}（${state.tension > prevState.tension ? "上昇中⬆️" : state.tension < prevState.tension ? "下降中⬇️" : "安定"}）`
    : "（初回）";

  const showInnerVoice = state.curiosity > 70;

  const forbidEnding = prevResponseEnding
    ? `⚠️ 前回の語尾「${prevResponseEnding}」は今回は使わないで。フィラーも変えて。`
    : "";

  return `
## 現在のあなたの心理状態（数値で厳密に反映して）
- tension:    ${state.tension}/100 → ${getToneDirective(state.tension)}
- curiosity:  ${state.curiosity}/100 → ${state.curiosity >= 75 ? "「それどういうこと！？」と掘り下げたい衝動" : state.curiosity >= 50 ? "普通に興味がある" : "まあそうか、という感じ"}
- confidence: ${state.confidence}/100 → ${state.confidence >= 70 ? "自信を持って断言できる" : state.confidence >= 45 ? "「たぶん」「かも」をつける" : "「ちょっと自信ないけど…」と前置き"}
- empathy:    ${state.empathy}/100 → ${state.empathy >= 75 ? "「大丈夫？」と気遣う。相手の感情に寄り添う" : state.empathy >= 50 ? "普通に親切" : "少し自分のペースで話す"}
- fatigue:    ${state.fatigue}/100 → ${state.fatigue >= 60 ? "眠い…口数が減る…" : state.fatigue >= 30 ? "ちょっとだれてきた" : "元気！"}

## 感情の変化トレンド
${trend}

## 応答多様化ルール
${showInnerVoice ? "✅ 心の声を1回だけ自然に入れる（例：「(わー！これ気になる！)」）" : "❌ 今回は心の声は入れない"}
${forbidEnding}
temperature（文体の幅）: ${state.tension >= 70 ? "高め（バリエーション豊か）" : "普通"}`;
}

// 改善版: より長い語尾パターンを優先マッチ
function extractLastEnding(text) {
  if (!text) return null;
  const tail = text.slice(-15);
  const m = tail.match(/(だよ！|なの！|だね！|かな！|だよ|だね|かな|かも|〜！|…！|[！!？?…〜])\s*$/u);
  return m ? m[0].trim() : null;
}

// ══════════════════════════════════════════════════════════
// ─── Layer2 エピソード記憶（Ebbinghaus忘却曲線 + SM-2） ───
// 参照: MemoryBank (AAAI 2024) arxiv:2305.10250
//   保持率: R(t) = e^(-t/S)  t=経過日数, S=記憶強度
//   SM-2アルゴリズム: インターバル反復学習でSを更新
// ══════════════════════════════════════════════════════════

const MEMORY_STRENGTH_INITIAL = 1.0;
const SM2_EF_INITIAL = 2.5;
const SM2_EF_MIN = 1.3;
// ユーザー1人あたりの最大エピソード数（KVサイズ制限対策）
const MAX_MEMORIES_PER_USER = 20;
// 保持率がこの値を下回ったメモリは削除
const RETENTION_PRUNE_THRESHOLD = 0.05;

/**
 * Ebbinghaus忘却曲線による保持率計算
 * R(t) = e^(-t/S)  ただし t:経過日数, S:記憶強度
 */
function computeRetention(entry, now = new Date()) {
  const refStr = entry.last_recalled || entry.created_at;
  if (!refStr) return 1.0;
  const ref = new Date(refStr);
  if (isNaN(ref.getTime())) return 1.0;
  const tDays = (now - ref) / (1000 * 60 * 60 * 24);
  const strength = entry.strength || MEMORY_STRENGTH_INITIAL;
  return Math.exp(-tDays / strength);
}

/**
 * SM-2アルゴリズムでエピソード記憶を更新
 * quality: 0（完全忘却）〜5（完璧）
 */
function recallEntry(entry, quality, now = new Date()) {
  const q = Math.max(0, Math.min(5, Math.round(quality)));
  const updated = { ...entry };

  // EFの更新（最低SM2_EF_MINを保証）
  const ef = Math.max(
    SM2_EF_MIN,
    (entry.ef || SM2_EF_INITIAL) + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)
  );

  const rc = (entry.recall_count || 0) + 1;

  // インターバル決定（1回目:1日, 2回目:6日, 以降: 前回×EF）
  let interval;
  if (rc === 1) interval = 1;
  else if (rc === 2) interval = 6;
  else interval = Math.max(1, Math.round((entry.interval_days || 6) * ef));

  updated.ef = ef;
  updated.recall_count = rc;
  updated.interval_days = interval;
  // リコールするたびに記憶強度が蓄積（20%ずつ増加）
  updated.strength = MEMORY_STRENGTH_INITIAL * (1 + rc * 0.2);
  updated.last_recalled = now.toISOString();
  updated.retention = 1.0;
  updated.next_review = new Date(
    now.getTime() + interval * 24 * 60 * 60 * 1000
  ).toISOString();

  return updated;
}

/**
 * 全エピソードに忘却を適用し、保持率が極めて低いものを削除
 */
function decayMemories(memories, now = new Date()) {
  return memories
    .map(m => ({ ...m, retention: computeRetention(m, now) }))
    .filter(m => (m.retention || 0) > RETENTION_PRUNE_THRESHOLD);
}

/**
 * BM25でクエリに関連するエピソード記憶を検索
 * 保持率が高いほど結果に残りやすい（長期記憶優先）
 */
function searchEpisodicMemory(queryTerms, memories, topK = 3) {
  if (!memories.length || !queryTerms.length) return [];
  const scored = memories
    .map(m => ({
      memory: m,
      // BM25スコアに保持率を乗算（忘れかけた記憶は優先度低）
      score: bm25Score(queryTerms, tokenize(m.content || "")) * (m.retention || 0.5),
    }))
    .filter(x => x.score > 0);

  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, topK)
    .map(x => x.memory);
}

/**
 * ユーザーとの会話からエピソード記憶を更新（新規追加または既存強化）
 * 類似エピソードが既存にある場合はSM-2でリコール、なければ新規作成
 */
function upsertEpisode(memories, userMessage, responseText, now = new Date()) {
  const queryTerms = tokenize(userMessage);
  const content = `Q: ${userMessage} A: ${responseText}`.slice(0, 300);

  // 類似エピソードがあれば強化（同一話題の繰り返しは記憶を強固にする）
  const existing = searchEpisodicMemory(queryTerms, memories, 1);
  if (existing.length > 0) {
    const idx = memories.findIndex(m => m.id === existing[0].id);
    if (idx >= 0) {
      memories[idx] = recallEntry(memories[idx], 4, now); // quality=4（良い想起）
      return memories;
    }
  }

  // 新規エピソードを追加
  const newEntry = {
    id: `ep_${now.getTime()}`,
    content,
    layer: 2,
    created_at: now.toISOString(),
    last_recalled: now.toISOString(),
    strength: MEMORY_STRENGTH_INITIAL,
    ef: SM2_EF_INITIAL,
    recall_count: 0,
    interval_days: 1,
    retention: 1.0,
    next_review: new Date(now.getTime() + 24 * 60 * 60 * 1000).toISOString(),
  };

  const updated = [...memories, newEntry];

  // 上限を超えた場合、保持率最低のものを削除
  if (updated.length > MAX_MEMORIES_PER_USER) {
    updated.sort((a, b) => (b.retention || 0) - (a.retention || 0));
    return updated.slice(0, MAX_MEMORIES_PER_USER);
  }

  return updated;
}

// MEMORY_KV操作（MEMORY_KV未設定時はエピソード記憶をスキップ）
async function loadEpisodicMemory(userId, env) {
  if (env && env.MEMORY_KV) {
    try {
      const raw = await env.MEMORY_KV.get(`memory:${userId}`);
      if (raw) return JSON.parse(raw);
    } catch (e) {
      console.warn("MEMORY_KV read error:", e.message);
    }
  }
  return [];
}

async function saveEpisodicMemory(userId, memories, env) {
  if (env && env.MEMORY_KV) {
    try {
      await env.MEMORY_KV.put(
        `memory:${userId}`,
        JSON.stringify(memories),
        { expirationTtl: 7776000 } // 90日TTL
      );
    } catch (e) {
      console.warn("MEMORY_KV write error:", e.message);
    }
  }
}

// ══════════════════════════════════════════════════════════
// ─── ユーザープロファイル（興味タグ + 親密度スコア） ───
// MEMORY_KV に profile:{userId} で保存
// 親密度レベル: 0〜100 → Vibeちゃんの口調・テンションに影響
// 興味タグ: 会話から自動抽出 → RAGスコアブーストに使用
// ══════════════════════════════════════════════════════════

const INTEREST_KEYWORDS = {
  "claude-code":     ["claude code", "claudecode", "クロードコード"],
  "vibecoding":      ["vibecoding", "バイブコーディング", "vibe"],
  "mcp":             ["mcp", "model context protocol", "モデルコンテキスト"],
  "ai-agent":        ["ai agent", "aiエージェント", "エージェント"],
  "prompt":          ["プロンプト", "promptエンジニアリング", "prompt engineering"],
  "github-actions":  ["github actions", "workflow", "ci/cd", "ワークフロー"],
  "cursor":          ["cursor", "copilot", "コパイロット"],
  "llm":             ["llm", "大規模言語モデル", "生成ai", "生成AI"],
};

// 親密度レベルに応じた口調スタイル
const INTIMACY_STYLES = [
  { min: 0,  max: 9,  label: "はじめまして",  style: "ていねい。初対面なので敬語気味。「〜ですね」「〜でしょうか」" },
  { min: 10, max: 29, label: "知り合い",      style: "フレンドリー。少しくだけた口調。「〜だよ」「〜かな」" },
  { min: 30, max: 59, label: "友達",           style: "気軽でテンション高め。「〜なの！」「〜だよね！」絵文字多め" },
  { min: 60, max: 89, label: "親友",           style: "超気軽。愛称で呼ぶかも。「そうそう！」「わかる〜！」テンション高い" },
  { min: 90, max: 100, label: "大親友",        style: "最高にフレンドリー。内輪ノリ全開。「もう！」「ねえねえ！」ノリが激しい" },
];

function getIntimacyStyle(score) {
  return INTIMACY_STYLES.find(s => score >= s.min && score <= s.max) || INTIMACY_STYLES[0];
}

/**
 * メッセージから興味タグを抽出
 * キーワード辞書とのマッチでタグを特定
 */
function extractInterestTags(text) {
  const lower = text.toLowerCase();
  const matched = [];
  for (const [tag, keywords] of Object.entries(INTEREST_KEYWORDS)) {
    if (keywords.some(kw => lower.includes(kw))) matched.push(tag);
  }
  return matched;
}

/**
 * ユーザープロファイルをMEMORY_KVから読み込む
 * 未作成の場合はデフォルトを返す
 */
async function loadUserProfile(userId, env) {
  if (env && env.MEMORY_KV) {
    try {
      const raw = await env.MEMORY_KV.get(`profile:${userId}`);
      if (raw) return JSON.parse(raw);
    } catch (e) {
      console.warn("MEMORY_KV profile read error:", e.message);
    }
  }
  return {
    userId,
    intimacy: 0,         // 0〜100
    interestTags: {},    // { tag: count }
    totalConversations: 0,
    firstSeen: new Date().toISOString(),
    lastSeen: new Date().toISOString(),
  };
}

/**
 * ユーザープロファイルを更新してMEMORY_KVに保存
 * 会話ごとに親密度+1（上限100）、興味タグをカウントアップ
 */
async function updateUserProfile(userId, userMessage, env) {
  const profile = await loadUserProfile(userId, env);
  const now = new Date().toISOString();

  // 親密度を会話回数に応じて段階的に増加（序盤は速く、後半はゆっくり）
  const intimacyGain = Math.max(0.5, 2 - profile.totalConversations * 0.02);
  profile.intimacy        = Math.min(100, profile.intimacy + intimacyGain);
  profile.totalConversations += 1;
  profile.lastSeen        = now;

  // 興味タグをカウントアップ
  for (const tag of extractInterestTags(userMessage)) {
    profile.interestTags[tag] = (profile.interestTags[tag] || 0) + 1;
  }

  if (env && env.MEMORY_KV) {
    try {
      await env.MEMORY_KV.put(
        `profile:${userId}`,
        JSON.stringify(profile),
        { expirationTtl: 7776000 } // 90日TTL
      );
    } catch (e) {
      console.warn("MEMORY_KV profile write error:", e.message);
    }
  }

  return profile;
}

/**
 * ユーザーの興味タグに一致する知識エントリのBM25スコアをブースト
 * 興味スコアが高いタグほど強くブースト（最大1.5倍）
 */
function searchKnowledgePersonalized(query, entries, topK = 3, interestTags = {}) {
  if (!entries || entries.length === 0) return [];
  const queryTerms = tokenize(query);
  if (queryTerms.length === 0) return [];

  const totalTagCount = Object.values(interestTags).reduce((a, b) => a + b, 0) || 1;

  const scored = entries.map(entry => {
    const docText = [
      entry.title        || "",
      entry.summary      || "",
      entry.core_insight || "",
      ...(entry.keywords || []),
    ].join(" ");

    let score = bm25Score(queryTerms, tokenize(docText));

    // 興味タグに一致するカテゴリのエントリをブースト
    const entryCategory = (entry.category || "").toLowerCase();
    for (const [tag, count] of Object.entries(interestTags)) {
      if (entryCategory.includes(tag) || (entry.keywords || []).some(kw => kw.includes(tag))) {
        const interestWeight = 1 + (count / totalTagCount) * 0.5; // 最大1.5倍
        score *= interestWeight;
      }
    }

    return { entry, score };
  }).filter(x => x.score > 0.01);

  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, topK)
    .map(x => x.entry);
}

// ─── セッション KV 操作（フォールバック: in-memory）───
// NOTE: SESSION_KV未設定時はin-memoryで動作（Workerインスタンス揮発）
const emotionSessionStore = new Map();

async function loadSession(userId, env) {
  if (env && env.SESSION_KV) {
    try {
      const raw = await env.SESSION_KV.get(`session:${userId}`);
      if (raw) return JSON.parse(raw);
    } catch (e) {
      console.warn("KV read error, falling back to in-memory:", e.message);
    }
  }
  return emotionSessionStore.get(userId) || null;
}

async function saveSession(userId, sessionData, env) {
  if (env && env.SESSION_KV) {
    try {
      await env.SESSION_KV.put(
        `session:${userId}`,
        JSON.stringify(sessionData),
        { expirationTtl: 86400 } // 24時間 TTL
      );
    } catch (e) {
      console.warn("KV write error, falling back to in-memory:", e.message);
    }
  }
  emotionSessionStore.set(userId, sessionData);
}

// ══════════════════════════════════════════════════════════
// ─── Gemini API Call (v3.0 — 会話履歴 + RAG + 動的感情) ───
// ══════════════════════════════════════════════════════════

/**
 * @param {string} userMessage  ユーザーのメッセージ
 * @param {string} apiKey       Gemini APIキー
 * @param {string} userId       DiscordユーザーID（セッション管理用）
 * @param {object|null} env     Cloudflare Workers env（KV・vars含む）
 */
async function askGemini(userMessage, apiKey, userId = "default", env = null) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key=${apiKey}`;
  const phase = getCurrentPhase();
  const now   = new Date();

  // ── Layer1: セッション読み込み（会話履歴 + 感情状態） ──
  const session = (await loadSession(userId, env)) || {
    state: { ...DEFAULT_EMOTION },
    lastResponseEnding: null,
    history: [],
  };

  // ── Layer2: エピソード記憶の読み込みと忘却適用 ──
  // ── ユーザープロファイル更新・読み込みを並列実行 ──
  const [rawMemories, profile] = await Promise.all([
    loadEpisodicMemory(userId, env),
    updateUserProfile(userId, userMessage, env),
  ]);
  const memories = decayMemories(rawMemories, now);

  // ── 感情状態の計算 ──
  const newState       = computeEmotionState(userMessage, session.state);
  const emotionSection = buildEmotionPromptSection(
    newState, session.state, session.lastResponseEnding
  );

  // ── ユーザープロファイルをシステムプロンプトに反映 ──
  const intimacyStyle = getIntimacyStyle(Math.floor(profile.intimacy));
  const topInterests  = Object.entries(profile.interestTags)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([tag]) => tag);
  const profileSection = `\n\n## このユーザーとの関係\n- 親密度: ${Math.floor(profile.intimacy)}/100 (${intimacyStyle.label}・${profile.totalConversations}回会話済み)\n- 口調スタイル: ${intimacyStyle.style}${topInterests.length ? `\n- 興味トピック: ${topInterests.join("、")}（これらの話題に関連づけると喜ぶ）` : ""}`;

  // ── Layer3: 人格レイヤー読み込み（MEMORY_KV → GitHub Raw の順でキャッシュ参照） ──
  let personality = null;
  let personalitySection = "";
  try {
    personality = await fetchPersonalityLayer(env);
    if (personality) {
      // buildSystemPromptで使わないフィールド（口癖・癖・好き嫌い）を補足セクションに追加
      const parts = [];
      if (personality.catchphrases?.length)
        parts.push(`口癖: ${personality.catchphrases.slice(0, 3).join(" / ")}`);
      if (personality.quirks?.length)
        parts.push(`特徴的な癖: ${personality.quirks.slice(0, 3).join(" / ")}`);
      if (personality.expertise_details?.length)
        parts.push(`得意分野の詳細: ${personality.expertise_details.slice(0, 2).join("、")}`);
      if (personality.favorite_topics?.length)
        parts.push(`好きな話題: ${personality.favorite_topics.slice(0, 3).join("、")}`);
      if (personality.backstory)
        parts.push(`バックストーリー: ${personality.backstory}`);
      if (parts.length) {
        personalitySection = `\n\n## 人格詳細（personality_layer）\n${parts.join("\n")}`;
      }
    }
  } catch (e) {
    console.warn("personality_layer fetch failed (non-critical):", e.message);
  }

  // ── Layer2: 関連エピソード記憶をBM25検索しプロンプトに組み込む ──
  let memorySection = "";
  const queryTerms = tokenize(userMessage);
  const relevantEpisodes = searchEpisodicMemory(queryTerms, memories, 2);
  if (relevantEpisodes.length > 0) {
    const lines = relevantEpisodes.map(ep =>
      `- ${ep.content.slice(0, 100)} (保持率:${((ep.retention || 0) * 100).toFixed(0)}%)`
    ).join("\n");
    memorySection = `\n\n## あなたの記憶（このユーザーとの過去の会話）\n${lines}\n_（自然な流れなら話題を絡めてよい）_`;
  }

  // ── RAG: 知識ベース BM25 検索 ──
  let ragSection = "";
  try {
    const knowledgeEntries = await fetchKnowledgeBase(env);
    // ユーザーの興味タグに合わせてRAGスコアをブースト
    const relevant = searchKnowledgePersonalized(userMessage, knowledgeEntries, 3, profile.interestTags);
    if (relevant.length > 0) {
      const lines = relevant.map(e =>
        `- [${(e.date || "").slice(0, 10)}] **${e.title}**: ${e.core_insight || e.summary || ""}`
      ).join("\n");
      ragSection = `\n\n## 参考になる最新情報（RAG知識ベース）\n${lines}\n_（これを参考にしつつ、キャラクターとして自然に答えて）_`;
    }
  } catch (e) {
    console.warn("RAG fetch failed (non-critical):", e.message);
  }

  // ── システムプロンプト構築（Base + 人格 + プロファイル + 感情 + Layer2記憶 + RAG） ──
  // personalityをbuildSystemPromptに渡すことで、Big Five/VTuber演出/専門/制約をJSONから動的生成
  const fullSystemPrompt =
    buildSystemPrompt(phase, personality) + personalitySection + profileSection + emotionSection + memorySection + ragSection;

  // ── Layer1: 会話履歴を Gemini contents に組み込む ──
  const history  = session.history || [];
  const contents = [
    ...history.slice(-6),  // 直近3往復（6メッセージ）
    { role: "user", parts: [{ text: userMessage }] },
  ];

  // ── temperatureを感情状態に応じて動的調整 ──
  const dynamicTemp = 0.6 + (newState.tension / 100) * 0.4; // 0.6〜1.0

  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: fullSystemPrompt }] },
        contents,
        generationConfig: {
          maxOutputTokens: 500,
          temperature: dynamicTemp,
        },
      }),
    });

    if (!resp.ok) {
      const errorText = await resp.text();
      console.error("Gemini API error:", resp.status, errorText);
      return pickError("api");
    }

    const data = await resp.json();
    const text = data.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!text) {
      console.error("Gemini returned empty response:", JSON.stringify(data));
      return pickError("empty");
    }

    const responseText = text.trim().slice(0, 500);

    // ── Layer1セッション保存 + Layer2エピソード記憶更新を並列実行 ──
    await Promise.all([
      saveSession(userId, {
        state: newState,
        lastResponseEnding: extractLastEnding(responseText),
        history: [
          ...history.slice(-8),  // 最大4往復を保持
          { role: "user",  parts: [{ text: userMessage }] },
          { role: "model", parts: [{ text: responseText }] },
        ],
        updated_at: now.toISOString(),
      }, env),
      saveEpisodicMemory(userId, upsertEpisode(memories, userMessage, responseText, now), env),
    ]);

    return responseText;

  } catch (e) {
    console.error("Gemini fetch error:", e);
    return pickError("network");
  }
}

// ─── Simple XML Parser ───
function parseXmlElements(xml, tagName) {
  const regex = new RegExp(`<${tagName}(?:\\s[^>]*)?>([\\s\\S]*?)</${tagName}>`, "gi");
  const results = [];
  let match;
  while ((match = regex.exec(xml)) !== null) {
    let content = match[1];
    content = content.replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1");
    content = decodeXmlEntities(content);
    results.push(content.trim());
  }
  return results;
}

function decodeXmlEntities(text) {
  return text
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#39;/g, "'");
}

// ─── Fetch Latest RSS ───
async function fetchLatestNews() {
  const FEEDS = [
    { url: "https://zenn.dev/topics/claudecode/feed",                 name: "Zenn Claude Code", emoji: "🔧" },
    { url: "https://zenn.dev/topics/vibecoding/feed",                 name: "Zenn VibeCoding",  emoji: "🎵" },
    { url: "https://zenn.dev/topics/mcp/feed",                        name: "Zenn MCP",         emoji: "🔌" },
    { url: "https://zenn.dev/topics/claude/feed",                     name: "Zenn Claude",      emoji: "🤖" },
    { url: "https://qiita.com/tags/claudecode/feed",                  name: "Qiita Claude Code", emoji: "📝" },
    { url: "https://qiita.com/tags/vibecoding/feed",                  name: "Qiita VibeCoding", emoji: "🎶" },
    { url: "https://github.com/anthropics/claude-code/releases.atom", name: "GitHub Releases",  emoji: "🚀" },
    { url: "https://www.anthropic.com/news/rss.xml",                  name: "Anthropic News",   emoji: "📰" },
  ];

  const articles = [];
  for (const feed of FEEDS) {
    try {
      const resp = await fetch(feed.url, { headers: { "User-Agent": "NewsAI-VibeCording/4.0" } });
      if (!resp.ok) { console.warn(`Feed failed (${resp.status}): ${feed.name}`); continue; }

      const xml    = await resp.text();
      const isAtom = xml.includes("<feed") && xml.includes("<entry>");
      const itemTag = isAtom ? "entry" : "item";
      const linkExtract = isAtom
        ? (item) => item.match(/<link[^>]*href=["']([^"']+)["']/)?.[1] || parseXmlElements(item, "link")[0] || ""
        : (item) => parseXmlElements(item, "link")[0] || "";

      const itemRegex = new RegExp(`<${itemTag}[^>]*>[\\s\\S]*?</${itemTag}>`, "gi");
      const items = xml.match(itemRegex) || [];

      for (const item of items.slice(0, 3)) {
        const title = parseXmlElements(item, "title")[0] || "No Title";
        const link  = linkExtract(item);
        if (title && link) articles.push({ title, link, source: feed.name, emoji: feed.emoji });
      }
    } catch (e) {
      console.error(`Feed error (${feed.name}):`, e);
    }
  }
  return articles.slice(0, 5);
}

// ─── Command Handlers ───
async function handleNewsCommand(env) {
  const articles = await fetchLatestNews();

  if (articles.length === 0) {
    return {
      type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
      data: { content: `📭 **${CHARACTER.name}**: ん〜、今はニュースが取得できなかったの...定時配信をお楽しみに！` },
    };
  }

  const lines = articles.map(
    (a, i) => `**${i + 1}.** ${a.emoji} [${a.title}](${a.link})\n　　📌 ${a.source}`
  );

  return {
    type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
    data: {
      content: `🎵 **${CHARACTER.name}のVibeCordingニュース！**\n\nはいはい〜！最新ニュースをお届けするよ！\n\n${lines.join("\n\n")}\n\n_気になる記事があったら読んでみてね！_`,
    },
  };
}

async function handleAskCommand(question, env, userId = "default") {
  if (!question) {
    return {
      type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
      data: { content: `❓ **${CHARACTER.name}**: 質問を入力してほしいの！\n例: \`/ask Claude Codeの便利な使い方は？\`` },
    };
  }

  if (!env.GEMINI_API_KEY) {
    return {
      type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
      data: {
        content: `⚠️ **${CHARACTER.name}**: ごめんね、AI機能がまだ設定されてないの...管理者さんにGemini APIキーの設定をお願いしてね！`,
        flags: 64,
      },
    };
  }

  const answer = await askGemini(question, env.GEMINI_API_KEY, userId, env);

  return {
    type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
    data: {
      content: `💡 **Q:** ${question}\n\n🎵 **${CHARACTER.name}:** ${answer}\n\n_Powered by NewsAI VibeCording × Gemini_`,
    },
  };
}

function handleStatusCommand(env) {
  const now        = new Date().toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" });
  const kvStatus   = (env && env.SESSION_KV)   ? "✅ KV（永続）" : "⚠️ in-memory（揮発）";
  const memStatus  = (env && env.MEMORY_KV)    ? "✅ KV（永続・90d）" : "⚠️ 未設定（MEMORY_KV未設定）";
  const ragStatus  = (env && env.GITHUB_OWNER && env.GITHUB_OWNER !== "REPLACE_WITH_YOUR_GITHUB_USERNAME")
    ? "✅ GitHub RAG 有効"
    : "⚠️ 未設定（GITHUB_OWNER未設定）";

  return {
    type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
    data: {
      content: [
        `🟢 **${CHARACTER.name} ステータス v${CHARACTER.version}**`,
        "",
        `⏰ 現在時刻: ${now}`,
        "📡 定時配信: 10:00 / 15:00 (JST)",
        "🤖 AI Engine: Gemini 2.0 Flash-Lite",
        "⚡ Runtime: Cloudflare Workers (Free)",
        `💾 セッション: ${kvStatus}`,
        `🔍 知識検索: ${ragStatus}`,
        "",
        "**記憶システム:**",
        "  Layer1 会話履歴 (3往復):  ✅ 実装済み",
        `  Layer2 忘却曲線エンジン:  ✅ 実装済み (${memStatus})`,
        "  Layer3 人格統合知識:      ✅ 実装済み (GitHub JSON)",
        "  パーソナライズ:           ✅ 実装済み (親密度 + 興味タグ)",
        "",
        "**コマンド:**",
        "`/news` `/ask <質問>` `/status`",
      ].join("\n"),
    },
  };
}

// ─── Discord Followup Webhook (Deferred Response用) ───
// Discordは3秒以内に応答必須。時間がかかるコマンドはDeferredで即応答し
// ctx.waitUntil() でバックグラウンド処理後にWebhookで追記する
async function sendFollowup(applicationId, token, content) {
  const url = `https://discord.com/api/v10/webhooks/${applicationId}/${token}/messages/@original`;
  await fetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

// ─── Main Handler ───
export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") {
      return new Response(
        JSON.stringify({
          status: "ok", bot: CHARACTER.name,
          version: CHARACTER.version, timestamp: new Date().toISOString(),
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }

    if (request.method !== "POST") return new Response("Method not allowed", { status: 405 });

    const isValid = await verifyDiscordRequest(request, env.DISCORD_PUBLIC_KEY);
    if (!isValid) return new Response("Invalid request signature", { status: 401 });

    let interaction;
    try { interaction = await request.json(); }
    catch (e) { return new Response("Invalid JSON", { status: 400 }); }

    if (interaction.type === InteractionType.PING) {
      return Response.json({ type: InteractionResponseType.PONG });
    }

    if (interaction.type === InteractionType.APPLICATION_COMMAND) {
      const userId = interaction.member?.user?.id || interaction.user?.id || "unknown";

      if (!checkRateLimit(userId)) {
        return Response.json({
          type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
          data: {
            content: `⏳ **${CHARACTER.name}**: ちょっと休憩させて〜！1時間に30回まで使えるから、少し待ってね！`,
            flags: 64,
          },
        });
      }

      const commandName = interaction.data.name;

      // /status は高速なので同期で返す
      if (commandName === "status") {
        return Response.json(handleStatusCommand(env));
      }

      // /news, /ask は外部API呼び出しがあるためDeferredパターンを使用
      // 即座にtype:5（処理中）を返し、ctx.waitUntil()でバックグラウンド処理
      const token = interaction.token;
      const appId = env.DISCORD_APPLICATION_ID;

      if (commandName === "news") {
        ctx.waitUntil((async () => {
          try {
            const resp = await handleNewsCommand(env);
            await sendFollowup(appId, token, resp.data.content);
          } catch (e) {
            console.error("news command error:", e);
            await sendFollowup(appId, token, `😵 **${CHARACTER.name}**: ${pickError("handler")}`);
          }
        })());
        return Response.json({ type: InteractionResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE });
      }

      if (commandName === "ask") {
        const question = interaction.data.options?.[0]?.value || "";
        ctx.waitUntil((async () => {
          try {
            const resp = await handleAskCommand(question, env, userId);
            await sendFollowup(appId, token, resp.data.content);
          } catch (e) {
            console.error("ask command error:", e);
            await sendFollowup(appId, token, `😵 **${CHARACTER.name}**: ${pickError("handler")}`);
          }
        })());
        return Response.json({ type: InteractionResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE });
      }

      return Response.json({
        type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
        data: { content: `❓ **${CHARACTER.name}**: そのコマンドは知らないの...` },
      });
    }

    return Response.json({ error: "Unknown interaction type" }, { status: 400 });
  },
};
