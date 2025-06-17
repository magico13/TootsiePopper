from pywinauto import Application
import time

class TootsieTerminalWrapper:
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
        return self.get_current_screen(current_text)

    def send_enter(self) -> str:
        # Send only the Enter key
        current_text = self.grab_text()
        self.window.type_keys("{ENTER}")
        return self.get_current_screen(current_text)

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

if __name__ == "__main__":
    wrapper = TootsieTerminalWrapper()
    previous_text = ""
    while True:
        current_text = wrapper.get_current_screen()
        if current_text:
            new_text = wrapper.get_new_text(previous_text)
            if new_text:
                print("New terminal text since last check:\n", new_text)
            previous_text = current_text
        wrapper.send_enter()
        time.sleep(1)  # Poll every second
