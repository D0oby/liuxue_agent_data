from __future__ import annotations

import html
import json
from pathlib import Path
import re
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
    "course_name_asc": ("course_name", True),
    "course_name_desc": ("course_name", False),
    "tuition_fee_asc": ("tuition_fee_aud", True),
    "tuition_fee_desc": ("tuition_fee_aud", False),
    "ielts_overall_asc": ("ielts_overall", True),
    "ielts_overall_desc": ("ielts_overall", False),
    "duration_max_asc": ("duration_max_years", True),
    "duration_max_desc": ("duration_max_years", False),
}
SORT_OPTION_LABEL_KEYS = {
    "course_name_asc": "sort_course_name_asc",
    "course_name_desc": "sort_course_name_desc",
    "tuition_fee_asc": "sort_tuition_fee_asc",
    "tuition_fee_desc": "sort_tuition_fee_desc",
    "ielts_overall_asc": "sort_ielts_overall_asc",
    "ielts_overall_desc": "sort_ielts_overall_desc",
    "duration_max_asc": "sort_duration_max_asc",
    "duration_max_desc": "sort_duration_max_desc",
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
DEFAULT_UI_LANGUAGE = "en"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_LANGUAGE_OPTIONS = ["EN", "中文"]
UI_TEXT = {
    "app_title": {
        "en": "USYD Recommendation Console",
        "zh": "USYD 留学方案工作台",
    },
    "app_caption": {
        "en": "Recommendations use the read-only RAG + Agent flow; course search keeps the Excel and official admissions backend.",
        "zh": "推荐方案使用只读 RAG + Agent 链路；课程查询保留 Excel 与官网招生信息后台。",
    },
    "workspace_label": {
        "en": "Workspace",
        "zh": "工作区",
    },
    "workspace_recommendation": {
        "en": "Recommendation Plan",
        "zh": "推荐方案",
    },
    "workspace_course_query": {
        "en": "Course Search",
        "zh": "课程查询",
    },
    "language_label": {
        "en": "Language",
        "zh": "语言",
    },
    "docs_link": {
        "en": "Docs",
        "zh": "文档",
    },
    "recommendation_subheader": {
        "en": "Eligibility Screening / Hard Filter",
        "zh": "申请资格筛选 / Hard Filter",
    },
    "recommendation_caption": {
        "en": "Domestic academic results use the University of Sydney arithmetic-average method across all subjects.",
        "zh": "国内院校成绩按悉尼大学口径使用所有科目的算术平均分。",
    },
    "target_area": {
        "en": "Target area",
        "zh": "目标方向",
    },
    "target_area_default": {
        "en": "Computer Science",
        "zh": "计算机",
    },
    "academic_background": {
        "en": "Undergraduate institution tier",
        "zh": "本科院校层级",
    },
    "prior_major": {
        "en": "Prior major",
        "zh": "本科专业",
    },
    "completed_courses": {
        "en": "Completed courses",
        "zh": "已修课程",
    },
    "completed_courses_help": {
        "en": "Use one course per line, or separate courses with commas.",
        "zh": "每行一门课，也可以用逗号分隔。",
    },
    "ielts_overall": {
        "en": "IELTS overall",
        "zh": "IELTS 总分",
    },
    "ielts_min_band": {
        "en": "IELTS minimum band",
        "zh": "IELTS 最低小分",
    },
    "accepts_pathway": {
        "en": "Accept pathway",
        "zh": "接受 pathway",
    },
    "ielts_listening": {
        "en": "IELTS listening",
        "zh": "IELTS 听力",
    },
    "ielts_reading": {
        "en": "IELTS reading",
        "zh": "IELTS 阅读",
    },
    "ielts_speaking": {
        "en": "IELTS speaking",
        "zh": "IELTS 口语",
    },
    "ielts_writing": {
        "en": "IELTS writing",
        "zh": "IELTS 写作",
    },
    "preferred_intake": {
        "en": "Preferred intake",
        "zh": "偏好开学季",
    },
    "budget_range": {
        "en": "Budget range AUD",
        "zh": "预算区间 AUD",
    },
    "duration_preference": {
        "en": "Duration preference years",
        "zh": "学制偏好 年",
    },
    "campus_preference": {
        "en": "Campus preference",
        "zh": "校区偏好",
    },
    "study_mode_preference": {
        "en": "Study mode preference",
        "zh": "学习模式偏好",
    },
    "degree_type_preference": {
        "en": "Degree type preference",
        "zh": "学位类型偏好",
    },
    "run_eligibility_screening": {
        "en": "Run Eligibility Screening",
        "zh": "运行申请资格筛选",
    },
    "recommendation_spinner": {
        "en": "Running hard filter and next-layer matching...",
        "zh": "正在运行 hard filter 并生成下一层匹配...",
    },
    "recommendation_generic_error_prefix": {
        "en": "Recommendation failed",
        "zh": "推荐失败",
    },
    "recommendation_empty_prompt": {
        "en": "Complete the user profile, then run eligibility screening.",
        "zh": "填写用户画像后运行申请资格筛选。",
    },
    "requirement_column_name": {
        "en": "Requirement",
        "zh": "条件",
    },
    "requirement_column_user_value": {
        "en": "User value",
        "zh": "用户情况",
    },
    "requirement_column_course_requirement": {
        "en": "Course requirement",
        "zh": "学校要求",
    },
    "requirement_column_status": {
        "en": "Status",
        "zh": "判断",
    },
    "requirement_column_reason": {
        "en": "Reason",
        "zh": "原因",
    },
    "admissions_semantic_search": {
        "en": "Admissions semantic search",
        "zh": "录取要求语义搜索",
    },
    "admissions_semantic_search_placeholder": {
        "en": "portfolio / personal statement / IELTS 7.0 / work experience",
        "zh": "作品集 / personal statement / IELTS 7.0 / work experience",
    },
    "result_count": {
        "en": "Result count",
        "zh": "结果数",
    },
    "search": {
        "en": "Search",
        "zh": "搜索",
    },
    "enter_search_query": {
        "en": "Enter search text.",
        "zh": "请输入搜索内容。",
    },
    "admissions_search_spinner": {
        "en": "Searching admissions requirements...",
        "zh": "正在搜索录取要求...",
    },
    "search_failed": {
        "en": "Search failed",
        "zh": "搜索失败",
    },
    "no_admissions_matches": {
        "en": "No matching admissions requirements found.",
        "zh": "没有找到匹配的录取要求。",
    },
    "matched_results": {
        "en": "Matched results",
        "zh": "命中结果",
    },
    "best_match_score": {
        "en": "Best match score",
        "zh": "最高匹配度",
    },
    "courses_covered": {
        "en": "Courses covered",
        "zh": "涉及课程",
    },
    "match_score": {
        "en": "Match score",
        "zh": "匹配度",
    },
    "official_source": {
        "en": "Official source",
        "zh": "官网来源",
    },
    "chunk_kind_academic": {
        "en": "Academic requirements",
        "zh": "学术要求",
    },
    "chunk_kind_english": {
        "en": "English requirements",
        "zh": "语言要求",
    },
    "chunk_kind_application": {
        "en": "Application materials",
        "zh": "申请材料",
    },
    "column_course_name": {
        "en": "Course name",
        "zh": "课程名",
    },
    "column_feature_tags": {
        "en": "Feature tags",
        "zh": "画像标签",
    },
    "column_admissions_source": {
        "en": "Admissions source",
        "zh": "招生来源",
    },
    "column_duration_range": {
        "en": "Duration range",
        "zh": "学制区间",
    },
    "column_duration_min": {
        "en": "Minimum duration years",
        "zh": "最小学制(年)",
    },
    "column_duration_max": {
        "en": "Maximum duration years",
        "zh": "最大学制(年)",
    },
    "column_intakes": {
        "en": "Intakes",
        "zh": "开学季",
    },
    "column_tuition_fee": {
        "en": "Tuition fee (AUD)",
        "zh": "学费(AUD)",
    },
    "column_application_flags": {
        "en": "Application flags",
        "zh": "申请标签",
    },
    "column_required_documents": {
        "en": "Required documents",
        "zh": "申请材料",
    },
    "column_language_tests": {
        "en": "Language tests",
        "zh": "语言测试",
    },
    "column_ielts_min_band": {
        "en": "IELTS minimum band",
        "zh": "IELTS 最低小分",
    },
    "column_listening": {
        "en": "Listening",
        "zh": "听力",
    },
    "column_reading": {
        "en": "Reading",
        "zh": "阅读",
    },
    "column_speaking": {
        "en": "Speaking",
        "zh": "口语",
    },
    "column_writing": {
        "en": "Writing",
        "zh": "写作",
    },
    "column_academic_summary": {
        "en": "Academic summary",
        "zh": "学术要求摘要",
    },
    "column_official_course_page": {
        "en": "Official course page",
        "zh": "官网课程页",
    },
    "column_source_file": {
        "en": "Source file",
        "zh": "来源文件",
    },
    "column_source_sheet": {
        "en": "Source sheet",
        "zh": "来源Sheet",
    },
    "column_source_row": {
        "en": "Source row",
        "zh": "来源行号",
    },
    "course_feature_storage_warning": {
        "en": (
            "Course Feature Profile data is unavailable: this database has not applied the "
            "course_features migration yet. Course search and recommendations will fall back "
            "to empty profiles until migrations and profile generation are complete."
        ),
        "zh": (
            "课程画像数据暂不可用：当前数据库尚未应用 course_features migration，"
            "课程查询和推荐会以空画像降级运行。完成 migration 并生成画像后会显示标签和画像分数。"
        ),
    },
    "recommendation_error_feature_migration": {
        "en": (
            "Recommendation failed: Course Feature Profile fields have not completed migration. "
            "Apply the course_features migration or confirm the recommendation repository fallback is enabled."
        ),
        "zh": "推荐失败：课程画像字段尚未完成 migration。请先应用 course_features migration，或确认推荐仓库 fallback 已启用。",
    },
    "recommendation_error_database": {
        "en": "Recommendation failed: database connection failed. Confirm PostgreSQL is running, DATABASE_URL is correct, and the process can access the local port.",
        "zh": "推荐失败：数据库连接失败。请确认 PostgreSQL 正在运行、DATABASE_URL 正确，并且当前进程有本地端口访问权限。",
    },
    "recommendation_error_vector": {
        "en": "Recommendation failed: vector retrieval or embedding configuration is unavailable. Check OPENAI_API_KEY, embedding configuration, and ChromaDB data.",
        "zh": "推荐失败：向量检索或 embedding 配置不可用。请检查 OPENAI_API_KEY、embedding 配置和 ChromaDB 数据。",
    },
    "filters_header": {
        "en": "Filters",
        "zh": "筛选条件",
    },
    "keyword": {
        "en": "Keyword",
        "zh": "关键词",
    },
    "keyword_placeholder": {
        "en": "Course name / CRICOS / admissions requirements / feature tags",
        "zh": "课程名 / CRICOS / 录取要求 / 画像标签",
    },
    "intake": {
        "en": "Intake",
        "zh": "开学季",
    },
    "only_official_admissions": {
        "en": "Only courses with official admissions data",
        "zh": "只看已补官网招生信息",
    },
    "application_features": {
        "en": "Application features",
        "zh": "申请特征",
    },
    "course_feature_discipline": {
        "en": "Course feature discipline",
        "zh": "课程画像学科",
    },
    "min_ai_relevance": {
        "en": "AI relevance at least",
        "zh": "AI 相关度不少于",
    },
    "fee_range": {
        "en": "Fee range (AUD)",
        "zh": "学费区间 (AUD)",
    },
    "duration_range_years": {
        "en": "Duration range (years)",
        "zh": "学制区间 (年)",
    },
    "ielts_min_band_at_least": {
        "en": "IELTS minimum band at least",
        "zh": "IELTS 最低小分不少于",
    },
    "listening_at_least": {
        "en": "Listening at least",
        "zh": "听力不少于",
    },
    "reading_at_least": {
        "en": "Reading at least",
        "zh": "阅读不少于",
    },
    "speaking_at_least": {
        "en": "Speaking at least",
        "zh": "口语不少于",
    },
    "writing_at_least": {
        "en": "Writing at least",
        "zh": "写作不少于",
    },
    "only_duplicate_cricos": {
        "en": "Only duplicate CRICOS",
        "zh": "只看重复 CRICOS",
    },
    "only_irregular_ielts_bands": {
        "en": "Only irregular IELTS component bands",
        "zh": "只看不规则 IELTS 小分",
    },
    "sort_by": {
        "en": "Sort by",
        "zh": "排序方式",
    },
    "sort_course_name_asc": {
        "en": "Course name A-Z",
        "zh": "课程名 A-Z",
    },
    "sort_course_name_desc": {
        "en": "Course name Z-A",
        "zh": "课程名 Z-A",
    },
    "sort_tuition_fee_asc": {
        "en": "Tuition fee low to high",
        "zh": "学费 从低到高",
    },
    "sort_tuition_fee_desc": {
        "en": "Tuition fee high to low",
        "zh": "学费 从高到低",
    },
    "sort_ielts_overall_asc": {
        "en": "IELTS overall low to high",
        "zh": "IELTS 总分 从低到高",
    },
    "sort_ielts_overall_desc": {
        "en": "IELTS overall high to low",
        "zh": "IELTS 总分 从高到低",
    },
    "sort_duration_max_asc": {
        "en": "Maximum duration low to high",
        "zh": "最大学制 从低到高",
    },
    "sort_duration_max_desc": {
        "en": "Maximum duration high to low",
        "zh": "最大学制 从高到低",
    },
    "metric_current_results": {
        "en": "Current results",
        "zh": "当前结果数",
    },
    "metric_official_admissions": {
        "en": "Official admissions",
        "zh": "官网已补齐",
    },
    "metric_required_documents": {
        "en": "Needs documents",
        "zh": "需补材料",
    },
    "metric_average_fee": {
        "en": "Average fee (AUD)",
        "zh": "平均学费(AUD)",
    },
    "admission_source_official": {
        "en": "Official admissions",
        "zh": "官网爬取",
    },
    "admission_source_import": {
        "en": "Excel / original import",
        "zh": "Excel / 原始导入",
    },
    "duration_year_suffix": {
        "en": " years",
        "zh": " 年",
    },
    "language_requirement_details": {
        "en": "Language Requirement Details",
        "zh": "语言要求明细",
    },
    "no_language_test_details": {
        "en": "This course has no structured language-test details.",
        "zh": "当前课程没有结构化语言测试明细。",
    },
    "language_test": {
        "en": "Test",
        "zh": "考试",
    },
    "overall_score": {
        "en": "Overall",
        "zh": "总分",
    },
    "source": {
        "en": "Source",
        "zh": "来源",
    },
    "academic_admission_requirements": {
        "en": "Academic Admission Requirements",
        "zh": "学术录取要求",
    },
    "no_academic_requirement_text": {
        "en": "No academic admission requirement source text was captured for this course.",
        "zh": "当前课程没有抓到学术录取要求原文。",
    },
    "application_materials_notes": {
        "en": "Application Materials And Notes",
        "zh": "申请材料与注意事项",
    },
    "required_materials": {
        "en": "Required materials:",
        "zh": "需要材料：",
    },
    "selection_notes": {
        "en": "Selection notes:",
        "zh": "筛选备注：",
    },
    "view_application_source_text": {
        "en": "View application source text",
        "zh": "查看申请说明原文",
    },
    "source_information": {
        "en": "Source Information",
        "zh": "来源信息",
    },
    "course_page": {
        "en": "Course page",
        "zh": "课程页",
    },
    "open_official_course_page": {
        "en": "Open official course page",
        "zh": "打开官网课程页",
    },
    "source_field": {
        "en": "Field",
        "zh": "字段",
    },
    "value": {
        "en": "Value",
        "zh": "值",
    },
    "source_url": {
        "en": "Source URL",
        "zh": "来源 URL",
    },
    "course_details": {
        "en": "Course Details",
        "zh": "课程详情",
    },
    "no_course_details": {
        "en": "Current filters have no courses to display.",
        "zh": "当前筛选结果为空，没有可展示的课程详情。",
    },
    "select_course_details": {
        "en": "Select a course to view details",
        "zh": "选择一门课程查看详情",
    },
    "duration": {
        "en": "Duration",
        "zh": "学制",
    },
    "recently_verified": {
        "en": "Recently verified",
        "zh": "最近验证",
    },
    "tab_academic_requirements": {
        "en": "Academic Requirements",
        "zh": "学术要求",
    },
    "tab_language_requirements": {
        "en": "Language Requirements",
        "zh": "语言要求",
    },
    "tab_application_materials": {
        "en": "Application Materials",
        "zh": "申请材料",
    },
    "tab_source": {
        "en": "Source",
        "zh": "来源",
    },
    "tab_feature_profile": {
        "en": "Feature Profile",
        "zh": "画像特征",
    },
    "view_language_source_text": {
        "en": "View language requirement source text",
        "zh": "查看语言要求原文",
    },
    "feature_match": {
        "en": "Feature match",
        "zh": "画像匹配",
    },
    "feature_risk": {
        "en": "Feature risk",
        "zh": "画像风险",
    },
    "hard_penalty": {
        "en": "Hard penalty",
        "zh": "硬性惩罚",
    },
    "strengths": {
        "en": "Strengths: ",
        "zh": "优势：",
    },
    "weaknesses": {
        "en": "Weaknesses: ",
        "zh": "弱项：",
    },
    "discipline_tags": {
        "en": "Discipline tags",
        "zh": "学科标签",
    },
    "knowledge_tags": {
        "en": "Knowledge tags",
        "zh": "知识标签",
    },
    "career_tags": {
        "en": "Career directions",
        "zh": "职业方向",
    },
    "background_fit_tags": {
        "en": "Background fit",
        "zh": "适合背景",
    },
    "dimension": {
        "en": "Dimension",
        "zh": "维度",
    },
    "score": {
        "en": "Score",
        "zh": "分数",
    },
    "edit_feature_profile": {
        "en": "Edit Feature Profile",
        "zh": "编辑画像特征",
    },
    "ai_relevance": {
        "en": "AI relevance",
        "zh": "AI 相关度",
    },
    "data_relevance": {
        "en": "Data relevance",
        "zh": "Data 相关度",
    },
    "risk_level": {
        "en": "Risk level",
        "zh": "风险等级",
    },
    "save_feature_override": {
        "en": "Save feature override",
        "zh": "保存画像覆盖",
    },
    "feature_save_failed": {
        "en": "Feature profile save failed",
        "zh": "画像特征保存失败",
    },
    "feature_saved": {
        "en": "Feature profile saved.",
        "zh": "画像特征已保存。",
    },
    "query_results": {
        "en": "Query Results",
        "zh": "查询结果",
    },
    "current_display_count": {
        "en": "Showing `{count}` results",
        "zh": "当前显示 `{count}` 条结果",
    },
    "download_csv": {
        "en": "Download Current Results CSV",
        "zh": "导出当前结果 CSV",
    },
    "course_data_load_failed": {
        "en": "Course data failed to load: {detail}. If Course Feature Profile was just updated, run the database migration first.",
        "zh": "课程数据加载失败：{detail}。如果刚更新课程画像功能，请先运行数据库 migration。",
    },
    "metric_total_candidates": {
        "en": "Total candidates",
        "zh": "总候选数",
    },
    "metric_eligible": {
        "en": "Eligible",
        "zh": "满足硬性要求",
    },
    "metric_high_risk": {
        "en": "High risk",
        "zh": "高风险",
    },
    "metric_info_missing": {
        "en": "Info missing",
        "zh": "信息不足",
    },
    "metric_ineligible": {
        "en": "Ineligible",
        "zh": "不满足",
    },
    "tab_eligible_next_layer": {
        "en": "Eligible for next-layer matching",
        "zh": "满足硬性要求，进入下一层匹配",
    },
    "tab_risk_pathway_unknown": {
        "en": "High risk / pathway / info missing",
        "zh": "高风险 / pathway / 信息不足",
    },
    "tab_ineligible": {
        "en": "Ineligible",
        "zh": "不满足硬性要求",
    },
    "query_summary_scoring_config": {
        "en": "Query Summary And Scoring Config",
        "zh": "查询摘要与评分配置",
    },
    "no_eligible_courses": {
        "en": "No courses currently pass the hard eligibility requirements.",
        "zh": "当前没有课程通过硬性申请条件。",
    },
    "next_layer_bands": {
        "en": "Next-Layer Match Bands",
        "zh": "下一层匹配分档",
    },
    "band_reach": {
        "en": "Reach",
        "zh": "冲刺",
    },
    "band_match": {
        "en": "Match",
        "zh": "匹配",
    },
    "band_safety": {
        "en": "Safety",
        "zh": "保底",
    },
    "no_high_risk_courses": {
        "en": "No high-risk, pathway-required, or info-missing courses currently.",
        "zh": "当前没有高风险、pathway required 或信息不足课程。",
    },
    "manual_review_fields": {
        "en": "Manual review fields: ",
        "zh": "需要人工复核字段: ",
    },
    "eligibility_status_eligible": {
        "en": "Eligible",
        "zh": "满足硬性要求",
    },
    "eligibility_status_high_risk": {
        "en": "High risk",
        "zh": "高风险",
    },
    "eligibility_status_unknown": {
        "en": "Info missing",
        "zh": "信息不足",
    },
    "eligibility_status_ineligible": {
        "en": "Ineligible",
        "zh": "不满足硬性要求",
    },
    "no_band_recommendations": {
        "en": "No recommendations in this band.",
        "zh": "当前没有该档推荐。",
    },
    "column_course": {
        "en": "Course",
        "zh": "课程",
    },
    "column_band": {
        "en": "Band",
        "zh": "档位",
    },
    "column_gpa_method": {
        "en": "GPA method",
        "zh": "GPA算法",
    },
    "column_feature_match": {
        "en": "Feature match",
        "zh": "画像匹配",
    },
    "academic_requirement_summary": {
        "en": "Academic Requirement Summary",
        "zh": "学术要求摘要",
    },
    "column_evidence": {
        "en": "Evidence",
        "zh": "证据",
    },
    "column_source_type": {
        "en": "Source type",
        "zh": "来源类型",
    },
    "no_ineligible_courses": {
        "en": "No courses currently fail hard eligibility requirements.",
        "zh": "当前没有不满足硬性要求的课程。",
    },
    "eligibility_status": {
        "en": "Eligibility status",
        "zh": "资格状态",
    },
    "description": {
        "en": "Description",
        "zh": "说明",
    },
    "scoring_config": {
        "en": "Scoring config",
        "zh": "评分配置",
    },
}


def normalize_ui_language(language: str | None) -> str:
    return "zh" if str(language or "").lower() in {"zh", "中文", "chinese"} else DEFAULT_UI_LANGUAGE


def ui_language_label(language: str | None = DEFAULT_UI_LANGUAGE) -> str:
    return "中文" if normalize_ui_language(language) == "zh" else "EN"


def ui_language_from_label(label: str | None) -> str:
    return "zh" if label == "中文" else DEFAULT_UI_LANGUAGE


def ui_text(key: str, language: str | None = DEFAULT_UI_LANGUAGE) -> str:
    translations = UI_TEXT.get(key, {})
    normalized = normalize_ui_language(language)
    return translations.get(normalized) or translations.get(DEFAULT_UI_LANGUAGE) or key


def current_ui_language() -> str:
    return normalize_ui_language(st.session_state.get("ui_language", DEFAULT_UI_LANGUAGE))


def localized_document_path(path: str, language: str | None = DEFAULT_UI_LANGUAGE) -> str:
    if normalize_ui_language(language) != "zh" or not path.endswith(".md"):
        return path
    base = Path(path)
    zh_path = str(base.with_name(f"{base.stem}.zh{base.suffix}"))
    return zh_path if (PROJECT_ROOT / zh_path).exists() else path


def fetch_dashboard_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    settings = load_settings()
    with connect(settings) as conn:
        courses_df = _read_courses_dataframe(conn)
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


def _read_courses_dataframe(conn) -> pd.DataFrame:
    try:
        courses_df = pd.read_sql(_build_courses_query(include_feature_columns=True), conn)
        courses_df.attrs["feature_profile_storage_available"] = True
        return courses_df
    except Exception as exc:
        if not _is_missing_feature_column_error(exc):
            raise
        courses_df = pd.read_sql(_build_courses_query(include_feature_columns=False), conn)
        courses_df.attrs["feature_profile_storage_available"] = False
        return courses_df


def _build_courses_query(*, include_feature_columns: bool = True) -> str:
    feature_columns = (
        """
                c.course_features,
                c.course_feature_overrides
        """
        if include_feature_columns
        else """
                null::jsonb as course_features,
                null::jsonb as course_feature_overrides
        """
    )
    return f"""
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
{feature_columns}
            from courses c
            left join course_admission_requirements car
              on car.course_id = c.id
             and car.is_current = true
            order by c.course_name, c.source_row_number
            """


def _is_missing_feature_column_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        message = str(current).lower()
        if "course_feature" in message and "does not exist" in message:
            return True
        current = current.__cause__ or current.__context__
    return False


def _feature_profile_storage_warning(language: str | None = DEFAULT_UI_LANGUAGE) -> str:
    return ui_text("course_feature_storage_warning", language)


def _format_recommendation_error(
    exc: RecommendationServiceError,
    language: str | None = DEFAULT_UI_LANGUAGE,
) -> str:
    messages = _exception_chain_messages(exc)
    normalized = " ".join(messages).lower()
    if "course_feature" in normalized and "does not exist" in normalized:
        return ui_text("recommendation_error_feature_migration", language)
    if "connection to server" in normalized or "connection refused" in normalized or "operation not permitted" in normalized:
        return ui_text("recommendation_error_database", language)
    if "vector retrieval" in normalized or "embedding" in normalized or "chromadb" in normalized:
        return ui_text("recommendation_error_vector", language)
    detail = messages[-1] if messages else str(exc)
    return f"{ui_text('recommendation_generic_error_prefix', language)}: {detail}"


def _exception_chain_messages(exc: BaseException) -> list[str]:
    messages: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        message = str(current).strip()
        if message:
            messages.append(message)
        current = current.__cause__ or current.__context__
    return messages


def build_duration_display(courses_df: pd.DataFrame) -> pd.Series:
    year_suffix = ui_text("duration_year_suffix", current_ui_language())
    labels = []
    for _, row in courses_df.iterrows():
        if row["duration_min_years"] == row["duration_max_years"]:
            labels.append(f'{row["duration_min_years"]:.2f}'.rstrip("0").rstrip(".") + year_suffix)
        else:
            labels.append(
                f'{row["duration_min_years"]:.2f}'.rstrip("0").rstrip(".")
                + " - "
                + f'{row["duration_max_years"]:.2f}'.rstrip("0").rstrip(".")
                + year_suffix
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


def _highlight_query_terms(text: str, query: str) -> str:
    highlighted = html.escape(str(text or ""))
    for term in _query_terms(query):
        pattern = re.compile(re.escape(html.escape(term)), re.IGNORECASE)
        highlighted = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", highlighted)
    return highlighted


def _query_terms(query: str) -> list[str]:
    terms = [chunk.strip() for chunk in re.split(r"\s+", query.strip()) if len(chunk.strip()) >= 2]
    if not terms and query.strip():
        terms = [query.strip()]
    return sorted(set(terms), key=len, reverse=True)


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
    language = current_ui_language()
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
        {True: ui_text("admission_source_official", language), False: ui_text("admission_source_import", language)}
    )
    enriched_df["language_tests_display"] = enriched_df["english_req_details"].apply(_format_language_tests)
    enriched_df["required_documents_display"] = enriched_df["application_details_json"].apply(_format_required_documents)
    enriched_df["application_flags_display"] = enriched_df.apply(
        lambda row: _format_admission_flags(row["application_details_json"], row["supplementary_metadata_json"]),
        axis=1,
    )
    enriched_df["academic_summary"] = enriched_df["academic_requirement_text"].fillna("").apply(_trim_text)
    enriched_df["source_url_display"] = enriched_df["source_url"].fillna("")
    enriched_df["feature_tags_display"] = enriched_df["course_features"].apply(_format_feature_search_text)

    for _, field_name in APPLICATION_FILTERS.items():
        enriched_df[field_name] = enriched_df["application_details_json"].apply(
            lambda value, field=field_name: bool(_as_dict(value).get(field, False))
        )

    return enriched_df


def apply_filters(courses_df: pd.DataFrame, intakes_df: pd.DataFrame) -> pd.DataFrame:
    language = current_ui_language()
    st.sidebar.header(ui_text("filters_header", language))

    keyword = st.sidebar.text_input(ui_text("keyword", language), placeholder=ui_text("keyword_placeholder", language))
    selected_intakes = st.sidebar.multiselect(ui_text("intake", language), INTAKE_ORDER)
    only_crawled = st.sidebar.checkbox(ui_text("only_official_admissions", language), value=True)
    selected_application_filters = st.sidebar.multiselect(ui_text("application_features", language), list(APPLICATION_FILTERS.keys()))
    selected_feature_tags = st.sidebar.multiselect(
        ui_text("course_feature_discipline", language),
        ["data science", "computer science", "business", "business analytics", "finance", "design", "health"],
    )
    min_ai_relevance = st.sidebar.slider(ui_text("min_ai_relevance", language), min_value=0, max_value=5, value=0, step=1)

    min_fee, max_fee = float(courses_df["tuition_fee_aud"].min()), float(courses_df["tuition_fee_aud"].max())
    fee_range = st.sidebar.slider(ui_text("fee_range", language), min_value=min_fee, max_value=max_fee, value=(min_fee, max_fee))

    min_duration = float(courses_df["duration_min_years"].min())
    max_duration = float(courses_df["duration_max_years"].max())
    duration_range = st.sidebar.slider(
        ui_text("duration_range_years", language),
        min_value=min_duration,
        max_value=max_duration,
        value=(min_duration, max_duration),
        step=0.5,
    )

    overall_options = sorted(value for value in courses_df["ielts_overall"].dropna().unique())
    selected_overall = st.sidebar.multiselect(ui_text("ielts_overall", language), overall_options)

    min_band_floor = st.sidebar.selectbox(
        ui_text("ielts_min_band_at_least", language), options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0
    )
    listening_floor = st.sidebar.selectbox(ui_text("listening_at_least", language), options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0)
    reading_floor = st.sidebar.selectbox(ui_text("reading_at_least", language), options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0)
    speaking_floor = st.sidebar.selectbox(ui_text("speaking_at_least", language), options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0)
    writing_floor = st.sidebar.selectbox(ui_text("writing_at_least", language), options=[None, 6.0, 6.5, 7.0, 7.5, 8.0], index=0)

    only_duplicates = st.sidebar.checkbox(ui_text("only_duplicate_cricos", language))
    only_irregular_ielts = st.sidebar.checkbox(ui_text("only_irregular_ielts_bands", language))
    sort_label_to_key = {ui_text(SORT_OPTION_LABEL_KEYS[key], language): key for key in SORT_OPTIONS}
    sort_label = st.sidebar.selectbox(ui_text("sort_by", language), list(sort_label_to_key.keys()))

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

    sort_column, ascending = SORT_OPTIONS[sort_label_to_key[sort_label]]
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
        "feature_tags_display",
    ]
    mask = pd.Series(False, index=display_df.index)
    for column in searchable_columns:
        if column not in display_df:
            continue
        mask = mask | display_df[column].fillna("").astype(str).str.lower().str.contains(
            normalized_keyword,
            regex=False,
        )
    if "course_features" in display_df:
        mask = mask | display_df["course_features"].apply(
            lambda value: normalized_keyword in _format_feature_search_text(value).lower()
        )
    return mask


