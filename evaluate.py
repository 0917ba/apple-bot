# evaluate.py
from __future__ import annotations
import importlib
import os
from dataclasses import dataclass
from typing import List, Tuple, Any

from board import Board

Rect = Tuple[int, int, int, int]

# 기본 10개 시드
DEFAULT_SEEDS: List[int] = [42, 43, 44, 45, 123, 777, 1001, 2024, 9001, 31415]

# -------- 내부 유틸 --------
def _resolve_bot(bot_ref: str) -> Any:
    """'package.module.ClassName' 형태에서 클래스를 찾아 인스턴스화."""
    mod_path, cls_name = bot_ref.rsplit(".", 1)
    mod = importlib.import_module(mod_path)
    cls = getattr(mod, cls_name)
    return cls()

def _moves(board: Board):
    """보드가 제공하는 유효수 나열 API (2-튜플: (rect, apples))."""
    if hasattr(board, "find_all_valid_moves"):
        return board.find_all_valid_moves()
    if hasattr(board, "find_valid_moves"):  # 구버전 호환
        return board.find_valid_moves()
    return []

def _has_any_move(board: Board) -> bool:
    return bool(_moves(board))

def _safe_is_valid(board: Board, rect: Rect) -> bool:
    """합==10 이고 직사각형 안에 최소 1칸은 0이 아님(점수 생김)."""
    try:
        if board.get_rectangle_sum(rect) != 10:
            return False
    except Exception:
        return False
    r1, c1, r2, c2 = (x-1 for x in rect)
    for r in range(r1, r2+1):
        for c in range(c1, c2+1):
            if board.grid[r][c] != 0:
                return True
    return False

# -------- 공개 데이터 구조 --------
@dataclass
class SeedScore:
    seed: int
    score: int
    def as_dict(self): return {"seed": self.seed, "score": self.score}

@dataclass
class Summary:
    per_seed: List[SeedScore]
    @property
    def average(self) -> float:
        return sum(s.score for s in self.per_seed)/len(self.per_seed) if self.per_seed else 0.0
    def as_dict(self):
        return {"average": self.average, "per_seed": [s.as_dict() for s in self.per_seed]}

# -------- 여기가 핵심: 프로세스에서 직접 호출될 '탑레벨' 함수 --------
def run_one_seed(bot_ref: str, seed: int, H: int = 10, W: int = 17, safety: int = 50000) -> int:
    """
    프로세스 풀에서 피클링 가능한 **모듈 탑레벨 함수**.
    - 다른 프로세스에서 import evaluate; evaluate.run_one_seed 로 접근 가능해야 함.
    """
    bot = _resolve_bot(bot_ref)
    b = Board(H=H, W=W, seed=seed)
    steps = safety
    while steps > 0:
        steps -= 1
        # 봇이 게임오버를 선언하면 즉시 종료
        try:
            if hasattr(bot, "gameover") and bot.gameover(b):
                break
        except Exception:
            break
        if not _has_any_move(b):
            break
        # 다음 수
        try:
            mv = bot.nextmove(b)
        except Exception:
            break
        if not mv or not _safe_is_valid(b, mv):
            break
        b.apply_move(mv)
    return b.score

# -------- 메인 평가 함수 --------
def evaluate_bot(bot_ref: str, seeds: List[int] = DEFAULT_SEEDS, H: int = 10, W: int = 17,
                 parallel: bool = False) -> Summary:
    """
    기본은 **직렬** 실행(서버/리로드 환경에서 가장 안전).
    parallel=True 로 넘기면 프로세스 풀 사용(문제시 자동 폴백).
    """
    scores: List[int] = []
    if parallel:
        try:
            # macOS/uvicorn 환경 안전성을 위해 spawn 컨텍스트 사용
            from multiprocessing import get_context
            ctx = get_context("spawn")
            tasks = [(bot_ref, s, H, W) for s in seeds]
            with ctx.Pool(processes=min(len(seeds), os.cpu_count() or 2)) as pool:
                # starmap으로 (bot_ref, seed, H, W) 전달
                scores = pool.starmap(run_one_seed, tasks)  # <-- 탑레벨 함수 참조
        except Exception:
            # 풀 실패시 직렬 폴백
            scores = [run_one_seed(bot_ref, s, H, W) for s in seeds]
    else:
        # 기본: 직렬 (가장 안전)
        scores = [run_one_seed(bot_ref, s, H, W) for s in seeds]

    per = [SeedScore(seed=s, score=sc) for s, sc in zip(seeds, scores)]
    return Summary(per)

__all__ = [
    "DEFAULT_SEEDS",
    "SeedScore",
    "Summary",
    "run_one_seed",
    "evaluate_bot",
]
