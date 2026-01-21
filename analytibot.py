# analytibot.py

import os
import sys
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import rc
import numpy as np

# 设置中文字体支持（防止乱码）
rc('font', family='SimHei')  # 需要系统有黑体字体，或使用其他方式
plt.rcParams['axes.unicode_minus'] = False  # 正常显示负号

# 在 Windows 控制台上，默认编码可能无法打印 emoji 等字符，尝试切换为 utf-8
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

#from langchain_openai import ChatOpenAI
from qwen_llm import Qwen
from langchain_core.prompts import PromptTemplate
from langchain.chains import LLMChain
from prompts import ANALYSIS_PROMPT

# ----------------------------
# 配置区（请按需修改）
# ----------------------------

# 设置你的 API Key（以 OpenAI 为例）
os.environ["OPENAI_API_KEY"] = "sk-c5f85b787a954210a04b8fe8f9481ee2"
# 如使用 Qwen，请替换为 LangChain 支持的代理方式（见下方说明）

DATA_FILE = "data.csv"



llm = Qwen(
    model="qwen-max",       # 或 qwen-plus / qwen-turbo
    temperature=0.2,
    max_retries=3
)

# 创建提示模板
prompt = PromptTemplate.from_template(ANALYSIS_PROMPT)
chain = LLMChain(llm=llm, prompt=prompt)

# ----------------------------
# 核心函数
# ----------------------------

def load_data(filepath):
    # 尝试多种常见编码以提高兼容性（例如 Windows 上的 GBK）
    last_exc = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin1"):
        try:
            df = pd.read_csv(filepath, encoding=enc)
            print(f"✅ 数据加载成功（encoding={enc}），共 {len(df)} 行，列名：{list(df.columns)}\n")
            return df
        except Exception as e:
            last_exc = e

    print(f"❌ 数据加载失败：{last_exc}")
    exit()

def get_analysis_code(question, columns, plot_file="output_plot.png"):
    response = chain.invoke({
        "question": question,
        "columns": ", ".join(columns),
        "plot_file": plot_file,
    })
    return response['text'].strip()

def execute_code(code, df):
    result = None
    # 在执行用户/模型生成的代码前，对 DataFrame 做浅拷贝并清洗，
    # 避免 matplotlib 将超大整数或带引号的 id 字段误判为数值/日期，触发 C 扩展溢出。
    safe_df = df.copy()
    try:
        for col in safe_df.columns:
            if safe_df[col].dtype == object:
                # 转为字符串，去除首尾空白与外层单/双引号
                safe_df[col] = safe_df[col].astype(str).str.strip().str.strip("'\"")
    except Exception:
        pass

    # 安全执行环境
    safe_locals = {'df': safe_df, 'pd': pd, 'np': np, 'result': None}
    plot_generated = False

    try:
        exec(code, {}, safe_locals)
        result = safe_locals.get('result')
        if os.path.exists("output_plot.png"):
            plot_generated = True
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        # 写入单独的执行错误日志，便于排查 C 扩展溢出类错误
        try:
            with open('execution_debug.log', 'a', encoding='utf-8') as lf:
                lf.write(f"[{pd.Timestamp.utcnow().isoformat()}] EXECUTION_EXCEPTION: {str(e)}\n")
                lf.write(tb + "\n")
        except Exception:
            pass
        result = f"⚠️ 执行错误：{str(e)}\n详细堆栈已写入 execution_debug.log"

    return result, plot_generated

def display_result(result, has_plot=False):
    print("\n🔍 分析结果：")
    print("-" * 40)
    if isinstance(result, pd.DataFrame):
        print(result.to_string(index=False))
    elif isinstance(result, (int, float)):
        print(result)
    else:
        print(result)
    
    if has_plot:
        print("\n🖼️  已生成图表：output_plot.png")
        # 可选：自动打开图片
        # import subprocess; subprocess.call(["open", "output_plot.png"])

# ----------------------------
# 主循环
# ----------------------------

def main():
    print("📊 欢迎使用 AnalytiBot-Mini！")
    print("输入 'quit' 退出\n")

    df = load_data(DATA_FILE)

    while True:
        query = input("\n❓ 请输入你的分析问题：").strip()
        if query.lower() in ['quit', 'exit', '退出']:
            print("👋 再见！")
            break
        if not query:
            continue

        # Step 1: 生成代码
        print("🧠 正在生成分析代码...")
        code = get_analysis_code(query, df.columns.tolist(), plot_file="output_plot.png")
        print("💡 生成的代码：")
        print(code)

        # Step 2: 执行代码
        print("⚙️ 正在执行...")
        result, has_plot = execute_code(code, df)

        # Step 3: 展示结果
        display_result(result, has_plot)

if __name__ == "__main__":
    main()
