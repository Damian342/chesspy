#!/usr/bin/env python3
import os
import sys
import time
import pygame
import chess
import chess.engine
import chess.pgn
import requests
import io
import socket
import threading
import random

# Inicjalizacja Pygame i konfiguracja okna
pygame.init()
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Chess Online + Silnik UCI + Gra na Serwerze")
clock = pygame.time.Clock()
FONT = pygame.font.SysFont("Arial", 24)

# Globalne zmienne i stałe
piece_images = {}
move_history = []

# Stałe do rysowania szachownicy
SQUARE_SIZE = 64
BOARD_WIDTH = 8 * SQUARE_SIZE
BOARD_HEIGHT = 8 * SQUARE_SIZE
DEFAULT_OFFSET_X = (WIDTH - BOARD_WIDTH) // 2
DEFAULT_OFFSET_Y = (HEIGHT - BOARD_HEIGHT) // 2

# Konfiguracja API Lichess
LICHESS_API_URL = "https://lichess.org/api"
PUZZLE_API_URL = f"{LICHESS_API_URL}/puzzle/next"

# Konfiguracja silnika UCI
ENGINE_PATH = "./stockfish-ubuntu-x86-64-avx2"  # Upewnij się, że ścieżka jest poprawna
ANALYSIS_TIME = 0.3
ENGINE_DEPTH = 15

# Konfiguracja gry online (serwer)
SERVER_IP = "13.38.13.177"
SERVER_PORT = 5555
client_socket = None
username = ""
password = ""

# ============================================================================
# Funkcje ogólne: ładowanie obrazków, rysowanie szachownicy, termometru itp.
# ============================================================================

def load_piece_images():
    """Ładuje obrazki figur ze wskazanego folderu 'pieces'."""
    pieces = ['wp', 'wr', 'wn', 'wb', 'wq', 'wk',
              'bp', 'br', 'bn', 'bb', 'bq', 'bk']
    for p in pieces:
        path = os.path.join("pieces", f"{p}.png")
        try:
            image = pygame.image.load(path)
            piece_images[p] = pygame.transform.scale(image, (SQUARE_SIZE, SQUARE_SIZE))
        except Exception as e:
            print(f"Nie można załadować obrazka {path}: {e}")

def draw_board(board, offset_x=DEFAULT_OFFSET_X, offset_y=DEFAULT_OFFSET_Y, square_size=SQUARE_SIZE):
    """Rysuje szachownicę i figury na zadanym obiekcie board."""
    colors = [(240, 217, 181), (181, 136, 99)]
    for rank in range(8):
        for file in range(8):
            rect = pygame.Rect(offset_x + file * square_size, offset_y + rank * square_size,
                               square_size, square_size)
            color = colors[(rank + file) % 2]
            pygame.draw.rect(screen, color, rect)
            square = chess.square(file, 7 - rank)
            piece = board.piece_at(square)
            if piece:
                symbol = piece.symbol().lower()
                color_prefix = 'w' if piece.color == chess.WHITE else 'b'
                img = piece_images.get(color_prefix + symbol)
                if img:
                    img_rect = img.get_rect(center=rect.center)
                    screen.blit(img, img_rect)

def draw_thermometer(score):
    """Rysuje termometr odzwierciedlający wartość oceny (score w skali -1 do 1)."""
    rect = pygame.Rect(WIDTH - 150, 50, 20, 300)
    fill_height = int((score + 1) * 150)  # przekształcamy zakres na 0...300 pikseli
    pygame.draw.rect(screen, (255, 0, 0), rect)
    pygame.draw.rect(screen, (0, 255, 0), pygame.Rect(WIDTH - 150, 50 + (300 - fill_height), 20, fill_height))

def get_analysis(engine_wrapper, board):
    """Pobiera analizę z silnika i wyświetla wynik wraz z termometrem."""
    evaluation_text = engine_wrapper.get_evaluation(board, ANALYSIS_TIME)
    eval_surface = FONT.render(f"Eval: {evaluation_text}", True, (255, 255, 255))
    screen.blit(eval_surface, (50, 20))
    if evaluation_text.startswith("cp"):
        try:
            cp_val = int(evaluation_text.split(" ")[1])
            draw_thermometer(cp_val / 100)  # przeskalowanie do zakresu -1 do 1
        except Exception as e:
            print("Błąd parsowania oceny:", e)
    pygame.display.flip()

def get_lichess_puzzle():
    """Pobiera zadanie szachowe z API Lichess."""
    try:
        response = requests.get(PUZZLE_API_URL)
        if response.status_code == 200:
            puzzle = response.json()
            return puzzle
        else:
            return None
    except Exception as e:
        print("Błąd pobierania zadania z Lichess:", e)
        return None

