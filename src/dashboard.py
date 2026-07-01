from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from src.config import load_settings
from src.db import connect
from src.models.course_features import CourseFeatureProfile
from src.models.recommendation import RangePreference, RecommendationRequest, RecommendationResponse
from src.recommendation.course_features import generate_course_features, merge_course_feature_override
from src.recommendation.feature_repository import CourseFeatureRepository
from src.recommendation.service import RecommendationService, RecommendationServiceError


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
                car.last_verified_at,
                c.course_features,
                c.course_feature_overrides
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
    enriched_df["course_features"] = enriched_df["course_features"].apply(_as_dict)
    enriched_df["course_feature_overrides"] = enriched_df["course_feature_overrides"].apply(_as_dict)

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

    keyword = st.sidebar.text_input("关键词", placeholder="课程名 / CRICOS / 录取要求")
    selected_intakes = st.sidebar.multiselect("开学季", INTAKE_ORDER)
    only_crawled = st.sidebar.checkbox("只看已补官网招生信息", value=True)
    selected_application_filters = st.sidebar.multiselect("申请特征", list(APPLICATION_FILTERS.keys()))
    selected_feature_tags = st.sidebar.multiselect(
        "课程画像学科",
        ["data science", "computer science", "business", "business analytics", "finance", "design", "health"],
    )
    min_ai_relevance = st.sidebar.slider("AI 相关度不少于", min_value=0, max_value=5, value=0, step=1)

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
        display_df = display_df[_build_keyword_mask(display_df, keyword)]

    if only_crawled:
        display_df = display_df[display_df["has_crawled_admissions"]]

    for label in selected_application_filters:
        display_df = display_df[display_df[APPLICATION_FILTERS[label]]]

    if selected_feature_tags:
        wanted_tags = set(selected_feature_tags)
        display_df = display_df[
            display_df["course_features"].apply(
                lambda value: bool(wanted_tags & set(_feature_profile(value).discipline_tags))
            )
        ]
    if min_ai_relevance:
        display_df = display_df[
            display_df["course_features"].apply(lambda value: _feature_profile(value).ai_relevance >= min_ai_relevance)
        ]

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


def _build_keyword_mask(display_df: pd.DataFrame, keyword: str) -> pd.Series:
    normalized_keyword = keyword.strip().lower()
    searchable_columns = [
        "course_name",
        "cricos",
        "academic_requirement_text",
        "raw_english_requirement",
        "academic_summary",
        "application_flags_display",
        "required_documents_display",
        "language_tests_display",
    ]
    mask = pd.Series(False, index=display_df.index)
    for column in searchable_columns:
        if column not in display_df:
            continue
        mask = mask | display_df[column].fillna("").astype(str).str.lower().str.contains(
            normalized_keyword,
            regex=False,
        )
    return mask


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


def run_admission_semantic_search(query: str, top_k: int) -> list[Any]:
    from src.vector_store.embeddings import OpenAIEmbeddingClient
    from src.vector_store.runner import search_admissions
    from src.vector_store.storage import ChromaVectorStore

    settings = load_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY 未配置，暂时不能使用语义搜索。")
    vector_store = ChromaVectorStore.from_settings(settings)

    embedding_client = OpenAIEmbeddingClient(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        base_url=settings.openai_base_url,
        api_mode=settings.embedding_api_mode,
        max_workers=settings.embedding_max_workers,
    )
    return search_admissions(
        vector_store=vector_store,
        embedding_client=embedding_client,
        embedding_model=settings.embedding_model,
        query=query,
        top_k=top_k,
    )


