import time
import os
import winpty
import select
import re
import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import threading

from assistant import AssistantPlayer
from terminal_wrapper import TootsieTerminalWrapper

# Helper to read all available output from the process without blocking
def read_all_available(proc, read_timeout=1):
    output_lines = []
    fd = proc.fd
    while True:
        rlist, _, _ = select.select([fd], [], [], read_timeout)
        if not rlist:
            break  # No data available within the timeout, assume done
        try:
            data = proc.read(1024)
        except Exception:
            break
        if not data:
            break
        output_lines.append(data.decode(errors="ignore") if isinstance(data, bytes) else data)
    return ''.join(output_lines)

# Remove ANSI escape sequences (color, cursor, etc.) and empty lines
def strip_ansi(text):
    ansi_escape = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07')
    no_ansi = ansi_escape.sub('', text)
    # Remove lines that are completely empty (only a newline, no whitespace)
    lines = no_ansi.splitlines()
    filtered = [line for line in lines if line.strip() != '']
    return '\n'.join(filtered)

# Start the tootsie.exe process and keep it open for interaction
class TootsieWrapper:
    def __init__(self):
        env = os.environ.copy()
        env["DOTNET_Console_UseStdoutRedirection"] = "0"
        self.proc = winpty.PtyProcess.spawn(
            "tootsie.exe",
            cwd=os.getcwd(),
            dimensions=(30, 120),
            env=env
        )

    def get_current_screen(self):
        raw = read_all_available(self.proc)
        return strip_ansi(raw)

    def send_text(self, text):
        self.proc.write(text)
        raw = self.get_current_screen()
        return raw
    
    def send_command(self, command):
        return self.send_text(command + "\r\n")

    def close(self):
        self.proc.close()

