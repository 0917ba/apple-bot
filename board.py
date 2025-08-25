# board.py
import random
from typing import Tuple, List

Rect = Tuple[int, int, int, int]  # (r1,c1,r2,c2) 1-based inclusive

class Board:
    """Apple board: HxW integers in 1..9.
    A move removes an axis-aligned rectangle iff its sum == 10.
    Removed cells are set to 0 and STAY EMPTY (no gravity/refill).
    Score = number of removed nonzero cells.
    """
    def __init__(self, H: int = 10, W: int = 17, seed: int = 42):
        self.H = H
        self.W = W
        self.rng = random.Random(seed)
        self.grid = [[self.rng.randint(1, 9) for _ in range(W)] for _ in range(H)]
        self.score = 0
        self.total_moves = 0
        self.failed_moves = 0
        self.successful_moves = 0
        self.seed = seed

    # -------- sums --------
    def get_rectangle_sum(self, rect: Rect) -> int:
        r1, c1, r2, c2 = (x - 1 for x in rect)
        if not (0 <= r1 <= r2 < self.H and 0 <= c1 <= c2 < self.W):
            raise ValueError("Invalid rectangle coordinates")
        s = 0
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                s += self.grid[r][c]
        return s

    # alias for old GUI code
    def rect_sum(self, rect: Rect) -> int:
        return self.get_rectangle_sum(rect)

    def _make_prefix_sum(self):
        """Create prefix sums for fast enumeration (values + nonzero counts)."""
        ps = [[0] * (self.W + 1) for _ in range(self.H + 1)]
        ones = [[0] * (self.W + 1) for _ in range(self.H + 1)]
        for r in range(1, self.H + 1):
            for c in range(1, self.W + 1):
                v = self.grid[r - 1][c - 1]
                ps[r][c] = v + ps[r - 1][c] + ps[r][c - 1] - ps[r - 1][c - 1]
                ones[r][c] = (1 if v != 0 else 0) + ones[r - 1][c] + ones[r][c - 1] - ones[r - 1][c - 1]
        return ps, ones

    def _pref_rect(self, pref, r1, c1, r2, c2):
        return pref[r2+1][c2+1] - pref[r1][c2+1] - pref[r2+1][c1] + pref[r1][c1]

    # -------- move enumeration (ROLLED BACK: 2-tuple) --------
    def find_all_valid_moves(self) -> List[Tuple[Rect, int]]:
        """Return list of (rect, apples_count) with sum==10.
        rect is 1-based inclusive. apples_count = # of nonzero cells in rect.
        """
        H, W = self.H, self.W
        ps, ones = self._make_prefix_sum()
        res: List[Tuple[Rect, int]] = []
        for r1 in range(H):
            for r2 in range(r1, H):
                for c1 in range(W):
                    for c2 in range(c1, W):
                        s = self._pref_rect(ps, r1, c1, r2, c2)
                        if s == 10:
                            apples = self._pref_rect(ones, r1, c1, r2, c2)
                            if apples > 0:
                                res.append(((r1+1, c1+1, r2+1, c2+1), apples))
        return res

    # legacy name some bots used
    def find_valid_moves(self) -> List[Tuple[Rect, int]]:
        return self.find_all_valid_moves()

    # -------- rules --------
    def is_valid_matching(self, rect: Rect) -> bool:
        return self.get_rectangle_sum(rect) == 10

    # alias used by some GUIs
    def is_valid_rect(self, rect: Rect) -> bool:
        return self.is_valid_matching(rect)

    def count_apples_inside_rectangle(self, rect: Rect) -> int:
        r1, c1, r2, c2 = (x - 1 for x in rect)
        if not (0 <= r1 <= r2 < self.H and 0 <= c1 <= c2 < self.W):
            raise ValueError("Invalid rectangle coordinates")
        cnt = 0
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                if self.grid[r][c] != 0:
                    cnt += 1
        return cnt

    def apply_move(self, rect: Rect) -> None:
        self.total_moves += 1
        if not self.is_valid_matching(rect):
            self.failed_moves += 1
            return
        self.successful_moves += 1
        self.score += self.count_apples_inside_rectangle(rect)
        r1, c1, r2, c2 = (x - 1 for x in rect)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                self.grid[r][c] = 0

    # -------- debug --------
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