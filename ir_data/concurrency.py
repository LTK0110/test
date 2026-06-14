"""並列処理ユーティリティ (複数クエリ・複数企業の同時取得)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, List, Tuple, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def run_parallel(
    func: Callable[[T], R],
    items: Iterable[T],
    max_workers: int = 8,
) -> List[Tuple[T, R, Exception | None]]:
    """``items`` の各要素に ``func`` を並列適用する.

    各要素について (入力, 結果 or None, 例外 or None) のタプルを返す。
    1 要素の失敗が全体を止めないよう例外は捕捉して持ち回る。
    レート制御は HttpClient 側で共有されるため worker 数は安全に増やせる。
    """
    results: List[Tuple[T, R, Exception | None]] = []
    items = list(items)
    if not items:
        return results
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        future_map = {ex.submit(func, item): item for item in items}
        for future in as_completed(future_map):
            item = future_map[future]
            try:
                results.append((item, future.result(), None))
            except Exception as exc:  # noqa: BLE001 - 個別失敗を全体に伝播させない
                results.append((item, None, exc))
    return results