def render_admission_search() -> None:
    with st.form("admission_semantic_search", border=False):
        search_query = st.text_input(
            "录取要求语义搜索",
            placeholder="作品集 / personal statement / IELTS 7.0 / work experience",
        )
        control_left, control_right = st.columns([1, 4])
        with control_left:
            top_k = st.number_input("结果数", min_value=3, max_value=20, value=5, step=1)
        with control_right:
            submitted = st.form_submit_button("搜索", type="primary", use_container_width=True)

    if not submitted:
        return

    normalized_query = search_query.strip()
    if not normalized_query:
        st.warning("请输入搜索内容。")
        return

    try:
        with st.spinner("正在搜索录取要求..."):
            results = run_admission_semantic_search(normalized_query, int(top_k))
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    except Exception as exc:  # pragma: no cover - Streamlit-facing safety net
        st.error(f"搜索失败：{exc}")
        return

    if not results:
        st.info("没有找到匹配的录取要求。")
        return

    result_rows = [
        {
            "课程": result.course_name,
            "CRICOS": result.cricos,
            "类型": _format_chunk_kind(result.chunk_kind),
            "匹配度": f"{result.similarity:.3f}",
            "摘要": _trim_text(result.content, limit=260),
            "来源": result.source_url or "",
        }
        for result in results
    ]
    st.dataframe(pd.DataFrame(result_rows), width="stretch", hide_index=True)


def _format_chunk_kind(chunk_kind: str) -> str:
    labels = {
        "academic": "学术要求",
        "english": "语言要求",
        "application": "申请材料",
    }
    return labels.get(chunk_kind, chunk_kind)


def run_usyd_recommendation(request: RecommendationRequest) -> RecommendationResponse:
    return RecommendationService().recommend(request)


def render_recommendation_console() -> None:
    st.subheader("申请资格筛选 / Hard Filter")

    with st.form("usyd_recommendation_form", border=True):
        st.caption("国内院校成绩按悉尼大学口径使用所有科目的算术平均分。")
        top_left, top_right = st.columns([2, 1])
        with top_left:
            target_major_keyword = st.text_input("目标方向", value="计算机")
        with top_right:
            academic_background = st.selectbox("本科院校层级", ["双非", "211", "985", "C9", "Tier1", "其他国内院校"], index=0)

        academic_left, academic_right = st.columns([1, 2])
        with academic_left:
            gpa_user = st.number_input("GPA / WAM", min_value=0.0, max_value=100.0, value=82.0, step=0.5)
        with academic_right:
            prior_major = st.text_input("本科专业", value="Computer Science")

        completed_courses_text = st.text_area(
            "已修课程",
            value="Programming\nStatistics\nDatabase Systems",
            help="每行一门课，也可以用逗号分隔。",
        )

        score_left, score_mid, score_right = st.columns(3)
        with score_left:
            ielts_overall_user = st.number_input("IELTS 总分", min_value=0.0, max_value=9.0, value=7.0, step=0.5)
        with score_mid:
            ielts_min_band_user = st.number_input("IELTS 最低小分", min_value=0.0, max_value=9.0, value=6.5, step=0.5)
        with score_right:
            accepts_pathway = st.checkbox("接受 pathway", value=False)

        band_left, band_mid_left, band_mid_right, band_right = st.columns(4)
        with band_left:
            ielts_listening_user = st.number_input("IELTS 听力", min_value=0.0, max_value=9.0, value=6.5, step=0.5)
        with band_mid_left:
            ielts_reading_user = st.number_input("IELTS 阅读", min_value=0.0, max_value=9.0, value=6.5, step=0.5)
        with band_mid_right:
            ielts_speaking_user = st.number_input("IELTS 口语", min_value=0.0, max_value=9.0, value=6.5, step=0.5)
        with band_right:
            ielts_writing_user = st.number_input("IELTS 写作", min_value=0.0, max_value=9.0, value=6.5, step=0.5)

        pref_left, pref_mid, pref_right = st.columns(3)
        with pref_left:
            preferred_intake = st.multiselect("偏好开学季", INTAKE_ORDER, default=["FEB", "JUL"])
        with pref_mid:
            budget_range = st.slider("预算区间 AUD", min_value=0, max_value=120000, value=(0, 70000), step=1000)
        with pref_right:
            duration_preference = st.slider("学制偏好 年", min_value=0.5, max_value=4.0, value=(1.0, 2.0), step=0.5)

        extra_left, extra_mid, extra_right = st.columns(3)
        with extra_left:
            campus_preference = st.text_input("校区偏好", placeholder="Camperdown / Sydney / Online")
        with extra_mid:
            study_mode_preference = st.selectbox("学习模式偏好", ["", "On campus", "Online", "Full time", "Part time"], index=0)
        with extra_right:
            degree_type_preference = st.selectbox("学位类型偏好", ["", "Master", "Graduate Diploma", "Graduate Certificate"], index=0)

        submitted = st.form_submit_button("运行申请资格筛选", type="primary", use_container_width=True)

    if submitted:
        request = RecommendationRequest(
            target_major_keyword=target_major_keyword,
            gpa_user=float(gpa_user),
            gpa_scale=100,
            ielts_overall_user=float(ielts_overall_user),
            ielts_min_band_user=float(ielts_min_band_user),
            ielts_listening_user=float(ielts_listening_user),
            ielts_reading_user=float(ielts_reading_user),
            ielts_speaking_user=float(ielts_speaking_user),
            ielts_writing_user=float(ielts_writing_user),
            academic_background=academic_background,
            prior_major=prior_major or None,
            completed_courses=_split_course_text(completed_courses_text),
            preferred_intake=preferred_intake or INTAKE_ORDER,
            budget_range=RangePreference(min=float(budget_range[0]), max=float(budget_range[1])),
            duration_preference=RangePreference(
                min=float(duration_preference[0]),
                max=float(duration_preference[1]),
            ),
            campus_preference=campus_preference or None,
            study_mode_preference=study_mode_preference or None,
            degree_type_preference=degree_type_preference or None,
            accepts_pathway=accepts_pathway,
        )
        try:
            with st.spinner("正在运行 hard filter 并生成下一层匹配..."):
                st.session_state["usyd_recommendation_response"] = run_usyd_recommendation(request)
        except RecommendationServiceError as exc:
            st.error(f"推荐失败：{exc}")
            return
        except Exception as exc:  # pragma: no cover - Streamlit-facing safety net
            st.error(f"推荐失败：{exc}")
            return

    response = st.session_state.get("usyd_recommendation_response")
    if response is None:
        st.info("填写用户画像后运行申请资格筛选。")
        return

    render_recommendation_response(response)


