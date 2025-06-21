from pywinauto import Application
import time

class TootsieTerminalWrapper:
    COMMAND_INPUT_PROMPT = "What do you do?:"

    def __init__(self, window_title_re=r".*tootsie.exe.*", exe_path="tootsie.exe"):        
        # Try UIA backend for Windows Terminal, fallback to classic
        try:
            self.app = Application(backend="uia").connect(title_re=window_title_re)
            self.window = self.app.window(title_re=window_title_re)
        except Exception:
            self.app = Application().connect(title_re=window_title_re)
            self.window = self.app.window(title_re=window_title_re)

    def grab_text(self) -> str:
        # Try to grab text using UIA backend (for Windows Terminal)
        try:
            # Windows Terminal: look for Text controls in the UI tree
            texts = self.window.descendants(control_type="Text")
            # first one is the title bar, skip it
            if texts and len(texts) > 1:
                output_text = texts[1].window_text()
                if output_text:
                    return output_text.rstrip()
        except Exception as e:
            print(f"UIA text grab failed: {e}")
        # Fallback: classic console
        try:
            return self.window.window(class_name="ConsoleWindowClass").window_text()
        except Exception as e:
            print(f"Classic text grab failed: {e}")
            return ''

    def send_command(self, command: str) -> str:
        # Send a command (string) followed by Enter
        current_text = self.grab_text()
        self.window.type_keys(command + "{ENTER}", with_spaces=True)
        new_screen = self.get_current_screen(current_text)
        # look backward in the new screen for the command we sent and return the new text after it
        if new_screen:
            lights_index = new_screen.rfind("*Click* You flick the lights")
            #command index should look for the command on a line by itself
            command_index = -1
            if command:
                command_index = new_screen.rfind(command)
                # maybe the command didn't come through correctly, also find the last instance of "What do you do?" prompt
                if command_index == -1:
                    command_index = new_screen.rfind(self.COMMAND_INPUT_PROMPT)
            if lights_index > command_index:
                # If the lights click happens after the command, return everything after the lights click
                return new_screen[lights_index:].lstrip()
            if command_index != -1:
                # If the command is found, return everything after it
                new_screen = new_screen[command_index + len(command):].lstrip()
        return new_screen

    def send_enter(self) -> str:
        # Send only the Enter key
        current_text = self.grab_text()
        self.window.type_keys("{ENTER}")
        new_screen = self.get_current_screen(current_text)
        # check for the text of "What do you do?" prompt and don't go any further back from that
        prompt_index = new_screen.rfind(self.COMMAND_INPUT_PROMPT)
        if prompt_index != -1:
            # If the prompt is found, return everything after it
            new_screen = new_screen[prompt_index + len(self.COMMAND_INPUT_PROMPT):].lstrip()
        return new_screen

    def get_current_screen(self, original_text: str | None= None) -> str:
        # Wait for output to stop changing for a certain period
        # This is useful to ensure we get the final output after a command
        timeout = 120
        start_time = time.time()
        prev_text = self.grab_text()
        if not original_text:
            # If no original text is provided, use the current text as the base
            original_text = prev_text.rstrip()
        current_text = prev_text
        while time.time() - start_time < timeout:
            time.sleep(1)
            current_text = self.grab_text()
            # strip all newlines after the last non-empty line
            if current_text:
                current_text = current_text.rstrip()
            else:
                # that means there is no new text at all, so we can return the previous one
                return prev_text
            if current_text != prev_text:
                prev_text = current_text
            else:
                # If the text hasn't changed for a while, consider it stable
                output = self.get_new_text(original_text, current_text)
                if output:
                    return output
                # if we would return nothing, then return the current text
                return current_text
        return current_text
    
    def close(self):
        # Close the terminal window
        try:
            self.window.close()
        except Exception as e:
            print(f"Failed to close window: {e}")
    
    def get_new_text(self, previous_text: str, current_text: str) -> str:
        """
        Returns only the new text that has appeared since previous_text.
        If previous_text is found as a suffix of the current text, returns the remainder.
        Otherwise, returns the full current text.
        """
        if not previous_text:
            return current_text
        if current_text.startswith(previous_text):
            return current_text[len(previous_text):].lstrip("\n")
        # If previous_text is not a prefix, try to find it anywhere in current_text
        idx = current_text.find(previous_text)
        if idx != -1:
            return current_text[idx + len(previous_text):].lstrip("\n")
        # If not found, return the full text
        return current_text