def render_summary(display_df: pd.DataFrame) -> None:
    language = current_ui_language()
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric(ui_text("metric_current_results", language), int(len(display_df)))
    col2.metric(ui_text("metric_official_admissions", language), int(display_df["has_crawled_admissions"].sum()))
    col3.metric("Limited places", int(display_df["limited_places"].sum()))
    col4.metric(ui_text("metric_required_documents", language), int((display_df["required_documents_display"] != "").sum()))
    col5.metric(ui_text("metric_average_fee", language), f'{display_df["tuition_fee_aud"].mean():,.0f}' if len(display_df) else "-")


def render_language_tests(row: pd.Series) -> None:
    language = current_ui_language()
    details = _as_dict(row["english_req_details"])
    tests = _as_list(details.get("language_tests"))
    st.markdown(f"**{ui_text('language_requirement_details', language)}**")
    if not tests:
        st.info(ui_text("no_language_test_details", language))
        return

    language_rows = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        component_scores = _as_dict(test.get("component_scores"))
        language_rows.append(
            {
                ui_text("language_test", language): test.get("test_name", ""),
                ui_text("overall_score", language): test.get("overall", ""),
                ui_text("column_listening", language): component_scores.get("listening", ""),
                ui_text("column_reading", language): component_scores.get("reading", ""),
                ui_text("column_speaking", language): component_scores.get("speaking", ""),
                ui_text("column_writing", language): component_scores.get("writing", ""),
                ui_text("source", language): test.get("source_type", ""),
            }
        )
    st.dataframe(pd.DataFrame(language_rows), width="stretch", hide_index=True)


