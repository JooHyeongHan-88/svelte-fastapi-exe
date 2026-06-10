"""SessionNamespace 변수의 디스크 직렬화.

타입별 분기:
    - ``pandas.DataFrame`` → parquet (타입 보존, 빠름, 작음)
    - ``numpy.ndarray`` → npy (네이티브)
    - 그 외 → pickle (범용)

원칙: 자기 자신이 dump 한 파일만 load 한다. 외부 신뢰되지 않은 데이터를
역직렬화하지 않으므로 pickle 사용이 안전하다. 세션 종료 시 cleanup 으로
disk 파일은 즉시 삭제된다.
"""

from __future__ import annotations

import logging
import pickle
import sys
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

Format = Literal["parquet", "npy", "pickle"]

# Format ↔ 확장자 단일 진실원천. extension_for / format_for_extension 양방향 공유.
_FORMAT_EXTENSIONS: dict[Format, str] = {
    "parquet": ".parquet",
    "npy": ".npy",
    "pickle": ".pkl",
}
_EXTENSION_FORMATS: dict[str, Format] = {
    ext: fmt for fmt, ext in _FORMAT_EXTENSIONS.items()
}


def estimate_size(obj: Any) -> int:
    """객체 메모리 점유 추정 (bytes). 타입별 정확도 차이 있음.

    DataFrame/ndarray 는 정확, 그 외는 sys.getsizeof 의 얕은 추정.
    LRU/tier 결정에는 충분.
    """
    try:
        import pandas as pd

        if isinstance(obj, pd.DataFrame):
            return int(obj.memory_usage(deep=True).sum())
        if isinstance(obj, pd.Series):
            return int(obj.memory_usage(deep=True))
    except ImportError:
        pass

    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            return int(obj.nbytes)
    except ImportError:
        pass

    return sys.getsizeof(obj)


def pick_format(obj: Any) -> Format:
    """객체 타입에 따라 적합한 직렬화 포맷을 선택한다."""
    try:
        import pandas as pd

        if isinstance(obj, pd.DataFrame):
            return "parquet"
    except ImportError:
        pass

    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            return "npy"
    except ImportError:
        pass

    return "pickle"


def extension_for(fmt: Format) -> str:
    return _FORMAT_EXTENSIONS[fmt]


def format_for_extension(filename_or_ext: str) -> Format | None:
    """파일명/확장자 → Format 역매핑. 미지의 확장자는 None.

    namespace 디스크 파일을 재색인할 때 파일 확장자로부터 직렬화 포맷을 복원한다.

    Args:
        filename_or_ext: 파일명('df.parquet') 또는 확장자('.parquet').

    Returns:
        대응 Format, 없으면 None.
    """
    ext = filename_or_ext.lower()
    if not ext.startswith("."):
        ext = Path(ext).suffix.lower()
    return _EXTENSION_FORMATS.get(ext)


def dump_to_disk(obj: Any, path: Path, fmt: Format) -> None:
    """obj 를 path 에 직렬화한다. path.parent 는 이미 존재해야 한다."""
    if fmt == "parquet":
        # parquet 은 pandas 가 pyarrow 또는 fastparquet 둘 중 하나 필요.
        obj.to_parquet(path)
        return
    if fmt == "npy":
        import numpy as np

        # path 에 .npy 확장자가 이미 있으면 numpy 가 중복 append 안 함.
        np.save(path, obj, allow_pickle=False)
        return
    with path.open("wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)


def load_from_disk(path: Path, fmt: Format) -> Any:
    """dump_to_disk 로 저장한 파일을 복원한다."""
    if fmt == "parquet":
        import pandas as pd

        return pd.read_parquet(path)
    if fmt == "npy":
        import numpy as np

        return np.load(path, allow_pickle=False)
    with path.open("rb") as f:
        return pickle.load(f)
