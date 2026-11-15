#!/usr/bin/env python3
"""ansi-flatten.py - replay raw terminal output and print the final text.

Usage: ansi-flatten.py <raw file> <columns> [start_at]

A minimal terminal emulator: it keeps every line ever printed (no scrollback
limit) and applies what progress bars and spinners use to redraw - carriage
return, backspace, erase in line/display and cursor movement - so each line
ends up as it looked last. Colors and text attributes (SGR) are kept and
written back as ANSI codes, which freeze then renders. Everything else
(window titles, mode switches, ...) is dropped.

With start_at, the benchmark's output is shown from the first line that
contains that text; the header pty-runner.sh prints before the output (the
command line) stays. Without such a line everything is kept.

freeze ignores the basic background colors (SGR 40-47), so they (and the
bright ones, 100-107) are written as true colors (48;2;r;g;b) instead.
"""

import re
import sys
import unicodedata

SCREEN_ROWS = 50  # height of the PTY, see pty-runner.sh

CSI_RE = re.compile(r"\x1b\[([0-9:;<=>?]*)[ -/]*([@-~])")
OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
OTHER_ESC_RE = re.compile(r"\x1b[()*+][0-9A-Za-z]|\x1b[@-Z\\-_]|\x1b[ #%][0-~]|\x1b[0-9=>]")

OUTPUT_MARKER = "\x1b]777;benchmark-output\x07"  # printed by pty-runner.sh

# Tango terminal palette for the basic backgrounds (SGR 40-47, 100-107).
# Darker than freeze's text palette, so white text on them stays readable.
BACKGROUNDS = {
    40: (0x2E, 0x34, 0x36), 41: (0xCC, 0x00, 0x00), 42: (0x4E, 0x9A, 0x06),
    43: (0xC4, 0xA0, 0x00), 44: (0x34, 0x65, 0xA4), 45: (0x75, 0x50, 0x7B),
    46: (0x06, 0x98, 0x9A), 47: (0xD3, 0xD7, 0xCF),
    100: (0x55, 0x57, 0x53), 101: (0xEF, 0x29, 0x29), 102: (0x8A, 0xE2, 0x34),
    103: (0xFC, 0xE9, 0x4F), 104: (0x72, 0x9F, 0xCF), 105: (0xAD, 0x7F, 0xA8),
    106: (0x34, 0xE2, 0xE2), 107: (0xEE, 0xEE, 0xEC),
}

ZERO_WIDTH = {"‍", "︎", "️"}


def char_width(ch):
    if ch in ZERO_WIDTH or unicodedata.combining(ch):
        return 0
    if unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


