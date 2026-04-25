from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.config import load_settings
from src.db import connect


INTAKE_ORDER = ["JAN", "FEB", "MAR", "JUL", "AUG", "OCT"]
SORT_OPTIONS = {
    "课程名 A-Z": ("course_name", True),
    "课程名 Z-A": ("course_name", False),
    "学费 从低到高": ("tuition_fee_aud", True),
    "学费 从高到低": ("tuition_fee_aud", False),
    "IELTS 总分 从低到高": ("ielts_overall", True),
    "IELTS 总分 从高到低": ("ielts_overall", False),
    "最大学制 从低到高": ("duration_max_years", True),
    "最大学制 从高到低": ("duration_max_years", False),
}
APPLICATION_FILTERS = {
    "Limited places": "limited_places",
    "Quota applies": "quota_applies",
    "Portfolio": "requires_portfolio",
    "Personal statement": "requires_personal_statement",
    "Supplementary form": "requires_supplementary_form",
    "CV / Resume": "requires_cv_or_resume",
    "References": "requires_references",
    "Work experience": "requires_work_experience",
}


def fetch_dashboard_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    settings = load_settings()
    with connect(settings) as conn:
        courses_df = pd.read_sql(
            """
            select
                c.id,
                c.course_name,
                c.course_name_raw,
                c.cricos,
                c.duration_min_years,
                c.duration_max_years,
                c.duration_raw,
                c.commencing_semester_raw,
                c.tuition_fee_aud,
                c.source_file_name,
                c.source_sheet_name,
                c.source_row_number,
                car.requirement_source,
                car.source_url,
                car.academic_requirement_text,
                car.academic_requirements_json,
                car.raw_english_requirement,
                car.english_req_details,
                car.application_details_json,
                car.supplementary_metadata_json,
                car.source_map_json,
                car.ielts_overall,
                car.ielts_min_band,
                car.ielts_listening,
                car.ielts_reading,
                car.ielts_speaking,
                car.ielts_writing,
                car.last_verified_at
            from courses c
            left join course_admission_requirements car
              on car.course_id = c.id
             and car.is_current = true
            order by c.course_name, c.source_row_number
            """,
            conn,
        )
        intakes_df = pd.read_sql(
            """
            select
                c.id as course_id,
                c.course_name,
                ci.intake_month,
                ci.sort_order
            from course_intakes ci
            join courses c on c.id = ci.course_id
            order by c.course_name, ci.sort_order
            """,
            conn,
        )
    return courses_df, intakes_df


def build_duration_display(courses_df: pd.DataFrame) -> pd.Series:
    labels = []
    for _, row in courses_df.iterrows():
        if row["duration_min_years"] == row["duration_max_years"]:
            labels.append(f'{row["duration_min_years"]:.2f}'.rstrip("0").rstrip(".") + " 年")
        else:
            labels.append(
                f'{row["duration_min_years"]:.2f}'.rstrip("0").rstrip(".")
                + " - "
                + f'{row["duration_max_years"]:.2f}'.rstrip("0").rstrip(".")
                + " 年"
            )
    return pd.Series(labels, index=courses_df.index)


