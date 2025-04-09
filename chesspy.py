#!/usr/bin/env python3
import curses
import chess
import chess.engine
import chess.syzygy
import sys
import io
import time

###############################################################################
# KONFIGURACJA
###############################################################################

ENGINE_PATH = "./stockfish-ubuntu-x86-64-avx2"  # Ścieżka/nazwa silnika UCI
TB_PATH = None             # Ścieżka do tablic Syzygy (lub None)
MULTI_PV = 3               # Ile wariantów pokazujemy
REFRESH_INTERVAL = 0.5     # Co ile sekund odświeżamy ekran i pobieramy zdarzenia
ANALYSIS_TIME = 0.3        # Limit czasu na każdą krótką analizę (sekundy)
USE_SYZYGY_AFTER_MOVE = True

###############################################################################
# Mapa typów figur -> odpowiednie symbole unicode
###############################################################################
UNICODE_PIECES = {
    (chess.PAWN, True): "♙",
    (chess.KNIGHT, True): "♘",
    (chess.BISHOP, True): "♗",
    (chess.ROOK, True): "♖",
    (chess.QUEEN, True): "♕",
    (chess.KING, True): "♔",
    (chess.PAWN, False): "♟",
    (chess.KNIGHT, False): "♞",
    (chess.BISHOP, False): "♝",
    (chess.ROOK, False): "♜",
    (chess.QUEEN, False): "♛",
    (chess.KING, False): "♚",
}

def piece_to_unicode(piece: chess.Piece) -> str:
    """
    Zwraca odpowiedni znak unicode dla danej figury (P, N, B, R, Q, K w wersji białej/czarnej).
    """
    return UNICODE_PIECES.get((piece.piece_type, piece.color), "?")

###############################################################################
# FUNKCJE POMOCNICZE
###############################################################################

def generate_thermometer(cp: int, cp_range: int = 300, length: int = 15) -> str:
    """
    Prosta wizualizacja 'termometru' (ASCII) dla oceny w centipunktach.
    """
    cp = max(-cp_range, min(cp, cp_range))
    center = length // 2
    offset = int(round((cp / cp_range) * center))
    marker = center + offset
    bar = ""
    for i in range(length):
        bar += "█" if i == marker else "-"
    return "[" + bar + "]"

def board_to_unicode_str(board: chess.Board) -> str:
    """
    Zwraca widok szachownicy w postaci 8 linii, każda po 8 pól,
    używając znaków unicode do figur. Puste pola zastępowane kropką.
    """
    lines = []
    for rank in reversed(range(8)):  # od 7 do 0
        row_str = ""
        for file in range(8):
            square = chess.square(file, rank)
            piece = board.piece_at(square)
            if piece is not None:
                row_str += piece_to_unicode(piece) + " "
            else:
                row_str += ". "
        lines.append(row_str.rstrip())
    return "\n".join(lines)

def parse_move(user_input: str, board: chess.Board) -> chess.Move:
    """
    Próbuje sparsować ruch (najpierw UCI, potem SAN).
    Gdy występuje np. "1. e4", odcina numerację.
    """
    s = user_input.strip()
    if '.' in s:
        tokens = s.split()
        if tokens:
            s = tokens[-1]
    # Najpierw UCI
    try:
        mv = board.parse_uci(s)
        return mv
    except:
        pass
    # Potem SAN
    return board.parse_san(s)

###############################################################################
# GŁÓWNA KLASA "APP" - ZARZĄDZA CAŁĄ LOGIKĄ
###############################################################################