class TootsieGUI:
    def __init__(self, root, game_wrapper):
        self.root = root
        self.root.title("TootsiePopper")
        # Make window larger
        self.root.geometry("1400x900")
        # Main vertical layout
        self.main_frame = tk.Frame(root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        # Top: main text area (game state)
        self.text_area = ScrolledText(self.main_frame, wrap=tk.WORD, height=30, width=120, state=tk.DISABLED)
        self.text_area.pack(side=tk.TOP, padx=10, pady=(10,2), fill=tk.BOTH, expand=False)
        # Status label (between main text and message)
        self.status_var = tk.StringVar()
        self.command_label = tk.Label(self.main_frame, textvariable=self.status_var, anchor="w", fg="blue")
        self.command_label.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0,2))
        # Message area (thin, wide)
        self.llm_message = tk.Text(self.main_frame, wrap=tk.WORD, height=2, width=120, state=tk.DISABLED, bg="#f0f0ff")
        self.llm_message.pack(side=tk.TOP, padx=10, pady=(0,2), fill=tk.X, expand=False)
        # Bottom: split horizontally for memory (left) and reasoning (right)
        self.bottom_frame = tk.Frame(self.main_frame)
        self.bottom_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(2,2))
        # Memory area (left)
        self.memory_area_frame = tk.Frame(self.bottom_frame)
        self.memory_area_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.memory_label = tk.Label(self.memory_area_frame, text="Memory", font=("Arial", 10, "bold"))
        self.memory_label.pack(side=tk.TOP, anchor="w")
        self.memory_area = ScrolledText(self.memory_area_frame, wrap=tk.WORD, height=8, width=50, state=tk.DISABLED, bg="#f8fff8")
        self.memory_area.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # Reasoning area (right)
        self.reasoning_area_frame = tk.Frame(self.bottom_frame)
        self.reasoning_area_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self.llm_reasoning_label = tk.Label(self.reasoning_area_frame, text="Reasoning", font=("Arial", 10, "bold"))
        self.llm_reasoning_label.pack(side=tk.TOP, anchor="w")
        self.llm_reasoning = ScrolledText(self.reasoning_area_frame, wrap=tk.WORD, height=8, width=50, state=tk.DISABLED, bg="#f8f8ff")
        self.llm_reasoning.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # Token usage at the very bottom
        self.token_var = tk.StringVar()
        self.token_label = tk.Label(root, textvariable=self.token_var, anchor="e", fg="#555")
        self.token_label.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0,10))
        self.game = game_wrapper
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def update_output(self, text):
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete(1.0, tk.END)
        self.text_area.insert(tk.END, text + '\n')
        self.text_area.see(tk.END)
        self.text_area.config(state=tk.DISABLED)

    def set_last_command(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            cmd = "<enter>"
        self.set_status(f"Sent command: {cmd}")

    def set_status(self, text):
        self.status_var.set(text)

    def reset_status(self):
        self.status_var.set("")

    def set_llm_message(self, message):
        self.llm_message.config(state=tk.NORMAL)
        self.llm_message.delete(1.0, tk.END)
        self.llm_message.insert(tk.END, message)
        self.llm_message.config(state=tk.DISABLED)

    def set_reasoning(self, reasoning):
        self.llm_reasoning.config(state=tk.NORMAL)
        self.llm_reasoning.delete(1.0, tk.END)
        self.llm_reasoning.insert(tk.END, reasoning)
        self.llm_reasoning.config(state=tk.DISABLED)

    def set_memory(self, memory_dict):
        self.memory_area.config(state=tk.NORMAL)
        self.memory_area.delete(1.0, tk.END)
        for k, v in memory_dict.items():
            self.memory_area.insert(tk.END, f"{k}: {v}\n")
        self.memory_area.config(state=tk.DISABLED)

    def set_token_usage(self, input_tokens=None, cached_input_tokens=None, output_tokens=None, turns_until_summary=None):
        if input_tokens is not None and cached_input_tokens is not None and output_tokens is not None:
            token_info = f"input: {input_tokens} ({cached_input_tokens}), output: {output_tokens}"
            if turns_until_summary is not None:
                token_info += f" | summary: T-{turns_until_summary}"
            self.token_var.set(token_info)
        else:
            self.token_var.set("")

    def on_close(self):
        try:
            self.game.close()
        except Exception:
            pass
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    api_key = ''
    with open("api_key.txt", "r") as f:
        api_key = f.read().strip()
    if not api_key:
        raise ValueError("API key not found. Please create a file named 'api_key.txt' with your OpenAI API key.")
    system_prompt = ''
    with open("system_prompt.txt", "r") as f:
        system_prompt = f.read().strip()
    player = AssistantPlayer(api_key=api_key, model_name="o4-mini", system_prompt=system_prompt)
    game = TootsieTerminalWrapper()
    gui = TootsieGUI(root, game)

    def send_and_refresh(cmd):
        gui.set_last_command(cmd)
        new_text = game.send_command(cmd)
        gui.update_output(new_text)
        gui.reset_status()
        return new_text

    # Example: programmatically send commands and update the GUI
    def play_game():
        # get the initial game state
        game_text = game.get_current_screen()
        gui.update_output(game_text)

        summarize_after = 25
        summary_counter = 0
        while True:
            # check if we need to summarize the game state
            if summary_counter >= summarize_after:
                gui.set_status("Summarizing game state...")
                player.perform_summary()
                summary_counter = 0
                continue
            gui.set_status("LLM Player thinking...")
            response = player.get_response(game_text)
            gui.set_llm_message(response.message)
            gui.set_reasoning(response.reasoning)
            gui.set_memory(player.memory)
            gui.set_token_usage(
                input_tokens=response.input_tokens,
                cached_input_tokens=response.cached_input_tokens,
                output_tokens=response.output_tokens,
                turns_until_summary=summarize_after - summary_counter
            )
            # execute the command in the game
            # if command is None, skip. If command is empty, send Enter.
            if response.command is not None:
                game_text = send_and_refresh(response.command)
                summary_counter += 1
            else:
                gui.set_status("No command generated by LLM, waiting for next turn...")
                game_text = '<meta>No new text from the game this turn.</meta>'

    threading.Thread(target=play_game, daemon=True).start()
    root.mainloop()