# ============================================================================
# Klasa opakowania dla silnika UCI (Stockfish)
# ============================================================================

class EngineWrapper:
    def __init__(self, engine_path):
        self.engine_path = engine_path
        self.engine = None

    def start_engine(self):
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
        except Exception as e:
            print(f"Błąd uruchomienia silnika: {e}")
            self.engine = None

    def stop_engine(self):
        if self.engine:
            self.engine.quit()
            self.engine = None

    def get_move(self, board: chess.Board, depth=10):
        if not self.engine:
            return None
        try:
            limit = chess.engine.Limit(depth=depth)
            result = self.engine.play(board, limit)
            return result.move
        except Exception as e:
            print(f"Błąd silnika: {e}")
            return None

    def get_evaluation(self, board: chess.Board, analysis_time=0.5):
        if not self.engine:
            return "Brak silnika"
        try:
            info = self.engine.analyse(board, limit=chess.engine.Limit(time=analysis_time))
            score = info["score"].relative
            if score.is_mate():
                return f"Mate in {score.mate()}"
            else:
                return f"cp {score.score()}"
        except Exception as e:
            return f"Błąd analizy: {e}"

# ============================================================================
# Funkcje trybu gry: gra z silnikiem, zadania szachowe, konwersja PGN → FEN
# ============================================================================

