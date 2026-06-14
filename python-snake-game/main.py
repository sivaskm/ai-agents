import os
import sys
import json
import math
import random
import struct
import pygame

# Initialize pygame
pygame.init()

# Constants
WIDTH = 800
HEIGHT = 600
GRID_SIZE = 20
HEADER_HEIGHT = 80
PLAY_WIDTH = WIDTH
PLAY_HEIGHT = HEIGHT - HEADER_HEIGHT
GRID_WIDTH = PLAY_WIDTH // GRID_SIZE   # 40
GRID_HEIGHT = PLAY_HEIGHT // GRID_SIZE # 26

# Colors
BG_COLOR = (11, 15, 26)          # Rich deep dark blue-grey
GRID_COLOR = (18, 24, 38)        # Subtly lighter blue-grey
BORDER_COLOR = (56, 189, 248)    # Neon Sky Blue
SNAKE_HEAD_COLOR = (34, 211, 238)# Bright Neon Cyan
SNAKE_BODY_GLOW = (139, 92, 246) # Neon Violet/Purple
FOOD_COLOR = (244, 63, 94)       # Neon Pink/Red
GOLDEN_FOOD_COLOR = (250, 204, 21)# Neon Gold/Yellow
TEXT_COLOR = (248, 250, 252)     # Off-white

# Setup window
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Neon Snake - Arcade Edition")
clock = pygame.time.Clock()

# Font definitions
try:
    font_large = pygame.font.SysFont("Outfit", 64, bold=True)
    font_medium = pygame.font.SysFont("Outfit", 36, bold=True)
    font_small = pygame.font.SysFont("Outfit", 20)
    font_score = pygame.font.SysFont("Outfit", 24, bold=True)
except:
    # Fallback to default system font
    font_large = pygame.font.Font(None, 74)
    font_medium = pygame.font.Font(None, 40)
    font_small = pygame.font.Font(None, 24)
    font_score = pygame.font.Font(None, 28)

# Audio Configuration
try:
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    sounds_enabled = True
except Exception as e:
    print(f"Mixer initialization failed, sounds disabled: {e}")
    sounds_enabled = False

def generate_beep(frequency, duration, volume=0.2, wave_type='sine'):
    """Generates synth wave bleeps programmatically without external files."""
    if not sounds_enabled or not pygame.mixer.get_init():
        return None
    try:
        sample_rate = pygame.mixer.get_init()[0]
        num_channels = pygame.mixer.get_init()[2]
        
        num_samples = int(sample_rate * duration)
        buffer = bytearray()
        
        for i in range(num_samples):
            t = i / sample_rate
            if wave_type == 'sine':
                val = math.sin(2.0 * math.pi * frequency * t)
            elif wave_type == 'square':
                val = 1.0 if math.sin(2.0 * math.pi * frequency * t) >= 0 else -1.0
            elif wave_type == 'triangle':
                val = 2.0 * abs(2.0 * (t * frequency - math.floor(t * frequency + 0.5))) - 1.0
            else:
                val = math.sin(2.0 * math.pi * frequency * t)
                
            # Click reduction: fade out the last 15% and fade in the first 5%
            fade_out_range = int(sample_rate * 0.02)
            if num_samples - i < fade_out_range:
                val *= (num_samples - i) / fade_out_range
            fade_in_range = int(sample_rate * 0.01)
            if i < fade_in_range:
                val *= i / fade_in_range
                
            int_val = int(val * 32767 * volume)
            packed = struct.pack('<h', int_val)
            for _ in range(num_channels):
                buffer.extend(packed)
                
        return pygame.mixer.Sound(buffer=buffer)
    except Exception as e:
        print(f"Sound generation failed: {e}")
        return None

