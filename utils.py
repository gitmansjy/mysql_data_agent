# utils.py

import os
import matplotlib.pyplot as plt

def clear_previous_plot(plot_file):
    """删除旧图表"""
    if os.path.exists(plot_file):
        os.remove(plot_file)

def display_result(result, has_plot=False, plot_file="output_plot.png"):
    """打印分析结果"""
    print("\n🔍 分析结果：")
    print("-" * 50)
    if isinstance(result, dict):
        for k, v in result.items():
            print(f"{k}: {v}")
    elif hasattr(result, "to_string"):
        print(result.to_string(index=False))
    else:
        print(result)
    
    if has_plot and os.path.exists(plot_file):
        print(f"\n🖼️  图表已生成 → {plot_file}")