def render_academic_pathways(row: pd.Series) -> None:
    language = current_ui_language()
    st.markdown(f"**{ui_text('academic_admission_requirements', language)}**")
    if row["academic_requirement_text"]:
        st.write(row["academic_requirement_text"])
    else:
        st.info(ui_text("no_academic_requirement_text", language))


def render_application_details(row: pd.Series) -> None:
    language = current_ui_language()
    details = _as_dict(row["application_details_json"])
    supplementary = _as_dict(row["supplementary_metadata_json"])

    st.markdown(f"**{ui_text('application_materials_notes', language)}**")

    badges = [label for label, field_name in APPLICATION_FILTERS.items() if details.get(field_name)]
    if supplementary.get("rpl_detected"):
        badges.append("RPL / Credit")
    if supplementary.get("award_requirements_detected"):
        badges.append("Award rules detected")

    if badges:
        st.caption(" | ".join(badges))

    docs = [str(item) for item in _as_list(details.get("required_documents")) if item]
    if docs:
        st.write(ui_text("required_materials", language), ", ".join(docs))

    notes = [str(item) for item in _as_list(details.get("selection_notes")) if item]
    if notes:
        st.write(ui_text("selection_notes", language))
        for note in notes:
            st.markdown(f"- {note}")

    raw_text = str(details.get("raw_text", "")).strip()
    if raw_text:
        with st.expander(ui_text("view_application_source_text", language), expanded=False):
            st.write(raw_text)


