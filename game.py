# game.py
# - Game: 게임 상태/진행/봇 상호작용/데이터만 담당 (렌더 X)
# - 봇 수 선택은 백그라운드 스레드에서 비동기로 계산
from __future__ import annotations
import time, random, threading, queue
from typing import List, Tuple, Optional

from board import Board
from bots.greedybot import MyBot as DefaultBot  # 기본 봇은 항상 GreedyBot


Rect = Tuple[int, int, int, int]  # 1-based inclusive
Cell = Tuple[int, int, int]       # (r,c,val) 0-based

# ----- 공통 설정 (GUI가 import) -----
H, W   = 10, 17
CELL   = 56
GAP    = 6
PAD_X  = 24
PAD_TOP= 110
TIME_LIMIT = 120.0

# 봇/애니메이션 파라미터
BOT_INTERVAL = 0.5          # '적용' 최소 간격(초)
BORDER_DUR   = 0.25         # 봇 테두리 유지 시간(초)
POP_DUR      = 0.15         # 팝 애니메이션 길이(초)

# 실패/없음 백오프
NO_MOVE_BACKOFF   = 0.5
FAIL_APPLY_BACKOFF= 0.2


# ---------- 유틸: 보드 스냅샷 ----------
def _clone_board(b: Board) -> Board:
    nb = Board(H=b.H, W=b.W, seed=b.seed)
    nb.grid = [row[:] for row in b.grid]
    nb.score = b.score
    nb.total_moves = b.total_moves
    nb.failed_moves = b.failed_moves
    nb.successful_moves = b.successful_moves
    return nb


# ---------- 유틸: 현재 보드 그리드 기준 직접 계산/적용 ----------
def _sum_rect_grid(grid: List[List[int]], rect: Rect) -> int:
    r1, c1, r2, c2 = rect
    r1 -= 1; c1 -= 1; r2 -= 1; c2 -= 1
    s = 0
    for r in range(r1, r2+1):
        row = grid[r]
        for c in range(c1, c2+1):
            s += row[c]
    return s

def _count_nonzero_rect_grid(grid: List[List[int]], rect: Rect) -> int:
    r1, c1, r2, c2 = rect
    r1 -= 1; c1 -= 1; r2 -= 1; c2 -= 1
    cnt = 0
    for r in range(r1, r2+1):
        row = grid[r]
        for c in range(c1, c2+1):
            if row[c] != 0:
                cnt += 1
    return cnt

def _apply_move_direct(board: Board, rect: Rect) -> bool:
    """보드 API 캐시/검증에 의존하지 않고 직접 적용. 성공 시 True."""
    board.total_moves += 1
    if _sum_rect_grid(board.grid, rect) != 10:
        board.failed_moves += 1
        return False
    apples = _count_nonzero_rect_grid(board.grid, rect)
    board.score += apples
    board.successful_moves += 1
    r1, c1, r2, c2 = rect
    r1 -= 1; c1 -= 1; r2 -= 1; c2 -= 1
    for r in range(r1, r2+1):
        row = board.grid[r]
        for c in range(c1, c2+1):
            row[c] = 0
    return True


# ---------- 백그라운드 워커 ----------
class _BotWorker(threading.Thread):
    """
    nextmove + gameover를 함께 계산해서 반환.
    결과: (version, rect|None, gameover_flag, timestamp)
    """
    def __init__(self, bot):
        super().__init__(daemon=True)
        self.bot = bot
        self.jobs: "queue.Queue[Tuple[int, Board]]" = queue.Queue()
        self.results: "queue.Queue[Tuple[int, Optional[Rect], bool, float]]" = queue.Queue()
        self._stop = threading.Event()

    def submit(self, version: int, board_copy: Board):
        if not self._stop.is_set():
            self.jobs.put((version, board_copy))

    def poll_result(self) -> Optional[Tuple[int, Optional[Rect], bool, float]]:
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                ver, bcopy = self.jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                # 봇이 gameover를 제공하지 않으면 기본: 가능한 수 없음이면 True
                if hasattr(self.bot, "gameover"):
                    go = bool(self.bot.gameover(bcopy))
                else:
                    # 보드 API에 의존 (prefix 캐시가 Board 쪽에서 최신으로 관리된다는 전제)
                    moves = getattr(bcopy, "find_valid_moves")()
                    go = (len(moves) == 0)
            except Exception:
                go = False

            rect: Optional[Rect]
            try:
                rect = self.bot.nextmove(bcopy) if not go else None
            except Exception:
                rect = None

            self.results.put((ver, rect, go, time.time()))


