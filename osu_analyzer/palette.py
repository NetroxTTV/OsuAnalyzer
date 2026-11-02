"""Colours shared by the app and the command-line plot."""

# Neutrals (dark theme)
BG = "#0f0f14"          # window
SURFACE = "#15151c"     # sidebar, bars
CARD = "#1b1b24"        # cards and panels
ELEVATED = "#24242f"    # inputs, hover
BORDER = "#2b2b38"
TEXT = "#ececf2"
MUTED = "#8e8ea4"
SUBTLE = "#5c5c70"

DEFAULT_ACCENT = "#ff66aa"
ACCENTS = ["#ff66aa", "#8b7bff", "#5ac8fa", "#3ddc97", "#ffb347", "#ff5c6c"]

GOLD = "#ffd84d"        # average hit, "now" markers
JUDGE_COLORS = {300: "#5ac8fa", 100: "#7ed957", 50: "#ffb347"}
MISS_RED = "#ff4d5e"
MISS_COLORS = {"outside": MISS_RED, "early": "#ffa94d", "no click": "#a8a8c0"}
EARLY_BLUE = "#4f9dff"  # timing colour scale: early -> on time -> late
LATE_RED = "#ff5470"
K1_COLOR = "#f0a030"
K2_COLOR = "#3fcf6a"
GOOD = "#3ddc97"         # improving (with an arrow, never colour alone)
BAD = MISS_RED          # getting worse
GRADE_COLORS = {"SS": "#ffd84d", "S": "#ffb347", "A": "#7ed957", "B": "#5ac8fa", "C": "#b48cff",
                "D": "#ff5c6c", "SSH": "#d9e2ec", "SH": "#d9e2ec"}
