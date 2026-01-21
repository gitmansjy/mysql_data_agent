# config.example.py
# 将此文件复制为 config.py 并填写真实的只读数据库凭据（不要提交真实凭据到版本库）

DEFAULT_DB_CONFIG = {
    "driver": "mysql+pymysql",
    "user": "root",
    "password": "a123456",
    "host": "localhost",
    "port": 3306,
    "database": "testdb",
}

# 可选：把你的 DashScope/Bailian API Key 放在这里以便本地使用（仅在本地环境下使用，不要提交真实密钥）
# DASHSCOPE_API_KEY = "sk-..."
