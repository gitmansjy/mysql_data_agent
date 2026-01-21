import os
import io
import streamlit as st
import pandas as pd

from analytibot import load_data, get_analysis_code, execute_code, DATA_FILE

st.set_page_config(page_title="AnalytiBot-Mini", layout="wide")

st.title("AnalytiBot-Mini — Streamlit 界面")

uploaded = st.file_uploader("上传 CSV 文件（可选）", type=["csv"])

if uploaded is not None:
    content = uploaded.getvalue()
    last_exc = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin1", "cp1252"):
        try:
            # 使用 BytesIO + encoding 以兼容不同 pandas 版本
            df = pd.read_csv(io.BytesIO(content), encoding=enc)
            st.success(f"已上传（encoding={enc}），{len(df)} 行，列：{list(df.columns)}")
            break
        except Exception as e:
            last_exc = e
    else:
        st.error(f"读取上传文件失败：{last_exc}")
        st.stop()
else:
    st.warning("请上传 CSV 文件。")
    st.stop()

question = st.text_input("请输入你的分析问题：", value="数据分析")
plot_name = st.text_input("生成图表文件名：", value="output_plot.png")

if st.button("开始分析"):
    with st.spinner("正在生成分析代码..."):
        try:
            code = get_analysis_code(question, df.columns.tolist(), plot_file=plot_name)
        except Exception as e:
            st.error(f"生成代码失败：{e}")
            st.stop()

    st.subheader("生成的代码")
    st.code(code, language="python")

    with st.spinner("正在执行代码..."):
        result, has_plot = execute_code(code, df)

    st.subheader("分析结果")
    if isinstance(result, pd.DataFrame):
        st.dataframe(result)
    else:
        st.write(result)

    if has_plot and os.path.exists(plot_name):
        st.image(plot_name, caption="生成的图表")
    elif has_plot:
        # 尝试默认名
        if os.path.exists("output_plot.png"):
            st.image("output_plot.png", caption="生成的图表")
        else:
            st.info("已生成图表文件，但未找到指定路径。")
