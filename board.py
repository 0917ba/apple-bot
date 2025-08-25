import random
from typing import Tuple, List, Optional

Rect = Tuple[int, int, int, int]  # (r1,c1,r2,c2) 1-based inclusive

class Board:
    """
    HxW 정수(1..9), 직사각형 합==10이면 제거(0으로 설정), 점수는 제거된 nonzero 개수.
    - prefix 합(ps_sum)과 nonzero 개수용 prefix(ps_ones)를 캐시하지만,
      grid 변경 시 dirty 플래그를 세우고, 질의 시 자동 재빌드합니다.
    """
    def __init__(self, H: int = 10, W: int = 17, seed: int = 42):
        self.H = H
        self.W = W
        self.rng = random.Random(seed)
        self.grid: List[List[int]] = [[self.rng.randint(1, 9) for _ in range(W)] for _ in range(H)]
        self.score = 0
        self.total_moves = 0
        self.failed_moves = 0
        self.successful_moves = 0
        self.seed = seed

        # prefix 캐시
        self._dirty = True
        self._ps_sum: List[List[int]] = [[0]*(W+1) for _ in range(H+1)]
        self._ps_ones: List[List[int]] = [[0]*(W+1) for _ in range(H+1)]

    # ---------- 내부: prefix 관리 ----------
    def _rebuild_prefix(self) -> None:
        H, W = self.H, self.W
        ps, ones = self._ps_sum, self._ps_ones
        # 재초기화
        for r in range(H+1):
            for c in range(W+1):
                ps[r][c] = 0
                ones[r][c] = 0
        # 빌드
        for r in range(1, H+1):
            row = self.grid[r-1]
            ps_r, ps_r_1 = ps[r], ps[r-1]
            ones_r, ones_r_1 = ones[r], ones[r-1]
            run_sum_ps = 0
            run_sum_ones = 0
            for c in range(1, W+1):
                v = row[c-1]
                run_sum_ps   += v
                run_sum_ones += (1 if v != 0 else 0)
                ps_r[c]   = ps_r_1[c]   + run_sum_ps
                ones_r[c] = ones_r_1[c] + run_sum_ones
        self._dirty = False

    def _ensure_prefix(self):
        if self._dirty:
            self._rebuild_prefix()

    @staticmethod
    def _pref_sum(pref: List[List[int]], r1: int, c1: int, r2: int, c2: int) -> int:
        # r1,c1,r2,c2 are 0-based inclusive
        return pref[r2+1][c2+1] - pref[r1][c2+1] - pref[r2+1][c1] + pref[r1][c1]

    # ---------- 질의 ----------
    def rect_sum(self, rect: Rect) -> int:
        r1, c1, r2, c2 = rect
        r1 -= 1; c1 -= 1; r2 -= 1; c2 -= 1
        if not (0 <= r1 <= r2 < self.H and 0 <= c1 <= c2 < self.W):
            raise ValueError("Invalid rectangle coordinates")
        self._ensure_prefix()
        return self._pref_sum(self._ps_sum, r1, c1, r2, c2)

    def rect_nonzero_count(self, rect: Rect) -> int:
        r1, c1, r2, c2 = rect
        r1 -= 1; c1 -= 1; r2 -= 1; c2 -= 1
        if not (0 <= r1 <= r2 < self.H and 0 <= c1 <= c2 < self.W):
            raise ValueError("Invalid rectangle coordinates")
        self._ensure_prefix()
        return self._pref_sum(self._ps_ones, r1, c1, r2, c2)

    def is_valid_rect(self, rect: Rect) -> bool:
        return self.rect_sum(rect) == 10

    def find_valid_moves(self):
        """
        합==10인 모든 직사각형(1-based)과 nonzero 개수를 함께 반환.
        prefix는 호출 시점의 최신 grid 기준으로 반드시 갱신됩니다.
        """
        self._ensure_prefix()
        H, W = self.H, self.W
        ps, ones = self._ps_sum, self._ps_ones
        res = []
        for r1 in range(H):
            for r2 in range(r1, H):
                for c1 in range(W):
                    row_sum = 0  # (최적화 여지 있지만 가독성 유지)
                    for c2 in range(c1, W):
                        s = self._pref_sum(ps, r1, c1, r2, c2)
                        if s == 10:
                            cnt = self._pref_sum(ones, r1, c1, r2, c2)
                            res.append(((r1+1, c1+1, r2+1, c2+1), cnt))
        return res

    def has_any_move(self) -> bool:
        """현재 그리드에서 합==10인 직사각형이 존재하는지 (내부 prefix로 빠르게) 반환."""
        self._ensure_prefix()
        H, W = self.H, self.W
        ps = self._ps_sum
        for r1 in range(H):
            for r2 in range(r1, H):
                for c1 in range(W):
                    for c2 in range(c1, W):
                        if self._pref_sum(ps, r1, c1, r2, c2) == 10:
                            return True
        return False

    def first_valid_move(self) -> Optional[Rect]:
        """가장 먼저 발견되는 합==10 직사각형(1-based)을 반환. 없으면 None."""
        self._ensure_prefix()
        H, W = self.H, self.W
        ps = self._ps_sum
        for r1 in range(H):
            for r2 in range(r1, H):
                for c1 in range(W):
                    for c2 in range(c1, W):
                        if self._pref_sum(ps, r1, c1, r2, c2) == 10:
                            return (r1+1, c1+1, r2+1, c2+1)
        return None
    
    # ---------- 변경(반드시 dirty=True 설정) ----------
    def apply_move(self, rect: Rect) -> None:
        """합==10이면 제거하고 점수/카운터 업데이트. 이후 prefix는 dirty 상태가 되어 다음 질의 시 갱신됩니다."""
        self.total_moves += 1
        if not self.is_valid_rect(rect):
            self.failed_moves += 1
            return

        apples = self.rect_nonzero_count(rect)
        self.score += apples
        self.successful_moves += 1

        r1, c1, r2, c2 = rect
        r1 -= 1; c1 -= 1; r2 -= 1; c2 -= 1
        for r in range(r1, r2 + 1):
            row = self.grid[r]
            for c in range(c1, c2 + 1):
                row[c] = 0

        # grid가 변했으므로 prefix 캐시 무효화
        self._dirty = True

    # ---------- 디버그 ----------
    def print_board(self) -> None:
        for row in self.grid:
            print(" ".join(f"{v:1d}" for v in row))
        print(f"Score: {self.score}, Total Moves: {self.total_moves}")
        print(f"Failed Moves: {self.failed_moves}, Successful Moves: {self.successful_moves}")

    def print_statistics(self) -> None:
        apple_counts = [0] * 10
        for row in self.grid:
            for value in row:
                if 1 <= value <= 9:
                    apple_counts[value] += 1
        for i in range(1, 10):
            print(f"Apples of type {i}: {apple_counts[i]}")