def render_source_details(row: pd.Series) -> None:
    language = current_ui_language()
    source_map = _as_dict(row["source_map_json"])

    st.markdown(f"**{ui_text('source_information', language)}**")
    if row["source_url"]:
        st.markdown(f"{ui_text('course_page', language)}: [{ui_text('open_official_course_page', language)}]({row['source_url']})")

    if not source_map:
        return

    source_rows = []
    for field_name, url in source_map.items():
        source_rows.append({ui_text("source_field", language): field_name, ui_text("source_url", language): url})
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
    language = current_ui_language()
    with st.form("admission_semantic_search", border=False):
        search_query = st.text_input(
            ui_text("admissions_semantic_search", language),
            placeholder=ui_text("admissions_semantic_search_placeholder", language),
        )
        control_left, control_right = st.columns([1, 4])
        with control_left:
            top_k = st.number_input(ui_text("result_count", language), min_value=3, max_value=20, value=5, step=1)
        with control_right:
            submitted = st.form_submit_button(ui_text("search", language), type="primary", use_container_width=True)

    if not submitted:
        return

    normalized_query = search_query.strip()
    if not normalized_query:
        st.warning(ui_text("enter_search_query", language))
        return

    try:
        with st.spinner(ui_text("admissions_search_spinner", language)):
            results = run_admission_semantic_search(normalized_query, int(top_k))
    except RuntimeError as exc:
        st.warning(str(exc))
        return
    except Exception as exc:  # pragma: no cover - Streamlit-facing safety net
        st.error(f"{ui_text('search_failed', language)}: {exc}")
        return

    if not results:
        st.info(ui_text("no_admissions_matches", language))
        return

    render_admission_search_results(results, normalized_query, language=language)


