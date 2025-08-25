# gui.py
# - GUI: 렌더링/입력(픽셀→격자 변환, 버튼 히트테스트)만 담당
# - Game: game.py 에서 import

from __future__ import annotations
import pygame, pygame.gfxdraw  # type: ignore
from typing import Tuple
from game import Game, H, W, CELL, GAP, PAD_X, PAD_TOP, TIME_LIMIT

# ------- 색/스타일 -------
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

# HUD / FPS
FPS = 360

# Modal / UI
MODAL_W, MODAL_H = 520, 320
MODAL_RADIUS = 16
SHADOW_PAD = 6
CARD_ALPHA = 235
BTN_RADIUS = 28
IN_ICON_RADIUS = 20

Rect0 = Tuple[int,int,int,int]  # 0-based inclusive


# --------- 좌표 변환 & 드로잉 유틸 ---------
def grid_to_px(r,c):
    x = PAD_X + c * (CELL + GAP)
    y = PAD_TOP + r * (CELL + GAP)
    return x, y

def draw_apple(surf, font, x, y, value, scale=1.0, alpha=255, apple_color=None, leaf_color=None):
    if value == 0:
        return
    apple_surf = pygame.Surface((CELL, CELL), pygame.SRCALPHA)
    radius = int((CELL//2 - 3) * scale)
    ac = apple_color if apple_color is not None else APPLE
    lc = leaf_color if leaf_color is not None else LEAF
    pygame.gfxdraw.aacircle(apple_surf, CELL//2, CELL//2, radius, (*ac, alpha))
    pygame.gfxdraw.filled_circle(apple_surf, CELL//2, CELL//2, radius, (*ac, alpha))
    lr = max(4, int(6*scale))
    pygame.draw.ellipse(apple_surf, (*lc, alpha), (CELL//2 + radius//3, CELL//2 - radius - 6, lr*3, lr*2))
    txt = font.render(str(value), True, WHITE)
    tr = txt.get_rect(center=(CELL//2, CELL//2))
    apple_surf.blit(txt, tr)
    surf.blit(apple_surf, (x, y))

def draw_icon_button(surf, center, radius, bg, icon_text='', icon_font=None, fg=WHITE, outline=None):
    SS = 3
    size_hi = radius * 2 * SS
    hi = pygame.Surface((size_hi, size_hi), pygame.SRCALPHA)
    cx = cy = radius * SS
    pygame.gfxdraw.filled_circle(hi, cx, cy, radius * SS, bg)
    pygame.gfxdraw.aacircle(hi, cx, cy, radius * SS, bg)
    pygame.gfxdraw.aacircle(hi, cx, cy, radius * SS - 1, bg)
    if outline is not None:
        pygame.gfxdraw.aacircle(hi, cx, cy, radius * SS - 2, outline)
    lo = pygame.transform.smoothscale(hi, (radius * 2, radius * 2))
    surf.blit(lo, (center[0] - radius, center[1] - radius))
    if icon_text and icon_font:
        txt = icon_font.render(icon_text, True, fg)
        surf.blit(txt, (center[0] - txt.get_width()//2, center[1] - txt.get_height()//2))


class GUI:
    """Pygame 초기화/렌더/입력의 책임만 갖는 클래스"""

    def __init__(self, game: Game):
        pygame.init()
        pygame.display.set_caption("Apple Game")
        W_px = PAD_X*2 + W*(CELL+GAP) - GAP
        H_px = PAD_TOP + H*(CELL+GAP) - GAP + 20
        self.screen = pygame.display.set_mode((W_px, H_px))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("arialrounded", 26, bold=True)
        self.hud_font = pygame.font.SysFont("arial", 26, bold=True)
        self.title_font = pygame.font.SysFont('arial', 42, bold=True)
        self.icon_font_small = pygame.font.SysFont('arial', 18, bold=True)
        self.game = game

        # 시작 모달 팝 애니메이션(렌더 전용)
        self.popup_anim = 0.0
        self.popup_anim_speed = 4.0

        self.running = True

    # -------------- 입력 처리 --------------
    def _pos_to_grid(self, mx: int, my: int):
        c = (mx - PAD_X) // (CELL + GAP)
        r = (my - PAD_TOP) // (CELL + GAP)
        return int(r), int(c)

    def _hit_circle(self, mx, my, cx, cy, radius) -> bool:
        dx = mx - cx; dy = my - cy
        return dx*dx + dy*dy <= radius*radius

    # -------------- 메인 루프 --------------
    def run(self):
        try:
            while self.running:
                dt = self.clock.tick(FPS) / 1000.0

                # 업데이트(로직)
                self.game.update(dt)

                # 입력 이벤트
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                        break

                    gs = self.game.state

                    if gs == 'start':
                        # 시작/종료 버튼 클릭
                        center_x = self.screen.get_width() // 2
                        center_y = self.screen.get_height() // 2
                        start_modal_x = center_x - MODAL_W // 2
                        start_modal_y = center_y - MODAL_H // 2
                        start_start_center = (start_modal_x + (MODAL_W // 2 - 140), start_modal_y + 210)
                        start_quit_center  = (start_modal_x + (MODAL_W // 2 + 140), start_modal_y + 210)

                        cur_radius = int(BTN_RADIUS * (0.9 + 0.1 * self.popup_anim))

                        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                            mx, my = event.pos
                            if self._hit_circle(mx, my, *start_start_center, cur_radius):
                                self.game.start_new()
                                self.popup_anim = 0.0
                            elif self._hit_circle(mx, my, *start_quit_center, cur_radius):
                                self.running = False

                    elif gs == 'playing':
                        # HUD 버튼 (Retry/Home)
                        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                            mx, my = event.pos
                            retry_center = (self.screen.get_width() - 120, 40)
                            home_center  = (self.screen.get_width() -  40, 40)
                            if self._hit_circle(mx, my, *retry_center, IN_ICON_RADIUS):
                                self.game.retry()
                                continue
                            if self._hit_circle(mx, my, *home_center, IN_ICON_RADIUS):
                                self.game.to_start()
                                continue

                        # 그리드 드래그 선택
                        if self.game.pop_state == "idle":  # 팝 중엔 선택 잠금
                            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                                r, c = self._pos_to_grid(*event.pos)
                                self.game.begin_selection(r, c)
                            elif event.type == pygame.MOUSEMOTION and self.game.selecting:
                                r, c = self._pos_to_grid(*event.pos)
                                self.game.update_selection(r, c)
                            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.game.selecting:
                                self.game.end_selection()

                    elif gs == 'gameover':
                        # 게임오버 모달 버튼 (Retry/Home/Quit)
                        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                            mx, my = event.pos
                            center_x = self.screen.get_width() // 2
                            center_y = self.screen.get_height() // 2
                            modal_x = center_x - MODAL_W // 2
                            modal_y = center_y - MODAL_H // 2
                            go_retry_center = (modal_x + (MODAL_W // 2 - 140), modal_y + 210)
                            go_home_center  = (modal_x + (MODAL_W // 2),       modal_y + 210)
                            go_quit_center  = (modal_x + (MODAL_W // 2 + 140), modal_y + 210)

                            if self._hit_circle(mx, my, *go_retry_center, BTN_RADIUS):
                                self.game.retry()
                                continue
                            if self._hit_circle(mx, my, *go_home_center, BTN_RADIUS):
                                self.game.to_start()
                                continue
                            if self._hit_circle(mx, my, *go_quit_center, BTN_RADIUS):
                                self.running = False
                                continue

                # 렌더
                self.draw()
        finally:
            # 정상 종료 시 워커 종료
            self.game.shutdown()
            pygame.quit()

    # -------------- 렌더 --------------
    def draw(self):
        screen = self.screen
        screen.fill(BG)

        # HUD (항상 보임; playing일 때만 인터랙션)
        score_to_show = self.game.score()
        remain = int(max(0, self.game.remain_time))
        ttxt = self.hud_font.render(f"Time: {remain}", True, INK)
        screen.blit(ttxt, (PAD_X, 18))
        bar_w = 380
        pygame.draw.rect(screen, GRAY, (PAD_X+120, 26, bar_w, 16), border_radius=8)
        filled = int(bar_w * (max(0.0, self.game.remain_time) / TIME_LIMIT)) if TIME_LIMIT > 0 else 0
        pygame.draw.rect(screen, GOLD, (PAD_X+120, 26, filled, 16), border_radius=8)
        stxt = self.hud_font.render(f"Score: {score_to_show}", True, INK)
        screen.blit(stxt, (PAD_X + 120 + bar_w + 30, 18))
        draw_icon_button(screen, (screen.get_width() - 120, 40), IN_ICON_RADIUS, GOLD, icon_text='R', icon_font=self.icon_font_small)
        draw_icon_button(screen, (screen.get_width() -  40, 40), IN_ICON_RADIUS, LEAF, icon_text='H', icon_font=self.icon_font_small)

        # Grid
        grid = self.game.current_grid()
        for r in range(H):
            for c in range(W):
                x,y = grid_to_px(r,c)
                pygame.draw.rect(screen, PANEL, (x,y,CELL,CELL), border_radius=12)
                val = grid[r][c]
                draw_apple(screen, self.font, x, y, val)

        # Manual selection overlay
        sel = self.game.selection_overlay()
        if sel is not None:
            r1, c1, r2, c2, valid = sel
            x1,y1 = grid_to_px(r1, c1)
            x2,y2 = grid_to_px(r2, c2)
            border = pygame.Rect(x1-3, y1-3, (x2-x1)+CELL+6, (y2-y1)+CELL+6)
            pygame.draw.rect(screen, (RED if valid else YEL), border, width=4, border_radius=12)

        # Bot highlight overlay
        bh = self.game.bot_highlight_rect()
        if bh is not None:
            r1, c1, r2, c2 = bh
            x1,y1 = grid_to_px(r1, c1)
            x2,y2 = grid_to_px(r2, c2)
            border = pygame.Rect(x1-3, y1-3, (x2-x1)+CELL+6, (y2-y1)+CELL+6)
            pygame.draw.rect(screen, RED, border, width=4, border_radius=12)

        # Pop animation layer
        pe = self.game.pop_effect()
        if pe is not None:
            scale, alpha, removed_cells = pe
            for (r,c,val) in removed_cells:
                x,y = grid_to_px(r,c)
                draw_apple(screen, self.font, x, y, val, scale=scale, alpha=alpha)

        # --------- START modal ----------
        if self.game.state == 'start':
            # 팝업 애니메이션(렌더 전용)
            if self.popup_anim < 1.0:
                self.popup_anim = min(1.0, self.popup_anim + (self.popup_anim_speed * self.clock.get_time()/1000.0))
            cur_radius = int(BTN_RADIUS * (0.9 + 0.1 * self.popup_anim))

            center_x = screen.get_width() // 2
            center_y = screen.get_height() // 2
            start_modal_x = center_x - MODAL_W // 2
            start_modal_y = center_y - MODAL_H // 2

            # shadow
            shadow = pygame.Surface((MODAL_W+SHADOW_PAD*2, MODAL_H+SHADOW_PAD*2), pygame.SRCALPHA)
            pygame.draw.rect(shadow, (0,0,0,60), shadow.get_rect(), border_radius=MODAL_RADIUS+2)
            screen.blit(shadow, (start_modal_x - SHADOW_PAD, start_modal_y - SHADOW_PAD))
            # card
            modal = pygame.Surface((MODAL_W, MODAL_H), pygame.SRCALPHA)
            pygame.draw.rect(modal, (255,255,255,CARD_ALPHA), modal.get_rect(), border_radius=MODAL_RADIUS)
            title = self.title_font.render('Apple Game', True, INK)
            modal.blit(title, (MODAL_W//2 - title.get_width()//2, 56))
            icon_font = pygame.font.SysFont('arial', max(20, int(cur_radius*0.9)), bold=True)
            draw_icon_button(modal, (MODAL_W//2 - 140, 210), cur_radius, LEAF, icon_text='S', icon_font=icon_font)
            draw_icon_button(modal, (MODAL_W//2 + 140, 210), cur_radius, INK,  icon_text='Q', icon_font=icon_font)
            screen.blit(modal, (start_modal_x, start_modal_y))

        # --------- GAMEOVER modal ----------
        if self.game.state == 'gameover':
            center_x = screen.get_width() // 2
            center_y = screen.get_height() // 2
            modal_x = center_x - MODAL_W // 2
            modal_y = center_y - MODAL_H // 2

            shadow = pygame.Surface((MODAL_W+SHADOW_PAD*2, MODAL_H+SHADOW_PAD*2), pygame.SRCALPHA)
            pygame.draw.rect(shadow, (0,0,0,60), shadow.get_rect(), border_radius=MODAL_RADIUS+2)
            screen.blit(shadow, (modal_x - SHADOW_PAD, modal_y - SHADOW_PAD))

            modal = pygame.Surface((MODAL_W, MODAL_H), pygame.SRCALPHA)
            pygame.draw.rect(modal, (255,255,255,CARD_ALPHA), modal.get_rect(), border_radius=MODAL_RADIUS)

            title = self.title_font.render('Game Over', True, INK)
            modal.blit(title, (MODAL_W//2 - title.get_width()//2, 32))

            score_big = pygame.font.SysFont('arialrounded', 56, bold=True)
            score_surf = score_big.render(str(self.game.score()), True, (0, 0, 0))
            modal.blit(score_surf, (MODAL_W // 2 - score_surf.get_width() // 2, 110 - score_surf.get_height() // 2))

            icon_font_go = pygame.font.SysFont('arial', max(18, BTN_RADIUS), bold=True)
            draw_icon_button(modal, (MODAL_W // 2 - 140, 210), BTN_RADIUS, GOLD, icon_text='R', icon_font=icon_font_go)
            draw_icon_button(modal, (MODAL_W // 2,       210), BTN_RADIUS, LEAF, icon_text='H', icon_font=icon_font_go)
            draw_icon_button(modal, (MODAL_W // 2 + 140, 210), BTN_RADIUS, INK,  icon_text='Q', icon_font=icon_font_go)

            screen.blit(modal, (modal_x, modal_y))

        pygame.display.flip()


# -------------- entrypoint --------------
if __name__ == "__main__":
    gui = GUI(Game())
    gui.run()