def _split_course_text(value: str) -> list[str]:
    courses: list[str] = []
    seen: set[str] = set()
    for chunk in value.replace(",", "\n").splitlines():
        label = " ".join(chunk.split()).strip()
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            courses.append(label)
    return courses


def render_recommendation_response(response: RecommendationResponse) -> None:
    metadata = response.metadata
    summary = response.eligibility_summary
    metric_cols = st.columns(6)
    metric_cols[0].metric("总候选数", summary.total_candidates)
    metric_cols[1].metric("满足硬性要求", summary.eligible_count)
    metric_cols[2].metric("高风险", summary.high_risk_count)
    metric_cols[3].metric("Pathway required", summary.pathway_required_count)
    metric_cols[4].metric("信息不足", summary.unknown_count)
    metric_cols[5].metric("不满足", summary.ineligible_count)

    st.caption(
        f"request_id: {metadata.request_id} | "
        f"model: {metadata.model_version} | "
        f"generated_at: {metadata.generated_at.isoformat()} | "
        f"scored_after_hard_filter: {metadata.scored_candidate_count} | "
        f"retrieval_degraded: {'yes' if metadata.degraded_retrieval else 'no'}"
    )

    hard_tabs = st.tabs(["满足硬性要求，进入下一层匹配", "高风险 / pathway / 信息不足", "不满足硬性要求"])
    with hard_tabs[0]:
        render_next_layer_candidates(response)
    with hard_tabs[1]:
        render_high_risk_programs(response)
    with hard_tabs[2]:
        render_excluded_programs(response)

    with st.expander("查询摘要与评分配置", expanded=False):
        render_query_summary(response)


def render_next_layer_candidates(response: RecommendationResponse) -> None:
    if not response.next_layer_candidates:
        st.info("当前没有课程通过硬性申请条件。")
        return

    st.markdown("**下一层匹配分档**")
    band_tabs = st.tabs(["冲刺", "匹配", "保底"])
    with band_tabs[0]:
        render_recommendation_band(response.reach_programs)
    with band_tabs[1]:
        render_recommendation_band(response.match_programs)
    with band_tabs[2]:
        render_recommendation_band(response.safety_programs)

    st.divider()
    for program in response.next_layer_candidates:
        render_eligibility_card(program, expanded=False)


