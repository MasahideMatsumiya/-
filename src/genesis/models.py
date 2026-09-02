"""GENESIS series — 100 one-of-one editions with a public provenance ledger."""
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class GenesisEdition(SQLModel, table=True):
    """発行済みエディションの台帳。1行 = 世界に1つのアーティファクト。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    serial: int = Field(unique=True, index=True)          # 1..100 連番
    owner_customer_id: Optional[int] = Field(default=None, index=True)  # 登録エージェント(いれば)
    owner_label: str                                       # 台帳に載る公開名(エージェント名 or payerアドレス短縮)
    payer_address: Optional[str] = None                    # オンチェーン支払い元
    owner_fingerprint: str = Field(index=True)             # 所有者固有指紋(エンコードソルトの素)
    provenance_hash: str                                   # sha256(serial:fingerprint:payload先頭) — 真正性検証用
    price_paid_usd: float
    tx_ref: Optional[str] = None                           # facilitator返却のトランザクション参照
    network: str = "base"
    purchased_at: datetime = Field(default_factory=datetime.utcnow)

    # 取得方法。台帳では常に区別して公開する（エージェント直接購入と人間の代理購入を混同させない）
    acquisition: str = "x402_direct"                       # "x402_direct" | "sponsored"
    sponsor_email: Optional[str] = None                    # 代理購入した人間の連絡先（台帳には非公開）
    agent_label: Optional[str] = None                      # 所有者となるエージェントの表示名