class Game:
    """게임 상태, 비동기 봇, 입력(격자 단위) 처리. (렌더 X)"""

    def __init__(self, seed: int = 42, bot=None):
        self.seed = seed
        self.bot = bot if bot is not None else DefaultBot()

        self.board: Optional[Board] = None
        self.state: str = "start"  # 'start' | 'playing' | 'gameover'

        self.start_time: Optional[float] = None
        self.remain_time: float = TIME_LIMIT

        # 드래그 선택(0b)
        self.selecting: bool = False
        self.sel_r1 = self.sel_c1 = self.sel_r2 = self.sel_c2 = 0

        # 팝 애니메이션
        self.pop_state: str = "idle"   # 'idle' | 'popping'
        self.pop_t: float = 0.0
        self.removed_cells: List[Cell] = []

        # 봇 하이라이트(0b)
        self.bot_hilite_rect: Optional[Tuple[int,int,int,int]] = None
        self.bot_hilite_t: float = 0.0

        # 비동기 봇
        self._worker = _BotWorker(self.bot)
        self._worker.start()
        self._version: int = 0                 # 보드 버전(성공 수 적용 시에만 +1)
        self._job_inflight: bool = False
        self._pending_rect: Optional[Rect] = None
        self._pending_ver: int = -1
        self._next_apply_time: float = 0.0
        self._no_move_backoff_until: float = 0.0

        rng = random.Random(1)
        self.preview_grid: List[List[int]] = [[rng.randint(1,9) for _ in range(W)] for _ in range(H)]

    # ---------- 수명주기 ----------
    def start_new(self):
        self.board = Board(H=H, W=W, seed=self.seed)
        self.state = "playing"
        self.start_time = time.time()
        self.remain_time = TIME_LIMIT
        self.selecting = False
        self.pop_state = "idle"
        self.pop_t = 0.0
        self.removed_cells.clear()
        self.bot_hilite_rect = None
        self.bot_hilite_t = 0.0

        self._version = 0
        self._job_inflight = False
        self._pending_rect = None
        self._pending_ver = -1
        now = time.time()
        self._next_apply_time = now + BOT_INTERVAL
        self._no_move_backoff_until = now
        self._ensure_job()

    def to_start(self):
        self.state = "start"
        self.board = None
        self.start_time = None
        self.remain_time = TIME_LIMIT
        self.selecting = False
        self.pop_state = "idle"
        self.pop_t = 0.0
        self.removed_cells.clear()
        self.bot_hilite_rect = None
        self.bot_hilite_t = 0.0

        self._job_inflight = False
        self._pending_rect = None
        self._pending_ver = -1

    def retry(self):
        self.start_new()

    def shutdown(self):
        self._worker.stop()

    # ---------- 프레임 업데이트 ----------
    def update(self, dt: float):
        if self.state == "playing" and self.start_time is not None:
            self.remain_time = max(0.0, TIME_LIMIT - (time.time() - self.start_time))
            if self.remain_time <= 0.0:
                self.state = "gameover"
                self.selecting = False
                self.pop_state = "idle"

        if self.bot_hilite_t > 0.0:
            self.bot_hilite_t = max(0.0, self.bot_hilite_t - dt)
            if self.bot_hilite_t == 0.0:
                self.bot_hilite_rect = None

        if self.state == "playing" and self.pop_state == "popping":
            self.pop_t += dt
            if self.pop_t >= POP_DUR:
                self.pop_state = "idle"
                self.pop_t = 0.0

        self._poll_worker()
        self._apply_pending_if_ready()
        self._ensure_job()

    # ---------- 비동기 관리 ----------
    def _ensure_job(self):
        if (self.state != "playing" or self.board is None or
            self.pop_state != "idle" or self._job_inflight or
            self._pending_rect is not None or
            time.time() < self._no_move_backoff_until):
            return
        self._worker.submit(self._version, _clone_board(self.board))
        self._job_inflight = True

    def _poll_worker(self):
        if not self._job_inflight:
            return
        res = self._worker.poll_result()
        if res is None:
            return
        self._job_inflight = False
        ver, rect, gameover_flag, ts = res
        now = time.time()

        # 보드가 바뀌었으면 폐기
        if ver != self._version:
            self._no_move_backoff_until = now
            return

        # ---- 봇이 종료를 선언했으면 즉시 종료 ----
        if gameover_flag and self.state == "playing":
            # 대기 중이던 rect도 폐기하고 즉시 게임오버
            self._pending_rect = None
            self._pending_ver = -1
            self.selecting = False
            self.pop_state = "idle"
            self.state = "gameover"
            return

        if rect is None:
            # 수 없음(혹은 계산 실패) → 잠깐 백오프
            self._no_move_backoff_until = now + NO_MOVE_BACKOFF
            return

        # 적용 대기
        self._pending_rect = rect
        self._pending_ver = ver

    def _apply_pending_if_ready(self):
        if (self.state != "playing" or self.board is None or
            self.pop_state != "idle" or self._pending_rect is None):
            return
        now = time.time()
        if now < self._next_apply_time:
            return
        if self._pending_ver != self._version:
            self._pending_rect = None
            return

        rect = self._pending_rect

        # ---- 현재 보드 그리드로 직접 검증 ----
        if _sum_rect_grid(self.board.grid, rect) != 10:
            # 유효하지 않음 → 폐기 & 짧은 백오프
            self._pending_rect = None
            self._no_move_backoff_until = now + FAIL_APPLY_BACKOFF
            return

        # 애니메이션용 캡처(현재 보드 기준)
        r1, c1, r2, c2 = rect
        r1b, c1b, r2b, c2b = r1-1, c1-1, r2-1, c2-1
        self.removed_cells = [(r, c, self.board.grid[r][c])
                              for r in range(r1b, r2b+1) for c in range(c1b, c2b+1)]

        # ---- 직접 적용 ----
        if not _apply_move_direct(self.board, rect):
            # 실패 시 애니/버전 증가 금지
            self.removed_cells.clear()
            self.bot_hilite_rect = None
            self.bot_hilite_t = 0.0
            self._pending_rect = None
            self._no_move_backoff_until = now + FAIL_APPLY_BACKOFF
            return

        # 성공: 버전/하이라이트/애니 갱신
        self._version += 1
        self.bot_hilite_rect = (r1b, c1b, r2b, c2b)
        self.bot_hilite_t = BORDER_DUR
        self.pop_state = "popping"
        self.pop_t = 0.0
        self._next_apply_time = now + BOT_INTERVAL
        self._pending_rect = None

    # ---------- 드래그 선택 ----------
    def begin_selection(self, r: int, c: int):
        if self.state != "playing" or self.pop_state != "idle":
            return
        if self.board is None:
            return
        if not (0 <= r < H and 0 <= c < W):
            return
        self.selecting = True
        self.sel_r1 = self.sel_r2 = r
        self.sel_c1 = self.sel_c2 = c

    def update_selection(self, r: int, c: int):
        if self.state != "playing" or not self.selecting:
            return
        r = max(0, min(H-1, r))
        c = max(0, min(W-1, c))
        self.sel_r2, self.sel_c2 = r, c

    def end_selection(self):
        if self.state != "playing" or not self.selecting or self.board is None:
            self.selecting = False
            return
        self.selecting = False
        r1 = min(self.sel_r1, self.sel_r2); r2 = max(self.sel_r1, self.sel_r2)
        c1 = min(self.sel_c1, self.sel_c2); c2 = max(self.sel_c1, self.sel_c2)
        rect = (r1+1, c1+1, r2+1, c2+1)  # 1-based

        if _sum_rect_grid(self.board.grid, rect) != 10:
            return

        # 애니 캡처
        self.removed_cells = [(r, c, self.board.grid[r][c])
                              for r in range(r1, r2+1) for c in range(c1, c2+1)]
        self.bot_hilite_rect = (r1, c1, r2, c2)
        self.bot_hilite_t = BORDER_DUR

        if not _apply_move_direct(self.board, rect):
            # 실패 시 롤백(하이라이트 제거)
            self.removed_cells.clear()
            self.bot_hilite_rect = None
            self.bot_hilite_t = 0.0
            return

        self._version += 1
        self.pop_state = "popping"
        self.pop_t = 0.0
        self._next_apply_time = time.time() + BOT_INTERVAL
        self._pending_rect = None  # 대기 결과는 버전불일치로 자연 폐기 예정

    # ---------- GUI 조회 ----------
    def current_grid(self) -> List[List[int]]:
        if self.state == "start":
            return self.preview_grid
        return self.board.grid if self.board is not None else [[0]*W for _ in range(H)]

    def score(self) -> int:
        return self.board.score if self.board is not None else 0

    def selection_overlay(self) -> Optional[Tuple[int,int,int,int,bool]]:
        if self.state != "playing" or not self.selecting or self.board is None:
            return None
        r1 = min(self.sel_r1, self.sel_r2); r2 = max(self.sel_r1, self.sel_r2)
        c1 = min(self.sel_c1, self.sel_c2); c2 = max(self.sel_c1, self.sel_c2)
        rect = (r1+1, c1+1, r2+1, c2+1)
        valid = (_sum_rect_grid(self.board.grid, rect) == 10)
        return (r1, c1, r2, c2, valid)

    def bot_highlight_rect(self) -> Optional[Tuple[int,int,int,int]]:
        return self.bot_hilite_rect

    def pop_effect(self) -> Optional[Tuple[float, int, List[Cell]]]:
        if self.state == "playing" and self.pop_state == "popping":
            t = min(1.0, self.pop_t / POP_DUR)
            scale = 1.0 - t*t
            alpha = int(255 * (1.0 - t))
            return (scale, alpha, list(self.removed_cells))
        return None
