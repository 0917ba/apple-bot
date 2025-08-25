"""
local_tester.py — Apple Game Local Tester (Mac-friendly)
- 학생들이 만든 봇(MyBot)을 로컬에서 쉽게 테스트/시연/평가할 수 있는 런처
- GUI(관찰) 모드: Tk 파일선택 + 시드 입력 → Pygame 실시간 렌더링 & 봇 자동 플레이
- Benchmark 모드: 기본 10개 시드 빠른 채점 → 평균점수 표시
- 맥북 대응: 시작 시 데스크톱 크기에 맞춰 '물리 창 크기' 자동 축소 + SCALED|RESIZABLE

요구:
  pip install pygame

실행 예:
  # 파일 선택 창(Tk)이 떠서 바로 사용
  python local_tester.py

  # 인자로 바로 실행 (관찰 모드)
  python local_tester.py --bot path/to/mybot.py --seed 42 --watch

  # 배치 평가(10개 시드)
  python local_tester.py --bot path/to/mybot.py --benchmark

관찰 모드 조작키:
  ESC: 종료
  F  : 전체화면 토글
  SPACE/P: 일시정지/재개
  R  : 같은 시드로 리셋
  N  : 새 랜덤 시드로 리셋

봇 규약(학생 제출과 동일):
  class MyBot:
      def nextmove(self, board) -> tuple(r1,c1,r2,c2) | None
      def gameover(self, board) -> bool
"""

from __future__ import annotations
import os
import sys
import time
import queue
import threading
import argparse
import importlib.util
from dataclasses import dataclass
from typing import Optional, Tuple, List

# --- Third party ---
try:
    import pygame
    import pygame.gfxdraw  # type: ignore
except Exception:
    print("pygame가 설치되어 있지 않습니다. 아래 명령으로 설치하세요:\n  pip install pygame")
    raise

# --- Optional Tkinter for file dialog ---
BOT_FILE_PATH_DEFAULT = None
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    TK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False

# --- Project modules ---
try:
    from board import Board
except Exception:
    print("board.py 를 찾지 못했습니다. local_tester.py 와 같은 폴더에 있어야 합니다.")
    raise

# --------- Visual Config (UI) ----------
H, W      = 10, 17
CELL      = 56
GAP       = 6
PAD_X     = 24
PAD_TOP   = 110
FPS       = 60

# Colors
BG    = (233,242,227)
PANEL = (242,248,240)
APPLE = (233, 85, 69)
LEAF  = ( 95,181, 93)
WHITE = (255,255,255)
INK   = ( 50, 50, 50)
GOLD  = (247,208, 80)
YEL   = (250,222,120)
RED   = (220, 64, 64)
GRAY  = (180,180,180)

# Animation
POP_DUR = 0.15
BOT_MIN_INTERVAL = 0.5  # 최소 간격(초). 봇이 오래 걸리면 이보다 길어질 수 있음.

Rect = Tuple[int,int,int,int]  # (r1,c1,r2,c2) 1-based inclusive

# --------- Utility ---------
def grid_to_px(r:int, c:int) -> Tuple[int,int]:
    x = PAD_X + c * (CELL + GAP)
    y = PAD_TOP + r * (CELL + GAP)
    return x, y

