import os
import io
import re
import streamlit as st
import pandas as pd
from qwen_llm import Qwen
from sqlalchemy import create_engine, inspect
from datetime import datetime

# 支持从本地 config.py 读取 DB 配置（优先）
try:
    from config import DEFAULT_DB_CONFIG  # type: ignore
except Exception:
    DEFAULT_DB_CONFIG = None


def build_db_url_from_config(cfg: dict) -> str:
    """根据 config 字典构造 SQLAlchemy URL。"""
    driver = cfg.get("driver", "mysql+pymysql")
    user = cfg.get("user")
    password = cfg.get("password")
    host = cfg.get("host", "localhost")
    port = cfg.get("port", 3306)
    database = cfg.get("database")
    if not all([user, password, database]):
        return ""
    return f"{driver}://{user}:{password}@{host}:{port}/{database}"

DEFAULT_DB_URL = build_db_url_from_config(DEFAULT_DB_CONFIG) if DEFAULT_DB_CONFIG else ""

# 尝试从本地 config.py 读取 API Key（若存在），优先使用本地配置
try:
    from config import DASHSCOPE_API_KEY as CONFIG_API_KEY  # type: ignore
except Exception:
    CONFIG_API_KEY = None

st.set_page_config(page_title="AnalytiBot-Chat", layout='wide')
st.title("AnalytiBot — Chat 模式")

