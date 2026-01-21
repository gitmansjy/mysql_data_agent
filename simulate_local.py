"""本地模拟脚本：
- 使用 `load_data` 加载本地 `data.csv`（尝试多编码）
- 使用 mock 分析代码（无 LLM 依赖）生成并执行
- 打印结果并保存图表为 output_plot.png
"""
from analytibot import load_data, execute_code
import pandas as pd

def mock_get_analysis_code(question, columns):
    # 简单示例：按城市汇总销售额并绘图，使用变量 df
    code = (
        "import matplotlib.pyplot as plt\n"
        "plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']\n"
        "plt.rcParams['axes.unicode_minus'] = False\n"
        "result = df.groupby('city')['sales'].sum().reset_index()\n"
        "plt.figure(figsize=(8,5))\n"
        "plt.bar(result['city'], result['sales'])\n"
        "plt.title('各城市销售额总和')\n"
        "plt.xlabel('城市')\n"
        "plt.ylabel('销售额')\n"
        "plt.tight_layout()\n"
        "plt.savefig('output_plot.png')\n"
    )
    return code

def run():
    df = load_data('data.csv')

    # 若 sales 列为字符串（因文件格式问题），尝试拆分第一列
    if df.shape[1] == 1 and df.columns[0].count(',')>0:
        df = df[df.columns[0]].str.strip('"').str.split(',', expand=True)
        df.columns = ['date','city','product','sales','customers']
    # 转换数值列
    df['sales'] = pd.to_numeric(df['sales'], errors='coerce')

    question = '各城市的销售额总和，请画柱状图'
    code = mock_get_analysis_code(question, df.columns.tolist())
    print('--- Generated Code ---')
    print(code)

    result, has_plot = execute_code(code, df)

    print('\n--- Result ---')
    if isinstance(result, pd.DataFrame):
        print(result.to_string(index=False))
    else:
        print(result)

    if has_plot:
        print('\nPlot generated: output_plot.png')

if __name__ == '__main__':
    run()