def play_against_ai():
    """Gra człowieka z silnikiem UCI (Stockfish)."""
    engine_wrapper = EngineWrapper(ENGINE_PATH)
    engine_wrapper.start_engine()

    board = chess.Board()
    selected_square = None
    move_history.clear()

    running = True
    while running:
        screen.fill((30, 30, 30))
        draw_board(board)
        get_analysis(engine_wrapper, board)

        # Wyświetlenie historii ruchów
        move_text = FONT.render("Ruchy: " + " ".join([move.uci() for move in move_history]), True, (255, 255, 255))
        screen.blit(move_text, (50, HEIGHT - 40))
        pygame.display.flip()

        if board.is_game_over():
            result = board.result()
            print("Gra zakończona:", result)
            time.sleep(3)
            break

        if board.turn == chess.WHITE:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    x, y = event.pos
                    file = (x - DEFAULT_OFFSET_X) // SQUARE_SIZE
                    rank = 7 - ((y - DEFAULT_OFFSET_Y) // SQUARE_SIZE)
                    if 0 <= file < 8 and 0 <= rank < 8:
                        square = chess.square(file, rank)
                        if selected_square is None:
                            if board.piece_at(square) and board.piece_at(square).color == chess.WHITE:
                                selected_square = square
                        else:
                            move = chess.Move(selected_square, square)
                            if move in board.legal_moves:
                                board.push(move)
                                move_history.append(move)
                                selected_square = None
                            else:
                                error_text = FONT.render("Błędny ruch! Spróbuj ponownie.", True, (255, 0, 0))
                                screen.blit(error_text, (WIDTH // 2 - 100, HEIGHT - 50))
                                pygame.display.flip()
                                time.sleep(1)
                                selected_square = None
        else:
            time.sleep(0.5)
            engine_move = engine_wrapper.get_move(board, ENGINE_DEPTH)
            if engine_move and engine_move in board.legal_moves:
                board.push(engine_move)
                move_history.append(engine_move)
            else:
                mv = random.choice(list(board.legal_moves))
                board.push(mv)
                move_history.append(mv)

        clock.tick(30)

    engine_wrapper.stop_engine()

def pgn_to_fen(pgn):
    """Konwertuje zapis PGN do pozycji FEN."""
    pgn_io = io.StringIO(pgn)
    game = chess.pgn.read_game(pgn_io)
    board = game.board()
    for move in game.mainline_moves():
        board.push(move)
    return board.fen()

def draw_puzzle(puzzle):
    """Wyświetla zadanie szachowe z Lichess oraz sprawdza ruchy rozwiązania."""
    if not puzzle:
        print("Brak zadania do wyświetlenia")
        return

    pgn = puzzle['game']['pgn']
    fen = pgn_to_fen(pgn)
    board = chess.Board(fen)
    screen.fill((30, 30, 30))
    draw_board(board)
    pygame.display.flip()

    solution_moves = puzzle['puzzle']['solution']
    solution_index = 0

    selected_square = None
    running_puzzle = True

    while running_puzzle:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                x, y = event.pos
                file = (x - DEFAULT_OFFSET_X) // SQUARE_SIZE
                rank = 7 - ((y - DEFAULT_OFFSET_Y) // SQUARE_SIZE)
                if 0 <= file < 8 and 0 <= rank < 8:
                    square = chess.square(file, rank)
                    if selected_square is None:
                        piece = board.piece_at(square)
                        if piece and piece.color == board.turn:
                            selected_square = square
                    else:
                        move = chess.Move(selected_square, square)
                        if move in board.legal_moves:
                            if solution_index < len(solution_moves):
                                correct_move_str = solution_moves[solution_index]
                                correct_move = chess.Move.from_uci(correct_move_str)
                                if move == correct_move:
                                    board.push(move)
                                    draw_board(board)
                                    pygame.display.flip()
                                    solution_index += 1
                                    selected_square = None
                                    pygame.time.wait(500)
                                    if solution_index < len(solution_moves):
                                        enemy_move_str = solution_moves[solution_index]
                                        enemy_move = chess.Move.from_uci(enemy_move_str)
                                        if enemy_move in board.legal_moves:
                                            board.push(enemy_move)
                                            solution_index += 1
                                            draw_board(board)
                                            pygame.display.flip()
                                        else:
                                            print("Błąd: nielegalny ruch przeciwnika", enemy_move_str)
                                            running_puzzle = False
                                    else:
                                        print("✅ Zadanie ukończone! Gratulacje!")
                                        running_puzzle = False
                                else:
                                    print(f"❌ Niepoprawny ruch! Oczekiwany ruch: {correct_move_str}")
                                    selected_square = None
                            else:
                                print("Zadanie już zakończone.")
                                running_puzzle = False
                        else:
                            selected_square = None

        clock.tick(30)

# ============================================================================
# Funkcje trybu gry online – komunikacja z serwerem, lobby, rozgrywka
# ============================================================================

def send_to_server(data):
    """Wysyła dane do serwera i odbiera odpowiedź."""
    global client_socket
    try:
        client_socket.send(data.encode())
        return client_socket.recv(2048).decode()
    except Exception as e:
        print("Błąd komunikacji z serwerem:", e)
        return "ERROR|Błąd komunikacji"

def login_screen():
    """Logowanie do serwera – wykorzystujemy przykładowe dane."""
    global username, password
    username = "Buldozer"
    password = "123"
    response = send_to_server(f"LOGIN|{username}|{password}")
    print("Odpowiedź serwera na login:", response)

def launch_online_game(color, opponent):
    """
    Rozpoczyna grę online. Tworzy wątek odbierający ruchy przeciwnika
    oraz główną pętlę gry.
    """
    board = chess.Board()
    is_white = color.lower() == "white"
    selected_square = None
    running = True

    def receive_thread():
        nonlocal board
        while True:
            try:
                data = client_socket.recv(1024).decode()
                if data.startswith("OPPONENT_MOVE"):
                    move = data.split("|")[1]
                    board.push_uci(move)
            except Exception as e:
                print("Błąd odbierania danych:", e)
                break

    threading.Thread(target=receive_thread, daemon=True).start()

    while running:
        screen.fill((30, 30, 30))
        draw_board(board)
        pygame.display.flip()

        if board.is_game_over():
            result = board.result()
            send_to_server(f"GAME_OVER|{username}|{opponent}|{result}")
            print("Gra zakończona:", result)
            time.sleep(3)
            break

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

            elif event.type == pygame.MOUSEBUTTONDOWN:
                # Zezwalamy na ruch, jeśli to nasza tura
                if (board.turn == chess.WHITE and is_white) or (board.turn == chess.BLACK and not is_white):
                    x, y = event.pos
                    file = (x - DEFAULT_OFFSET_X) // SQUARE_SIZE
                    rank = 7 - ((y - DEFAULT_OFFSET_Y) // SQUARE_SIZE)
                    if 0 <= file < 8 and 0 <= rank < 8:
                        square = chess.square(file, rank)
                        if selected_square is None:
                            if board.piece_at(square) and board.piece_at(square).color == board.turn:
                                selected_square = square
                        else:
                            move = chess.Move(selected_square, square)
                            if move in board.legal_moves:
                                board.push(move)
                                send_to_server(f"MOVE|{opponent}|{move.uci()}")
                            selected_square = None
        clock.tick(30)

def wait_for_match():
    """
    Czeka na wiadomość serwera o znalezieniu przeciwnika.
    Dla celów demonstracyjnych symulujemy oczekiwanie.
    """
    print("Oczekiwanie na przeciwnika...")
    time.sleep(2)  # symulacja oczekiwania
    # Symulujemy: otrzymujemy kolor i nazwę przeciwnika
    return "white", "Przeciwnik1"

def choose_opponent():
    """Menu wyboru przeciwnika online lub gry z botem."""
    while True:
        screen.fill((20, 20, 20))
        title = FONT.render("Wybierz przeciwnika", True, (255, 255, 255))
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 50))
        pygame.draw.rect(screen, (100, 100, 250), (250, 120, 300, 40))
        screen.blit(FONT.render("Losowy gracz online", True, (0, 0, 0)), (270, 125))
        pygame.draw.rect(screen, (100, 200, 100), (250, 180, 300, 40))
        screen.blit(FONT.render("Zagraj z botem (AI)", True, (0, 0, 0)), (270, 185))
        pygame.draw.rect(screen, (200, 100, 100), (250, 240, 300, 40))
        screen.blit(FONT.render("Anuluj", True, (0, 0, 0)), (360, 245))
        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.MOUSEBUTTONDOWN:
                x, y = event.pos
                if 250 <= x <= 550:
                    if 120 <= y <= 160:
                        send_to_server("START_MATCH")
                        color, opponent = wait_for_match()
                        launch_online_game(color, opponent)
                        return
                    elif 180 <= y <= 220:
                        play_against_ai()  # Gra offline z botem
                        return
                    elif 240 <= y <= 280:
                        return
        clock.tick(30)

def stats_screen():
    """Tymczasowy ekran statystyk."""
    screen.fill((20, 20, 20))
    stat_text = FONT.render("Statystyki - niezaimplementowane", True, (255, 255, 255))
    screen.blit(stat_text, (WIDTH//2 - stat_text.get_width()//2, HEIGHT//2))
    pygame.display.flip()
    time.sleep(2)

def draw_lobby():
    """Rysuje lobby gracza online."""
    screen.fill((20, 20, 20))
    welcome_text = FONT.render(f"Witaj, {username}!", True, (255, 255, 255))
    screen.blit(welcome_text, (50, 30))
    pygame.draw.rect(screen, (80, 80, 200), (50, 100, 200, 40))
    screen.blit(FONT.render("Szybki mecz online", True, (0, 0, 0)), (55, 110))
    pygame.draw.rect(screen, (80, 200, 100), (50, 160, 200, 40))
    screen.blit(FONT.render("Statystyki", True, (0, 0, 0)), (90, 170))
    pygame.draw.rect(screen, (200, 80, 80), (50, 220, 200, 40))
    screen.blit(FONT.render("Wyloguj", True, (0, 0, 0)), (115, 230))
    pygame.display.flip()

def lobby_screen():
    """Menu lobby – wybór opcji w trybie online."""
    while True:
        draw_lobby()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.MOUSEBUTTONDOWN:
                x, y = event.pos
                if 50 <= x <= 250:
                    if 100 <= y <= 140:
                        choose_opponent()
                    elif 160 <= y <= 200:
                        stats_screen()
                    elif 220 <= y <= 260:
                        return  # Wylogowanie, powrót do menu głównego
        clock.tick(30)

def online_game_mode():
    """Łączy się z serwerem, loguje użytkownika i przechodzi do lobby."""
    global client_socket
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.connect((SERVER_IP, SERVER_PORT))
    except Exception as e:
        print("Błąd połączenia z serwerem:", e)
        time.sleep(2)
        return

    login_screen()
    lobby_screen()
    client_socket.close()

# ============================================================================
# Menu główne
# ============================================================================

def main_menu():
    while True:
        screen.fill((20, 20, 20))
        title = FONT.render("Wybierz tryb:", True, (255, 255, 255))
        screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 30))
        
        # Definicja przycisków i ich położenie
        buttons = [
            ("Gra z silnikiem", 100),
            ("Analiza partii", 160),
            ("Zadania z Lichess", 220),
            ("Gra na serwerze", 280),
            ("Zakończ", 340)
        ]
        for text, y in buttons:
            rect = pygame.Rect(250, y, 300, 40)
            if text == "Gra z silnikiem":
                color = (100, 100, 250)
            elif text == "Analiza partii":
                color = (100, 200, 100)
            elif text == "Zadania z Lichess":
                color = (200, 100, 100)
            elif text == "Gra na serwerze":
                color = (150, 150, 50)
            elif text == "Zakończ":
                color = (200, 80, 80)
            pygame.draw.rect(screen, color, rect)
            label = FONT.render(text, True, (0, 0, 0))
            screen.blit(label, (rect.x + 10, rect.y + 5))
        
        pygame.display.flip()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.MOUSEBUTTONDOWN:
                x, y = event.pos
                if 250 <= x <= 550:
                    if 100 <= y <= 140:
                        play_against_ai()         # Gra z silnikiem
                    elif 160 <= y <= 200:
                        print("Analiza partii - funkcja niezaimplementowana.")
                        time.sleep(2)
                    elif 220 <= y <= 260:
                        puzzle = get_lichess_puzzle()
                        draw_puzzle(puzzle)         # Zadania z Lichess
                    elif 280 <= y <= 320:
                        online_game_mode()          # Gra na serwerze
                    elif 340 <= y <= 380:
                        pygame.quit()
                        sys.exit()
        clock.tick(30)

def main():
    load_piece_images()
    main_menu()

if __name__ == "__main__":
    main()

