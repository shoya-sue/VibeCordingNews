---
description: API 設計に関するルール
paths:
  - "src/api/**"
  - "src/routes/**"
  - "src/controllers/**"
---

# API Conventions

- RESTful 設計に従う（GET=取得, POST=作成, PUT=更新, DELETE=削除）
- レスポンスは常に JSON 形式
- エラーレスポンスは `{ "error": { "code": "...", "message": "..." } }` 形式
- ページネーションは `?page=1&per_page=20` 形式
- 認証は Authorization ヘッダーで Bearer トークンを使用
- バリデーションエラーは 422、認証エラーは 401、権限エラーは 403 を返す