def import_bot_from_file(py_path: str, class_name: str = "MyBot"):
    """동적으로 .py 파일에서 MyBot 클래스를 import."""
    if not os.path.exists(py_path):
        raise FileNotFoundError(py_path)
    spec = importlib.util.spec_from_file_location("student_bot_module", py_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"spec 로딩 실패: {py_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["student_bot_module"] = module
    spec.loader.exec_module(module)  # type: ignore
    if not hasattr(module, class_name):
        raise AttributeError(f"파일 내에 class {class_name} 이(가) 없습니다.")
    bot_cls = getattr(module, class_name)
    return bot_cls()

def has_any_move(board: Board) -> bool:
    """Board 내부 데이터로 판단: 합==10 직사각형이 하나라도 있으면 True."""
    return bool(board.find_valid_moves())

def safe_is_valid(board: Board, rect: Rect) -> bool:
    """
    합==10 이고, 최소 한 칸은 0이 아닌지(=실제 제거 점수 > 0)까지 확인.
    """
    try:
        s = board.rect_sum(rect)
    except Exception:
        return False
    if s != 10:
        return False
    r1,c1,r2,c2 = (x-1 for x in rect)
    for r in range(r1, r2+1):
        for c in range(c1, c2+1):
            if board.grid[r][c] != 0:
                return True
    return False

# --------- Headless benchmark (no GUI) ---------
DEFAULT_SEEDS = [42, 43, 44, 45, 123, 777, 1001, 2024, 9001, 31415]

def run_single_seed(bot, seed: int) -> int:
    b = Board(H=H, W=W, seed=seed)
    safety = 20000
    while safety > 0:
        safety -= 1
        # 게임오버 판정
        if hasattr(bot, "gameover"):
            if bot.gameover(b):
                break
        else:
            if not has_any_move(b):
                break
        # 다음 수
        mv = bot.nextmove(b)
        if not mv or not safe_is_valid(b, mv):
            if not has_any_move(b):
                break
            break  # 봇 에러/무효수 보호 종료
        b.apply_move(mv)
    return b.score

def run_benchmark(bot, seeds: List[int] = DEFAULT_SEEDS) -> Tuple[float, List[int]]:
    scores = [run_single_seed(bot, s) for s in seeds]
    avg = sum(scores)/len(scores) if scores else 0.0
    return avg, scores

# --------- GUI (pygame) with async bot thread ---------
@dataclass
class MoveEvent:
    rect0b: Tuple[int,int,int,int]              # 0-based
    removed_cells: List[Tuple[int,int,int]]     # (r,c,val) before removal

class WatchSession:
    """렌더링은 메인 스레드, 봇은 별도 스레드에서 동작."""
    def __init__(self, bot_file: str, seed: int = 42):
        self.bot_file = bot_file
        self.seed = seed
        self.bot = import_bot_from_file(bot_file, "MyBot")

        self.board = Board(H=H, W=W, seed=seed)
        self.lock = threading.Lock()
        self.events: "queue.Queue[MoveEvent|str]" = queue.Queue()

        # UI/anim
        self.state = "idle"  # "idle"|"popping"
        self.anim_t = 0.0
        self.removed_cells: List[Tuple[int,int,int]] = []
        self.hilite_rect0b: Optional[Tuple[int,int,int,int]] = None
        self.hilite_t = 0.0

        self.running = True
        self.paused = False
        self.finished = False
        self.last_apply_time = 0.0

        # worker thread
        self.worker = threading.Thread(target=self._bot_worker, daemon=True)
        self.worker.start()

    def reset(self, seed: Optional[int] = None):
        with self.lock:
            if seed is not None:
                self.seed = seed
            self.board = Board(H=H, W=W, seed=self.seed)
            self.state = "idle"
            self.anim_t = 0.0
            self.removed_cells.clear()
            self.hilite_rect0b = None
            self.hilite_t = 0.0
            self.finished = False
            self.last_apply_time = 0.0
        # 봇 인스턴스 재생성(내부 상태 유지형 대비)
        self.bot = import_bot_from_file(self.bot_file, "MyBot")

    def stop(self):
        self.running = False

    def _bot_worker(self):
        # 렌더링과 독립 실행: 최소 간격만 보장
        while self.running:
            if self.paused or self.finished:
                time.sleep(0.05)
                continue

            # 최소 간격 보장
            if (time.time() - self.last_apply_time) < BOT_MIN_INTERVAL:
                time.sleep(0.01)
                continue

            # 게임 끝?
            with self.lock:
                board_ref = self.board
                # 미리 빠른 종료 스캔
                if hasattr(self.bot, "gameover") and self.bot.gameover(board_ref):
                    self.finished = True
                    self.events.put("gameover")
                    continue
                if not has_any_move(board_ref):
                    self.finished = True
                    self.events.put("gameover")
                    continue

            # 다음 수 계산 (오래 걸려도 렌더링은 계속 됨) — 잠금 없이 호출
            try:
                rect = self.bot.nextmove(board_ref)
            except Exception as e:
                self.events.put(f"error: {e}")
                self.finished = True
                continue

            if not rect:
                # 수 없음 → 재확인 후 종료/대기
                with self.lock:
                    if not has_any_move(self.board):
                        self.finished = True
                        self.events.put("gameover")
                time.sleep(0.05)
                continue

            # 적용 직전 유효성 재확인 & removed_cells 준비 (잠금 하에)
            with self.lock:
                if not safe_is_valid(self.board, rect):
                    # 무효수: 다음 루프
                    time.sleep(0.02)
                    continue
                r1b, c1b, r2b, c2b = rect[0]-1, rect[1]-1, rect[2]-1, rect[3]-1
                removed = [(r, c, self.board.grid[r][c])
                           for r in range(r1b, r2b+1)
                           for c in range(c1b, c2b+1)]
                # 먼저 이벤트 큐에 알리고
                self.events.put(MoveEvent((r1b,c1b,r2b,c2b), removed))
                # 실제 적용
                self.board.apply_move(rect)
                self.last_apply_time = time.time()

            time.sleep(0.001)

# --- Drawing helpers ---
def draw_apple(surface, font, x, y, value, scale=1.0, alpha=255):
    if value == 0:
        return
    apple_surf = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
    radius = int((CELL//2 - 3) * scale)
    pygame.gfxdraw.aacircle(apple_surf, CELL//2, CELL//2, radius, (*APPLE, alpha))
    pygame.gfxdraw.filled_circle(apple_surf, CELL//2, CELL//2, radius, (*APPLE, alpha))
    # leaf
    lr = max(4, int(6*scale))
    pygame.draw.ellipse(apple_surf, (*LEAF, alpha),
                        (CELL//2 + radius//3, CELL//2 - radius - 6, lr*3, lr*2))
    # number
    txt = font.render(str(value), True, WHITE)
    tr = txt.get_rect(center=(CELL//2, CELL//2))
    apple_surf.blit(txt, tr)
    surface.blit(apple_surf, (x, y))

def run_watch(bot_file: str, seed: int = 42):
    pygame.init()
    pygame.display.set_caption("Apple Game - Local Tester (Watch)")

    # 논리 크기(그리드 기준) — 유지
    W_px = PAD_X*2 + W*(CELL+GAP) - GAP
    H_px = PAD_TOP + H*(CELL+GAP) - GAP + 20

    # 논리 해상도 유지 + 리사이즈 가능
    screen = pygame.display.set_mode((W_px, H_px), pygame.SCALED | pygame.RESIZABLE)

    # ---- MacBook 등에서 시작부터 잘리는 것 방지: 초기 '물리' 창 크기 축소 ----
    try:
        desk_w, desk_h = pygame.display.get_desktop_sizes()[0]  # pygame 2.0+
    except Exception:
        info = pygame.display.Info()
        desk_w, desk_h = info.current_w, info.current_h
    SAFE_TOP  = 90   # macOS 메뉴바/노치 여유
    SAFE_SIDE = 24   # 좌우 여유
    scale = min((desk_w - SAFE_SIDE) / W_px, (desk_h - SAFE_TOP) / H_px, 1.0)
    phys_w = max(640, int(W_px * scale))
    phys_h = max(480, int(H_px * scale))
    if hasattr(pygame.display, "set_window_size"):
        pygame.display.set_window_size((phys_w, phys_h))
    else:
        screen = pygame.display.set_mode((phys_w, phys_h), pygame.SCALED | pygame.RESIZABLE)
    # -----------------------------------------------------------------------

    clock = pygame.time.Clock()
    font = pygame.font.SysFont("arialrounded", 26, bold=True)
    hud_font = pygame.font.SysFont("arial", 24, bold=True)

    sess = WatchSession(bot_file, seed)

    running = True
    while running and sess.running:
        dt = clock.tick(FPS) / 1000.0

        # 이벤트 처리
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                sess.stop()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                    sess.stop()
                elif event.key in (pygame.K_SPACE, pygame.K_p):
                    sess.paused = not sess.paused
                elif event.key == pygame.K_r:
                    sess.reset(seed=sess.seed)   # 같은 시드 리셋
                elif event.key == pygame.K_n:
                    sess.reset(seed=int(time.time()) & 0xFFFFFFFF)  # 새로운 시드
                elif event.key == pygame.K_f:
                    # 전체화면 토글
                    try:
                        pygame.display.toggle_fullscreen()
                    except Exception:
                        pass

        # 봇 이벤트 폴링 (non-blocking)
        try:
            while True:
                ev = sess.events.get_nowait()
                if isinstance(ev, str):
                    if ev.startswith("error:"):
                        print(ev)
                        sess.finished = True
                    elif ev == "gameover":
                        sess.finished = True
                elif isinstance(ev, MoveEvent):
                    sess.hilite_rect0b = ev.rect0b
                    sess.hilite_t = 0.25
                    sess.removed_cells = ev.removed_cells
                    sess.state = "popping"
                    sess.anim_t = 0.0
        except queue.Empty:
            pass

        # 팝 애니메이션
        if sess.state == "popping":
            sess.anim_t += dt
            if sess.anim_t >= POP_DUR:
                sess.state = "idle"
                sess.anim_t = 0.0

        # 하이라이트 타이머
        if sess.hilite_t > 0.0:
            sess.hilite_t = max(0.0, sess.hilite_t - dt)
            if sess.hilite_t == 0.0:
                sess.hilite_rect0b = None

        # ------- DRAW -------
        screen.fill(BG)

        # HUD
        stxt = hud_font.render(f"Score: {sess.board.score}", True, INK)
        letxt = hud_font.render(f"Seed: {sess.seed}", True, INK)
        statxt = hud_font.render(f"{'PAUSED' if sess.paused else ('FINISHED' if sess.finished else 'RUNNING')}", True, INK)
        screen.blit(stxt, (PAD_X, 18))
        screen.blit(letxt, (PAD_X + 180, 18))
        screen.blit(statxt, (PAD_X + 340, 18))

        # Grid + apples
        with sess.lock:
            for r in range(H):
                for c in range(W):
                    x,y = grid_to_px(r,c)
                    pygame.draw.rect(screen, PANEL, (x,y,CELL,CELL), border_radius=12)
                    draw_apple(screen, font, x, y, sess.board.grid[r][c])

        # Bot highlight rectangle
        if sess.hilite_rect0b is not None:
            r1, c1, r2, c2 = sess.hilite_rect0b
            x1,y1 = grid_to_px(r1,c1)
            x2,y2 = grid_to_px(r2,c2)
            border = pygame.Rect(x1-3, y1-3, (x2-x1)+CELL+6, (y2-y1)+CELL+6)
            pygame.draw.rect(screen, RED, border, width=4, border_radius=12)

        # Pop animation shrinking over removed cells
        if sess.state == "popping":
            t = min(1.0, sess.anim_t/POP_DUR)
            scale = 1.0 - t*t
            alpha = int(255*(1.0 - t))
            for (r,c,val) in sess.removed_cells:
                x,y = grid_to_px(r,c)
                draw_apple(screen, font, x, y, val, scale=scale, alpha=alpha)

        # Footer help
        help1 = "ESC:Quit  F:Fullscreen  SPACE/P:Pause  R:Reset(seed)  N:New Seed"
        htxt = pygame.font.SysFont("arial", 18).render(help1, True, INK)
        screen.blit(htxt, (PAD_X, H_px-26))

        pygame.display.flip()

    pygame.quit()

# --------- Tk wrapper (optional) ----------
def ask_user_inputs_with_tk():
    if not TK_AVAILABLE:
        print("Tkinter를 사용할 수 없습니다. 명령행 인자로 실행하세요.")
        return

    root = tk.Tk()
    root.title("Apple Game Local Tester")

    # macOS 노치/메뉴바/독 여유
    SAFE_SIDE = 40
    SAFE_TOP  = 100
    SAFE_BOTTOM = 80

    # ----- UI 구성 -----
    chosen_file = tk.StringVar(value=BOT_FILE_PATH_DEFAULT or "" )
    seed_var = tk.StringVar(value="42")
    mode_var = tk.StringVar(value="watch")  # or "benchmark"

    frm = tk.Frame(root, padx=16, pady=16)
    frm.pack(fill="both", expand=True)

    # 레이아웃: 3열 그리드, 가운데 열이 넓게 늘어나도록
    for col in (0, 1, 2):
        frm.grid_columnconfigure(col, weight=(1 if col == 1 else 0))

    # 1) 파일 선택
    tk.Label(frm, text="봇 파일(.py)").grid(row=0, column=0, sticky="w")
    e_path = tk.Entry(frm, textvariable=chosen_file)
    e_path.grid(row=0, column=1, sticky="we", padx=(8,0))
    tk.Button(frm, text="찾기", command=lambda: chosen_file.set(
        filedialog.askopenfilename(title="봇 파일 선택 (.py)", filetypes=[("Python file","*.py")])
        or chosen_file.get()
    )).grid(row=0, column=2, padx=(8,0))

    # 2) 시드
    tk.Label(frm, text="Seed (정수)").grid(row=1, column=0, sticky="w", pady=(12,0))
    tk.Entry(frm, textvariable=seed_var, width=12).grid(row=1, column=1, sticky="w",
                                                       padx=(8,0), pady=(12,0))

    # 3) 모드
    tk.Label(frm, text="모드").grid(row=2, column=0, sticky="w", pady=(12,0))
    tk.Radiobutton(frm, text="관찰(Watch)", variable=mode_var, value="watch")\
        .grid(row=2, column=1, sticky="w", pady=(12,0))
    tk.Radiobutton(frm, text="평가(Benchmark)", variable=mode_var, value="benchmark")\
        .grid(row=2, column=1, sticky="w", padx=(160,0), pady=(12,0))

    # 4) 실행 버튼
    def run_now():
        path = chosen_file.get().strip()
        if not path:
            messagebox.showwarning("알림","봇 파일(.py)을 선택하세요.")
            return
        try:
            s = int(seed_var.get())
        except Exception:
            messagebox.showwarning("알림","Seed는 정수로 입력하세요.")
            return
        root.destroy()
        if mode_var.get() == "watch":
            run_watch(path, seed=s)
        else:
            bot = import_bot_from_file(path, "MyBot")
            avg, scores = run_benchmark(bot, DEFAULT_SEEDS)
            print(f"[Benchmark] seeds={DEFAULT_SEEDS}")
            print("Scores :", scores)
            print("Average:", f"{avg:.2f}")

    tk.Button(frm, text="실행", command=run_now).grid(row=3, column=2, sticky="e", pady=(16,0))

    # ----- 여기부터가 핵심: 화면 크기에 맞춰 '자동 크기 & 중앙 배치' -----
    root.update_idletasks()  # 실제 요청 크기 계산
    req_w = max(480, frm.winfo_reqwidth() + 32)   # 프레임 여백 보정
    req_h = max(200, frm.winfo_reqheight() + 32)

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()

    # 화면에 무조건 들어오도록 축소
    width  = min(req_w, sw - SAFE_SIDE)
    height = min(req_h, sh - SAFE_TOP - SAFE_BOTTOM)

    # 중앙 배치
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2 - SAFE_TOP // 2)
    root.geometry(f"{int(width)}x{int(height)}+{x}+{y}")

    # 리사이즈 허용 (잘리면 사용자가 늘릴 수 있도록)
    root.minsize(420, 180)
    root.resizable(True, True)

    root.mainloop()


# --------- CLI main ----------
def main():
    ap = argparse.ArgumentParser(description="Apple Game Local Tester")
    ap.add_argument("--bot", type=str, help="봇 파일(.py). class MyBot 필수")
    ap.add_argument("--seed", type=int, default=42, help="초기 시드 (기본: 42)")
    ap.add_argument("--watch", action="store_true", help="Pygame GUI로 관찰 모드 실행")
    ap.add_argument("--benchmark", action="store_true", help="표준 10개 시드로 빠른 평가 실행")
    args = ap.parse_args()

    # 인자 없으면 GUI 런처
    if not any([args.bot, args.watch, args.benchmark]):
        ask_user_inputs_with_tk()
        return

    if not args.bot:
        print("--bot 경로가 필요합니다. 또는 인자 없이 실행해 GUI 런처를 사용하세요.")
        sys.exit(1)

    if args.benchmark:
        bot = import_bot_from_file(args.bot, "MyBot")
        avg, scores = run_benchmark(bot, DEFAULT_SEEDS)
        print(f"[Benchmark] seeds={DEFAULT_SEEDS}")
        print("Scores :", scores)
        print("Average:", f"{avg:.2f}")
        return

    # watch (GUI)
    run_watch(args.bot, seed=args.seed)

if __name__ == "__main__":
    main()