def generate_sweep(start_freq, end_freq, duration, volume=0.2, wave_type='square'):
    """Generates frequency-swept synth sound (useful for Game Over/Start)."""
    if not sounds_enabled or not pygame.mixer.get_init():
        return None
    try:
        sample_rate = pygame.mixer.get_init()[0]
        num_channels = pygame.mixer.get_init()[2]
        
        num_samples = int(sample_rate * duration)
        buffer = bytearray()
        
        for i in range(num_samples):
            t = i / sample_rate
            # Linear frequency interpolation
            freq = start_freq + (end_freq - start_freq) * (i / num_samples)
            
            if wave_type == 'sine':
                val = math.sin(2.0 * math.pi * freq * t)
            elif wave_type == 'square':
                val = 1.0 if math.sin(2.0 * math.pi * freq * t) >= 0 else -1.0
            elif wave_type == 'triangle':
                val = 2.0 * abs(2.0 * (t * freq - math.floor(t * freq + 0.5))) - 1.0
            else:
                val = math.sin(2.0 * math.pi * freq * t)
                
            # Fade out
            val *= (1.0 - i / num_samples)
            
            int_val = int(val * 32767 * volume)
            packed = struct.pack('<h', int_val)
            for _ in range(num_channels):
                buffer.extend(packed)
                
        return pygame.mixer.Sound(buffer=buffer)
    except Exception as e:
        print(f"Sound sweep generation failed: {e}")
        return None

# Generate retro sounds
sound_eat = generate_beep(659.25, 0.08, volume=0.15, wave_type='triangle') # E5 note
sound_golden_eat = generate_beep(880.00, 0.15, volume=0.20, wave_type='sine') # A5 note
sound_game_over = generate_sweep(280, 70, 0.5, volume=0.25, wave_type='square')
sound_start = generate_sweep(150, 600, 0.35, volume=0.15, wave_type='triangle')
sound_click = generate_beep(523.25, 0.04, volume=0.10, wave_type='sine') # C5 note

# Global Audio Mute Flag
muted = False

def play_sound(sound):
    if sound and not muted:
        sound.play()

# Persistence Highscore File
HIGH_SCORE_FILE = "highscore.json"

def load_high_score():
    try:
        if os.path.exists(HIGH_SCORE_FILE):
            with open(HIGH_SCORE_FILE, "r") as f:
                data = json.load(f)
                return data.get("high_score", 0)
    except Exception as e:
        print(f"Failed to load high score: {e}")
    return 0

def save_high_score(score):
    try:
        with open(HIGH_SCORE_FILE, "w") as f:
            json.dump({"high_score": score}, f)
    except Exception as e:
        print(f"Failed to save high score: {e}")

# Particle System
class Particle:
    def __init__(self, x, y, color):
        self.x = x
        self.y = y
        # Velocity in polar coordinates
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(2, 6)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.color = color
        self.life = 1.0  # Fades down to 0
        self.decay = random.uniform(0.04, 0.08)
        self.size = random.uniform(3, 7)

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.15  # Soft gravity
        self.life -= self.decay

    def draw(self, surface):
        if self.life > 0:
            alpha = int(self.life * 255)
            # Create transparent surface for smooth alpha particle rendering
            p_surf = pygame.Surface((int(self.size * 2), int(self.size * 2)), pygame.SRCALPHA)
            color_with_alpha = (*self.color, alpha)
            pygame.draw.circle(p_surf, color_with_alpha, (int(self.size), int(self.size)), int(self.size))
            surface.blit(p_surf, (int(self.x - self.size), int(self.y - self.size)))

# Neon drawing helpers
def draw_glowing_circle(surface, center, radius, color, glow_intensity=3):
    """Draws a solid circle with a soft outer glowing neon halo."""
    # Render glowing outer halos
    for r in range(radius + glow_intensity * 4, radius, -2):
        dist = r - radius
        # Opacity decays with distance
        alpha = int(255 * (1.0 - dist / (glow_intensity * 4)) * 0.15)
        if alpha <= 0:
            continue
        g_surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(g_surf, (*color, alpha), (r, r), r)
        surface.blit(g_surf, (center[0] - r, center[1] - r))
    # Core solid circle
    pygame.draw.circle(surface, color, center, radius)

def render_glowing_text(text, font, color, glow_color, glow_radius=3):
    """Generates a text surface with a beautiful neon glow outline."""
    text_surf = font.render(text, True, color)
    w, h = text_surf.get_size()
    glow_surf = pygame.Surface((w + glow_radius * 2, h + glow_radius * 2), pygame.SRCALPHA)
    
    # Blit offset versions to build the glow
    for dx in range(-glow_radius, glow_radius + 1):
        for dy in range(-glow_radius, glow_radius + 1):
            if dx == 0 and dy == 0:
                continue
            dist = math.hypot(dx, dy)
            if dist > glow_radius:
                continue
            alpha = int(120 * (1.0 - dist / glow_radius))
            temp_surf = font.render(text, True, (*glow_color, alpha))
            glow_surf.blit(temp_surf, (dx + glow_radius, dy + glow_radius))
            
    # Center the core text
    glow_surf.blit(text_surf, (glow_radius, glow_radius))
    return glow_surf

