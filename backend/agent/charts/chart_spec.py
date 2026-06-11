"""선언적 차트 스펙 (ChartSpecV1) — Vega-Lite 풍 mark + encoding + data 참조 분리.

이 모듈은 디스크의 ``charts.spec.json`` 파일을 파싱하는 Pydantic 모델만 정의한다.
실제 ECharts 렌더링은 ``chart_renderer`` 가 담당한다.

설계 원칙:
    - data.source 는 같은 폴더의 parquet 파일명 (상대) — 다중 차트가 동일 데이터 공유 가능
    - encoding.type 은 quantitative / nominal / temporal — ECharts 축 타입을 결정
    - aggregate 는 선택적 집계 (count·mean 등). 미지원 값은 렌더러에서 명확한 에러
    - extra_option 으로 ECharts option 깊은 병합 (toolbox·dataZoom 등 추가 설정)

이 스키마는 향후 scatter point selection·cross-chart brush filtering 같은 인터랙티브
확장점을 위한 1차 정의다. 확장 시 ``version`` 을 올리고 새 모델을 추가 (v1 은 보존).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EncodingType = Literal["quantitative", "nominal", "temporal"]
MarkType = Literal["bar", "line", "scatter", "box", "histogram", "heatmap", "ecdf"]
AggregateFn = Literal["count", "mean", "sum", "min", "max"]

# 실 LLM 이 자주 쓰는 근사 표기를 정식 값으로 정규화하는 관용 매핑 (Postel's law).
# 사소한 표기 차이('normal' 등)가 ValidationError → self-correct 라운드트립으로
# 반복 예산 1회를 태우는 것을 막는다. 의미가 모호한 값은 매핑하지 않고
# Pydantic Literal 검증 에러에 맡긴다 (진짜 오류는 그대로 드러나야 함).
_ENCODING_TYPE_ALIASES: dict[str, str] = {
    "normal": "nominal",
    "category": "nominal",
    "categorical": "nominal",
    "ordinal": "nominal",
    "string": "nominal",
    "numeric": "quantitative",
    "number": "quantitative",
    "value": "quantitative",
    "float": "quantitative",
    "int": "quantitative",
    "integer": "quantitative",
    "time": "temporal",
    "date": "temporal",
    "datetime": "temporal",
    "timestamp": "temporal",
}

_MARK_ALIASES: dict[str, str] = {
    "hist": "histogram",
    "point": "scatter",
    "boxplot": "box",
}

_AGGREGATE_ALIASES: dict[str, str] = {
    "avg": "mean",
    "average": "mean",
}


def _normalize_alias(value: Any, aliases: dict[str, str]) -> Any:
    """문자열 값을 소문자 정규화 후 alias 매핑을 적용한다 (비문자열은 그대로)."""
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    return aliases.get(normalized, normalized)


class EncodingChannel(BaseModel):
    """하나의 축/색 채널 — 데이터 컬럼과 시각적 매핑을 연결한다."""

    field: Annotated[str, "참조 parquet 의 컬럼명"]
    type: Annotated[
        EncodingType, "축 타입 — quantitative(수치) / nominal(범주) / temporal(시간)"
    ]
    aggregate: Annotated[AggregateFn | None, "선택적 집계 함수"] = None
    bin: Annotated[bool, "histogram 의 x: 빈 분할 활성화"] = False
    title: Annotated[str, "축/범례 레이블 (생략 시 field 명)"] = ""

    @field_validator("type", mode="before")
    @classmethod
    def _coerce_type_alias(cls, value: Any) -> Any:
        return _normalize_alias(value, _ENCODING_TYPE_ALIASES)

    @field_validator("aggregate", mode="before")
    @classmethod
    def _coerce_aggregate_alias(cls, value: Any) -> Any:
        return _normalize_alias(value, _AGGREGATE_ALIASES)


class Encoding(BaseModel):
    """차트의 시각적 매핑 — 적어도 x 또는 y 중 하나는 있어야 한다."""

    x: EncodingChannel | None = None
    y: EncodingChannel | None = None
    color: Annotated[
        EncodingChannel | None,
        "시리즈 분할 (예: 그룹별 다중 시리즈 bar / line)",
    ] = None


class DataRef(BaseModel):
    """차트가 참조하는 parquet 데이터.

    두 표기 허용: (1) 같은 폴더 파일명 ('samples.parquet'), (2) 이전 턴 산출물을
    재사용할 때의 전체 상대 경로 ('result/<session>/<ts>/samples.parquet').
    """

    source: Annotated[
        str,
        "parquet 데이터 경로. 같은 폴더 파일명('samples.parquet') 또는 "
        "'result/...' 전체 상대 경로(이전 턴 parquet 재사용) 둘 다 허용. "
        "한 spec 안에서 같은 데이터는 표기를 통일하라 (Filter All 그룹 판정 기준).",
    ]


class ChartV1(BaseModel):
    """단일 차트 정의 — mark + data + encoding + 선택적 ECharts override."""

    mark: Annotated[MarkType, "차트 유형 — bar/line/scatter/box/histogram/heatmap/ecdf"]
    title: Annotated[str, "차트 제목"] = ""
    data: DataRef
    encoding: Encoding
    extra_option: Annotated[
        dict[str, Any] | None,
        "ECharts option 추가 필드 (기본 option 에 deep-merge). 선택 사항.",
    ] = None

    @field_validator("mark", mode="before")
    @classmethod
    def _coerce_mark_alias(cls, value: Any) -> Any:
        return _normalize_alias(value, _MARK_ALIASES)

    @model_validator(mode="after")
    def _default_histogram_bin(self) -> ChartV1:
        """histogram 의 ``x.bin`` 누락을 에러 대신 자동 보정한다.

        bin=True 는 histogram 의 무조건적 필수값이라 정보 손실이 없다 — LLM 이
        스키마 세부를 몰라도 첫 시도에 렌더되도록 관용적으로 처리한다.
        x.type 등 의미가 걸린 조건은 렌더러 검증에 그대로 맡긴다.
        """
        if self.mark == "histogram" and self.encoding.x is not None:
            self.encoding.x.bin = True
        return self


class ChartSpecV1(BaseModel):
    """차트 spec 의 루트 — 한 파일에 여러 차트를 정의할 수 있다."""

    version: Annotated[Literal["1"], "spec 스키마 버전 (현재 1 만 지원)"] = "1"
    charts: Annotated[list[ChartV1], "차트 리스트 (1 개 이상)"] = Field(min_length=1)
