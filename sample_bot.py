import random

class MyBot:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def nextmove(self, board):
        moves = board.find_all_valid_moves()
        m = self.rng.choice(moves)
        rect = m[0]
        return rect

    def gameover(self, board):
        return not bool(board.find_all_valid_moves())
