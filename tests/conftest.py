"""pytest 公共夹具：测试使用独立临时数据目录。"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 必须在导入 app 之前设置独立数据目录
_TMP = tempfile.mkdtemp(prefix="contest-test-")
os.environ["CONTEST_DATA_DIR"] = _TMP
os.environ["ADMIN_INITIAL_PASSWORD"] = "test-admin-pwd"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import run as seed_run  # noqa: E402

seed_run()  # 幂等：创建管理员 + 样题库


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password},
                    headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 200, r.text
    return r.json()