def render_high_risk_programs(response: RecommendationResponse) -> None:
    if not response.high_risk_programs:
        st.success("当前没有高风险、pathway required 或信息不足课程。")
        return

    for program in response.high_risk_programs:
        render_eligibility_card(program, expanded=False)


def render_eligibility_card(program: Any, *, expanded: bool) -> None:
    badge = _eligibility_badge(program.eligibility_status)
    title = f"{program.course_name} | {badge}"
    with st.expander(title, expanded=expanded):
        top_cols = st.columns(4)
        top_cols[0].markdown(f"**Course**  \n{program.course_name}")
        top_cols[1].markdown(f"**Faculty / School**  \n{program.faculty or '-'} / {program.school or '-'}")
        top_cols[2].markdown(f"**Degree**  \n{program.degree_type or '-'}")
        top_cols[3].markdown(f"**Tuition**  \n{_format_money(program.tuition_fee_aud)}")

        meta_cols = st.columns(4)
        meta_cols[0].markdown(f"**Duration**  \n{program.duration or '-'}")
        meta_cols[1].markdown(f"**Campus**  \n{program.campus or '-'}")
        meta_cols[2].markdown(f"**Study mode**  \n{program.study_mode or '-'}")
        meta_cols[3].markdown(f"**Intake**  \n{', '.join(program.intakes) or '-'}")

        if program.source_url:
            st.markdown(f"[打开官网来源]({program.source_url})")

        st.markdown(f"**Hard filter summary**  \n{program.hard_filter_summary}")
        if program.blocking_reasons:
            st.error("Blocking reasons: " + " | ".join(program.blocking_reasons))
        if program.warnings:
            st.warning("Warnings: " + " | ".join(program.warnings))
        if program.missing_fields:
            st.info("需要人工复核字段: " + ", ".join(program.missing_fields))

        checklist_df = build_requirement_checks_dataframe(program.requirement_checks)
        st.dataframe(checklist_df, width="stretch", hide_index=True)
        render_check_evidence(program.requirement_checks)


def build_requirement_checks_dataframe(checks: list[Any]) -> pd.DataFrame:
    rows = []
    for check in checks:
        item = check.model_dump() if hasattr(check, "model_dump") else dict(check)
        rows.append(
            {
                "条件": item.get("name", ""),
                "用户情况": _display_cell_value(item.get("user_value")),
                "学校要求": _display_cell_value(item.get("required_value")),
                "判断": item.get("status", ""),
                "原因": item.get("reason", ""),
            }
        )
    return pd.DataFrame(rows, columns=["条件", "用户情况", "学校要求", "判断", "原因"])


def render_check_evidence(checks: list[Any]) -> None:
    for check in checks:
        item = check.model_dump() if hasattr(check, "model_dump") else dict(check)
        if item.get("status") not in {"fail", "warning", "unknown"}:
            continue
        snippets = item.get("evidence_snippets") or []
        if not snippets and not item.get("source_url"):
            continue
        with st.expander(f"Evidence | {item.get('name', '')} | {item.get('status', '')}", expanded=False):
            evidence_rows = []
            for snippet in snippets:
                if hasattr(snippet, "model_dump"):
                    snippet_data = snippet.model_dump()
                else:
                    snippet_data = dict(snippet)
                evidence_rows.append(
                    {
                        "evidence snippet": snippet_data.get("text", ""),
                        "source_url": snippet_data.get("source_url") or item.get("source_url") or "",
                        "source type": snippet_data.get("source") or item.get("source_type") or "",
                    }
                )
            if not evidence_rows:
                evidence_rows.append(
                    {
                        "evidence snippet": "",
                        "source_url": item.get("source_url") or "",
                        "source type": item.get("source_type") or "",
                    }
                )
            st.dataframe(pd.DataFrame(evidence_rows), width="stretch", hide_index=True)


def _display_cell_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}: {val}" for key, val in value.items())
    return str(value)


