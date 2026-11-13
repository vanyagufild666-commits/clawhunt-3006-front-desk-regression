# 3006 · front_desk 越权回归测试（S2-IAM-022）

## 运行

```bash
pip install fastapi httpx pytest pyyaml
APP_ENV=test pytest -v
```

## 覆盖

| 验收 | 用例 |
|------|------|
| 1 | `test_allowed_probe_200` ×9 参数化 + `test_denied_probe_403` ×12 参数化 + 真实接口 2 条 |
| 2 | 每个禁止项断言 `error == permission_denied` |
| 3 | `test_site_b_allows_become_403` ×9 参数化（X-Site-Id=会所 B） |
| 4 | `test_records_site_scope`：恰好 6 条会所 A 记录，会所 B 不泄漏 |

## 矩阵来源

`role_matrix.yml` 为种子（若平台已合并角色矩阵，则以平台为准替换 fixture）。允许项 9 个（7 site + 1 org + 1 self），禁止项 12 个权限点 + 2 个真实接口。

探针路由仅在 `APP_ENV=test` 挂载（`app/permissions.py: mount_probe`）。测试数据全部虚构。
