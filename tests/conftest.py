# -*- coding: utf-8 -*-
"""pytest 全局配置：测试结束后清理运行期产物，避免污染仓库。"""
import os
import shutil

import pytest


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_artifacts():
    """测试 session 结束后清理 observer_logs/ 等运行期产物。
    这些目录已在 .gitignore 中，但长时间运行会堆积。"""
    yield
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("observer_logs",):
        path = os.path.join(repo_root, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
