"""
初期商品データをDBに投入するシードスクリプト

使い方:
  python scripts/seed_products.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

BASE_URL = "http://localhost:8000"

PRODUCTS = [
    {
        "name": "Claude Prompt Pack Vol.1",
        "short_description": "すぐ使えるClaudeプロンプト20選",
        "description": (
            "Claude向け高品質プロンプトテンプレート20選。\n\n"
            "コード生成・文章作成・分析・マーケティングなど実務ですぐ使えるプロンプト集。\n"
            "変数プレースホルダーで即カスタマイズ可能。チーム共有用途にも最適。\n\n"
            "【収録カテゴリ】\n"
            "- コード生成 (5本): レビュー、テスト生成、API設計、SQL最適化、デバッグ\n"
            "- 文章作成 (3本): 技術ブログ、プレスリリース、ビジネスメール\n"
            "- 分析 (4本): 競合分析、フィードバック分析、KPI設計、リスク分析\n"
            "- プロダクト開発 (2本): PRD作成、ユーザーインタビュー設計\n"
            "- マーケティング (2本): LPコピー、SNSカレンダー\n"
            "- AI活用 (2本): System Prompt設計、プロンプトチェーン\n"
            "- 業務効率化 (2本): 議事録生成、週次レポート"
        ),
        "category": "prompt",
        "price_usd": 9.90,
        "status": "active",
        "download_url": "content/products/claude-prompt-pack-vol1.json",
        "tags": "claude,prompt,ai,productivity,template",
        "ai_models": "claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5",
    },
    {
        "name": "Claude System Prompt 完全ガイド",
        "short_description": "Claudeを最大限に活用するSystem Prompt設計の決定版",
        "description": (
            "Claudeのパフォーマンスを最大化するSystem Promptの設計手法を体系的に解説。\n\n"
            "【収録内容】\n"
            "- 第1章: System Promptとは何か（基礎と重要性）\n"
            "- 第2章: 6つの構成要素（ロール/能力/行動ガイドライン/制約/フォーマット/コンテキスト）\n"
            "- 第3章: カテゴリ別テンプレート集（サポートBot/コードレビュー/ライティング/データ分析）\n"
            "- 第4章: 高度なテクニック（Chain of Thought/Few-shot/動的コンテキスト）\n"
            "- 第5章: よくある失敗パターンと対策\n"
            "- 第6章: API実装ガイド（Python コード付き）\n\n"
            "すぐ使えるSystem Promptテンプレート4本 + クイックリファレンス付き。"
        ),
        "category": "guide",
        "price_usd": 9.90,
        "status": "active",
        "download_url": "content/products/claude-system-prompt-guide.json",
        "tags": "claude,system-prompt,guide,api,tutorial",
        "ai_models": "claude-opus-4-6,claude-sonnet-4-6",
    },
    {
        "name": "n8n × Claude ワークフローテンプレート集",
        "short_description": "コピペで使えるAI自動化ワークフロー10本",
        "description": (
            "n8nとClaude APIを連携した実務自動化ワークフロー10本セット。\n\n"
            "【収録ワークフロー】\n"
            "1. メール自動要約＆返信ドラフト（Gmail + Slack）\n"
            "2. 社内Q&A自動応答Bot（Slack + Notion）\n"
            "3. 競合情報モニタリング＆レポート（RSS + Sheets）\n"
            "4. カスタマーレビュー分析＆対応（CRM連携）\n"
            "5. 週次レポート自動生成（GA4 + Stripe）\n"
            "6. 採用書類スクリーニング（ATS連携）\n"
            "7. ブログ記事自動生成パイプライン（WordPress）\n"
            "8. インシデント自動トリアージ（PagerDuty + Jira）\n"
            "9. 商談メモ→CRM自動入力（Salesforce）\n"
            "10. 多言語カスタマーサポート（自動翻訳）\n\n"
            "各ワークフローにセットアップガイド・想定コスト・節約時間の目安付き。"
        ),
        "category": "workflow",
        "price_usd": 19.90,
        "status": "active",
        "download_url": "content/products/n8n-claude-workflow-templates.json",
        "tags": "n8n,claude,workflow,automation,no-code",
        "ai_models": "claude-sonnet-4-6,claude-haiku-4-5",
    },
    {
        "name": "AI Agent スターターパック",
        "short_description": "Claude APIで本格エージェントを今日から構築",
        "description": (
            "Claude APIで本格的なAIエージェントを構築するための設定テンプレート・コードスニペット集。\n\n"
            "【収録エージェント設計図 5種】\n"
            "1. リサーチエージェント（ウェブ検索＋レポート生成）\n"
            "2. コーディングエージェント（コード生成＋テスト＋デバッグ）\n"
            "3. データ分析エージェント（EDA＋可視化＋インサイト）\n"
            "4. カスタマーサポートエージェント（多言語対応）\n"
            "5. プロジェクト管理エージェント（マルチエージェント設計）\n\n"
            "各エージェントには System Prompt・Tool定義・実装コード（Python）が含まれます。\n\n"
            "【付属】\n"
            "- 汎用 AgentRunner クラス\n"
            "- リトライ/エラーハンドリングユーティリティ\n"
            "- モデル選定ガイド（コスト vs 品質）\n"
            "- 5分クイックスタートガイド"
        ),
        "category": "agent",
        "price_usd": 24.90,
        "status": "active",
        "download_url": "content/products/ai-agent-starter-pack.json",
        "tags": "claude,agent,python,api,tools,automation",
        "ai_models": "claude-opus-4-6,claude-sonnet-4-6,claude-haiku-4-5",
    },
]


async def seed():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        # ヘルスチェック
        r = await client.get("/health")
        if r.status_code != 200:
            print(f"❌ サーバーが起動していません: {BASE_URL}")
            return

        print(f"✅ サーバー接続確認: {BASE_URL}\n")

        created = 0
        for p in PRODUCTS:
            r = await client.post("/products/", json=p)
            if r.status_code == 200:
                data = r.json()
                print(f"✅ 商品登録: [{data['id']}] {data['name']} (${data['price_usd']}) status={data['status']}")
                created += 1
            else:
                print(f"❌ 登録失敗: {p['name']} - {r.status_code} {r.text[:100]}")

        print(f"\n🎉 シード完了: {created}/{len(PRODUCTS)} 件の商品を登録")

        # 商品一覧確認
        r = await client.get("/products/")
        if r.status_code == 200:
            products = r.json()
            print(f"\n📦 現在の商品数: {len(products)} 件")
            for p in products:
                print(f"  - [{p['id']}] {p['name']} (${p['price_usd']}) [{p['status']}]")


if __name__ == "__main__":
    asyncio.run(seed())