def render_admission_search_results(
    results: list[Any], query: str, language: str | None = DEFAULT_UI_LANGUAGE
) -> None:
    best_similarity = max(result.similarity for result in results)
    summary_cols = st.columns(3)
    summary_cols[0].metric(ui_text("matched_results", language), len(results))
    summary_cols[1].metric(ui_text("best_match_score", language), f"{best_similarity:.3f}")
    summary_cols[2].metric(ui_text("courses_covered", language), len({result.course_id for result in results}))

    for index, result in enumerate(results, start=1):
        with st.container(border=True):
            header_left, header_right = st.columns([4, 1])
            header_left.markdown(f"**{index}. {result.course_name}**")
            header_left.caption(f"CRICOS {result.cricos or '-'} | {_format_chunk_kind(result.chunk_kind, language)}")
            header_right.metric(ui_text("match_score", language), f"{result.similarity:.3f}")
            st.markdown(
                _highlight_query_terms(_trim_text(result.content, limit=520), query),
                unsafe_allow_html=True,
            )
            source_bits = _format_semantic_result_source_bits(result, language=language)
            if source_bits:
                st.caption(" | ".join(source_bits))


def _format_semantic_result_source_bits(result: Any, language: str | None = DEFAULT_UI_LANGUAGE) -> list[str]:
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    field_name = metadata.get("field")
    source_bits = [str(field_name)] if field_name else []
    if result.source_url:
        source_bits.append(f"[{ui_text('official_source', language)}]({result.source_url})")
    return source_bits