class ChessApp:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.board = chess.Board()
        self.engine = None
        self.tb_path = TB_PATH

        self.human_color = chess.WHITE
        self.move_count = 1
        self.last_move_white = "-"
        self.last_move_black = "-"
        self.input_line = ""

        # Przechowywana ocena i warianty
        self.best_eval_str = "---"
        self.analysis_variants = []
        self.status_msg = ""

    def init_engine(self):
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
        except Exception as e:
            self.status_msg = f"Błąd uruchomienia silnika: {e}"
            self.engine = None

    def close_engine(self):
        if self.engine:
            try:
                self.engine.quit()
            except:
                pass
            self.engine = None

    def synergy_check(self):
        """
        Jeśli TB_PATH i ≤7 figur -> sprawdzamy ocenę z tablic Syzygy (WDL).
        """
        if self.tb_path and len(self.board.piece_map()) <= 7:
            try:
                with chess.syzygy.open_tablebase(self.tb_path) as tablebase:
                    wdl = tablebase.probe_wdl(self.board)
                    self.status_msg = f"(Syzygy) WDL = {wdl}"
            except Exception as e:
                self.status_msg = f"Błąd Syzygy: {e}"

    def do_move(self, mv: chess.Move):
        """
        Wykonuje ruch mv na boardzie, aktualizuje last_move, move_count, itp.
        """
        # Najpierw zachowaj SAN (jeszcze w starej pozycji!)
        move_san = self.board.san(mv)
        self.board.push(mv)

        if self.board.turn == chess.WHITE:
            self.last_move_black = move_san
            self.move_count += 1
        else:
            self.last_move_white = move_san

        if USE_SYZYGY_AFTER_MOVE:
            self.synergy_check()

    def handle_player_move(self, user_input: str):
        """
        Parsowanie i wykonywanie ruchu wpisanego przez gracza.
        """
        try:
            mv = parse_move(user_input, self.board)
            if mv not in self.board.legal_moves:
                self.status_msg = "Nielegalny ruch."
            else:
                self.do_move(mv)
                self.status_msg = ""
        except Exception as e:
            self.status_msg = f"Błąd ruchu: {e}"

    def handle_engine_move(self):
        """
        Ruch silnika.
        """
        if not self.engine:
            return
        try:
            # Głębokość docelowa np. 10
            result = self.engine.play(self.board, chess.engine.Limit(depth=10))
            move_san = self.board.san(result.move)
            self.do_move(result.move)
            self.status_msg = f"Silnik (ruch): {move_san}"
        except Exception as e:
            self.status_msg = f"Błąd silnika: {e}"

    def do_continuous_analysis(self):
        """
        *Krótka* analiza z limitem czasowym (ANALYSIS_TIME).
        Zwraca listę info (dla multiPV=MULTI_PV).
        """
        if not self.engine:
            return
        try:
            infos = self.engine.analyse(
                self.board,
                limit=chess.engine.Limit(time=ANALYSIS_TIME),
                multipv=MULTI_PV
            )
            if isinstance(infos, dict):
                infos = [infos]

            self.analysis_variants = []
            for inf in infos:
                score = inf["score"].white()
                if score.is_mate():
                    score_str = f"Mate in {score.mate()}"
                    cp_val = 0
                else:
                    cp_val = score.score()
                    sign = "+" if cp_val >= 0 else ""
                    score_str = f"{sign}{cp_val/100:.2f}"
                pv = inf.get("pv", [])
                temp_board = self.board.copy()
                moves_san = []
                for mv in pv:
                    try:
                        san_mv = temp_board.san(mv)
                        temp_board.push(mv)
                        moves_san.append(san_mv)
                    except:
                        moves_san.append("???")
                        break
                var_str = " ".join(moves_san)[:60]  # skróć
                self.analysis_variants.append((cp_val, score_str, var_str))

            if self.analysis_variants:
                cp_val = self.analysis_variants[0][0]
                therm = generate_thermometer(cp_val)
                self.best_eval_str = f"{self.analysis_variants[0][1]} {therm}"
            else:
                self.best_eval_str = "---"

        except Exception as e:
            self.status_msg = f"Błąd analizy: {e}"

    def draw_screen(self):
        """
        Rysuje cały "ekran" curses.
        """
        self.stdscr.clear()
        # Linia nagłówkowa
        line1 = f"[Ruch: {self.move_count}]  Białe: {self.last_move_white} | Czarne: {self.last_move_black}"
        self.stdscr.addstr(0, 0, line1)

        # Szachownica (unicode)
        board_str = board_to_unicode_str(self.board)
        board_lines = board_str.split("\n")
        for i, ln in enumerate(board_lines):
            self.stdscr.addstr(2 + i, 0, ln)

        # Ocena + warianty
        self.stdscr.addstr(2, 25, f"Eval: {self.best_eval_str}")
        row = 3
        for i, (cp_val, sc, var_str) in enumerate(self.analysis_variants):
            if i == 0:
                continue  # pierwszy wariant jest w best_eval_str
            self.stdscr.addstr(row, 25, f"{sc}  {var_str}")
            row += 1

        # Status/błędy
        self.stdscr.addstr(12, 0, f"{self.status_msg:80s}")

        # Input
        self.stdscr.addstr(14, 0, "Twój ruch ('exit' aby zakończyć): ")
        self.stdscr.addstr(15, 0, "> " + self.input_line[:50])

        self.stdscr.refresh()

    def main_loop(self):
        """
        Główna pętla: dopóki partia się nie skończy, pobiera input, robi krótką analizę, itd.
        """
        self.draw_screen()
        while not self.board.is_game_over():
            # Ruch silnika (jeśli to nie kolej gracza)
            if self.board.turn != self.human_color:
                self.handle_engine_move()
                self.draw_screen()

            # W ciągu REFRESH_INTERVAL zbieramy input i rysujemy
            start_t = time.time()
            while time.time() - start_t < REFRESH_INTERVAL:
                self.stdscr.nodelay(True)
                try:
                    ch = self.stdscr.getch()
                except:
                    ch = -1
                self.stdscr.nodelay(False)

                if ch == -1:
                    time.sleep(0.01)
                    continue
                elif ch in [curses.KEY_BACKSPACE, 127, 8]:
                    if self.input_line:
                        self.input_line = self.input_line[:-1]
                elif ch == curses.KEY_ENTER or ch in [10, 13]:
                    cmd = self.input_line.strip().lower()
                    if cmd == "exit":
                        return
                    else:
                        self.handle_player_move(self.input_line)
                    self.input_line = ""
                else:
                    if 32 <= ch < 127:
                        self.input_line += chr(ch)

                self.draw_screen()

            # Po upływie REFRESH_INTERVAL wykonujemy krótką analizę
            if not self.board.is_game_over():
                self.do_continuous_analysis()
                self.draw_screen()

        # Gdy partia się skończy
        self.draw_screen()
        time.sleep(1.0)

    def run(self):
        self.init_engine()
        self.draw_screen()
        self.main_loop()
        self.close_engine()
        self.stdscr.clear()
        self.stdscr.addstr(0, 0, f"Koniec gry. Wynik: {self.board.result()}")
        self.stdscr.addstr(1, 0, "Naciśnij dowolny klawisz, aby wyjść.")
        self.stdscr.refresh()
        self.stdscr.getch()

###############################################################################
# FUNKCJA STARTOWA CURSES
###############################################################################

def curses_main(stdscr):
    curses.curs_set(0)  # Wyłączamy kursor
    stdscr.keypad(True)
    app = ChessApp(stdscr)
    app.run()

def main():
    curses.wrapper(curses_main)

if __name__ == "__main__":
    main()