def draw_grid(surface):
    """Draws a clean subtle grid to helper orient players."""
    for x in range(0, PLAY_WIDTH, GRID_SIZE):
        pygame.draw.line(surface, GRID_COLOR, (x, HEADER_HEIGHT), (x, HEIGHT), 1)
    for y in range(HEADER_HEIGHT, HEIGHT, GRID_SIZE):
        pygame.draw.line(surface, GRID_COLOR, (0, y), (WIDTH, y), 1)

def draw_borders(surface):
    """Draws glowing borders around the playable viewport."""
    pygame.draw.line(surface, (30, 41, 59), (0, HEADER_HEIGHT), (WIDTH, HEADER_HEIGHT), 2)
    
    # Outer boundaries glow
    color = BORDER_COLOR
    for w in range(6, 1, -1):
        alpha = int(255 * (1.0 - w / 6) * 0.12)
        # Top boundary glow
        s = pygame.Surface((WIDTH, w), pygame.SRCALPHA)
        s.fill((*color, alpha))
        surface.blit(s, (0, HEADER_HEIGHT - w // 2))
        # Bottom boundary glow
        s = pygame.Surface((WIDTH, w), pygame.SRCALPHA)
        s.fill((*color, alpha))
        surface.blit(s, (0, HEIGHT - w // 2))
        # Left boundary glow
        s = pygame.Surface((w, PLAY_HEIGHT), pygame.SRCALPHA)
        s.fill((*color, alpha))
        surface.blit(s, (-w // 2, HEADER_HEIGHT))
        # Right boundary glow
        s = pygame.Surface((w, PLAY_HEIGHT), pygame.SRCALPHA)
        s.fill((*color, alpha))
        surface.blit(s, (WIDTH - w // 2, HEADER_HEIGHT))
        
    # Solid clean bounds
    pygame.draw.line(surface, color, (0, HEADER_HEIGHT), (WIDTH, HEADER_HEIGHT), 2)
    pygame.draw.line(surface, color, (0, HEIGHT - 1), (WIDTH, HEIGHT - 1), 2)
    pygame.draw.line(surface, color, (0, HEADER_HEIGHT), (0, HEIGHT), 2)
    pygame.draw.line(surface, color, (WIDTH - 1, HEADER_HEIGHT), (WIDTH - 1, HEIGHT), 2)

class Game:
    def __init__(self):
        self.high_score = load_high_score()
        self.reset_game()
        self.state = "START"
        self.shake_intensity = 0.0
        self.shake_decay = 0.8
        self.muted = False

    def reset_game(self):
        # Initial positions
        self.snake = [
            [20, 13],  # Head
            [19, 13],
            [18, 13]   # Tail
        ]
        self.direction = [1, 0]
        self.next_direction = [1, 0]
        self.score = 0
        self.particles = []
        self.golden_food = None
        self.golden_food_timer = 0
        self.spawn_new_food()
        self.new_high_score_achieved = False

    def spawn_new_food(self):
        # Spawn regular food
        while True:
            pos = [random.randint(0, GRID_WIDTH - 1), random.randint(0, GRID_HEIGHT - 1)]
            if pos not in self.snake:
                self.food = pos
                break
                
        # Roll chance for golden food spawning (15% chance)
        if self.score > 0 and random.random() < 0.15 and not self.golden_food:
            while True:
                pos = [random.randint(0, GRID_WIDTH - 1), random.randint(0, GRID_HEIGHT - 1)]
                if pos not in self.snake and pos != self.food:
                    self.golden_food = pos
                    self.golden_food_timer = 150 # 150 frames to consume
                    break

    def spawn_food_particles(self, pos, color):
        cx = pos[0] * GRID_SIZE + GRID_SIZE // 2
        cy = pos[1] * GRID_SIZE + HEADER_HEIGHT + GRID_SIZE // 2
        for _ in range(16):
            self.particles.append(Particle(cx, cy, color))

    def trigger_screen_shake(self, intensity=10.0):
        self.shake_intensity = intensity

    def update(self):
        # Update particles
        for p in self.particles[:]:
            p.update()
            if p.life <= 0:
                self.particles.remove(p)

        # Decay screen shake
        if self.shake_intensity > 0:
            self.shake_intensity -= self.shake_decay
            if self.shake_intensity < 0:
                self.shake_intensity = 0.0

        if self.state != "PLAYING":
            return

        # Update golden food timer
        if self.golden_food:
            self.golden_food_timer -= 1
            if self.golden_food_timer <= 0:
                self.golden_food = None

        # Lock direction
        self.direction = self.next_direction
        
        # Calculate new head location
        head = self.snake[0]
        new_head = [head[0] + self.direction[0], head[1] + self.direction[1]]

        # Collision detection (Walls)
        if (new_head[0] < 0 or new_head[0] >= GRID_WIDTH or
            new_head[1] < 0 or new_head[1] >= GRID_HEIGHT):
            self.game_over()
            return

        # Collision detection (Self)
        if new_head in self.snake:
            self.game_over()
            return

        # Advance snake head
        self.snake.insert(0, new_head)

        # Eating mechanisms
        ate_something = False

        # Eat Golden Food
        if self.golden_food and new_head == self.golden_food:
            self.score += 30
            self.spawn_food_particles(self.golden_food, GOLDEN_FOOD_COLOR)
            self.golden_food = None
            self.golden_food_timer = 0
            play_sound(sound_golden_eat)
            self.trigger_screen_shake(6.0)
            ate_something = True

        # Eat Normal Food
        if new_head == self.food:
            self.score += 10
            self.spawn_food_particles(self.food, FOOD_COLOR)
            self.spawn_new_food()
            play_sound(sound_eat)
            self.trigger_screen_shake(4.0)
            ate_something = True

        # If didn't eat anything, shrink tail
        if not ate_something:
            self.snake.pop()

        # Update high score real-time
        if self.score > self.high_score:
            self.high_score = self.score
            self.new_high_score_achieved = True

    def game_over(self):
        self.state = "GAME_OVER"
        self.trigger_screen_shake(15.0)
        play_sound(sound_game_over)
        save_high_score(self.high_score)

    def draw(self, surface):
        surface.fill(BG_COLOR)
        draw_grid(surface)
        
        # Draw Food
        # Normal food glow pulsing slightly
        pulse = 1 + int(math.sin(pygame.time.get_ticks() / 100) * 1.5)
        fx = self.food[0] * GRID_SIZE + GRID_SIZE // 2
        fy = self.food[1] * GRID_SIZE + HEADER_HEIGHT + GRID_SIZE // 2
        draw_glowing_circle(surface, (fx, fy), 6 + pulse // 2, FOOD_COLOR, glow_intensity=3)
        
        # Golden Food
        if self.golden_food:
            g_pulse = 1 + int(math.cos(pygame.time.get_ticks() / 80) * 2)
            gx = self.golden_food[0] * GRID_SIZE + GRID_SIZE // 2
            gy = self.golden_food[1] * GRID_SIZE + HEADER_HEIGHT + GRID_SIZE // 2
            draw_glowing_circle(surface, (gx, gy), 7 + g_pulse // 2, GOLDEN_FOOD_COLOR, glow_intensity=4)
            # Golden border/timer ring around it
            timer_ratio = self.golden_food_timer / 150.0
            pygame.draw.circle(surface, GOLDEN_FOOD_COLOR, (gx, gy), int(16 * timer_ratio) + 8, 1)

        # Draw Particles
        for p in self.particles:
            p.draw(surface)

        # Draw Snake
        for idx, (gx, gy) in enumerate(reversed(self.snake)):
            # Convert grid coordinate to screen pixels
            cx = gx * GRID_SIZE + GRID_SIZE // 2
            cy = gy * GRID_SIZE + HEADER_HEIGHT + GRID_SIZE // 2
            
            # Draw tail smaller than head
            pos_ratio = (idx + 1) / len(self.snake)
            radius = int((GRID_SIZE // 2 - 1) * (0.6 + 0.4 * pos_ratio))
            
            # Snake body colors fade from Purple/Violet to Neon Cyan at the head
            seg_color = (
                int(SNAKE_HEAD_COLOR[0] * pos_ratio + SNAKE_BODY_GLOW[0] * (1 - pos_ratio)),
                int(SNAKE_HEAD_COLOR[1] * pos_ratio + SNAKE_BODY_GLOW[1] * (1 - pos_ratio)),
                int(SNAKE_HEAD_COLOR[2] * pos_ratio + SNAKE_BODY_GLOW[2] * (1 - pos_ratio))
            )
            
            # Head has distinct look
            is_head = (idx == len(self.snake) - 1)
            
            draw_glowing_circle(surface, (cx, cy), radius, seg_color, glow_intensity=3 if is_head else 1)
            
            # Small details for eyes
            if is_head:
                eye_color = (15, 23, 42)
                # Offset eyes based on current direction
                dx, dy = self.direction
                if dx != 0:
                    pygame.draw.circle(surface, eye_color, (cx + dx * 2, cy - 4), 2)
                    pygame.draw.circle(surface, eye_color, (cx + dx * 2, cy + 4), 2)
                elif dy != 0:
                    pygame.draw.circle(surface, eye_color, (cx - 4, cy + dy * 2), 2)
                    pygame.draw.circle(surface, eye_color, (cx + 4, cy + dy * 2), 2)

        # Draw borders
        draw_borders(surface)

        # Header Stats UI
        # Background Header panel
        pygame.draw.rect(surface, (15, 23, 42), (0, 0, WIDTH, HEADER_HEIGHT))
        
        # Neon glowing stats
        score_lbl = font_score.render("SCORE", True, (148, 163, 184))
        score_val = font_medium.render(f"{self.score:04d}", True, FOOD_COLOR)
        surface.blit(score_lbl, (40, 10))
        surface.blit(score_val, (40, 32))
        
        hs_lbl = font_score.render("HIGH SCORE", True, (148, 163, 184))
        hs_color = GOLDEN_FOOD_COLOR if self.new_high_score_achieved else TEXT_COLOR
        hs_val = font_medium.render(f"{self.high_score:04d}", True, hs_color)
        surface.blit(hs_lbl, (WIDTH - 180, 10))
        surface.blit(hs_val, (WIDTH - 180, 32))
        
        # Audio Mute status icon
        mute_txt = "MUTED" if muted else "SOUNDS ON"
        mute_color = (239, 68, 68) if muted else (34, 197, 94)
        mute_surf = font_small.render(f"[M] {mute_txt}", True, mute_color)
        surface.blit(mute_surf, (WIDTH // 2 - mute_surf.get_width() // 2, 30))

        # Screens Overlays (Start, Pause, Game Over)
        if self.state == "START":
            # Dark transparent overlay
            overlay = pygame.Surface((PLAY_WIDTH, PLAY_HEIGHT), pygame.SRCALPHA)
            overlay.fill((8, 10, 18, 220))
            surface.blit(overlay, (0, HEADER_HEIGHT))
            
            # Glow Title
            title_glow = render_glowing_text("NEON SNAKE", font_large, BORDER_COLOR, SNAKE_HEAD_COLOR, glow_radius=6)
            surface.blit(title_glow, (WIDTH // 2 - title_glow.get_width() // 2, HEIGHT // 2 - 120))
            
            # Pulsing press space prompt
            pulse_alpha = int(140 + 115 * math.sin(pygame.time.get_ticks() / 150))
            start_lbl = font_medium.render("PRESS [SPACE] TO START", True, TEXT_COLOR)
            start_lbl.set_alpha(pulse_alpha)
            surface.blit(start_lbl, (WIDTH // 2 - start_lbl.get_width() // 2, HEIGHT // 2 + 10))
            
            # Controls info
            ctrl_lbl = font_small.render("Move: WASD or ARROW KEYS    Mute: M    Pause: P or ESC", True, (100, 116, 139))
            surface.blit(ctrl_lbl, (WIDTH // 2 - ctrl_lbl.get_width() // 2, HEIGHT // 2 + 100))
            
        elif self.state == "PAUSED":
            overlay = pygame.Surface((PLAY_WIDTH, PLAY_HEIGHT), pygame.SRCALPHA)
            overlay.fill((8, 10, 18, 180))
            surface.blit(overlay, (0, HEADER_HEIGHT))
            
            paused_glow = render_glowing_text("GAME PAUSED", font_large, GOLDEN_FOOD_COLOR, (234, 179, 8), glow_radius=5)
            surface.blit(paused_glow, (WIDTH // 2 - paused_glow.get_width() // 2, HEIGHT // 2 - 80))
            
            resume_lbl = font_small.render("Press SPACE or P to Resume", True, TEXT_COLOR)
            surface.blit(resume_lbl, (WIDTH // 2 - resume_lbl.get_width() // 2, HEIGHT // 2 + 20))
            
        elif self.state == "GAME_OVER":
            overlay = pygame.Surface((PLAY_WIDTH, PLAY_HEIGHT), pygame.SRCALPHA)
            overlay.fill((20, 10, 15, 220)) # Dark reddish overlay
            surface.blit(overlay, (0, HEADER_HEIGHT))
            
            go_glow = render_glowing_text("GAME OVER", font_large, FOOD_COLOR, (225, 29, 72), glow_radius=6)
            surface.blit(go_glow, (WIDTH // 2 - go_glow.get_width() // 2, HEIGHT // 2 - 120))
            
            score_lbl = font_medium.render(f"FINAL SCORE: {self.score}", True, TEXT_COLOR)
            surface.blit(score_lbl, (WIDTH // 2 - score_lbl.get_width() // 2, HEIGHT // 2 - 10))
            
            if self.new_high_score_achieved:
                hs_glow = render_glowing_text("NEW HIGH SCORE!", font_medium, GOLDEN_FOOD_COLOR, (234, 179, 8), glow_radius=3)
                surface.blit(hs_glow, (WIDTH // 2 - hs_glow.get_width() // 2, HEIGHT // 2 + 40))
                
            retry_lbl = font_small.render("Press SPACE to play again or ESC to exit", True, (148, 163, 184))
            surface.blit(retry_lbl, (WIDTH // 2 - retry_lbl.get_width() // 2, HEIGHT // 2 + 110))


def main():
    global muted
    game = Game()
    
    # Render canvas surface for screen shake implementation
    game_surface = pygame.Surface((WIDTH, HEIGHT))

    while True:
        # Event Queue
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
                
            elif event.type == pygame.KEYDOWN:
                # Quit bindings
                if event.key == pygame.K_ESCAPE:
                    if game.state == "PLAYING":
                        game.state = "PAUSED"
                        play_sound(sound_click)
                    elif game.state in ("START", "GAME_OVER", "PAUSED"):
                        pygame.quit()
                        sys.exit()
                
                # Start / Pause / Restart bindings
                elif event.key == pygame.K_SPACE:
                    if game.state == "START":
                        game.state = "PLAYING"
                        play_sound(sound_start)
                    elif game.state == "PAUSED":
                        game.state = "PLAYING"
                        play_sound(sound_click)
                    elif game.state == "GAME_OVER":
                        game.reset_game()
                        game.state = "PLAYING"
                        play_sound(sound_start)
                        
                elif event.key == pygame.K_p:
                    if game.state == "PLAYING":
                        game.state = "PAUSED"
                        play_sound(sound_click)
                    elif game.state == "PAUSED":
                        game.state = "PLAYING"
                        play_sound(sound_click)
                        
                # Audio Mute trigger
                elif event.key == pygame.K_m:
                    muted = not muted
                    
                # Snake Movement Input
                elif game.state == "PLAYING":
                    # Lock movements: can't turn directly back into self
                    if event.key in (pygame.K_UP, pygame.K_w) and game.direction != [0, 1]:
                        game.next_direction = [0, -1]
                    elif event.key in (pygame.K_DOWN, pygame.K_s) and game.direction != [0, -1]:
                        game.next_direction = [0, 1]
                    elif event.key in (pygame.K_LEFT, pygame.K_a) and game.direction != [1, 0]:
                        game.next_direction = [-1, 0]
                    elif event.key in (pygame.K_RIGHT, pygame.K_d) and game.direction != [-1, 0]:
                        game.next_direction = [1, 0]

        # Tick calculations
        game.update()
        
        # Draw standard graphics to canvas surface
        game.draw(game_surface)
        
        # Apply Screen Shake offset if active
        offset_x = 0
        offset_y = 0
        if game.shake_intensity > 0:
            offset_x = random.randint(-int(game.shake_intensity), int(game.shake_intensity))
            offset_y = random.randint(-int(game.shake_intensity), int(game.shake_intensity))
            
        screen.fill((8, 10, 18)) # Dark matte padding background
        screen.blit(game_surface, (offset_x, offset_y))
        
        pygame.display.flip()
        
        # Speed dynamics: slightly increases speed as score goes up
        current_speed = 10 + min(12, game.score // 40)
        clock.tick(current_speed if game.state == "PLAYING" else 30)

if __name__ == "__main__":
    main()