class Terminal:
    def __init__(self, columns):
        self.columns = columns
        self.lines = [[]]  # each cell: [text, sgr] or None (right half of a wide char)
        self.row = 0
        self.col = 0
        self.pending_wrap = False
        self.sgr = ""
        self.fg = None
        self.bg = None
        self.attrs = set()
        self.output_row = None
        self.base = 0  # first row of the current screen after a clear

    def apply_sgr(self, params):
        codes = [int(p) if p.isdigit() else 0 for p in params.replace(":", ";").split(";")]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                self.fg = self.bg = None
                self.attrs = set()
            elif 1 <= c <= 9:
                self.attrs.add(c)
            elif c == 22:
                self.attrs -= {1, 2}
            elif 23 <= c <= 29:
                self.attrs.discard(c - 20)
            elif 30 <= c <= 37 or 90 <= c <= 97:
                self.fg = str(c)
            elif 40 <= c <= 47 or 100 <= c <= 107:
                self.bg = "48;2;%d;%d;%d" % BACKGROUNDS[c]
            elif c == 39:
                self.fg = None
            elif c == 49:
                self.bg = None
            elif c in (38, 48):
                # extended color: 5;n (256 colors) or 2;r;g;b (true color)
                mode = codes[i + 1] if i + 1 < len(codes) else None
                take = 2 if mode == 5 else 4 if mode == 2 else 1
                value = ";".join(str(x) for x in codes[i:i + 1 + take])
                if c == 38:
                    self.fg = value
                else:
                    self.bg = value
                i += take
            i += 1
        parts = [str(a) for a in sorted(self.attrs)]
        if self.fg:
            parts.append(self.fg)
        if self.bg:
            parts.append(self.bg)
        self.sgr = ";".join(parts)

    def _line(self, row):
        while len(self.lines) <= row:
            self.lines.append([])
        return self.lines[row]

    def _screen_top(self):
        return max(self.base, len(self.lines) - SCREEN_ROWS)

    def newline(self):
        self.row += 1
        self._line(self.row)
        self.pending_wrap = False

    def put(self, ch):
        width = char_width(ch)
        line = self._line(self.row)
        if width == 0:
            # combining mark / joiner / variation selector: glue to the cell before
            col = self.col - 1
            while col >= 0 and col < len(line) and line[col] is None:
                col -= 1
            if 0 <= col < len(line) and line[col] is not None:
                line[col][0] += ch
            return
        if self.pending_wrap or self.col + width > self.columns:
            self.newline()
            self.col = 0
            line = self._line(self.row)
        while len(line) < self.col + width:
            line.append([" ", ""])
        line[self.col] = [ch, self.sgr]
        if width == 2:
            line[self.col + 1] = None
        self.col += width
        if self.col >= self.columns:
            self.col = self.columns - 1
            self.pending_wrap = True

    def erase_line(self, mode):
        line = self._line(self.row)
        if mode == 0:
            del line[self.col:]
        elif mode == 1:
            for i in range(min(self.col + 1, len(line))):
                line[i] = [" ", ""]
        else:
            line.clear()

    def erase_display(self, mode):
        if mode == 0:
            self.erase_line(0)
            del self.lines[self.row + 1:]
        elif mode == 1:
            for r in range(self._screen_top(), self.row):
                self.lines[r] = []
            self.erase_line(1)
        elif mode == 2:
            # Clear screen (e.g. `clear`): a terminal would wipe what is on
            # screen, but for a screenshot nothing is lost - a fresh screen
            # starts below everything printed so far
            while len(self.lines) > 1 and not self.lines[-1]:
                self.lines.pop()
            if any(self.lines):
                self.lines.append([])
            self.base = len(self.lines) - 1
            self.row = self.base
        # mode 3 (clear scrollback) is ignored for the same reason

    def csi(self, params, final):
        private = params.startswith("?") or params.startswith(">") or params.startswith("=")
        if private:
            return
        nums = []
        for p in params.replace(":", ";").split(";"):
            nums.append(int(p) if p.isdigit() else None)
        first = nums[0] if nums and nums[0] is not None else None
        n = first if first else 1

        if final == "m":
            self.apply_sgr(params)
            return
        self.pending_wrap = False
        if final == "K":
            self.erase_line(first or 0)
        elif final == "J":
            self.erase_display(first or 0)
        elif final == "A":
            self.row = max(self._screen_top(), self.row - n)
        elif final in ("B", "e"):
            self.row += n
            self._line(self.row)
        elif final in ("C", "a"):
            self.col = min(self.columns - 1, self.col + n)
        elif final == "D":
            self.col = max(0, self.col - n)
        elif final == "E":
            self.row += n
            self._line(self.row)
            self.col = 0
        elif final == "F":
            self.row = max(self._screen_top(), self.row - n)
            self.col = 0
        elif final in ("G", "`"):
            self.col = min(self.columns - 1, max(0, n - 1))
        elif final in ("H", "f"):
            r = nums[0] if len(nums) > 0 and nums[0] else 1
            c = nums[1] if len(nums) > 1 and nums[1] else 1
            self.row = self._screen_top() + r - 1
            self._line(self.row)
            self.col = min(self.columns - 1, c - 1)
        elif final == "d":
            self.row = self._screen_top() + n - 1
            self._line(self.row)
        elif final == "X":
            line = self._line(self.row)
            for i in range(self.col, min(self.col + n, len(line))):
                line[i] = [" ", ""]
        elif final == "P":
            line = self._line(self.row)
            del line[self.col:self.col + n]
        elif final == "@":
            line = self._line(self.row)
            for _ in range(n):
                line.insert(self.col, [" ", ""])
            del line[self.columns:]

    def feed(self, text):
        i = 0
        length = len(text)
        while i < length:
            ch = text[i]
            if ch == "\x1b":
                m = CSI_RE.match(text, i)
                if m:
                    self.csi(m.group(1), m.group(2))
                    i = m.end()
                    continue
                if self.output_row is None and text.startswith(OUTPUT_MARKER, i):
                    # the output starts on the next line written to
                    self.output_row = self.row if self.col == 0 else self.row + 1
                m = OSC_RE.match(text, i) or OTHER_ESC_RE.match(text, i)
                if m:
                    i = m.end()
                    continue
                i += 1
                continue
            if ch == "\n":
                self.newline()
            elif ch == "\r":
                self.col = 0
                self.pending_wrap = False
            elif ch == "\b":
                self.col = max(0, self.col - 1)
                self.pending_wrap = False
            elif ch == "\t":
                self.col = min(self.columns - 1, (self.col // 8 + 1) * 8)
            elif ch < " " or ch == "\x7f":
                pass
            else:
                self.put(ch)
            i += 1

    def trim(self, start_at):
        """Drop the output lines before the first one containing start_at."""
        first = self.output_row or 0
        for row in range(first, len(self.lines)):
            text = "".join(c[0] for c in self.lines[row] if c is not None)
            if start_at in text:
                del self.lines[first:row]
                return

    def render(self):
        out = []
        for line in self.lines:
            cells = [c for c in line if c is not None]
            while cells and cells[-1][0] == " " and not cells[-1][1]:
                cells.pop()
            parts = []
            current = ""
            for text, sgr in cells:
                if sgr != current:
                    parts.append("\x1b[0m" + (f"\x1b[{sgr}m" if sgr else ""))
                    current = sgr
                parts.append(text)
            if current:
                parts.append("\x1b[0m")
            out.append("".join(parts))
        while out and out[-1] == "":
            out.pop()
        while out and out[0] == "":
            out.pop(0)
        return "\n".join(out) + "\n"


def main():
    if len(sys.argv) not in (3, 4):
        sys.exit(__doc__)
    with open(sys.argv[1], "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    term = Terminal(int(sys.argv[2]))
    term.feed(text)
    if len(sys.argv) == 4 and sys.argv[3]:
        term.trim(sys.argv[3])
    sys.stdout.write(term.render())


if __name__ == "__main__":
    main()
