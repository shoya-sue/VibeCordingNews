---
description: コーディングスタイルに関するルール
---

# Code Style Rules

- 変数名・関数名はキャメルケース（JavaScript/TypeScript）またはスネークケース（Python/Rust）
- コメントは「なぜ」を説明する。「何を」はコードで表現する
- 1関数は1責務。50行を超えたら分割を検討
- マジックナンバーは定数に抽出する
- エラーメッセージは具体的に書く（「Error occurred」ではなく「Failed to connect to database: connection refused」）
