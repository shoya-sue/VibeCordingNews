#!/usr/bin/env node
/**
 * Discord Slash Commands 登録スクリプト
 *
 * 使い方:
 *   DISCORD_APPLICATION_ID=xxx DISCORD_BOT_TOKEN=xxx node register-commands.js
 *
 * 初回のみ実行すればOK。コマンド定義を変更した場合は再実行する。
 */

const DISCORD_API = "https://discord.com/api/v10";

const commands = [
  {
    name: "news",
    description: "VibeCoding / Claude Code の最新ニュースを表示します",
    type: 1, // CHAT_INPUT
  },
  {
    name: "ask",
    description: "VibeCoding関連の質問にAIが回答します",
    type: 1,
    options: [
      {
        name: "question",
        description: "質問内容（例: Claude Codeの便利な使い方は？）",
        type: 3, // STRING
        required: true,
      },
    ],
  },
  {
    name: "status",
    description: "Botの稼働状況を確認します",
    type: 1,
  },
];

async function registerCommands() {
  const appId = process.env.DISCORD_APPLICATION_ID;
  const botToken = process.env.DISCORD_BOT_TOKEN;

  if (!appId || !botToken) {
    console.error("Error: DISCORD_APPLICATION_ID and DISCORD_BOT_TOKEN are required.");
    console.error("");
    console.error("Usage:");
    console.error("  DISCORD_APPLICATION_ID=xxx DISCORD_BOT_TOKEN=xxx node register-commands.js");
    process.exit(1);
  }

  const url = `${DISCORD_API}/applications/${appId}/commands`;

  console.log("Registering slash commands...");
  console.log(`  App ID: ${appId}`);
  console.log(`  Commands: ${commands.map((c) => "/" + c.name).join(", ")}`);

  try {
    const resp = await fetch(url, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bot ${botToken}`,
      },
      body: JSON.stringify(commands),
    });

    if (!resp.ok) {
      const error = await resp.text();
      console.error(`Failed (${resp.status}): ${error}`);
      process.exit(1);
    }

    const data = await resp.json();
    console.log(`\n✅ Successfully registered ${data.length} commands:`);
    data.forEach((cmd) => {
      console.log(`   /${cmd.name} (id: ${cmd.id})`);
    });
  } catch (e) {
    console.error("Error:", e);
    process.exit(1);
  }
}

registerCommands();