def _eligibility_badge(status: Any) -> str:
    status_value = getattr(status, "value", str(status))
    labels = {
        "ELIGIBLE": "满足硬性要求",
        "HIGH_RISK": "高风险",
        "PATHWAY_REQUIRED": "Pathway required",
        "UNKNOWN": "信息不足",
        "INELIGIBLE": "不满足硬性要求",
    }
    return labels.get(status_value, status_value)


def _format_money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"AUD {value:,.0f}"


def render_recommendation_band(programs: list[Any]) -> None:
    if not programs:
        st.info("当前没有该档推荐。")
        return

    rows = [
        {
            "课程": program.course_name,
            "CRICOS": program.cricos,
            "分数": f"{program.score:.4f}",
            "档位": program.band,
            "学制": program.duration,
            "开学季": ", ".join(program.intakes),
            "学费(AUD)": program.tuition_fee_aud,
            "IELTS": program.ielts_requirement,
            "GPA算法": _format_gpa_method(program.gpa_calculation_method),
            "画像匹配": (
                f"{program.feature_match.score:.1f}" if getattr(program, "feature_match", None) is not None else ""
            ),
            "来源": program.source_url or "",
        }
        for program in programs
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    for program in programs:
        with st.expander(f"{program.course_name} | {program.band} | score {program.score:.4f}", expanded=False):
            st.write(program.recommendation_reason)
            if getattr(program, "feature_match", None) is not None:
                render_feature_match(program.feature_match)
            st.markdown("**学术要求摘要**")
            st.write(program.academic_requirement_summary)
            evidence_rows = [
                {
                    "证据": snippet.text,
                    "来源类型": snippet.source or "",
                    "来源 URL": snippet.source_url or "",
                }
                for snippet in program.evidence_snippets
            ]
            if evidence_rows:
                st.dataframe(pd.DataFrame(evidence_rows), width="stretch", hide_index=True)


def render_excluded_programs(response: RecommendationResponse) -> None:
    if not response.excluded_programs:
        st.success("当前没有不满足硬性要求的课程。")
        return

    rows = [
        {
            "课程": program.course_name,
            "资格状态": _eligibility_badge(program.eligibility_status),
            "Blocking reasons": " | ".join(program.blocking_reasons) or program.reason,
            "说明": program.hard_filter_summary,
            "来源": program.source_url or "",
        }
        for program in response.excluded_programs
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    for program in response.excluded_programs:
        render_eligibility_card(program, expanded=False)


def render_query_summary(response: RecommendationResponse) -> None:
    query_summary = response.query_summary
    summary_rows = [
        {"字段": key, "值": value}
        for key, value in query_summary.items()
        if key not in {"degraded_retrieval"}
    ]
    st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)

    with st.expander("评分配置", expanded=False):
        st.json(response.metadata.scoring_config)


def _format_gpa_method(method: str) -> str:
    labels = {
        "usyd_arithmetic_average_all_courses": "悉尼大学：所有科目的算术平均分",
    }
    return labels.get(method, method)


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
            <div style="background:#f7f5ef;border:1px solid #d8d1c3;padding:0.85rem 1rem;border-radius:8px;">
                <div style="font-size:0.9rem;color:#6c6558;">招生信息来源</div>
                <div style="font-size:1.1rem;font-weight:600;color:#2d2a26;">{row["admission_source_label"]}</div>
                <div style="margin-top:0.35rem;font-size:0.9rem;color:#6c6558;">最近验证: {row["last_verified_at"] or "-"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["学术要求", "语言要求", "申请材料", "来源", "画像特征"])
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
    with tab5:
        render_course_features(row)


def render_feature_match(match_result: Any) -> None:
    cols = st.columns(3)
    cols[0].metric("画像匹配", f"{match_result.score:.1f}/100")
    cols[1].metric("画像风险", f"{match_result.risk_level:.1f}/5")
    cols[2].metric("硬性惩罚", f"{match_result.penalty_score:.1f}")
    if match_result.strengths:
        st.success("优势：" + " | ".join(match_result.strengths))
    if match_result.weaknesses:
        st.warning("弱项：" + " | ".join(match_result.weaknesses))


def render_course_features(row: pd.Series) -> None:
    profile = _feature_profile(row.get("course_features"))
    tag_cols = st.columns(4)
    tag_cols[0].markdown("**学科标签**  \n" + _format_tags(profile.discipline_tags))
    tag_cols[1].markdown("**知识标签**  \n" + _format_tags(profile.knowledge_tags))
    tag_cols[2].markdown("**职业方向**  \n" + _format_tags(profile.career_tags))
    tag_cols[3].markdown("**适合背景**  \n" + _format_tags(profile.background_fit_tags))

    score_rows = [
        {"维度": "Math", "分数": profile.math_intensity},
        {"维度": "Coding", "分数": profile.coding_intensity},
        {"维度": "Theory", "分数": profile.theory_intensity},
        {"维度": "Business", "分数": profile.business_intensity},
        {"维度": "AI", "分数": profile.ai_relevance},
        {"维度": "Data", "分数": profile.data_relevance},
        {"维度": "Conversion", "分数": profile.conversion_friendliness},
        {"维度": "Risk", "分数": profile.risk_level},
    ]
    st.dataframe(pd.DataFrame(score_rows), width="stretch", hide_index=True)

    with st.expander("编辑画像特征", expanded=False):
        render_course_feature_editor(row, profile)


def render_course_feature_editor(row: pd.Series, profile: CourseFeatureProfile) -> None:
    with st.form(f"feature_editor_{row['id']}", border=False):
        tags_text = st.text_input("学科标签", value=", ".join(profile.discipline_tags))
        ai_relevance = st.slider("AI 相关度", min_value=0, max_value=5, value=int(profile.ai_relevance), step=1)
        data_relevance = st.slider("Data 相关度", min_value=0, max_value=5, value=int(profile.data_relevance), step=1)
        risk_level = st.slider("风险等级", min_value=0, max_value=5, value=int(profile.risk_level), step=1)
        submitted = st.form_submit_button("保存画像覆盖", use_container_width=True)
    if not submitted:
        return
    overrides = {
        "discipline_tags": _split_csv(tags_text),
        "ai_relevance": float(ai_relevance),
        "data_relevance": float(data_relevance),
        "risk_level": float(risk_level),
    }
    try:
        generated = generate_course_features(row.to_dict())
        merged = merge_course_feature_override(generated, {**_as_dict(row.get("course_feature_overrides")), **overrides})
        settings = load_settings()
        with connect(settings) as conn:
            with conn.transaction():
                CourseFeatureRepository().save_course_features(
                    conn,
                    course_id=str(row["id"]),
                    course_features=merged,
                    manual_overrides={**_as_dict(row.get("course_feature_overrides")), **overrides},
                )
    except Exception as exc:  # pragma: no cover - Streamlit-facing safety net
        st.error(f"画像特征保存失败：{exc}")
        return
    st.success("画像特征已保存。")


def _feature_profile(value: Any) -> CourseFeatureProfile:
    return CourseFeatureProfile.model_validate(_as_dict(value))


def _format_tags(tags: list[str]) -> str:
    return ", ".join(tags) if tags else "-"


def _split_csv(value: str) -> list[str]:
    return [chunk.strip() for chunk in value.split(",") if chunk.strip()]


def render_dashboard() -> None:
    st.set_page_config(page_title="USYD Recommendation Console", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {padding-top: 1.2rem; padding-bottom: 1.2rem; max-width: 1500px;}
        div[data-testid="stMetric"] {
            background: #f7f5ef;
            border: 1px solid #d8d1c3;
            padding: 0.9rem 1rem;
            border-radius: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("USYD 留学方案工作台")
    st.caption("推荐方案使用只读 RAG + Agent 链路；课程查询保留 Excel 与官网招生信息后台。")

    mode = st.radio(
        "工作区",
        ["推荐方案", "课程查询"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if mode == "推荐方案":
        render_recommendation_console()
        return

    render_admission_search()

    try:
        courses_df, intakes_df = fetch_dashboard_data()
    except Exception as exc:  # pragma: no cover - Streamlit-facing safety net
        st.error(f"课程数据加载失败：{exc}。如果刚更新课程画像功能，请先运行数据库 migration。")
        return
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
