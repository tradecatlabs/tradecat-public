# 配置（Configuration）

配置统一收敛到 `config/.env`。

- 模板：`config/.env.example`
- 运行时：`config/.env`（含密钥，不提交）

建议用顶层脚本生成并校验权限：

```bash
cp config/.env.example config/.env
chmod 600 config/.env
./scripts/check_env.sh
```
