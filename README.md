# Analytibot-mini — 部署说明

简要说明如何把本项目部署到 Streamlit Cloud（share.streamlit.io）。

必备文件
- `streamlit_chat.py` — 主应用入口（已在仓库）
- `requirements.txt` — Python 依赖（已在仓库）
- `.env.example` — 环境变量示例（请在部署平台用 Secrets 填写真实值）

必须的环境变量
- `DASHSCOPE_API_KEY`：模型/服务的 API Key，必需。
- `DEFAULT_DB_URL`：可选，线上数据库连接字符串（例如 `mysql+pymysql://user:pass@host:3306/db`）。

在 Streamlit Cloud 部署（快速）
1. 将代码推送到 GitHub（仓库根包含 `streamlit_chat.py` 与 `requirements.txt`）。
2. 打开 https://share.streamlit.io 并登录 GitHub。点击 "New app" → 选择你的仓库与分支 → 入口文件填写 `streamlit_chat.py` → Deploy。
3. 在 App Settings → Secrets 中添加 `DASHSCOPE_API_KEY`（和 `DEFAULT_DB_URL`，如需要）。不要把密钥写入代码或提交到仓库。
4. 部署完成后访问分配的 URL，查看应用并使用 Logs 页面排查错误。

本地快速测试
```powershell
cd /d D:\py\analytibot-mini
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run streamlit_chat.py --server.port 8501
```

注意事项与最佳实践
- 切勿将 `DASHSCOPE_API_KEY` 或数据库密码提交到仓库。使用平台提供的 Secret 管理功能。
- 若使用远程数据库，请确认云平台所在网络允许出站连接到数据库主机，或将数据库置于可访问的网络中。
- 生产环境建议通过反向代理（如 Nginx）或平台接入层做访问控制与 TLS。

常见问题排查
- 模型调用失败：检查 `DASHSCOPE_API_KEY` 是否正确、配额是否耗尽，以及网络是否允许外发请求。
- 无法连接数据库：检查 `DEFAULT_DB_URL` 格式、数据库是否接受来自平台 IP 的连接、数据库用户权限。

下一步（可选）
- 我可以为你生成 `Procfile` / `start.sh` 或 `Dockerfile`，以便在其他 PaaS 或容器环境部署（回复我 A=Procfile, B=Dockerfile）。