def _format_chunk_kind(chunk_kind: str, language: str | None = DEFAULT_UI_LANGUAGE) -> str:
    labels = {
        "academic": ui_text("chunk_kind_academic", language),
        "english": ui_text("chunk_kind_english", language),
        "application": ui_text("chunk_kind_application", language),
    }
    return labels.get(chunk_kind, chunk_kind)


def run_usyd_recommendation(request: RecommendationRequest) -> RecommendationResponse:
    return RecommendationService().recommend(request)


def render_recommendation_console() -> None:
    language = current_ui_language()
    st.subheader(ui_text("recommendation_subheader", language))

    with st.form("usyd_recommendation_form", border=True):
        st.caption(ui_text("recommendation_caption", language))
        top_left, top_right = st.columns([2, 1])
        with top_left:
            target_major_keyword = st.text_input(
                ui_text("target_area", language),
                value=ui_text("target_area_default", language),
            )
        with top_right:
            academic_background = st.selectbox(
                ui_text("academic_background", language),
                ["双非", "211", "985", "C9", "Tier1", "其他国内院校"],
                index=0,
            )

        academic_left, academic_right = st.columns([1, 2])
        with academic_left:
            gpa_user = st.number_input("GPA / WAM", min_value=0.0, max_value=100.0, value=82.0, step=0.5)
        with academic_right:
            prior_major = st.text_input(ui_text("prior_major", language), value="Computer Science")

        completed_courses_text = st.text_area(
            ui_text("completed_courses", language),
            value="Programming\nStatistics\nDatabase Systems",
            help=ui_text("completed_courses_help", language),
        )

        score_left, score_mid, score_right = st.columns(3)
        with score_left:
            ielts_overall_user = st.number_input(
                ui_text("ielts_overall", language), min_value=0.0, max_value=9.0, value=7.0, step=0.5
            )
        with score_mid:
            ielts_min_band_user = st.number_input(
                ui_text("ielts_min_band", language), min_value=0.0, max_value=9.0, value=6.5, step=0.5
            )
        with score_right:
            accepts_pathway = st.checkbox(ui_text("accepts_pathway", language), value=False)

        band_left, band_mid_left, band_mid_right, band_right = st.columns(4)
        with band_left:
            ielts_listening_user = st.number_input(
                ui_text("ielts_listening", language), min_value=0.0, max_value=9.0, value=6.5, step=0.5
            )
        with band_mid_left:
            ielts_reading_user = st.number_input(
                ui_text("ielts_reading", language), min_value=0.0, max_value=9.0, value=6.5, step=0.5
            )
        with band_mid_right:
            ielts_speaking_user = st.number_input(
                ui_text("ielts_speaking", language), min_value=0.0, max_value=9.0, value=6.5, step=0.5
            )
        with band_right:
            ielts_writing_user = st.number_input(
                ui_text("ielts_writing", language), min_value=0.0, max_value=9.0, value=6.5, step=0.5
            )

        pref_left, pref_mid, pref_right = st.columns(3)
        with pref_left:
            preferred_intake = st.multiselect(ui_text("preferred_intake", language), INTAKE_ORDER, default=["FEB", "JUL"])
        with pref_mid:
            budget_range = st.slider(
                ui_text("budget_range", language), min_value=0, max_value=120000, value=(0, 70000), step=1000
            )
        with pref_right:
            duration_preference = st.slider(
                ui_text("duration_preference", language),
                min_value=0.5,
                max_value=4.0,
                value=(1.0, 2.0),
                step=0.5,
            )

        extra_left, extra_mid, extra_right = st.columns(3)
        with extra_left:
            campus_preference = st.text_input(
                ui_text("campus_preference", language),
                placeholder="Camperdown / Sydney / Online",
            )
        with extra_mid:
            study_mode_preference = st.selectbox(
                ui_text("study_mode_preference", language),
                ["", "On campus", "Online", "Full time", "Part time"],
                index=0,
            )
        with extra_right:
            degree_type_preference = st.selectbox(
                ui_text("degree_type_preference", language),
                ["", "Master", "Graduate Diploma", "Graduate Certificate"],
                index=0,
            )

        submitted = st.form_submit_button(ui_text("run_eligibility_screening", language), type="primary", use_container_width=True)

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
            with st.spinner(ui_text("recommendation_spinner", language)):
                st.session_state["usyd_recommendation_response"] = run_usyd_recommendation(request)
        except RecommendationServiceError as exc:
            st.error(_format_recommendation_error(exc, language=language))
            return
        except Exception as exc:  # pragma: no cover - Streamlit-facing safety net
            st.error(f"{ui_text('recommendation_generic_error_prefix', language)}: {exc}")
            return

    response = st.session_state.get("usyd_recommendation_response")
    if response is None:
        st.info(ui_text("recommendation_empty_prompt", language))
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
    language = current_ui_language()
    metadata = response.metadata
    summary = response.eligibility_summary
    metric_cols = st.columns(6)
    metric_cols[0].metric(ui_text("metric_total_candidates", language), summary.total_candidates)
    metric_cols[1].metric(ui_text("metric_eligible", language), summary.eligible_count)
    metric_cols[2].metric(ui_text("metric_high_risk", language), summary.high_risk_count)
    metric_cols[3].metric("Pathway required", summary.pathway_required_count)
    metric_cols[4].metric(ui_text("metric_info_missing", language), summary.unknown_count)
    metric_cols[5].metric(ui_text("metric_ineligible", language), summary.ineligible_count)

    st.caption(
        f"request_id: {metadata.request_id} | "
        f"model: {metadata.model_version} | "
        f"generated_at: {metadata.generated_at.isoformat()} | "
        f"scored_after_hard_filter: {metadata.scored_candidate_count} | "
        f"retrieval_degraded: {'yes' if metadata.degraded_retrieval else 'no'}"
    )

    hard_tabs = st.tabs(
        [
            ui_text("tab_eligible_next_layer", language),
            ui_text("tab_risk_pathway_unknown", language),
            ui_text("tab_ineligible", language),
        ]
    )
    with hard_tabs[0]:
        render_next_layer_candidates(response)
    with hard_tabs[1]:
        render_high_risk_programs(response)
    with hard_tabs[2]:
        render_excluded_programs(response)

    with st.expander(ui_text("query_summary_scoring_config", language), expanded=False):
        render_query_summary(response)


