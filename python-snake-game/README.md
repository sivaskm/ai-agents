# Neon Snake - Arcade Edition

A beautifully styled, retro-themed arcade snake game built in Python using Pygame.

## Features

- **Neon Aesthetics**: Glowing snake, food, particles, and borders.
- **Dynamic Speed**: The game gets faster and more challenging as your score increases.
- **Golden Food**: Rare high-value food that appears randomly and lasts for a limited time.
- **Juicy Visuals**: Screen shake on eating food and crashes, plus exploding neon particle effects.
- **Synth Audio**: Programmatically generated retro arcade sound effects (sine, square, and triangle wave synthesized sound effects) with click prevention.
- **Mute Toggle**: Easily mute/unmute audio by pressing `M`.
- **Persistent High Scores**: High scores are saved to `highscore.json` and persist across play sessions.

## Controls

- **Move**: `W` / `A` / `S` / `D` or **Arrow Keys**
- **Pause/Resume**: `P` or `ESC`
- **Mute/Unmute**: `M`
- **Restart (on Game Over)**: `SPACE`
- **Exit**: `ESC` (from menu or pause screen)

## Requirements

- Python >= 3.13
- Pygame >= 2.6.1

## How to Run

If you have `uv` installed, simply run the following in this folder:

```bash
uv run main.py
```

Otherwise, create a virtual environment, install Pygame, and run the script:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install pygame
python main.py
```