def build_intake_map(intakes_df: pd.DataFrame) -> dict[str, str]:
    return (
        intakes_df.sort_values(["course_id", "sort_order"])
        .groupby("course_id")["intake_month"]
        .apply(lambda values: ", ".join(values))
        .to_dict()
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _truthy(value: Any) -> bool:
    return bool(value) and not pd.isna(value)


def _trim_text(value: str, limit: int = 140) -> str:
    if not value:
        return ""
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _format_language_tests(details: dict[str, Any]) -> str:
    tests = _as_list(details.get("language_tests"))
    labels: list[str] = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        name = test.get("test_name")
        overall = test.get("overall")
        if name and overall:
            labels.append(f"{name} {overall}")
        elif name:
            labels.append(str(name))
    return " | ".join(labels)


def _format_required_documents(details: dict[str, Any]) -> str:
    docs = [str(doc) for doc in _as_list(details.get("required_documents")) if doc]
    return ", ".join(docs)


def _format_admission_flags(details: dict[str, Any], supplementary: dict[str, Any]) -> str:
    flags: list[str] = []
    if details.get("limited_places"):
        flags.append("Limited places")
    if details.get("quota_applies"):
        flags.append("Quota applies")
    if details.get("requires_portfolio"):
        flags.append("Portfolio")
    if details.get("requires_personal_statement"):
        flags.append("Personal statement")
    if details.get("requires_supplementary_form"):
        flags.append("Supplementary form")
    if details.get("requires_cv_or_resume"):
        flags.append("CV/Resume")
    if details.get("requires_references"):
        flags.append("References")
    if details.get("requires_work_experience"):
        flags.append("Work experience")
    if supplementary.get("rpl_detected"):
        flags.append("RPL / Credit")
    return ", ".join(flags)


def enrich_courses_df(courses_df: pd.DataFrame) -> pd.DataFrame:
    enriched_df = courses_df.copy()

    enriched_df["academic_requirements_json"] = enriched_df["academic_requirements_json"].apply(_as_dict)
    enriched_df["english_req_details"] = enriched_df["english_req_details"].apply(_as_dict)
    enriched_df["application_details_json"] = enriched_df["application_details_json"].apply(_as_dict)
    enriched_df["supplementary_metadata_json"] = enriched_df["supplementary_metadata_json"].apply(_as_dict)
    enriched_df["source_map_json"] = enriched_df["source_map_json"].apply(_as_dict)

    enriched_df["has_crawled_admissions"] = enriched_df["requirement_source"].eq("usyd_web_crawl")
    enriched_df["admission_source_label"] = enriched_df["has_crawled_admissions"].map(
        {True: "官网爬取", False: "Excel / 原始导入"}
    )
    enriched_df["language_tests_display"] = enriched_df["english_req_details"].apply(_format_language_tests)
    enriched_df["required_documents_display"] = enriched_df["application_details_json"].apply(_format_required_documents)
    enriched_df["application_flags_display"] = enriched_df.apply(
        lambda row: _format_admission_flags(row["application_details_json"], row["supplementary_metadata_json"]),
        axis=1,
    )
    enriched_df["academic_summary"] = enriched_df["academic_requirement_text"].fillna("").apply(_trim_text)
    enriched_df["source_url_display"] = enriched_df["source_url"].fillna("")

    for _, field_name in APPLICATION_FILTERS.items():
        enriched_df[field_name] = enriched_df["application_details_json"].apply(
            lambda value, field=field_name: bool(_as_dict(value).get(field, False))
        )

    return enriched_df


def apply_filters(courses_df: pd.DataFrame, intakes_df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.header("筛选条件")

    keyword = st.sidebar.text_input("关键词", placeholder="课程名 / CRICOS")
    selected_intakes = st.sidebar.multiselect("开学季", INTAKE_ORDER)
    only_crawled = st.sidebar.checkbox("只看已补官网招生信息", value=True)
    selected_application_filters = st.sidebar.multiselect("申请特征", list(APPLICATION_FILTERS.keys()))

    min_fee, max_fee = float(courses_df["tuition_fee_aud"].min()), float(courses_df["tuition_fee_aud"].max())
    fee_range = st.sidebar.slider("学费区间 (AUD)", min_value=min_fee, max_value=max_fee, value=(min_fee, max_fee))

    min_duration = float(courses_df["duration_min_years"].min())
    max_duration = float(courses_df["duration_max_years"].max())
    duration_range = st.sidebar.slider(
        "学制区间 (年)",
        min_value=min_duration,
        max_value=max_duration,
        value=(min_duration, max_duration),
        step=0.5,
    )

    overall_options = sorted(value for value in courses_df["ielts_overall"].dropna().unique())
    selected_overall = st.sidebar.multiselect("IELTS 总分", overall_options)

    min_band_floor = st.sidebar.selectbox("IELTS 最低小分不少于", options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0)
    listening_floor = st.sidebar.selectbox("听力不少于", options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0)
    reading_floor = st.sidebar.selectbox("阅读不少于", options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0)
    speaking_floor = st.sidebar.selectbox("口语不少于", options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0)
    writing_floor = st.sidebar.selectbox("写作不少于", options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0)

    only_duplicates = st.sidebar.checkbox("只看重复 CRICOS")
    only_irregular_ielts = st.sidebar.checkbox("只看不规则 IELTS 小分")
    sort_label = st.sidebar.selectbox("排序方式", list(SORT_OPTIONS.keys()))

    display_df = courses_df.copy()

    if selected_intakes:
        matched_course_ids = intakes_df.loc[intakes_df["intake_month"].isin(selected_intakes), "course_id"].unique()
        display_df = display_df[display_df["id"].isin(matched_course_ids)]

    if keyword.strip():
        normalized_keyword = keyword.strip().lower()
        display_df = display_df[
            display_df["course_name"].str.lower().str.contains(normalized_keyword, na=False)
            | display_df["cricos"].str.lower().str.contains(normalized_keyword, na=False)
        ]

    if only_crawled:
        display_df = display_df[display_df["has_crawled_admissions"]]

    for label in selected_application_filters:
        display_df = display_df[display_df[APPLICATION_FILTERS[label]]]

    display_df = display_df[
        display_df["tuition_fee_aud"].between(fee_range[0], fee_range[1], inclusive="both")
        & (display_df["duration_min_years"] >= duration_range[0])
        & (display_df["duration_max_years"] <= duration_range[1])
    ]

    if selected_overall:
        display_df = display_df[display_df["ielts_overall"].isin(selected_overall)]
    if min_band_floor is not None:
        display_df = display_df[display_df["ielts_min_band"].fillna(-1) >= min_band_floor]
    if listening_floor is not None:
        display_df = display_df[display_df["ielts_listening"].fillna(-1) >= listening_floor]
    if reading_floor is not None:
        display_df = display_df[display_df["ielts_reading"].fillna(-1) >= reading_floor]
    if speaking_floor is not None:
        display_df = display_df[display_df["ielts_speaking"].fillna(-1) >= speaking_floor]
    if writing_floor is not None:
        display_df = display_df[display_df["ielts_writing"].fillna(-1) >= writing_floor]

    if only_duplicates:
        duplicate_cricos = display_df["cricos"].value_counts()
        display_df = display_df[display_df["cricos"].isin(duplicate_cricos[duplicate_cricos > 1].index)]

    if only_irregular_ielts:
        display_df = display_df[
            (display_df["ielts_listening"] != display_df["ielts_min_band"])
            | (display_df["ielts_reading"] != display_df["ielts_min_band"])
            | (display_df["ielts_speaking"] != display_df["ielts_min_band"])
            | (display_df["ielts_writing"] != display_df["ielts_min_band"])
        ]

    sort_column, ascending = SORT_OPTIONS[sort_label]
    display_df = display_df.sort_values(sort_column, ascending=ascending, na_position="last")
    return display_df


def render_summary(display_df: pd.DataFrame) -> None:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("当前结果数", int(len(display_df)))
    col2.metric("官网已补齐", int(display_df["has_crawled_admissions"].sum()))
    col3.metric("Limited places", int(display_df["limited_places"].sum()))
    col4.metric("需补材料", int((display_df["required_documents_display"] != "").sum()))
    col5.metric("平均学费(AUD)", f'{display_df["tuition_fee_aud"].mean():,.0f}' if len(display_df) else "-")


def render_language_tests(row: pd.Series) -> None:
    details = _as_dict(row["english_req_details"])
    tests = _as_list(details.get("language_tests"))
    st.markdown("**语言要求明细**")
    if not tests:
        st.info("当前课程没有结构化语言测试明细。")
        return

    language_rows = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        component_scores = _as_dict(test.get("component_scores"))
        language_rows.append(
            {
                "考试": test.get("test_name", ""),
                "总分": test.get("overall", ""),
                "听力": component_scores.get("listening", ""),
                "阅读": component_scores.get("reading", ""),
                "口语": component_scores.get("speaking", ""),
                "写作": component_scores.get("writing", ""),
                "来源": test.get("source_type", ""),
            }
        )
    st.dataframe(pd.DataFrame(language_rows), width="stretch", hide_index=True)


def render_academic_pathways(row: pd.Series) -> None:
    st.markdown("**学术录取要求**")
    if row["academic_requirement_text"]:
        st.write(row["academic_requirement_text"])
    else:
        st.info("当前课程没有抓到学术录取要求原文。")


def render_application_details(row: pd.Series) -> None:
    details = _as_dict(row["application_details_json"])
    supplementary = _as_dict(row["supplementary_metadata_json"])

    st.markdown("**申请材料与注意事项**")

    badges = [label for label, field_name in APPLICATION_FILTERS.items() if details.get(field_name)]
    if supplementary.get("rpl_detected"):
        badges.append("RPL / Credit")
    if supplementary.get("award_requirements_detected"):
        badges.append("Award rules detected")

    if badges:
        st.caption(" | ".join(badges))

    docs = [str(item) for item in _as_list(details.get("required_documents")) if item]
    if docs:
        st.write("需要材料：", ", ".join(docs))

    notes = [str(item) for item in _as_list(details.get("selection_notes")) if item]
    if notes:
        st.write("筛选备注：")
        for note in notes:
            st.markdown(f"- {note}")

    raw_text = str(details.get("raw_text", "")).strip()
    if raw_text:
        with st.expander("查看申请说明原文", expanded=False):
            st.write(raw_text)


def render_source_details(row: pd.Series) -> None:
    source_map = _as_dict(row["source_map_json"])

    st.markdown("**来源信息**")
    if row["source_url"]:
        st.markdown(f"课程页：[打开官网课程页]({row['source_url']})")

    if not source_map:
        return

    source_rows = []
    for field_name, url in source_map.items():
        source_rows.append({"字段": field_name, "来源 URL": url})
    st.dataframe(pd.DataFrame(source_rows), width="stretch", hide_index=True)


def render_course_detail(display_df: pd.DataFrame) -> None:
    st.divider()
    st.subheader("课程详情")

    if display_df.empty:
        st.info("当前筛选结果为空，没有可展示的课程详情。")
        return

    selected_index = st.selectbox(
        "选择一门课程查看详情",
        options=list(display_df.index),
        format_func=lambda idx: (
            f"{display_df.loc[idx, 'course_name']} | {display_df.loc[idx, 'cricos']} | "
            f"{display_df.loc[idx, 'admission_source_label']}"
        ),
    )
    row = display_df.loc[selected_index]

    header_left, header_right = st.columns([3, 2])
    with header_left:
        st.markdown(f"### {row['course_name']}")
        st.caption(
            f"CRICOS: {row['cricos']} | 学制: {row['duration_display']} | 开学季: {row['intakes'] or '-'}"
        )
    with header_right:
        st.markdown(
            f"""
            <div style="background:#f7f5ef;border:1px solid #d8d1c3;padding:0.85rem 1rem;border-radius:12px;">
                <div style="font-size:0.9rem;color:#6c6558;">招生信息来源</div>
                <div style="font-size:1.1rem;font-weight:600;color:#2d2a26;">{row["admission_source_label"]}</div>
                <div style="margin-top:0.35rem;font-size:0.9rem;color:#6c6558;">最近验证: {row["last_verified_at"] or "-"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    tab1, tab2, tab3, tab4 = st.tabs(["学术要求", "语言要求", "申请材料", "来源"])
    with tab1:
        render_academic_pathways(row)
    with tab2:
        render_language_tests(row)
        if row["raw_english_requirement"]:
            with st.expander("查看语言要求原文", expanded=False):
                st.write(row["raw_english_requirement"])
    with tab3:
        render_application_details(row)
    with tab4:
        render_source_details(row)


def render_dashboard() -> None:
    st.set_page_config(page_title="USYD Query Console", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.2rem; padding-bottom: 1.2rem; max-width: 1500px;}
        div[data-testid="stMetric"] {
            background: linear-gradient(180deg, #faf7f0 0%, #f2ede1 100%);
            border: 1px solid #d8d1c3;
            padding: 0.9rem 1rem;
            border-radius: 12px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("USYD 课程查询后台")
    st.caption("现在会同时展示 Excel 基础字段和官网新爬回来的 academic requirements、language tests、application details。")

    courses_df, intakes_df = fetch_dashboard_data()
    intake_map = build_intake_map(intakes_df)
    courses_df["intakes"] = courses_df["id"].map(intake_map).fillna("")
    courses_df["duration_display"] = build_duration_display(courses_df)
    courses_df = enrich_courses_df(courses_df)

    display_df = apply_filters(courses_df, intakes_df)
    render_summary(display_df)

    st.divider()
    st.subheader("查询结果")

    export_df = display_df[
        [
            "course_name",
            "cricos",
            "admission_source_label",
            "duration_display",
            "duration_min_years",
            "duration_max_years",
            "intakes",
            "tuition_fee_aud",
            "application_flags_display",
            "required_documents_display",
            "language_tests_display",
            "ielts_overall",
            "ielts_min_band",
            "ielts_listening",
            "ielts_reading",
            "ielts_speaking",
            "ielts_writing",
            "academic_summary",
            "source_url_display",
            "source_file_name",
            "source_sheet_name",
            "source_row_number",
        ]
    ].rename(
        columns={
            "course_name": "课程名",
            "cricos": "CRICOS",
            "admission_source_label": "招生来源",
            "duration_display": "学制区间",
            "duration_min_years": "最小学制(年)",
            "duration_max_years": "最大学制(年)",
            "intakes": "开学季",
            "tuition_fee_aud": "学费(AUD)",
            "application_flags_display": "申请标签",
            "required_documents_display": "申请材料",
            "language_tests_display": "语言测试",
            "ielts_overall": "IELTS 总分",
            "ielts_min_band": "IELTS 最低小分",
            "ielts_listening": "听力",
            "ielts_reading": "阅读",
            "ielts_speaking": "口语",
            "ielts_writing": "写作",
            "academic_summary": "学术要求摘要",
            "source_url_display": "官网课程页",
            "source_file_name": "来源文件",
            "source_sheet_name": "来源Sheet",
            "source_row_number": "来源行号",
        }
    )

    control_left, control_right = st.columns([2, 1])
    with control_left:
        st.write(f"当前显示 `{len(export_df)}` 条结果")
    with control_right:
        st.download_button(
            "导出当前结果 CSV",
            data=export_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="usyd_courses_filtered.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.dataframe(export_df, width="stretch", hide_index=True, height=520)
    render_course_detail(display_df)


if __name__ == "__main__":
    render_dashboard()
