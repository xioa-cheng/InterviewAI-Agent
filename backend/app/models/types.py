"""共享列类型：PostgreSQL 用 JSONB，SQLite 回退到通用 JSON。

JSONB 是 PostgreSQL 专属类型；用 with_variant 让 SQLite 方言退回通用 JSON，
这样 Docker(PostgreSQL) 里半结构化字段是 jsonb，本地 SQLite(dev/测试) 里是 json，
两套环境都能正常建表、老库无需重建。
"""
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

JSONType = JSONB().with_variant(JSON, "sqlite")