# 将输入框固定到页面底部（影响所有 form；若有问题可进一步限定选择器）
st.markdown(
    """
    <style>
    /* 固定表单到页面底部 */
    div.stForm {
        position: fixed !important;
        bottom: 0 !important;
        left: 0 !important;
        right: 0 !important;
        background: rgba(255,255,255,0.98) !important;
        padding: 10px !important;
        z-index: 9999 !important;
        box-shadow: 0 -2px 8px rgba(0,0,0,0.08) !important;
    }
    /* 让输入框更宽以适配固定布局 */
    div.stForm .stTextInput>div>div>input {
        width: 100% !important;
    }
    /* 聊天内容容器：中间滚动区域 */
    .chat-wrapper { display:flex; justify-content:center; }
    .chat-container {
        width: 100%;
        max-width: 1000px;
        height: calc(100vh - 240px) !important;
        overflow-y: auto !important;
        padding: 24px 16px !important;
        background: transparent !important;
        box-sizing: border-box;
    }
    .chat-msg { padding: 12px 16px; margin: 8px 0; border-radius: 12px; display: inline-block; max-width: 78%; word-break: break-word; }
    .chat-msg.user { background: #0ea5a3; color: white; align-self: flex-end; margin-left: auto; }
    .chat-msg.assistant { background: #f1f5f9; color: #111827; align-self: flex-start; margin-right: auto; }
    .chat-row { display: flex; flex-direction: column; }

    /* 底部浮动输入：居中、圆角、带阴影 */
    div.stForm[role="form"] {
        position: fixed !important;
        bottom: 20px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        width: calc(100% - 40px) !important;
        max-width: 980px !important;
        background: #ffffff !important;
        border-radius: 14px !important;
        padding: 10px 14px !important;
        box-shadow: 0 8px 24px rgba(15,23,42,0.12) !important;
        z-index: 99999 !important;
    }
    div.stForm[role="form"] .stTextInput>div{ display:flex; }
    div.stForm[role="form"] .stTextInput>div>div>input { flex:1; padding:10px 12px !important; border-radius:10px; }
    div.stForm[role="form"] .stButton>button { margin-left:8px; height:44px; border-radius:10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

if 'history' not in st.session_state:
    st.session_state.history = []  # list of {'role':'user'|'assistant','content':...}
if 'df' not in st.session_state:
    st.session_state.df = None


def _prune_consecutive_assistant_duplicates():
    """移除会话历史中连续重复的助手消息，避免 UI 中出现闪烁或重复条目。"""
    h = st.session_state.get('history', [])
    if not h:
        return
    new_h = []
    last = None
    for item in h:
        if last and last['role'] == 'assistant' and item['role'] == 'assistant' and last['content'] == item['content']:
            # 跳过连续重复的助手消息
            continue
        new_h.append(item)
        last = item
    st.session_state.history = new_h

# 初始清理，避免历史中已有连续重复项
_prune_consecutive_assistant_duplicates()


def _escape_html(s: str) -> str:
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('\n', '<br/>'))

# 布局：左侧会话与数据预览，右侧数据加载控件
left, right = st.columns([3, 1])

with right:
    st.header("数据源")
    uploaded = st.file_uploader("上传 CSV (可选)", type=["csv"])
    st.markdown("\n")
    if DEFAULT_DB_URL:
        st.info("已配置默认数据库连接（使用代码内 DEFAULT_DB_URL）")
    else:
        st.warning("未配置默认数据库连接；若需执行模型生成的 SQL，请在 `config.py` 中配置 DEFAULT_DB_CONFIG 或联系管理员。")
    # 使用代码内默认数据库（若已配置 DEFAULT_DB_URL）

    if uploaded is not None:
        content = uploaded.getvalue()
        last_exc = None
        for enc in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin1", "cp1252"):
            try:
                st.session_state.df = pd.read_csv(io.BytesIO(content), encoding=enc)
                st.success(f"已加载上传文件（encoding={enc}），共 {len(st.session_state.df)} 行")
                break
            except Exception as e:
                last_exc = e
        else:
            st.error(f"读取上传文件失败：{last_exc}")

    # 不再在界面中直接接收 db_url 或 table_name，执行 SQL 时使用 DEFAULT_DB_URL（若已配置）

    if st.button("清空会话/数据"):
        st.session_state.history = []
        st.session_state.df = None
    # SQL 由模型生成并执行流程（只读）
    st.markdown("---")
    # 已移除界面上的“生成 SQL”开关。默认不对所有输入自动生成 SQL，
    # 系统将根据用户意图与启发式规则决定是否生成 SQL（仅在明确请求时触发）。
    generate_sql = False

with left:
    st.subheader("会话历史")
    # 渲染可滚动的聊天容器（使用 HTML 以便整体控制高度与滚动）
    chat_html = ['<div class="chat-container">']
    for msg in st.session_state.history:
        role = msg.get('role', '')
        content = _escape_html(str(msg.get('content', '')))
        if role == 'user':
            chat_html.append(f"<div class=\"chat-row\"><div class=\"chat-msg user\">{content}</div></div>")
        else:
            chat_html.append(f"<div class=\"chat-row\"><div class=\"chat-msg assistant\">{content}</div></div>")
    chat_html.append('</div>')
    st.markdown('\n'.join(chat_html), unsafe_allow_html=True)
    # 注入小段 JS 自动滚动聊天容器到最底部（在每次渲染时执行）
    try:
        import streamlit.components.v1 as components
        scroll_js = """
        <script>
        setTimeout(function(){
            var el = document.querySelector('.chat-container');
            if(el){ el.scrollTop = el.scrollHeight; }
        }, 50);
        </script>
        """
        components.html(scroll_js, height=1)
    except Exception:
        pass

    st.markdown("---")

    if st.session_state.df is not None:
        st.subheader("当前数据预览 (前 100 行)")
        st.dataframe(st.session_state.df.head(100))

    # 显示最近一次执行的 SQL 结果（若存在），保证即使发生重跑也能看到结果
    if 'last_exec_df' in st.session_state:
        st.markdown('')
        st.subheader('上次执行结果（已缓存，前 200 行）')
        last_sql = st.session_state.get('last_exec_sql', '')
        if last_sql:
            st.code(last_sql, language='sql')
        try:
            st.dataframe(st.session_state['last_exec_df'])
        except Exception:
            # 兼容性：若保存为 dict，可重建 DataFrame
            try:
                import pandas as _pd
                st.dataframe(_pd.DataFrame(st.session_state['last_exec_df']))
            except Exception:
                st.write('无法显示上次执行的结果。')

    # 在页面底部渲染固定输入表单（放在主逻辑之前以便发送能立即触发）
    if 'send_now' not in st.session_state:
        st.session_state['send_now'] = False
    with st.form(key='bottom_chat_form', clear_on_submit=True):
        c1, c2 = st.columns([8, 1])
        with c1:
            st.text_input('消息输入', key='chat_input_bottom', placeholder='在此输入并回车或点击发送...', label_visibility='collapsed')
        with c2:
            submit_bottom = st.form_submit_button('发送')

    # 如果刚刚提交底部表单，则同步并设置发送标志，随后在本次运行继续处理 user_input
    if submit_bottom:
        st.session_state['chat_input'] = st.session_state.get('chat_input_bottom', '')
        st.session_state['send_now'] = True

    user_input = None
    # 如果底部表单触发发送标志，则将 session 中的 chat_input 同步为本地 user_input 供后续处理
    if st.session_state.get('send_now') and st.session_state.get('chat_input'):
        user_input = st.session_state.get('chat_input', '').strip()
        # 清除发送标志，避免重复提交
        st.session_state['send_now'] = False
        # 清空临时存储，避免重复处理（该键不是当前表单的 widget key，安全清空）
        st.session_state['chat_input'] = ''

    def build_dataset_summary(df: pd.DataFrame, max_chars=1500) -> str:
        cols = list(df.columns)
        types = {c: str(df[c].dtype) for c in cols}
        sample_lines = []
        try:
            sample = df.head(5).astype(str).to_dict(orient='records')
            for r in sample:
                sample_lines.append(' | '.join([f"{k}:{v}" for k, v in r.items()]))
        except Exception:
            sample_lines = []
        summary = f"COLUMNS: {', '.join(cols)}\nTYPES: {types}\nSAMPLE:\n" + '\n'.join(sample_lines)
        if len(summary) > max_chars:
            return summary[:max_chars] + '...'
        return summary

    # 注意：意图检测由大模型完成，不在本地进行关键词检测。

    if user_input:
        st.session_state.history.append({'role': 'user', 'content': user_input})
        # 清理上一次生成/修正的 SQL，确保新会话使用新的 SQL
        st.session_state.pop('generated_sql', None)
        st.session_state.pop('fixed_sql', None)

        # build conversation text (include dataset summary when available)
        conv_lines = []
        for m in st.session_state.history:
            role = 'User' if m['role'] == 'user' else 'Assistant'
            conv_lines.append(f"{role}: {m['content']}")
        if st.session_state.df is not None:
            conv_lines.append('\n--- DATASET SUMMARY ---')
            conv_lines.append(build_dataset_summary(st.session_state.df))
        # 若之前执行过 SQL，把其结果摘要也加入对话上下文，便于模型在后续分析时参考
        if 'last_exec_df' in st.session_state:
            try:
                conv_lines.append('\n--- LAST SQL RESULT ---')
                last_sql_text = st.session_state.get('last_exec_sql', '')
                if last_sql_text:
                    conv_lines.append(f'LAST_SQL: {last_sql_text}')
                conv_lines.append(build_dataset_summary(st.session_state['last_exec_df']))
            except Exception:
                # 若构建摘要失败则忽略，不阻塞主流程
                pass
        conversation = "\n".join(conv_lines)

        api_key = CONFIG_API_KEY or os.getenv('DASHSCOPE_API_KEY')
        if not api_key:
            st.error('未检测到 DASHSCOPE_API_KEY 环境变量，请先设置后重试。')
        else:
            with st.spinner('等待模型回复...'):
                reply = ""
                try:
                    q = Qwen(model='qwen-plus', api_key=api_key)
                    # 判断是否需要生成 SQL：优先使用用户勾选；否则使用启发式规则或模型判定
                    def _heuristic_needs_sql(text: str, table_candidates: list | None = None) -> bool:
                        if not text:
                            return False
                        t = text.lower()
                        # 明确的写 SQL 请求或常见关键词
                        if '帮我写' in t and ('sql' in t or '查询' in t):
                            return True
                        if re.search(r'写(一条|一个)?\s*(sql|查询)', t):
                            return True
                        # 如果直接包含表名提示（如查询 wx_tm_market_goods_data）
                        m = re.search(r'查询\s+([\w\.]+)', t)
                        if m:
                            return True
                        # 若已知的表名出现在请求中，则也触发
                        if table_candidates:
                            for tbl in table_candidates:
                                if tbl and tbl.lower() in t:
                                    return True
                        return False

                    # 先尝试从数据库获取表名用于启发式匹配（若配置了 DEFAULT_DB_URL）
                    allowed_for_heuristic = None
                    try:
                        if DEFAULT_DB_URL:
                            eng_tmp = create_engine(DEFAULT_DB_URL)
                            allowed_for_heuristic = inspect(eng_tmp).get_table_names()
                    except Exception:
                        allowed_for_heuristic = None

                    explicit_sql_request = _heuristic_needs_sql(user_input, allowed_for_heuristic)
                    # 若用户意图明显为数据分析/描述类请求，则优先不生成 SQL（除非显式请求 SQL）
                    analysis_keywords = ['分析', '描述', '统计', '汇总', '可视化', '画图', '总结', '解释', '洞察', '趋势', '分布', '关联']
                    is_analysis_request = False
                    if user_input:
                        for kw in analysis_keywords:
                            if kw in user_input:
                                is_analysis_request = True
                                break
                    if is_analysis_request and not explicit_sql_request:
                        need_sql = False
                    else:
                        need_sql = bool(generate_sql) or explicit_sql_request
                    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    generated_sql = ""
                    if not need_sql:
                        # 更保守的意图检测：只有当用户明确要求查询数据库、写 SQL、或指定表名时才返回 SQL。
                        # 对于常见的数据分析请求（例如：描述数据、计算统计量、作图建议、解释模型结果等），请返回 NO_SQL。
                       
                        intent_prompt = (
                            "当前时间：" + current_time + "\n"
                            "请判断下面的用户请求是否确实需要对数据库表执行查询并返回结果。"
                            " 仅在用户明确要求：\n  - 运行或构造 SQL 查询；\n  - 指定表名或列名需要从数据库检索；\n  - 或明确写出如 '请帮我写 SQL' / '查询 <table>' 等需求时，才返回一条合法的 SELECT SQL 语句。"
                        )
                        intent_prompt += "\n如果不需要查询数据库（例如用户要求对已加载的数据做统计分析、可视化、解读或建议），请只返回 NO_SQL。"
                        intent_prompt += f"\n用户请求：{user_input}\n请仅返回一行：要么是一条 SQL（以 SELECT 开头，不要任何解释、标点或分号），要么返回 NO_SQL。"
                        intent_response = q.predict(intent_prompt)
                        # 如果模型返回了 SQL（包含 select），则视为需要生成 SQL
                        for ln in intent_response.splitlines():
                            s = ln.strip()
                            if not s:
                                continue
                            if s.upper() == 'NO_SQL':
                                break
                            # 以首个非空行作为可能的 SQL
                            generated_sql = s
                            break
                        if generated_sql:
                            # 持久化生成的 SQL，保证在脚本重跑后仍可执行
                            st.session_state['generated_sql'] = generated_sql
                            need_sql = True
                            # 告知用户模型生成 SQL（未执行）
                            st.info('模型判断需要查询；已生成 SQL，需你确认后执行。')
                    # 若需要生成 SQL（用户勾选或模型判定），则使用模型或上一步生成的 SQL
                    if need_sql:
                        # 给模型明确的指令，要求仅返回 SQL 查询，不要多余文字
                        # 构造 prompt：若有已加载的 DataFrame，附带数据摘要；否则只用会话上下文
                        sql_prompt = (
                            "当前时间：" + current_time + "\n"
                            "请基于下面的对话，生成一个只包含单条 SELECT SQL 查询的语句，"
                            "仅使用目标表，并使用 CURRENT_DATE 替代当天日期相关条件。"
                        )
                        sql_prompt += (
                            "\n如果目标表的列名可能未知，请返回一条或多条安全的探测 SQL（每行一条、仅使用 SELECT），"
                            "用于定位列名或查看样例数据。例如：查询 `information_schema.columns` 获取列名，或使用 `SELECT * FROM <table> LIMIT 10` 查看样本。"
                            "不要包含分号或任何注释，也不要包含插入/更新/删除等写操作。"
                        )
                        if st.session_state.df is not None:
                            sql_prompt += f"数据摘要：\n{build_dataset_summary(st.session_state.df)}\n"
                        sql_prompt += f"对话：\n{conversation}\n只返回 SQL，不要解释。"
                        generated = q.predict(sql_prompt)
                        # 清理模型输出，取首个非空行作为 SQL
                        generated_sql = ""
                        for ln in generated.splitlines():
                            s = ln.strip()
                            if s:
                                generated_sql = s
                                break
                        # 持久化生成的 SQL，保证在脚本重跑后仍可执行
                        if generated_sql:
                            st.session_state['generated_sql'] = generated_sql
                        # 如果之前 intent 阶段已经生成了 SQL，则优先使用；否则使用本次生成结果
                        if not generated_sql:
                            if not generated_sql:
                                generated_sql = ""
                            if not generated_sql and not generated.strip():
                                st.error('模型未生成有效 SQL。')
                                reply = f"[模型未生成 SQL] {generated}"
                        if not generated_sql:
                            # 清理模型输出，取首个非空行作为 SQL
                            for ln in generated.splitlines():
                                s = ln.strip()
                                if s:
                                    generated_sql = s
                                    break
                        if not generated_sql:
                            st.error('模型未生成有效 SQL。')
                            reply = f"[模型未生成 SQL] {generated}"
                        else:
                            # 可编辑的 SQL 文本区域，允许用户修改模型生成的 SQL
                            st.text_area('生成的 SQL（可编辑）', value=st.session_state.get('generated_sql', generated_sql), height=140, key='generated_sql_editor')
                            # 将编辑器内容同步回主生成 SQL 存储
                            st.session_state['generated_sql'] = st.session_state.get('generated_sql_editor', generated_sql)
                            # 调试信息：显示生成的 SQL 与校验状态，便于排查按钮消失问题
                            try:
                                debug_expanded = st.checkbox('显示 SQL 调试信息', value=False, key='debug_sql_info')
                                if debug_expanded:
                                    st.write('generated_sql:', generated_sql)
                                    st.write('DEFAULT_DB_URL configured:', bool(DEFAULT_DB_URL))
                                    try:
                                        st.write('allowed tables:', allowed)
                                    except Exception:
                                        st.write('allowed tables: <未定义>')
                                    try:
                                        st.write('is_safe_select:', is_safe_select(generated_sql, allowed))
                                    except Exception:
                                        st.write('is_safe_select: <error>')
                                    st.warning('若你确定 SQL 安全，也可启用下方调试开关强制执行（仅用于调试环境）。')
                                    force = st.checkbox('允许调试强制执行生成的 SQL（跳过表白名单）', value=False, key='debug_force_exec')
                            except Exception:
                                pass
                            # 将生成的 SQL 插入会话历史，便于追溯（但不自动执行）
                            st.session_state.history.append({'role': 'assistant', 'content': f'[生成的 SQL] {generated_sql}'})
                            # 始终显示一个可见的调试执行按钮，便于在 UI 中手动触发执行（会执行安全检查）
                            try:
                                exec_always = st.button('执行生成的 SQL（始终可见，调试）', key='always_exec_button')
                            except Exception:
                                exec_always = False
                            if exec_always:
                                sql_to_execute = st.session_state.get('generated_sql', generated_sql)
                                low = sql_to_execute.lower()
                                if ';' in low:
                                    st.error('检测到不安全的 SQL（包含分号/多语句），已拒绝执行。')
                                else:
                                    forbidden = ['insert ', 'update ', 'delete ', 'drop ', 'create ', 'alter ', 'truncate ', 'replace ']
                                    if any(k in low for k in forbidden):
                                        st.error('检测到写操作或不安全关键词，已拒绝执行。')
                                    else:
                                        if not DEFAULT_DB_URL:
                                            st.error('未配置默认数据库连接，无法执行 SQL。请在 config.py 中配置 DEFAULT_DB_CONFIG。')
                                        else:
                                            try:
                                                st.session_state.history.append({'role': 'assistant', 'content': f'[开始执行 SQL 调试按钮] {sql_to_execute}'})
                                                eng = create_engine(DEFAULT_DB_URL)
                                                df_res = pd.read_sql_query(sql_to_execute, con=eng)
                                                rows = len(df_res)
                                                cols_res = list(df_res.columns)
                                                st.session_state['last_exec_sql'] = sql_to_execute
                                                st.session_state['last_exec_df'] = df_res.head(200)
                                                st.session_state['last_exec_meta'] = {'rows': rows, 'cols': cols_res}
                                                st.session_state.history.append({'role': 'assistant', 'content': f'[SQL 调试执行完成] rows={rows}, cols={cols_res}'})
                                                st.subheader('SQL 执行结果（前 200 行）')
                                                st.dataframe(st.session_state['last_exec_df'])
                                            except Exception as e:
                                                st.error(f'执行 SQL 失败：{e}')
                                                st.session_state.history.append({'role': 'assistant', 'content': f'[调试执行失败] {e}'})

                            # 验证 SQL 安全性
                            def is_safe_select(sql_text: str, allowed_tables: list = None) -> bool:
                                low = sql_text.lower()
                                # 禁止 ; 多语句
                                if ';' in low:
                                    return False
                                # 禁止写操作关键词
                                forbidden = ['insert ', 'update ', 'delete ', 'drop ', 'create ', 'alter ', 'truncate ', 'replace ']
                                if any(k in low for k in forbidden):
                                    return False
                                # 必须以 select 开头
                                if not low.strip().startswith('select'):
                                    return False
                                # 简单检查表名白名单
                                if allowed_tables is not None:
                                    found = False
                                    for t in allowed_tables:
                                        if t.lower() in low:
                                            found = True
                                            break
                                    if not found:
                                        return False
                                return True

                            # 获取可用表用于校验（若配置 DEFAULT_DB_URL）
                            allowed = None
                            try:
                                if DEFAULT_DB_URL:
                                    eng = create_engine(DEFAULT_DB_URL)
                                    allowed = inspect(eng).get_table_names()
                                    if allowed is None:
                                        allowed = []
                                    # 允许查询 information_schema 以便模型返回基于 schema 的探测 SQL
                                    if 'information_schema' not in [t.lower() for t in allowed]:
                                        allowed.append('information_schema')
                            except Exception:
                                allowed = None

                            safe = is_safe_select(generated_sql, allowed)
                            # 支持调试强制执行：若用户在界面勾选了 debug_force_exec，则允许跳过表名白名单
                            force_exec = bool(st.session_state.get('debug_force_exec', False))
                            can_execute = safe or force_exec
                            if not can_execute:
                                st.error('模型生成的 SQL 未通过安全校验，已拒绝执行。')
                                st.session_state.history.append({'role': 'assistant', 'content': f'[生成的 SQL 被拒绝] {generated_sql}'})
                                if force_exec:
                                    st.warning('已启用强制执行，但 SQL 未通过安全校验：请确认只读并谨慎执行。')
                            else:
                                st.session_state.history.append({'role': 'assistant', 'content': f'[生成的 SQL 已通过安全校验（未执行）] {generated_sql}'})
                                if not DEFAULT_DB_URL:
                                    st.error('未配置默认数据库连接，无法执行 SQL。请在 config.py 中配置 DEFAULT_DB_CONFIG。')
                                else:
                                    if st.button('执行生成的 SQL'):
                                        sql_to_execute = st.session_state.get('generated_sql', generated_sql)
                                        try:
                                            st.session_state.history.append({'role': 'assistant', 'content': f'[开始执行 SQL] {sql_to_execute}'})
                                            eng = create_engine(DEFAULT_DB_URL)
                                            df_res = pd.read_sql_query(sql_to_execute, con=eng)
                                            rows = len(df_res)
                                            cols_res = list(df_res.columns)
                                            st.session_state.history.append({'role': 'assistant', 'content': f'[SQL 执行完成] rows={rows}, cols={cols_res}'})
                                            # 缓存执行结果，便于在重跑后查看
                                            st.session_state['last_exec_sql'] = sql_to_execute
                                            st.session_state['last_exec_df'] = df_res.head(200)
                                            st.session_state['last_exec_meta'] = {'rows': rows, 'cols': cols_res}
                                            st.subheader('SQL 执行结果（前 200 行）')
                                            st.dataframe(st.session_state['last_exec_df'])
                                        except Exception as e:
                                            err = str(e)
                                            st.error(f'执行 SQL 失败：{err}')
                                            st.session_state.history.append({'role': 'assistant', 'content': f'[执行失败] {err}'})
                                            # 将执行错误和原始 SQL 返回给模型，请求修正（仅在用户允许的情况下）
                                            fix_prompt = (
                                                "下面是一个 SQL 语句及其执行时的错误信息。请在确保只读的前提下修正该 SQL。"
                                                "为了定位列名或数据问题，你可以采用以下两种策略之一："
                                                "(1) 返回一个宽泛的安全扫描语句，例如 `SELECT * FROM <table> LIMIT 100`，用于查看表的真实列和值；"
                                                "(2) 或者返回多条安全的探测查询（每行一条 SELECT、不要分号），每条用于检查某些候选列或筛选条件。"
                                                "请只返回 SQL 语句（可以是一条或多条，每行一条），不要任何解释或分号。\n"
                                            )
                                            # 附带可用表名和前几列信息（若有）以帮助模型修正
                                            schema_info = ''
                                            if allowed:
                                                schema_info += '可用表：' + ', '.join(allowed) + '\n'
                                            if st.session_state.df is not None:
                                                cols = ', '.join(list(st.session_state.df.columns)[:30])
                                                schema_info += f'当前上传数据列（示例）: {cols}\n'
                                            fix_prompt += schema_info
                                            fix_prompt += f"原始 SQL: {generated_sql}\n错误信息: {err}\n请返回修正后的 SQL（一条或多条，每行一条）："
                                            fixed_sql_resp = q.predict(fix_prompt)
                                            # 解析模型返回：允许多行，每行为一条 SQL
                                            fixed_sqls = []
                                            for ln in fixed_sql_resp.splitlines():
                                                s = ln.strip()
                                                if not s:
                                                    continue
                                                # 忽略非以 select 开头的无关行
                                                if s.lower().startswith('select'):
                                                    fixed_sqls.append(s)
                                            if not fixed_sqls:
                                                # 退回兼容旧逻辑：尝试取第一非空行
                                                fallback = ''
                                                for ln in fixed_sql_resp.splitlines():
                                                    s = ln.strip()
                                                    if s:
                                                        fallback = s
                                                        break
                                                if fallback:
                                                    fixed_sqls = [fallback]

                                            if not fixed_sqls:
                                                st.error('模型未返回修正后的 SQL。')
                                                st.session_state.history.append({'role': 'assistant', 'content': f'[修正失败] {fixed_sql_resp}'})
                                            else:
                                                # 持久化修正后的 SQL 列表
                                                st.session_state['fixed_sql_list'] = fixed_sqls
                                                # 显示每条 SQL 并提供独立执行按钮
                                                st.session_state.history.append({'role': 'assistant', 'content': f'[模型修正 SQL 列表] {fixed_sqls}'})
                                                for idx, ssql in enumerate(fixed_sqls):
                                                    st.code(ssql, language='sql')
                                                    safe_fixed = is_safe_select(ssql, allowed)
                                                    if not safe_fixed:
                                                        st.error(f'第 {idx+1} 条 SQL 未通过安全校验，已拒绝执行。')
                                                        st.session_state.history.append({'role': 'assistant', 'content': f'[第 {idx+1} 条 SQL 被拒绝] {ssql}'})
                                                        continue
                                                    btn_key = f'exec_fixed_{idx}'
                                                    if st.button(f'执行第 {idx+1} 条 SQL', key=btn_key):
                                                        try:
                                                            st.session_state.history.append({'role': 'assistant', 'content': f'[开始执行 修正后 SQL 第 {idx+1} 条] {ssql}'})
                                                            eng = create_engine(DEFAULT_DB_URL)
                                                            df_fixed = pd.read_sql_query(ssql, con=eng)
                                                            rows = len(df_fixed)
                                                            cols_fixed = list(df_fixed.columns)
                                                            st.session_state.history.append({'role': 'assistant', 'content': f'[修正后 SQL 第 {idx+1} 条 执行完成] rows={rows}, cols={cols_fixed}'})
                                                            # 缓存执行结果
                                                            st.session_state['last_exec_sql'] = ssql
                                                            st.session_state['last_exec_df'] = df_fixed.head(200)
                                                            st.session_state['last_exec_meta'] = {'rows': rows, 'cols': cols_fixed}
                                                            st.subheader(f'修正后 SQL 第 {idx+1} 条 执行结果（前 200 行）')
                                                            st.dataframe(st.session_state['last_exec_df'])
                                                        except Exception as e2:
                                                            st.error(f'执行修正后的 SQL 第 {idx+1} 条 失败：{e2}')
                                                            st.session_state.history.append({'role': 'assistant', 'content': f'[修正后执行失败 第 {idx+1} 条] {e2}'})
                                    else:
                                        st.info('如果确认该 SQL 安全，请点击上方按钮执行。')
                    else:
                        reply = q.predict(conversation)
                except Exception as e:
                    reply = f"[调用错误] {e}"

            # 当不是 SQL-生成/执行流程时，把模型回复加入会话（仅在 reply 非空时）
            if not (generate_sql and st.session_state.df is not None):
                if reply:
                    st.session_state.history.append({'role': 'assistant', 'content': reply})
                st.rerun()

    # 如果上一次会话已经生成了 SQL（保存在 session），但当前无新的 user_input，
    # 仍然需要在界面上渲染生成的 SQL 与执行按钮，避免用户在点击执行时按钮闪现消失。
    if 'generated_sql' in st.session_state and not user_input:
        generated_sql = st.session_state.get('generated_sql', '')
        if generated_sql:
            # 在持久化视图中也提供一个可编辑的 SQL 文本区域（与生成时使用相同的编辑器 key，从而保持同步）
            st.text_area('生成的 SQL（可编辑）', value=st.session_state.get('generated_sql', generated_sql), height=140, key='generated_sql_editor')
            st.session_state['generated_sql'] = st.session_state.get('generated_sql_editor', generated_sql)
            # 简单安全校验函数（与上面逻辑保持一致）
            def _is_safe_select(sql_text: str, allowed_tables: list = None) -> bool:
                low = sql_text.lower()
                if ';' in low:
                    return False
                forbidden = ['insert ', 'update ', 'delete ', 'drop ', 'create ', 'alter ', 'truncate ', 'replace ']
                if any(k in low for k in forbidden):
                    return False
                if not low.strip().startswith('select'):
                    return False
                if allowed_tables is not None:
                    found = False
                    for t in allowed_tables:
                        if t.lower() in low:
                            found = True
                            break
                    if not found:
                        return False
                return True

            # 显示调试信息开关
            debug_expanded = st.checkbox('显示 SQL 调试信息', value=False, key='debug_sql_info_persist')
            if debug_expanded:
                st.write('generated_sql:', generated_sql)
                st.write('DEFAULT_DB_URL configured:', bool(DEFAULT_DB_URL))
                # 重新获取 allowed 表
                allowed = None
                try:
                    if DEFAULT_DB_URL:
                        eng = create_engine(DEFAULT_DB_URL)
                        allowed = inspect(eng).get_table_names()
                        if allowed is None:
                            allowed = []
                except Exception:
                    allowed = None
                st.write('allowed tables:', allowed)
                try:
                    st.write('is_safe_select:', _is_safe_select(generated_sql, allowed))
                except Exception:
                    st.write('is_safe_select: <error>')
                st.warning('若你确定 SQL 安全，也可启用下方调试开关强制执行（仅用于调试环境）。')
                force = st.checkbox('允许调试强制执行生成的 SQL（跳过表白名单）', value=False, key='debug_force_exec_persist')

            # 始终可见的调试执行按钮（与上方按钮行为一致）
            try:
                exec_always = st.button('执行生成的 SQL（始终可见，调试）', key='always_exec_button_persist')
            except Exception:
                exec_always = False
            if exec_always:
                sql_to_execute = generated_sql
                low = sql_to_execute.lower()
                if ';' in low:
                    st.error('检测到不安全的 SQL（包含分号/多语句），已拒绝执行。')
                else:
                    forbidden = ['insert ', 'update ', 'delete ', 'drop ', 'create ', 'alter ', 'truncate ', 'replace ']
                    if any(k in low for k in forbidden):
                        st.error('检测到写操作或不安全关键词，已拒绝执行。')
                    else:
                        if not DEFAULT_DB_URL:
                            st.error('未配置默认数据库连接，无法执行 SQL。请在 config.py 中配置 DEFAULT_DB_CONFIG。')
                        else:
                            try:
                                st.session_state.history.append({'role': 'assistant', 'content': f'[开始执行 SQL 调试按钮] {sql_to_execute}'})
                                eng = create_engine(DEFAULT_DB_URL)
                                df_res = pd.read_sql_query(sql_to_execute, con=eng)
                                rows = len(df_res)
                                cols_res = list(df_res.columns)
                                st.session_state['last_exec_sql'] = sql_to_execute
                                st.session_state['last_exec_df'] = df_res.head(200)
                                st.session_state['last_exec_meta'] = {'rows': rows, 'cols': cols_res}
                                st.session_state.history.append({'role': 'assistant', 'content': f'[SQL 调试执行完成] rows={rows}, cols={cols_res}'})
                                st.subheader('SQL 执行结果（前 200 行）')
                                st.dataframe(st.session_state['last_exec_df'])
                            except Exception as e:
                                st.error(f'执行 SQL 失败：{e}')
                                st.session_state.history.append({'role': 'assistant', 'content': f'[调试执行失败] {e}'})

# 底部固定表单将被渲染在主流程开始处以确保按下发送能立即触发处理（见上方插入点）。

st.markdown("\n---\n使用说明：可上传 CSV 或填写数据库连接 + 表名以自动加载数据；会话中会附带数据摘要发送给模型以便生成与数据相关的回答。")