def render_next_layer_candidates(response: RecommendationResponse) -> None:
    language = current_ui_language()
    if not response.next_layer_candidates:
        st.info(ui_text("no_eligible_courses", language))
        return

    st.markdown(f"**{ui_text('next_layer_bands', language)}**")
    band_tabs = st.tabs([ui_text("band_reach", language), ui_text("band_match", language), ui_text("band_safety", language)])
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
    language = current_ui_language()
    if not response.high_risk_programs:
        st.success(ui_text("no_high_risk_courses", language))
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
            st.info(ui_text("manual_review_fields", current_ui_language()) + ", ".join(program.missing_fields))

        checklist_df = build_requirement_checks_dataframe(program.requirement_checks, language=current_ui_language())
        st.dataframe(checklist_df, width="stretch", hide_index=True)
        render_check_evidence(program.requirement_checks)


def build_requirement_checks_dataframe(checks: list[Any], language: str | None = DEFAULT_UI_LANGUAGE) -> pd.DataFrame:
    columns = [
        ui_text("requirement_column_name", language),
        ui_text("requirement_column_user_value", language),
        ui_text("requirement_column_course_requirement", language),
        ui_text("requirement_column_status", language),
        ui_text("requirement_column_reason", language),
    ]
    rows = []
    for check in checks:
        item = check.model_dump() if hasattr(check, "model_dump") else dict(check)
        rows.append(
            {
                columns[0]: item.get("name", ""),
                columns[1]: _display_cell_value(item.get("user_value")),
                columns[2]: _display_cell_value(item.get("required_value")),
                columns[3]: item.get("status", ""),
                columns[4]: item.get("reason", ""),
            }
        )
    return pd.DataFrame(rows, columns=columns)


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
    language = current_ui_language()
    status_value = getattr(status, "value", str(status))
    labels = {
        "ELIGIBLE": ui_text("eligibility_status_eligible", language),
        "HIGH_RISK": ui_text("eligibility_status_high_risk", language),
        "PATHWAY_REQUIRED": "Pathway required",
        "UNKNOWN": ui_text("eligibility_status_unknown", language),
        "INELIGIBLE": ui_text("eligibility_status_ineligible", language),
    }
    return labels.get(status_value, status_value)


def _format_money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"AUD {value:,.0f}"


def render_recommendation_band(programs: list[Any]) -> None:
    language = current_ui_language()
    if not programs:
        st.info(ui_text("no_band_recommendations", language))
        return

    rows = [
        {
            ui_text("column_course", language): program.course_name,
            "CRICOS": program.cricos,
            ui_text("score", language): f"{program.score:.4f}",
            ui_text("column_band", language): program.band,
            ui_text("duration", language): program.duration,
            ui_text("intake", language): ", ".join(program.intakes),
            ui_text("column_tuition_fee", language): program.tuition_fee_aud,
            "IELTS": program.ielts_requirement,
            ui_text("column_gpa_method", language): _format_gpa_method(program.gpa_calculation_method),
            ui_text("column_feature_match", language): (
                f"{program.feature_match.score:.1f}" if getattr(program, "feature_match", None) is not None else ""
            ),
            ui_text("source", language): program.source_url or "",
        }
        for program in programs
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    for program in programs:
        with st.expander(f"{program.course_name} | {program.band} | score {program.score:.4f}", expanded=False):
            st.write(program.recommendation_reason)
            if getattr(program, "feature_match", None) is not None:
                render_feature_match(program.feature_match)
            st.markdown(f"**{ui_text('academic_requirement_summary', language)}**")
            st.write(program.academic_requirement_summary)
            evidence_rows = [
                {
                    ui_text("column_evidence", language): snippet.text,
                    ui_text("column_source_type", language): snippet.source or "",
                    ui_text("source_url", language): snippet.source_url or "",
                }
                for snippet in program.evidence_snippets
            ]
            if evidence_rows:
                st.dataframe(pd.DataFrame(evidence_rows), width="stretch", hide_index=True)


def render_excluded_programs(response: RecommendationResponse) -> None:
    language = current_ui_language()
    if not response.excluded_programs:
        st.success(ui_text("no_ineligible_courses", language))
        return

    rows = [
        {
            ui_text("column_course", language): program.course_name,
            ui_text("eligibility_status", language): _eligibility_badge(program.eligibility_status),
            "Blocking reasons": " | ".join(program.blocking_reasons) or program.reason,
            ui_text("description", language): program.hard_filter_summary,
            ui_text("source", language): program.source_url or "",
        }
        for program in response.excluded_programs
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    for program in response.excluded_programs:
        render_eligibility_card(program, expanded=False)


def render_query_summary(response: RecommendationResponse) -> None:
    language = current_ui_language()
    query_summary = response.query_summary
    summary_rows = [
        {ui_text("source_field", language): key, ui_text("value", language): value}
        for key, value in query_summary.items()
        if key not in {"degraded_retrieval"}
    ]
    st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)

    with st.expander(ui_text("scoring_config", language), expanded=False):
        st.json(response.metadata.scoring_config)


def _format_gpa_method(method: str) -> str:
    labels = {
        "usyd_arithmetic_average_all_courses": "悉尼大学：所有科目的算术平均分",
    }
    return labels.get(method, method)


def render_course_detail(display_df: pd.DataFrame) -> None:
    language = current_ui_language()
    st.divider()
    st.subheader(ui_text("course_details", language))

    if display_df.empty:
        st.info(ui_text("no_course_details", language))
        return

    selected_index = st.selectbox(
        ui_text("select_course_details", language),
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
            f"CRICOS: {row['cricos']} | {ui_text('duration', language)}: {row['duration_display']} | "
            f"{ui_text('intake', language)}: {row['intakes'] or '-'}"
        )
    with header_right:
        st.markdown(
            f"""
            <div style="background:#f7f5ef;border:1px solid #d8d1c3;padding:0.85rem 1rem;border-radius:8px;">
                <div style="font-size:0.9rem;color:#6c6558;">{ui_text("column_admissions_source", language)}</div>
                <div style="font-size:1.1rem;font-weight:600;color:#2d2a26;">{row["admission_source_label"]}</div>
                <div style="margin-top:0.35rem;font-size:0.9rem;color:#6c6558;">{ui_text("recently_verified", language)}: {row["last_verified_at"] or "-"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            ui_text("tab_academic_requirements", language),
            ui_text("tab_language_requirements", language),
            ui_text("tab_application_materials", language),
            ui_text("tab_source", language),
            ui_text("tab_feature_profile", language),
        ]
    )
    with tab1:
        render_academic_pathways(row)
    with tab2:
        render_language_tests(row)
        if row["raw_english_requirement"]:
            with st.expander(ui_text("view_language_source_text", language), expanded=False):
                st.write(row["raw_english_requirement"])
    with tab3:
        render_application_details(row)
    with tab4:
        render_source_details(row)
    with tab5:
        render_course_features(row)


def render_feature_match(match_result: Any) -> None:
    language = current_ui_language()
    cols = st.columns(3)
    cols[0].metric(ui_text("feature_match", language), f"{match_result.score:.1f}/100")
    cols[1].metric(ui_text("feature_risk", language), f"{match_result.risk_level:.1f}/5")
    cols[2].metric(ui_text("hard_penalty", language), f"{match_result.penalty_score:.1f}")
    if match_result.strengths:
        st.success(ui_text("strengths", language) + " | ".join(match_result.strengths))
    if match_result.weaknesses:
        st.warning(ui_text("weaknesses", language) + " | ".join(match_result.weaknesses))


def render_course_features(row: pd.Series) -> None:
    language = current_ui_language()
    profile = _feature_profile(row.get("course_features"))
    tag_cols = st.columns(4)
    tag_cols[0].markdown(f"**{ui_text('discipline_tags', language)}**  \n" + _format_tags(profile.discipline_tags))
    tag_cols[1].markdown(f"**{ui_text('knowledge_tags', language)}**  \n" + _format_tags(profile.knowledge_tags))
    tag_cols[2].markdown(f"**{ui_text('career_tags', language)}**  \n" + _format_tags(profile.career_tags))
    tag_cols[3].markdown(f"**{ui_text('background_fit_tags', language)}**  \n" + _format_tags(profile.background_fit_tags))

    score_rows = [
        {ui_text("dimension", language): "Math", ui_text("score", language): profile.math_intensity},
        {ui_text("dimension", language): "Coding", ui_text("score", language): profile.coding_intensity},
        {ui_text("dimension", language): "Theory", ui_text("score", language): profile.theory_intensity},
        {ui_text("dimension", language): "Business", ui_text("score", language): profile.business_intensity},
        {ui_text("dimension", language): "AI", ui_text("score", language): profile.ai_relevance},
        {ui_text("dimension", language): "Data", ui_text("score", language): profile.data_relevance},
        {ui_text("dimension", language): "Conversion", ui_text("score", language): profile.conversion_friendliness},
        {ui_text("dimension", language): "Risk", ui_text("score", language): profile.risk_level},
    ]
    st.dataframe(pd.DataFrame(score_rows), width="stretch", hide_index=True)

    with st.expander(ui_text("edit_feature_profile", language), expanded=False):
        render_course_feature_editor(row, profile)


def render_course_feature_editor(row: pd.Series, profile: CourseFeatureProfile) -> None:
    language = current_ui_language()
    with st.form(f"feature_editor_{row['id']}", border=False):
        tags_text = st.text_input(ui_text("discipline_tags", language), value=", ".join(profile.discipline_tags))
        ai_relevance = st.slider(ui_text("ai_relevance", language), min_value=0, max_value=5, value=int(profile.ai_relevance), step=1)
        data_relevance = st.slider(ui_text("data_relevance", language), min_value=0, max_value=5, value=int(profile.data_relevance), step=1)
        risk_level = st.slider(ui_text("risk_level", language), min_value=0, max_value=5, value=int(profile.risk_level), step=1)
        submitted = st.form_submit_button(ui_text("save_feature_override", language), use_container_width=True)
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
        st.error(f"{ui_text('feature_save_failed', language)}: {exc}")
        return
    st.success(ui_text("feature_saved", language))


def _feature_profile(value: Any) -> CourseFeatureProfile:
    return CourseFeatureProfile.model_validate(_as_dict(value))


def _format_tags(tags: list[str]) -> str:
    return ", ".join(tags) if tags else "-"


def _format_feature_search_text(value: Any) -> str:
    profile = _feature_profile(value)
    tags: list[str] = []
    for field_name in (
        "discipline_tags",
        "knowledge_tags",
        "career_tags",
        "background_fit_tags",
    ):
        tags.extend(getattr(profile, field_name))
    return ", ".join(dict.fromkeys(tags))


def _split_csv(value: str) -> list[str]:
    return [chunk.strip() for chunk in value.split(",") if chunk.strip()]


def build_course_export_dataframe(
    display_df: pd.DataFrame,
    language: str | None = DEFAULT_UI_LANGUAGE,
) -> pd.DataFrame:
    return display_df[
        [
            "course_name",
            "feature_tags_display",
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
            "course_name": ui_text("column_course_name", language),
            "feature_tags_display": ui_text("column_feature_tags", language),
            "cricos": "CRICOS",
            "admission_source_label": ui_text("column_admissions_source", language),
            "duration_display": ui_text("column_duration_range", language),
            "duration_min_years": ui_text("column_duration_min", language),
            "duration_max_years": ui_text("column_duration_max", language),
            "intakes": ui_text("column_intakes", language),
            "tuition_fee_aud": ui_text("column_tuition_fee", language),
            "application_flags_display": ui_text("column_application_flags", language),
            "required_documents_display": ui_text("column_required_documents", language),
            "language_tests_display": ui_text("column_language_tests", language),
            "ielts_overall": ui_text("ielts_overall", language),
            "ielts_min_band": ui_text("column_ielts_min_band", language),
            "ielts_listening": ui_text("column_listening", language),
            "ielts_reading": ui_text("column_reading", language),
            "ielts_speaking": ui_text("column_speaking", language),
            "ielts_writing": ui_text("column_writing", language),
            "academic_summary": ui_text("column_academic_summary", language),
            "source_url_display": ui_text("column_official_course_page", language),
            "source_file_name": ui_text("column_source_file", language),
            "source_sheet_name": ui_text("column_source_sheet", language),
            "source_row_number": ui_text("column_source_row", language),
        }
    )


def render_dashboard() -> None:
    st.set_page_config(page_title="USYD Recommendation Console", layout="wide")
    st.markdown(
        """
        <style>
        .block-container {padding-top: 3.2rem; padding-bottom: 1.2rem; max-width: 1500px;}
        mark {
            background: #fff1a8;
            color: #1f1f1f;
            padding: 0 0.12rem;
            border-radius: 3px;
        }
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

    language = normalize_ui_language(st.session_state.get("ui_language", DEFAULT_UI_LANGUAGE))
    header_left, header_right = st.columns([4, 1])
    with header_right:
        selected_language_label = st.segmented_control(
            ui_text("language_label", language),
            options=UI_LANGUAGE_OPTIONS,
            default=ui_language_label(language),
            key="ui_language_selector",
            label_visibility="collapsed",
        )
    language = ui_language_from_label(selected_language_label)
    st.session_state["ui_language"] = language
    with header_right:
        st.markdown(f"[{ui_text('docs_link', language)}]({localized_document_path('README.md', language)})")

    with header_left:
        st.title(ui_text("app_title", language))
        st.caption(ui_text("app_caption", language))

    mode = st.radio(
        ui_text("workspace_label", language),
        [ui_text("workspace_recommendation", language), ui_text("workspace_course_query", language)],
        horizontal=True,
        label_visibility="collapsed",
    )

    if mode == ui_text("workspace_recommendation", language):
        render_recommendation_console()
        return

    render_admission_search()

    try:
        courses_df, intakes_df = fetch_dashboard_data()
    except Exception as exc:  # pragma: no cover - Streamlit-facing safety net
        st.error(ui_text("course_data_load_failed", language).format(detail=exc))
        return
    if not courses_df.attrs.get("feature_profile_storage_available", True):
        st.warning(_feature_profile_storage_warning(language))
    intake_map = build_intake_map(intakes_df)
    courses_df["intakes"] = courses_df["id"].map(intake_map).fillna("")
    courses_df["duration_display"] = build_duration_display(courses_df)
    courses_df = enrich_courses_df(courses_df)

    display_df = apply_filters(courses_df, intakes_df)
    render_summary(display_df)

    st.divider()
    st.subheader(ui_text("query_results", language))

    export_df = build_course_export_dataframe(display_df, language=language)

    control_left, control_right = st.columns([2, 1])
    with control_left:
        st.write(ui_text("current_display_count", language).format(count=len(export_df)))
    with control_right:
        st.download_button(
            ui_text("download_csv", language),
            data=export_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="usyd_courses_filtered.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.dataframe(export_df, width="stretch", hide_index=True, height=520)
    render_course_detail(display_df)


if __name__ == "__main__":
    render_dashboard()
